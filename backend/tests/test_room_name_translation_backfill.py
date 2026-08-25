"""
POST /api/maintenance/translate-room-names — safety regression suite.

This endpoint exists to fill the empty Arabic/Hebrew slots of Destinations
that ALREADY EXIST, on a live estate whose navigation graph is working. So
the interesting assertions here are not "does it translate" — that part is
one dictionary merge — they are "what can it possibly damage", and the
answer has to be provably nothing except names.ar / names.he.

Every test below therefore compares the ENTIRE database, document by
document, before and after the call, rather than spot-checking a field.
A regression that rewrote route_point_id, moved a room to another map, or
blanked an English name would fail these tests even though nobody wrote an
assertion naming that specific failure.

The AI provider is always stubbed. No test in this file makes a network
call, and no test applies anything to a real database.

Run with: pytest backend/tests/test_room_name_translation_backfill.py -v
"""

import ast
import asyncio
import copy
import json
import re

import pytest

from models.building_model import Building
from models.location_code_model import LocationCode
from models.map_model import Map
from models.room_model import Room
from models.route_edge_model import RouteEdge
from models.route_point_model import RoutePoint
from models.semantic_map_analysis_model import SemanticMapAnalysis

from routes import maintenance_routes
from services import room_name_translation_service
from services.room_name_translation_service import (
    KIND_CODE_ONLY,
    KIND_DESCRIPTIVE,
    KIND_UNTRANSLATABLE,
    RoomNameTranslationError,
    build_proposal,
    collect_source_names,
    parse_translation_payload,
    updates_for_room,
)

from tests.test_api_integration import (
    auth_headers,
    create_admin_and_get_token,
)


ENDPOINT = "/api/maintenance/translate-room-names"

BUILDING_ID = "7b936ffae3e4a269a4589f01"
OTHER_BUILDING_ID = "7b936ffae3e4a269a4589f02"
MAP_ID = "7b936ffae3e4a269a4589f11"
OTHER_MAP_ID = "7b936ffae3e4a269a4589f12"


def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# ---------------------------------------------------------
# Whole-database snapshots
#
# Read straight off the driver so the comparison sees exactly what is
# persisted — including fields no test mentions by name.
# ---------------------------------------------------------

SNAPSHOT_MODELS = (
    Room,
    RoutePoint,
    RouteEdge,
    LocationCode,
    Map,
    Building,
    SemanticMapAnalysis,
)


async def _snapshot():
    state = {}

    for model in SNAPSHOT_MODELS:
        collection = model.get_pymongo_collection()
        documents = await collection.find({}).to_list(length=None)
        state[model.get_collection_name()] = {
            str(document["_id"]): copy.deepcopy(document) for document in documents
        }

    return state


def snapshot():
    return run(_snapshot())


def assert_untouched(before, after, *, except_rooms=()):
    """
    Every collection is byte-identical, except the Room documents whose
    ids are explicitly listed — and even those may differ only in `names`
    and `updated_at`.
    """

    allowed = {str(room_id) for room_id in except_rooms}

    for collection_name, before_docs in before.items():
        after_docs = after[collection_name]

        assert set(before_docs) == set(after_docs), (
            f"{collection_name}: documents were created or deleted"
        )

        for document_id, before_doc in before_docs.items():
            after_doc = after_docs[document_id]

            if collection_name == Room.get_collection_name() and document_id in allowed:
                changed = {
                    key
                    for key in set(before_doc) | set(after_doc)
                    if before_doc.get(key) != after_doc.get(key)
                }
                assert changed <= {"names", "updated_at"}, (
                    f"room {document_id} changed disallowed fields: "
                    f"{sorted(changed - {'names', 'updated_at'})}"
                )
                continue

            assert before_doc == after_doc, (
                f"{collection_name}/{document_id} was modified"
            )


# ---------------------------------------------------------
# Seeding — a realistic slice: a placed, routed, QR-labelled room on
# one map, plus a second map and a second building for scope tests.
# ---------------------------------------------------------


async def _make_room(**kwargs):
    kwargs.setdefault("building_id", BUILDING_ID)
    kwargs.setdefault("map_id", MAP_ID)
    kwargs.setdefault("name_en", "Room")
    kwargs.setdefault("room_type", "store")
    kwargs.setdefault("floor", 1)
    room = Room(**kwargs)
    await room.insert()
    return room


async def _seed_graph():
    """
    The things this endpoint must never touch: two RoutePoints joined by a
    RouteEdge, and a LocationCode. Nothing here is referenced by the
    translation code at all — they are seeded precisely so the snapshot
    can prove that.
    """

    building = Building(name_en="Campus")
    await building.insert()

    map_item = Map(title="Floor 1", building_id=BUILDING_ID, floor=1)
    await map_item.insert()

    corridor = RoutePoint(
        map_id=MAP_ID,
        building_id=BUILDING_ID,
        name="Corridor",
        x=10.0,
        y=10.0,
        point_type="hallway",
        floor=1,
    )
    await corridor.insert()

    door = RoutePoint(
        map_id=MAP_ID,
        building_id=BUILDING_ID,
        name="Destination Point",
        x=20.0,
        y=20.0,
        point_type="destination",
        floor=1,
    )
    await door.insert()

    edge = RouteEdge(
        map_id=MAP_ID,
        from_point_id=str(corridor.id),
        to_point_id=str(door.id),
        distance=10.0,
    )
    await edge.insert()

    code = LocationCode(
        code="QR-TRANSLATE-1",
        map_id=MAP_ID,
        building_id=BUILDING_ID,
        route_point_id=str(door.id),
    )
    await code.insert()

    return door


async def _seed_default():
    """
    Four rooms covering the cases that matter:
      untranslated  — both languages empty, the ordinary case
      partial       — Hebrew already present, Arabic empty
      complete      — both present already
      branded       — a business name the model will decline
    """

    door = await _seed_graph()

    untranslated = await _make_room(
        name_en="Electrical Room",
        names={"en": "Electrical Room", "ar": None, "he": None},
        route_point_id=str(door.id),
        x=20.0,
        y=20.0,
        room_number="B-12",
    )

    partial = await _make_room(
        name_en="Storage",
        names={"en": "Storage", "ar": None, "he": "מחסן ידני"},
    )

    complete = await _make_room(
        name_en="Reception",
        names={"en": "Reception", "ar": "الاستقبال", "he": "קבלה"},
    )

    branded = await _make_room(
        name_en="Cafe Aroma",
        names={"en": "Cafe Aroma", "ar": None, "he": None},
    )

    return {
        "untranslated": untranslated,
        "partial": partial,
        "complete": complete,
        "branded": branded,
    }


DEFAULT_TRANSLATIONS = {
    "Electrical Room": {"ar": "غرفة الكهرباء", "he": "חדר חשמל"},
    "Storage": {"ar": "مخزن", "he": "מחסן"},
    # A brand: the model is instructed to decline rather than guess.
    "Cafe Aroma": {"ar": None, "he": None},
}


class ProviderStub:
    """Stands in for the one outbound Anthropic call. Records every
    invocation so a test can prove batching."""

    def __init__(self, table=None, error=None):
        self.table = DEFAULT_TRANSLATIONS if table is None else table
        self.error = error
        self.calls = []

    def __call__(self, names):
        self.calls.append(list(names))

        if self.error is not None:
            raise self.error

        return {
            name: self.table[name] for name in names if name in self.table
        }


@pytest.fixture()
def provider(monkeypatch):
    stub = ProviderStub()
    monkeypatch.setattr(
        room_name_translation_service, "call_translation_provider", stub
    )
    # The route resolves the function through the module object, so this
    # single patch covers the only path to the provider.
    monkeypatch.setattr(
        maintenance_routes.room_name_translation_service,
        "call_translation_provider",
        stub,
        raising=False,
    )
    return stub


@pytest.fixture()
def admin(client):
    token, _ = create_admin_and_get_token(
        client, role="super_admin", email="translate-admin@example.com"
    )
    return token


def preview(client, token, **params):
    return client.post(ENDPOINT, params=params, headers=auth_headers(token))


def apply_now(client, token, **params):
    params.setdefault("dry_run", "false")
    params.setdefault("confirm_apply", "true")
    return client.post(ENDPOINT, params=params, headers=auth_headers(token))


def room_names(room_id):
    return run(Room.get(room_id)).names


# =========================================================
# 1. Dry run writes NOTHING
# =========================================================

def test_dry_run_performs_zero_database_writes(client, admin, provider):
    rooms = run(_seed_default())
    before = snapshot()

    response = preview(client, admin)
    assert response.status_code == 200, response.text

    body = response.json()
    assert body["dry_run"] is True
    assert body["applied"] is False
    assert body["rooms_updated"] == 0

    # The AI genuinely ran and genuinely produced proposals — this is a
    # real preview, not a no-op that trivially writes nothing.
    assert provider.calls
    assert body["proposals"]

    assert_untouched(before, snapshot())
    assert room_names(rooms["untranslated"].id)["ar"] is None


# =========================================================
# 2. The preview is structured, and says exactly what would change
# =========================================================

def test_dry_run_returns_structured_proposals_with_will_change(client, admin, provider):
    rooms = run(_seed_default())

    body = preview(client, admin).json()
    by_id = {item["room_id"]: item for item in body["proposals"]}

    untranslated = by_id[str(rooms["untranslated"].id)]
    assert untranslated["source_name"] == "Electrical Room"
    assert sorted(untranslated["will_change"]) == ["ar", "he"]
    assert untranslated["current"] == {"ar": None, "he": None, "en": "Electrical Room"}
    assert untranslated["proposed"]["ar"] == "غرفة الكهرباء"
    assert untranslated["proposed"]["he"] == "חדר חשמל"
    assert untranslated["map_id"] == MAP_ID
    assert untranslated["building_id"] == BUILDING_ID

    # Hebrew already exists here, so only Arabic is offered.
    partial = by_id[str(rooms["partial"].id)]
    assert partial["will_change"] == ["ar"]
    assert partial["proposed"]["he"] == "מחסן ידני"

    # Nothing to do / nothing usable — no proposal at all.
    assert str(rooms["complete"].id) not in by_id
    assert str(rooms["branded"].id) not in by_id


# =========================================================
# 3. Applying requires an explicit confirmation flag
# =========================================================

def test_dry_run_false_alone_is_refused_and_writes_nothing(client, admin, provider):
    run(_seed_default())
    before = snapshot()

    response = client.post(
        ENDPOINT, params={"dry_run": "false"}, headers=auth_headers(admin)
    )
    assert response.status_code == 200, response.text

    body = response.json()
    assert body["applied"] is False
    assert body["error"] == "confirmation_required"
    assert body["rooms_updated"] == 0

    # It refused before doing anything at all — no provider call either.
    assert provider.calls == []
    assert_untouched(before, snapshot())


# =========================================================
# 4. Apply fills the empty slots — and only those
# =========================================================

def test_apply_fills_only_empty_languages(client, admin, provider):
    rooms = run(_seed_default())
    before = snapshot()

    body = apply_now(client, admin).json()
    assert body["applied"] is True
    assert body["rooms_updated"] == 2

    assert room_names(rooms["untranslated"].id) == {
        "en": "Electrical Room",
        "ar": "غرفة الكهرباء",
        "he": "חדר חשמל",
    }

    # Hebrew was already filled by a human and is preserved verbatim;
    # only the empty Arabic slot was written.
    assert room_names(rooms["partial"].id) == {
        "en": "Storage",
        "ar": "مخزن",
        "he": "מחסן ידני",
    }

    assert_untouched(
        before,
        snapshot(),
        except_rooms=[rooms["untranslated"].id, rooms["partial"].id],
    )


# =========================================================
# 5. An existing translation is never overwritten
# =========================================================

def test_existing_translations_are_never_overwritten(client, admin, monkeypatch):
    rooms = run(_seed_default())

    # A hostile table: the model returns a translation for EVERY name,
    # including the ones that are already filled in.
    hostile = ProviderStub(
        table={
            "Electrical Room": {"ar": "س", "he": "ח"},
            "Storage": {"ar": "مخزن", "he": "OVERWRITTEN"},
            "Reception": {"ar": "OVERWRITTEN", "he": "OVERWRITTEN"},
            "Cafe Aroma": {"ar": "OVERWRITTEN", "he": "OVERWRITTEN"},
        }
    )
    monkeypatch.setattr(
        room_name_translation_service, "call_translation_provider", hostile
    )

    apply_now(client, admin)

    assert room_names(rooms["partial"].id)["he"] == "מחסן ידני"
    assert room_names(rooms["complete"].id) == {
        "en": "Reception",
        "ar": "الاستقبال",
        "he": "קבלה",
    }


def test_the_merge_itself_refuses_to_overwrite_or_blank(client):
    """
    build_proposal already declines to propose a language that is filled,
    so the endpoint test above passes even if this second layer is
    removed. This pins the second layer down directly: hand it a
    deliberately hostile proposal — one that tries to replace both
    existing translations AND the English name, and to blank a third —
    and it must still write only what was empty.
    """

    room = Room(
        building_id=BUILDING_ID,
        name_en="Reception",
        names={"en": "Reception", "ar": None, "he": "קבלה"},
    )

    hostile = {
        "proposed": {
            "en": "REPLACED",
            "ar": "الاستقبال",
            "he": "REPLACED",
        },
        "will_change": ["en", "ar", "he"],
    }

    update = updates_for_room(room, hostile)

    assert update["applied"] == ["ar"]
    assert update["names"] == {
        "en": "Reception",
        "ar": "الاستقبال",
        "he": "קבלה",
    }


def test_the_merge_never_blanks_a_value_when_the_proposal_is_empty(client):
    room = Room(
        building_id=BUILDING_ID,
        name_en="Reception",
        names={"en": "Reception", "ar": "الاستقبال", "he": "קבלה"},
    )

    update = updates_for_room(room, {"proposed": {"ar": "", "he": None, "en": None}})

    assert update["applied"] == []
    assert update["names"] == {
        "en": "Reception",
        "ar": "الاستقبال",
        "he": "קבלה",
    }


# =========================================================
# 6. A stale preview cannot overwrite an edit made after it
# =========================================================

def test_apply_re_reads_each_room_so_a_stale_proposal_cannot_win(
    client, admin, monkeypatch
):
    rooms = run(_seed_default())
    target_id = rooms["untranslated"].id

    monkeypatch.setattr(
        room_name_translation_service, "call_translation_provider", ProviderStub()
    )

    # Simulates the real race: the proposals have already been built from
    # a snapshot in which `ar` was empty, and only THEN does someone type
    # a correct Arabic name in the admin UI. The proposal still in flight
    # carries the AI's value for `ar`.
    #
    # Hooked onto Room.get because that is the endpoint's re-read — which
    # means the edit lands strictly after the proposal was computed and
    # strictly before the write, which is exactly the window the re-read
    # exists to close.
    original_get = Room.get
    state = {"edited": False}

    async def racing_get(document_id, *args, **kwargs):
        if not state["edited"]:
            state["edited"] = True
            current = await original_get(target_id)
            current.names = dict(current.names or {})
            current.names["ar"] = "اسم يدوي"
            await current.save()

        return await original_get(document_id, *args, **kwargs)

    monkeypatch.setattr(Room, "get", racing_get)

    body = apply_now(client, admin).json()

    monkeypatch.undo()
    assert state["edited"], "the racing edit never ran"

    final = room_names(target_id)
    assert final["ar"] == "اسم يدوي", "the hand-typed value was overwritten"
    # Hebrew was still empty at write time, so it is filled normally.
    assert final["he"] == "חדר חשמל"

    detail = {item["room_id"]: item for item in body["applied_detail"]}
    assert detail[str(target_id)]["applied_languages"] == ["he"]


# =========================================================
# 7. English is never modified
# =========================================================

def test_english_names_survive_untouched(client, admin, provider, monkeypatch):
    rooms = run(_seed_default())

    # Even if the provider tries to return an `en` key, it cannot reach
    # the database: `en` is not a translatable language here.
    monkeypatch.setattr(
        room_name_translation_service,
        "call_translation_provider",
        ProviderStub(
            table={
                "Electrical Room": {
                    "ar": "غرفة الكهرباء",
                    "he": "חדר חשמל",
                    "en": "REPLACED",
                }
            }
        ),
    )

    apply_now(client, admin)

    room = run(Room.get(rooms["untranslated"].id))
    assert room.names["en"] == "Electrical Room"
    assert room.name_en == "Electrical Room"


# =========================================================
# 8-10. The navigation graph and the QR codes are untouched
# =========================================================

def test_no_route_point_is_written(client, admin, provider):
    run(_seed_default())
    before = snapshot()[RoutePoint.get_collection_name()]

    apply_now(client, admin)

    assert snapshot()[RoutePoint.get_collection_name()] == before


def test_no_route_edge_is_written(client, admin, provider):
    run(_seed_default())
    before = snapshot()[RouteEdge.get_collection_name()]

    apply_now(client, admin)

    assert snapshot()[RouteEdge.get_collection_name()] == before


def test_no_location_code_is_written(client, admin, provider):
    run(_seed_default())
    before = snapshot()[LocationCode.get_collection_name()]

    apply_now(client, admin)

    assert snapshot()[LocationCode.get_collection_name()] == before


def test_the_translation_module_cannot_reach_the_graph_at_all(client):
    """
    Static guarantee behind the three tests above: the service does not
    import RoutePoint, RouteEdge or LocationCode, so no future edit to it
    can write one by accident.
    """

    source = open(room_name_translation_service.__file__, encoding="utf-8").read()
    tree = ast.parse(source)

    imported = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add(node.module or "")
            imported.update(alias.name for alias in node.names)

    # Not a single models.* import — the service is structurally unable to
    # load, let alone write, any document type.
    assert not any(name.startswith("models") for name in imported), sorted(imported)

    referenced = {
        node.id for node in ast.walk(tree) if isinstance(node, ast.Name)
    } | {
        node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)
    }

    for forbidden in ("RoutePoint", "RouteEdge", "LocationCode", "Map", "Building"):
        assert forbidden not in referenced, f"the service references {forbidden}"

    # And it never calls a Beanie persistence method on anything.
    # (`update`/`set` are deliberately not in this list — they are also
    # plain dict methods, which this module does use on its own local
    # dictionaries; the no-models-imported assertion above is what rules
    # out a document ever being on the receiving end of one.)
    called = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }

    for forbidden in ("save", "insert", "delete", "replace", "save_changes"):
        assert forbidden not in called, f"the service calls .{forbidden}()"


# =========================================================
# 11. No room is created, deleted or re-created
# =========================================================

def test_no_room_is_created_or_deleted(client, admin, provider):
    rooms = run(_seed_default())
    before_ids = sorted(str(room.id) for room in rooms.values())

    apply_now(client, admin)

    after = run(Room.find_all().to_list())
    assert sorted(str(room.id) for room in after) == before_ids


# =========================================================
# 12. Every other Room field survives
# =========================================================

def test_placement_and_routing_fields_survive(client, admin, provider):
    rooms = run(_seed_default())
    original = run(Room.get(rooms["untranslated"].id))

    apply_now(client, admin)

    updated = run(Room.get(rooms["untranslated"].id))

    for field in (
        "building_id",
        "map_id",
        "floor",
        "room_type",
        "room_number",
        "route_point_id",
        "parent_room_id",
        "x",
        "y",
        "name_en",
        "name_local",
        "is_active",
        "created_at",
        "semantic_publication_id",
    ):
        assert getattr(updated, field) == getattr(original, field), field


# =========================================================
# 13. Scoping
# =========================================================

def test_scoping_by_map_id_leaves_other_maps_alone(client, admin, provider):
    run(_seed_default())
    other = run(
        _make_room(
            name_en="Storage",
            names={"en": "Storage", "ar": None, "he": None},
            map_id=OTHER_MAP_ID,
        )
    )

    body = apply_now(client, admin, map_id=MAP_ID).json()

    assert body["scope"] == {"building_id": None, "map_id": MAP_ID}
    assert all(item["map_id"] == MAP_ID for item in body["proposals"])
    assert room_names(other.id)["ar"] is None


def test_scoping_by_building_id_leaves_other_buildings_alone(client, admin, provider):
    run(_seed_default())
    other = run(
        _make_room(
            name_en="Storage",
            names={"en": "Storage", "ar": None, "he": None},
            building_id=OTHER_BUILDING_ID,
            map_id=OTHER_MAP_ID,
        )
    )

    body = apply_now(client, admin, building_id=BUILDING_ID).json()

    assert all(item["building_id"] == BUILDING_ID for item in body["proposals"])
    assert room_names(other.id)["ar"] is None


# =========================================================
# 14. Idempotent
# =========================================================

def test_running_apply_twice_changes_nothing_the_second_time(client, admin, provider):
    run(_seed_default())

    first = apply_now(client, admin).json()
    assert first["rooms_updated"] == 2

    after_first = snapshot()

    second = apply_now(client, admin).json()
    assert second["rooms_updated"] == 0
    assert second["proposals"] == []

    assert_untouched(after_first, snapshot())


# =========================================================
# 15. Malformed / partial AI output cannot damage data
# =========================================================

@pytest.mark.parametrize(
    "raw",
    [
        "not json at all",
        "[]",
        '{"translations": {}}',
        '{"nope": []}',
        "",
    ],
)
def test_malformed_provider_output_is_rejected_outright(raw):
    with pytest.raises(RoomNameTranslationError):
        parse_translation_payload(raw)


def test_empty_and_null_values_never_become_proposals():
    parsed = parse_translation_payload(
        '{"translations": ['
        '  {"source": "Storage", "ar": "", "he": "   "},'
        '  {"source": "Lobby", "ar": null, "he": null},'
        '  {"nosource": true},'
        '  "junk",'
        '  {"source": "Lab 204", "ar": "مختبر 204", "he": "מעבדה 204"}'
        ']}'
    )

    assert parsed["Storage"] == {"ar": None, "he": None}
    assert parsed["Lobby"] == {"ar": None, "he": None}
    assert parsed["Lab 204"]["he"] == "מעבדה 204"

    room = Room(
        building_id=BUILDING_ID,
        name_en="Storage",
        names={"en": "Storage", "ar": None, "he": None},
    )
    assert build_proposal(room, parsed) is None


def test_a_partial_response_only_affects_the_rooms_it_covers(client, admin, monkeypatch):
    rooms = run(_seed_default())

    # The model answered for one name and silently dropped the other.
    monkeypatch.setattr(
        room_name_translation_service,
        "call_translation_provider",
        ProviderStub(table={"Electrical Room": {"ar": "غرفة الكهرباء", "he": None}}),
    )

    body = apply_now(client, admin).json()

    assert body["rooms_updated"] == 1
    assert room_names(rooms["untranslated"].id) == {
        "en": "Electrical Room",
        "ar": "غرفة الكهرباء",
        "he": None,
    }
    # Untouched: no entry came back for it.
    assert room_names(rooms["partial"].id)["ar"] is None


def test_a_provider_failure_writes_nothing(client, admin, monkeypatch):
    run(_seed_default())
    before = snapshot()

    monkeypatch.setattr(
        room_name_translation_service,
        "call_translation_provider",
        ProviderStub(
            error=RoomNameTranslationError("missing_api_key", "not configured")
        ),
    )

    body = apply_now(client, admin).json()

    assert body["error"] == "missing_api_key"
    assert body["applied"] is False
    assert body["rooms_updated"] == 0
    assert_untouched(before, snapshot())


# =========================================================
# 16. One batched request, never one per room
# =========================================================

def test_one_batched_request_covers_every_room(client, admin, provider):
    run(_seed_default())

    # 30 more rooms, all sharing two English names between them.
    for index in range(30):
        run(
            _make_room(
                name_en="Storage" if index % 2 else "Electrical Room",
                names={
                    "en": "Storage" if index % 2 else "Electrical Room",
                    "ar": None,
                    "he": None,
                },
            )
        )

    apply_now(client, admin)

    assert len(provider.calls) == 1, "the provider was called more than once"

    # And it was asked about DISTINCT names only — 34 candidate rooms
    # collapse to 3 strings.
    assert sorted(provider.calls[0]) == ["Cafe Aroma", "Electrical Room", "Storage"]


def test_collect_source_names_deduplicates_and_skips_complete_rooms():
    rooms = [
        Room(building_id=BUILDING_ID, name_en="Storage", names={"en": "Storage"}),
        Room(building_id=BUILDING_ID, name_en="Storage", names={"en": "Storage"}),
        Room(
            building_id=BUILDING_ID,
            name_en="Reception",
            names={"en": "Reception", "ar": "الاستقبال", "he": "קבלה"},
        ),
        # Legacy room, no `names` object at all — name_en is the source.
        Room(building_id=BUILDING_ID, name_en="Lab 204"),
    ]

    assert collect_source_names(rooms) == ["Storage", "Lab 204"]


# =========================================================
# 17. Numbers/codes preserved, brands declined
# =========================================================

def test_room_numbers_and_identifiers_are_stored_exactly_as_returned(
    client, admin, monkeypatch
):
    numbered = run(
        _make_room(
            name_en="Lab 204-B",
            names={"en": "Lab 204-B", "ar": None, "he": None},
            room_number="204-B",
        )
    )

    monkeypatch.setattr(
        room_name_translation_service,
        "call_translation_provider",
        ProviderStub(
            table={"Lab 204-B": {"ar": "مختبر 204-B", "he": "מעבדה 204-B"}}
        ),
    )

    apply_now(client, admin)

    room = run(Room.get(numbered.id))
    assert room.names["ar"] == "مختبر 204-B"
    assert room.names["he"] == "מעבדה 204-B"
    assert room.room_number == "204-B"


def test_a_declined_business_name_is_left_in_english(client, admin, provider):
    rooms = run(_seed_default())

    apply_now(client, admin)

    # The stub returns {"ar": None, "he": None} for "Cafe Aroma" — the
    # room keeps falling back to English, which is the safe outcome.
    assert room_names(rooms["branded"].id) == {
        "en": "Cafe Aroma",
        "ar": None,
        "he": None,
    }


def test_the_prompt_forbids_a_hard_coded_dictionary_of_answers():
    """
    The requirement is a general translator, not a lookup table. The
    prompt must say its examples are open-ended, and the module must not
    ship a name->translation mapping of its own.
    """

    source = open(room_name_translation_service.__file__, encoding="utf-8").read()

    assert "not a closed list" in source
    # No Arabic or Hebrew literal anywhere in the service — any such
    # string would be a hard-coded translation.
    assert not any("֐" <= ch <= "ۿ" for ch in source)


# =========================================================
# 18. Authorization
# =========================================================

def test_a_regular_user_cannot_call_it(client):
    from tests.test_api_integration import make_invitation_code, signup

    code = make_invitation_code(client, code="QR-TRANSREG1", role="regular_user")
    token = signup(client, code, email="regular-translate@example.com").json()[
        "access_token"
    ]

    response = client.post(ENDPOINT, headers=auth_headers(token))
    assert response.status_code in (401, 403)


def test_an_anonymous_caller_cannot_call_it(client):
    response = client.post(ENDPOINT)
    assert response.status_code in (401, 403)


# =========================================================
# 19. Semantic analysis is never re-run
# =========================================================

def test_no_semantic_analysis_is_created_or_re_run(client, admin, provider):
    run(_seed_default())

    apply_now(client, admin)

    assert run(SemanticMapAnalysis.find_all().to_list()) == []


# =========================================================
# 20. The pure layer never touches the database
# =========================================================

def test_build_proposal_and_updates_for_room_are_pure(client, admin, provider):
    rooms = run(_seed_default())
    room = run(Room.get(rooms["untranslated"].id))
    before = snapshot()

    proposal = build_proposal(room, dict(DEFAULT_TRANSLATIONS))
    assert proposal["will_change"] == ["ar", "he"]

    update = updates_for_room(room, proposal)
    assert update["applied"] == ["ar", "he"]
    assert update["names"]["en"] == "Electrical Room"

    assert_untouched(before, snapshot())


# =========================================================
# 21. Descriptive labels vs code-only labels
#
# Real floor-plan labels are a mixture. "WOMEN RRW 315" says what the
# space is in ordinary words and merely carries an architectural code
# along with it — that is translatable, and the code rides through
# untouched. "TEL 312" says nothing translatable at all: TEL might be
# telephone, telecom, telemetry or a draughtsman's private shorthand, and
# a confident-looking wrong expansion is the one error nobody would ever
# catch by looking at the screen.
#
# So the model classifies (`kind`), and the code acts on that verdict
# deterministically: a code_only label is preserved EXACTLY, taken from
# the source string rather than from anything the model wrote.
# =========================================================

DESCRIPTIVE_REPLY = json.dumps(
    {
        "translations": [
            {
                "source": "WOMEN RRW 315",
                "kind": "descriptive",
                "ar": "دورة مياه النساء RRW 315",
                "he": "שירותי נשים RRW 315",
            },
            {
                "source": "MEN RRM 309",
                "kind": "descriptive",
                "ar": "دورة مياه الرجال RRM 309",
                "he": "שירותי גברים RRM 309",
            },
        ]
    },
    ensure_ascii=False,
)


def test_a_descriptive_label_is_translated_and_keeps_its_code(client):
    parsed = parse_translation_payload(DESCRIPTIVE_REPLY)

    assert parsed["WOMEN RRW 315"]["ar"] == "دورة مياه النساء RRW 315"
    assert parsed["WOMEN RRW 315"]["he"] == "שירותי נשים RRW 315"
    assert parsed["MEN RRM 309"]["ar"] == "دورة مياه الرجال RRM 309"
    assert parsed["MEN RRM 309"]["he"] == "שירותי גברים RRM 309"

    # The code token survives in both scripts — this is the property that
    # makes the translated sign still match the door.
    for source, code in (("WOMEN RRW 315", "RRW 315"), ("MEN RRM 309", "RRM 309")):
        for lang in ("ar", "he"):
            assert code in parsed[source][lang], (source, lang)


def test_a_code_only_label_is_preserved_exactly(client):
    reply = json.dumps(
        {
            "translations": [
                {"source": "TEL 312", "kind": "code_only", "ar": None, "he": None},
                {"source": "ELEC310", "kind": "code_only", "ar": None, "he": None},
            ]
        }
    )

    parsed = parse_translation_payload(reply)

    assert parsed["TEL 312"] == {"ar": "TEL 312", "he": "TEL 312"}
    assert parsed["ELEC310"] == {"ar": "ELEC310", "he": "ELEC310"}


@pytest.mark.parametrize(
    "label",
    [
        "TEL 312",
        "ELEC310",
        "AHU-4/B",
        "MDF  204",          # doubled space
        "RM.117A",
        "E/M 3",
    ],
)
def test_code_only_preservation_is_byte_exact(client, label):
    """
    Whatever the label's spacing, punctuation or casing, the preserved
    value is the input string itself — not a normalized, trimmed or
    re-spaced version of it.
    """

    reply = json.dumps(
        {"translations": [{"source": label, "kind": "code_only", "ar": None, "he": None}]}
    )

    parsed = parse_translation_payload(reply)

    assert parsed[label]["ar"] == label
    assert parsed[label]["he"] == label


def test_a_code_only_entry_discards_an_expansion_the_model_tried_anyway(client):
    """
    The critical guard. If the model classifies correctly but then also
    fills in a guessed expansion — "TEL" as telephone, say — that guess
    must never reach the database. The code takes the source, not the
    model's text.
    """

    reply = json.dumps(
        {
            "translations": [
                {
                    "source": "TEL 312",
                    "kind": "code_only",
                    "ar": "غرفة الهاتف 312",
                    "he": "חדר טלפון 312",
                }
            ]
        },
        ensure_ascii=False,
    )

    parsed = parse_translation_payload(reply)

    assert parsed["TEL 312"] == {"ar": "TEL 312", "he": "TEL 312"}


def test_an_untranslatable_label_still_produces_no_proposal(client):
    reply = json.dumps(
        {
            "translations": [
                {"source": "Cafe Aroma", "kind": "untranslatable", "ar": None, "he": None}
            ]
        }
    )

    parsed = parse_translation_payload(reply)
    assert parsed["Cafe Aroma"] == {"ar": None, "he": None}

    room = Room(
        building_id=BUILDING_ID,
        name_en="Cafe Aroma",
        names={"en": "Cafe Aroma", "ar": None, "he": None},
    )
    assert build_proposal(room, parsed) is None


def test_a_missing_or_unknown_kind_falls_back_to_the_previous_behavior(client):
    """
    `kind` is additive. A reply that predates it — or that carries a value
    this code does not recognize — must behave exactly as this parser did
    before the field existed, never as code_only.
    """

    reply = json.dumps(
        {
            "translations": [
                {"source": "Storage", "ar": "مخزن", "he": "מחסן"},
                {"source": "Lobby", "kind": "something_new", "ar": None, "he": None},
                {"source": "Kitchen", "kind": "", "ar": "مطبخ", "he": "מטבח"},
            ]
        },
        ensure_ascii=False,
    )

    parsed = parse_translation_payload(reply)

    assert parsed["Storage"] == {"ar": "مخزن", "he": "מחסן"}
    # Not preserved as "Lobby" — an unknown kind is not code_only.
    assert parsed["Lobby"] == {"ar": None, "he": None}
    assert parsed["Kitchen"]["ar"] == "مطبخ"


def test_the_kind_value_is_matched_case_insensitively(client):
    reply = json.dumps(
        {"translations": [{"source": "TEL 312", "kind": " Code_Only ", "ar": None, "he": None}]}
    )

    assert parse_translation_payload(reply)["TEL 312"]["he"] == "TEL 312"


# ── End to end, through the real endpoint ────────────────────────────────

def test_apply_stores_translations_and_preserved_labels_side_by_side(
    client, admin, monkeypatch
):
    run(_seed_graph())

    women = run(
        _make_room(
            name_en="WOMEN RRW 315",
            names={"en": "WOMEN RRW 315", "ar": None, "he": None},
        )
    )
    tel = run(
        _make_room(name_en="TEL 312", names={"en": "TEL 312", "ar": None, "he": None})
    )
    elec = run(
        _make_room(name_en="ELEC310", names={"en": "ELEC310", "ar": None, "he": None})
    )

    # The stub returns what parse_translation_payload would have produced
    # from a correctly-classified reply.
    monkeypatch.setattr(
        room_name_translation_service,
        "call_translation_provider",
        ProviderStub(
            table={
                "WOMEN RRW 315": {
                    "ar": "دورة مياه النساء RRW 315",
                    "he": "שירותי נשים RRW 315",
                },
                "TEL 312": {"ar": "TEL 312", "he": "TEL 312"},
                "ELEC310": {"ar": "ELEC310", "he": "ELEC310"},
            }
        ),
    )

    body = apply_now(client, admin).json()
    assert body["rooms_updated"] == 3

    assert room_names(women.id) == {
        "en": "WOMEN RRW 315",
        "ar": "دورة مياه النساء RRW 315",
        "he": "שירותי נשים RRW 315",
    }
    assert room_names(tel.id) == {"en": "TEL 312", "ar": "TEL 312", "he": "TEL 312"}
    assert room_names(elec.id) == {"en": "ELEC310", "ar": "ELEC310", "he": "ELEC310"}


def test_a_preserved_label_is_idempotent_and_never_re_proposed(
    client, admin, monkeypatch
):
    run(_seed_graph())
    tel = run(
        _make_room(name_en="TEL 312", names={"en": "TEL 312", "ar": None, "he": None})
    )

    monkeypatch.setattr(
        room_name_translation_service,
        "call_translation_provider",
        ProviderStub(table={"TEL 312": {"ar": "TEL 312", "he": "TEL 312"}}),
    )

    assert apply_now(client, admin).json()["rooms_updated"] == 1

    after_first = snapshot()

    second = apply_now(client, admin).json()
    assert second["rooms_updated"] == 0
    assert second["proposals"] == []

    assert_untouched(after_first, snapshot())
    assert room_names(tel.id)["ar"] == "TEL 312"


def test_the_preview_shows_a_preserved_label_as_an_explicit_change(
    client, admin, monkeypatch
):
    """
    A preserved label is a real write, not a no-op, so the preview must
    show it as one — an admin reading the proposals should be able to see
    that TEL 312 is being stored verbatim rather than silently skipped.
    """

    run(_seed_graph())
    tel = run(
        _make_room(name_en="TEL 312", names={"en": "TEL 312", "ar": None, "he": None})
    )

    monkeypatch.setattr(
        room_name_translation_service,
        "call_translation_provider",
        ProviderStub(table={"TEL 312": {"ar": "TEL 312", "he": "TEL 312"}}),
    )

    body = preview(client, admin).json()
    proposal = next(p for p in body["proposals"] if p["room_id"] == str(tel.id))

    assert sorted(proposal["will_change"]) == ["ar", "he"]
    assert proposal["proposed"]["ar"] == "TEL 312"
    assert proposal["proposed"]["he"] == "TEL 312"
    # Still a preview: nothing was written.
    assert room_names(tel.id)["ar"] is None


# ── The rule lives in the prompt, not in a table ─────────────────────────

def test_the_prompt_states_the_rule_without_listing_abbreviations(client):
    """
    The descriptive/code-only decision must be expressed as a RULE the
    model applies to any label, never as a list of known abbreviations —
    the next building's drawings will use different ones.
    """

    # What the MODEL actually receives — explanatory comments elsewhere in
    # the module are not instructions and are deliberately out of scope.
    prompt = room_name_translation_service.TRANSLATION_SYSTEM_PROMPT

    # The rule is stated, as a rule.
    assert KIND_DESCRIPTIVE in prompt
    assert KIND_CODE_ONLY in prompt
    assert KIND_UNTRANSLATABLE in prompt
    assert "not a closed list" in prompt

    # No abbreviation from a real drawing appears in the prompt at all —
    # naming one would make it a lookup entry for that abbreviation and
    # leave every other building's shorthand unhandled.
    for abbreviation in ("TEL", "ELEC", "RRW", "RRM", "MDF", "AHU"):
        assert not re.search(rf"\b{abbreviation}\b", prompt), abbreviation

    # And no expansion of one, which is precisely the guess the model is
    # being told not to make.
    for expansion in ("telephone", "telecom", "telemetry"):
        assert expansion not in prompt.lower(), expansion

    # And no answers: no Arabic or Hebrew text anywhere in the service.
    source = open(room_name_translation_service.__file__, encoding="utf-8").read()
    assert not any("֐" <= ch <= "ۿ" for ch in source)


def test_the_request_chunk_cannot_outgrow_the_output_budget(client):
    """
    Each reply entry now carries a source echo, two non-Latin
    translations and a kind. A chunk that cannot fit in MAX_OUTPUT_TOKENS
    gets cut off mid-JSON, which this code correctly refuses to parse —
    but that turns a large estate into a hard failure instead of a slower
    run, so the chunk size has to stay inside the budget.
    """

    worst_case_tokens_per_entry = 90

    assert (
        room_name_translation_service.MAX_NAMES_PER_REQUEST
        * worst_case_tokens_per_entry
        < room_name_translation_service.MAX_OUTPUT_TOKENS
    ), "a full chunk could overflow the reply budget and be truncated"
