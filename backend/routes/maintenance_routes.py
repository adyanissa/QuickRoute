"""
One-off, admin-triggered data-consistency maintenance operations.

Kept as an explicit authenticated endpoint (rather than a startup
migration) so it never runs unexpectedly against production data — an
admin has to deliberately call it, can see exactly what it did from the
response, and can call it again safely since every operation here is
idempotent.
"""

from datetime import datetime
from typing import Optional

from beanie import PydanticObjectId
from fastapi import APIRouter, Depends

from core.auth_deps import require_global_admin
from models.building_model import Building
from models.location_code_model import LocationCode
from models.map_group_model import MapGroup
from models.map_model import Map
from models.room_model import Room
from models.route_point_model import RoutePoint
from models.user_model import User
from schemas.localization_schema import localized_text_to_dict
from services.building_service import find_or_create_building
from services.map_group_service import generate_unique_group_code


router = APIRouter(
    prefix="/api/maintenance",
    tags=["Maintenance"],
)


@router.post("/backfill-buildings")
async def backfill_buildings(
    _admin: User = Depends(require_global_admin),
):
    """
    For every Map missing a building_id, find-or-create a Building from
    its campus (preferred) or title, assign it, then propagate the same
    building_id onto every RoutePoint of that map that doesn't already
    have one. Never touches a map/point that already has a building_id,
    never deletes anything, and never hard-codes any specific map/point
    ID — it generically fixes every map currently missing this
    relationship, which is exactly what running it against the real
    "QuickRoute Mall - Floor 1" map (campus "QuickRoute Mall") does today,
    without that map's ID appearing anywhere in this code.

    Idempotent: a map with building_id already set, or a point that
    already has one, is left untouched on every subsequent run — so
    running this twice produces the same end state as running it once,
    with zero duplicate buildings (find_or_create_building's unique
    normalized_name index guarantees that even under concurrent calls).
    """

    maps_missing_building = await Map.find(
        {"building_id": None}
    ).to_list()

    buildings_touched = {}
    maps_updated = 0
    points_updated = 0

    for map_item in maps_missing_building:
        building_name = (map_item.campus or map_item.title or "").strip()

        if not building_name:
            continue

        building = await find_or_create_building(
            building_name,
            campus=map_item.campus,
        )

        building_id = str(building.id)
        buildings_touched[building_id] = building.name_en

        map_item.building_id = building_id
        map_item.updated_at = datetime.utcnow()
        await map_item.save()
        maps_updated += 1

        points_missing_building = await RoutePoint.find(
            {
                "map_id": str(map_item.id),
                "building_id": None,
            }
        ).to_list()

        for point in points_missing_building:
            point.building_id = building_id
            point.updated_at = datetime.utcnow()
            await point.save()
            points_updated += 1

    # Validation pass (Part 8) — report inconsistencies rather than
    # silently rewriting them, since fixing a genuine mismatch (as opposed
    # to just filling in a missing value) is a judgment call for an admin,
    # not something a maintenance script should guess at.
    rooms_with_missing_building = 0

    for room in await Room.find_all().to_list():
        building = await Building.get(_try_object_id(room.building_id))
        if not building:
            rooms_with_missing_building += 1

    location_codes_inconsistent = 0

    for code in await LocationCode.find_all().to_list():
        route_point = await RoutePoint.get(
            _try_object_id(code.route_point_id)
        )

        if not route_point or route_point.map_id != code.map_id:
            location_codes_inconsistent += 1
            continue

        if (
            route_point.building_id
            and route_point.building_id != code.building_id
        ):
            location_codes_inconsistent += 1

    return {
        "maps_updated": maps_updated,
        "points_updated": points_updated,
        "buildings_created_or_reused": buildings_touched,
        "rooms_with_missing_building": rooms_with_missing_building,
        "location_codes_inconsistent": location_codes_inconsistent,
    }


@router.post("/backfill-map-groups")
async def backfill_map_groups(
    _admin: User = Depends(require_global_admin),
):
    """
    Backward-compatibility backfill for the multi-floor Map Groups
    feature (see models/map_group_model.py). Every pre-existing Map
    document created before this feature has `map_group_id = None`, and
    keeps working completely unchanged either way — grouping is optional,
    never required for a Map to function. This operation is a convenience
    for admins who want an old map to also show up in the new grouped Map
    Management UI: for every Map still missing a map_group_id (and already
    having a building_id — run backfill-buildings first for maps that
    don't), it creates one brand-new one-floor MapGroup derived only from
    that single map's own building_id/campus/title/address/description,
    and links that one map to it.

    Deliberately never merges two or more pre-existing, already-separate
    Map documents into one shared group automatically, even if they share
    a building_id — the data as it stands today does not say whether two
    such maps are genuinely different floors of one indoor space or two
    unrelated maps that merely happen to belong to the same building, and
    guessing that relationship risks fabricating a structure that isn't
    real. Every backfilled group therefore has exactly one floor, matching
    exactly what existed before — an admin can still explicitly add more
    floors to it afterwards through the normal "Add Floor" flow.

    Idempotent: a map that already has a map_group_id (whether from a
    prior backfill run or a normal multi-floor upload) is left completely
    untouched on every subsequent run. Never hard-codes any specific
    map/building/group ID.
    """

    maps_missing_group = await Map.find({"map_group_id": None}).to_list()

    groups_created = 0
    maps_updated = 0
    maps_skipped_no_building = 0

    for map_item in maps_missing_group:
        if not map_item.building_id:
            # Fix with backfill-buildings first — a MapGroup always needs
            # a real building_id, and this operation never invents one.
            maps_skipped_no_building += 1
            continue

        building = await Building.get(_try_object_id(map_item.building_id))
        base_name = (
            map_item.campus
            or (building.name_en if building else None)
            or map_item.title
            or "Indoor Map"
        ).strip()

        group_name = (
            base_name
            if base_name.lower().endswith("indoor map")
            else f"{base_name} Indoor Map"
        )

        code = await generate_unique_group_code(group_name)

        new_group = MapGroup(
            building_id=map_item.building_id,
            name=group_name,
            code=code,
            description=map_item.description,
            campus=map_item.campus,
            address=map_item.address,
        )
        await new_group.insert()
        groups_created += 1

        map_item.map_group_id = str(new_group.id)
        # A one-floor group's single map is assumed to be its ground floor
        # when no floor was ever recorded for it — never overwrites a
        # floor value that already exists.
        if map_item.floor is None:
            map_item.floor = 0
        map_item.updated_at = datetime.utcnow()
        await map_item.save()
        maps_updated += 1

    return {
        "groups_created": groups_created,
        "maps_updated": maps_updated,
        "maps_skipped_no_building": maps_skipped_no_building,
    }


@router.post("/backfill-room-names")
async def backfill_room_names(
    dry_run: bool = True,
    _admin: User = Depends(require_global_admin),
):
    """
    Safe, optional, idempotent backfill for the multilingual `names`
    field added to Room (see models/room_model.py and the multilingual
    content spec, Section 12: "Legacy Data and Safe Migration").

    For every Room whose `names` is still None (i.e. it predates this
    field), this copies ONLY its existing legacy `name_en` (and
    `name_local`, if present) into the new `names` structure — never
    invents an Arabic or Hebrew translation, never calls any AI/
    translation service, and never overwrites a `names` value that is
    already set (even a partially-filled one) on a subsequent run. A
    Room's actual API response already resolves correctly without this
    backfill ever being run, via get_localized_text()'s legacy-name
    fallback — this is purely a convenience so `names` is explicitly
    populated going forward, not a correctness requirement.

    - `dry_run=True` (the default) reports exactly what WOULD change
      without writing anything — safe to call repeatedly to inspect
      current state.
    - `dry_run=False` performs the actual, idempotent update.
    - Never runs automatically (no startup hook calls this) and is
      admin-gated like every other maintenance endpoint in this file.
    """

    rooms_missing_names = await Room.find({"names": None}).to_list()

    would_update = 0
    updated = 0
    room_ids: list[str] = []

    for room in rooms_missing_names:
        if not room.name_en and not room.name_local:
            continue

        would_update += 1
        room_ids.append(str(room.id))

        if dry_run:
            continue

        # name_local is deliberately NOT assumed to be any particular
        # one of ar/he — this codebase's existing name_local convention
        # doesn't record which language it is, so it is intentionally
        # left out of the structured `names` object here rather than
        # guessed into the wrong language slot. Only the known-English
        # name_en is safely backfillable into names.en.
        room.names = localized_text_to_dict({"en": room.name_en})
        room.updated_at = datetime.utcnow()
        await room.save()
        updated += 1

    return {
        "dry_run": dry_run,
        "rooms_missing_names_field": len(rooms_missing_names),
        "rooms_that_would_be_updated": would_update,
        "rooms_updated": updated,
        "room_ids": room_ids,
    }


def _try_object_id(value: Optional[str]):
    if not value:
        return None

    try:
        return PydanticObjectId(value)
    except Exception:
        return None
