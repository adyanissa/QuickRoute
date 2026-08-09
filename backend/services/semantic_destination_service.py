"""
"Approved Semantic Analysis -> Automatic Destinations and Nested-Room
Navigation" — Stage 1 of the two-stage workflow described in the task
spec: turns admin-approved semantic-analysis places/facilities into real
Room + destination RoutePoint documents (idempotently), and records
explicit nested-room relationships (Room.parent_room_id /
RoutePoint.allow_transit_through) once an admin has confirmed them.

Deliberately does NOT create any RouteEdge/RouteConnection — Stage 2
("create the correct access connections", both the ordinary Room/Store ->
Hallway/Junction case and the nested Outer-Room -> Inner-Room case) is the
existing, separately-updated "Auto Connect Destinations to Corridors"
feature (see services/auto_connect_destinations_service.py, which this
task extends to understand an approved nested parent). This mirrors the
admin workflow the spec itself describes (Section 18): "6. Confirm
creation" (this module) happens before "7. Open Auto Connect
Destinations... 9. Apply accepted connections" (that module).

ARCHITECTURAL FACT (see schemas/semantic_destination_schema.py's own
docstring for the full explanation): semantic-analysis data has NO
coordinates/geometry anywhere by design. A genuinely new destination's
map position can only ever come from an admin manually placing it during
preview review (or from reusing an already-placed RoutePoint) — never from
AI-derived door/boundary/centroid data, because none exists.

Never touches: Dijkstra/shortest-path logic, existing RouteEdges, Maps,
Map calibration, vertical connectors, QR/location codes, authentication.

FLOOR-CODE DEFENSE-IN-DEPTH: Room.floor / RoutePoint.floor below have
always been set from map_item.floor (the authoritative physical-floor
field on the Map document) — that part of "Fix semantic floor
identifiers" needed no change. What this module DOES add is
_floor_code_mismatch: apply_semantic_destinations recomputes the
expected `floor_XXX` code itself from map_item.floor and refuses to
create any destinations for a map whose semantic floor entity/links are
still stale, rather than trusting whatever floor_external_id happens to
already be stored (see semantic_publication_service.
compute_authoritative_floor_code / normalize_floor_codes / repair_floor_
codes_for_map for how a stale code gets corrected).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from beanie import PydanticObjectId

from constants.destination_types import ALL_ACCEPTED_DESTINATION_TYPES
from models.map_model import Map
from models.room_model import Room
from models.route_point_model import RoutePoint
from models.semantic_map_publication_model import SemanticMapPublication
from services.point_dedup_service import find_or_create_route_point
from services.semantic_publication_service import compute_authoritative_floor_code


# entity_kind -> (reviewed_result array key, external-id field name).
# Deliberately just places/facilities — see Section 3 of the spec and
# semantic_publication_service.ENTITY_ARRAYS for the full set of entity
# types this codebase recognizes; access_points/public_areas/
# vertical_connections/outdoor_areas/parking_* are never destination
# candidates for this feature (vertical connections are the separate,
# untouched connector workflow).
DESTINATION_ENTITY_ARRAYS: Dict[str, Tuple[str, str]] = {
    "place": ("places", "place_external_id"),
    "facility": ("facilities", "facility_external_id"),
}

_MAX_PARENT_CHAIN_DEPTH = 50


async def _get_publication(
    map_id: str, publication_id: Optional[str]
) -> Optional[SemanticMapPublication]:
    if publication_id:
        return await SemanticMapPublication.find_one(
            {"publication_id": publication_id}
        )
    return await SemanticMapPublication.find_one(
        {"map_id": map_id, "is_active": True}
    )


def _normalize_name(value: Optional[str]) -> str:
    return (value or "").strip().lower()


def _resolve_room_type(
    category: Optional[str], subcategory: Optional[str]
) -> Optional[str]:
    """Only ever maps to a room_type when the AI-detected value is an
    EXACT (case-insensitive) match to a canonical
    constants/destination_types.py value — never a fabricated/guessed
    mapping table, since none exists anywhere else in this codebase."""

    for candidate in (subcategory, category):
        if not candidate:
            continue
        normalized = candidate.strip().lower()
        for accepted in ALL_ACCEPTED_DESTINATION_TYPES:
            if accepted.lower() == normalized:
                return accepted
    return None


def _selectable(item: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
    """Section 4: 'keep the item approved but exclude it from destination
    creation' maps directly onto the already-existing
    administrator_settings.selectable_destination field the semantic
    schema provides — an explicit False here always wins over any AI
    recommendation."""

    settings = item.get("administrator_settings") or {}
    if settings.get("selectable_destination") is False:
        return False, "excluded_by_admin_setting"
    return True, None


def _iter_candidate_items(
    reviewed: Dict[str, Any],
    map_id: str,
    floor_external_id_to_map: Dict[str, str],
    item_filter: Optional[set],
):
    """Yields (entity_kind, item_dict) for every accepted/corrected
    place/facility belonging to this exact map (resolved the same way
    semantic_publication_service._build_semantic_entity_index resolves
    map_id from floor_external_id), optionally narrowed to item_filter.
    Single pass over reviewed_result's in-memory lists — no per-item
    database query, satisfying Section 17's performance requirement."""

    for entity_kind, (array_name, id_field) in DESTINATION_ENTITY_ARRAYS.items():
        for item in reviewed.get(array_name, []) or []:
            if not isinstance(item, dict):
                continue

            item_id = item.get(id_field)
            if not item_id:
                continue
            if item_filter and item_id not in item_filter:
                continue

            review = item.get("review") or {}
            if review.get("status") not in ("accepted", "corrected"):
                continue

            floor_external_id = item.get("floor_external_id")
            if floor_external_id:
                item_map_id = floor_external_id_to_map.get(floor_external_id)
            elif len(set(floor_external_id_to_map.values())) == 1:
                # Single-map publication with an item that never set
                # floor_external_id (schema allows it to be optional) —
                # there is only one possible map it could belong to, so
                # this is not a guess.
                item_map_id = next(iter(floor_external_id_to_map.values()))
            else:
                item_map_id = None

            if item_map_id != map_id:
                continue

            yield entity_kind, item


def _all_item_names_by_id(reviewed: Dict[str, Any]) -> Dict[str, str]:
    """Every place/facility's best-effort display name, keyed by its own
    external id, regardless of review/map status — used only to show a
    human-readable name for a nested-parent candidate that may not itself
    be in the current scan scope. Never used for matching/writes."""

    names: Dict[str, str] = {}
    for _entity_kind, (array_name, id_field) in DESTINATION_ENTITY_ARRAYS.items():
        for item in reviewed.get(array_name, []) or []:
            if not isinstance(item, dict):
                continue
            item_id = item.get(id_field)
            if not item_id:
                continue
            item_names = item.get("names") or {}
            names[item_id] = (
                item_names.get("en")
                or item_names.get("original")
                or item_names.get("ar")
                or item_names.get("he")
                or item_id
            )
    return names


def _floor_map_lookup(publication: SemanticMapPublication) -> Dict[str, str]:
    return {
        link.get("floor_external_id"): link.get("map_id")
        for link in (publication.quickroute_links.get("floor_links") or [])
        if link.get("floor_external_id")
    }


def _floor_code_mismatch(
    floor_to_map: Dict[str, str],
    map_id: str,
    map_item: Map,
) -> Optional[str]:
    """Section 8 defense-in-depth: recompute the expected `floor_XXX` code
    from Map.floor (the one authoritative source) and never trust whatever
    floor_external_id is already stored on this map's floor_links. Returns
    a human-readable error if this map is still linked from a stale/
    incorrect code, None if everything already matches. Publish-time
    normalization (semantic_publication_service.normalize_floor_codes,
    wired into publish_analysis) is expected to prevent this from firing
    on anything published after the floor-code fix landed — this guards
    apply against analyses published/edited before that fix, or
    floor_links edited directly in the database."""

    if map_item.floor is None:
        return None

    expected_code = compute_authoritative_floor_code(map_item.floor)
    this_map_codes = {
        ext_id for ext_id, linked_map_id in floor_to_map.items() if linked_map_id == map_id
    }
    if not this_map_codes or this_map_codes == {expected_code}:
        return None

    stale = sorted(this_map_codes - {expected_code})
    return (
        "This map's semantic floor code is out of date (found "
        f"{stale}, expected '{expected_code}' for physical floor "
        f"{map_item.floor}). Run the admin floor-code repair action for "
        "this map (POST /api/maps/{map_id}/semantic-analysis/repair-floor-codes) "
        "before creating destinations."
    )


async def preview_semantic_destinations(
    map_id: str,
    *,
    item_external_ids: Optional[List[str]] = None,
    lang: str = "en",
) -> dict:
    """Entirely read-only — never calls .insert()/.save()/.delete() on
    anything."""

    summary = {
        "scanned": 0,
        "new_rooms_proposed": 0,
        "new_route_points_proposed": 0,
        "existing_linked_found": 0,
        "updates_proposed": 0,
        "nested_relationships_proposed": 0,
        "needs_location_review": 0,
        "rejected_or_invalid": 0,
        "ambiguous_matches": 0,
        "duplicates_prevented": 0,
    }
    proposals: List[dict] = []

    warnings: List[str] = []

    map_item = await Map.get(PydanticObjectId(map_id))
    if not map_item:
        return {"publication_id": None, "summary": summary, "proposals": proposals, "warnings": warnings}

    publication = await _get_publication(map_id, None)
    if not publication:
        return {"publication_id": None, "summary": summary, "proposals": proposals, "warnings": warnings}

    reviewed = publication.reviewed_result or {}
    floor_to_map = _floor_map_lookup(publication)
    all_names_by_id = _all_item_names_by_id(reviewed)
    item_filter = set(item_external_ids) if item_external_ids else None

    # Section 8, read-only half: preview never blocks (it makes nothing),
    # but it must surface a stale floor code so the admin knows to run the
    # repair action before relying on `floor` proposals below.
    floor_mismatch = _floor_code_mismatch(floor_to_map, map_id, map_item)
    if floor_mismatch:
        warnings.append(floor_mismatch)

    # Single batched read of every Room/RoutePoint already on this map —
    # never one query per semantic item (Section 17).
    existing_rooms = await Room.find({"map_id": map_id}).to_list()
    existing_points = await RoutePoint.find({"map_id": map_id}).to_list()

    rooms_by_semantic_id: Dict[str, Room] = {
        r.semantic_entity_external_id: r
        for r in existing_rooms
        if r.semantic_entity_external_id
    }
    points_by_semantic_id: Dict[str, RoutePoint] = {
        p.semantic_entity_external_id: p
        for p in existing_points
        if p.semantic_entity_external_id
    }
    unlinked_legacy_rooms = [
        r for r in existing_rooms if not r.route_point_id and not r.semantic_entity_external_id
    ]

    for entity_kind, item in _iter_candidate_items(
        reviewed, map_id, floor_to_map, item_filter
    ):
        item_id = item[DESTINATION_ENTITY_ARRAYS[entity_kind][1]]
        summary["scanned"] += 1

        names = item.get("names") or {}
        name_en = names.get("en")
        name_ar = names.get("ar")
        name_he = names.get("he")
        name_original = names.get("original")
        best_name = name_en or name_original or name_ar or name_he or item_id

        selectable, exclusion_reason = _selectable(item)

        proposal: Dict[str, Any] = {
            "semantic_item_id": item_id,
            "entity_kind": entity_kind,
            "map_id": map_id,
            "floor": map_item.floor,
            "name_en": name_en,
            "name_ar": name_ar,
            "name_he": name_he,
            "name_original": name_original,
            "detected_category": item.get("category") or item.get("facility_type"),
            "detected_subcategory": item.get("subcategory"),
            "proposed_room_type": _resolve_room_type(
                item.get("category") or item.get("facility_type"), item.get("subcategory")
            ),
            "confidence": item.get("confidence"),
            "needs_review": (item.get("confidence") is not None and item.get("confidence") < 0.5),
            "warnings": [],
            "excluded": not selectable,
            "exclusion_reason": exclusion_reason,
        }

        if not selectable:
            summary["rejected_or_invalid"] += 1
            proposal["room_action"] = "skip"
            proposal["route_point_action"] = "skip"
            proposal["placement_source"] = "needs_manual_placement"
            proposals.append(proposal)
            continue

        matched_room = rooms_by_semantic_id.get(item_id)
        match_basis = "semantic_id" if matched_room else None

        if not matched_room:
            matched_point = points_by_semantic_id.get(item_id)
            if matched_point and matched_point.room_id:
                matched_room = next(
                    (r for r in existing_rooms if str(r.id) == matched_point.room_id),
                    None,
                )
                if matched_room:
                    match_basis = "direct_link"

        if not matched_room:
            normalized_target = _normalize_name(best_name)
            legacy_matches = [
                r
                for r in unlinked_legacy_rooms
                if _normalize_name(r.name_en) == normalized_target
                and (r.floor is None or r.floor == map_item.floor)
            ]
            if len(legacy_matches) == 1:
                matched_room = legacy_matches[0]
                match_basis = "legacy_name"
            elif len(legacy_matches) > 1:
                summary["ambiguous_matches"] += 1
                proposal["room_action"] = "skip"
                proposal["route_point_action"] = "skip"
                proposal["placement_source"] = "needs_manual_placement"
                proposal["warnings"].append(
                    f"{len(legacy_matches)} existing unlinked rooms match this "
                    "name/floor — skipped rather than guessing which one to "
                    "reuse."
                )
                proposals.append(proposal)
                continue

        if matched_room:
            proposal["matched_room_id"] = str(matched_room.id)
            has_point = bool(matched_room.route_point_id)
            proposal["matched_route_point_id"] = matched_room.route_point_id

            needs_update = (
                (name_en and matched_room.name_en != name_en)
                or matched_room.semantic_entity_external_id != item_id
            )

            if has_point:
                proposal["placement_source"] = "existing_route_point"
                point = next(
                    (p for p in existing_points if str(p.id) == matched_room.route_point_id),
                    None,
                )
                proposal["proposed_x"] = point.x if point else matched_room.x
                proposal["proposed_y"] = point.y if point else matched_room.y
                summary["existing_linked_found"] += 1
                if needs_update:
                    proposal["room_action"] = "update"
                    proposal["route_point_action"] = "reuse"
                    summary["updates_proposed"] += 1
                else:
                    proposal["room_action"] = "reuse"
                    proposal["route_point_action"] = "reuse"
                    summary["duplicates_prevented"] += 1
            else:
                proposal["placement_source"] = "needs_manual_placement"
                proposal["needs_location_review"] = True
                proposal["room_action"] = "update" if needs_update else "reuse"
                proposal["route_point_action"] = "create"
                proposal["warnings"].append(
                    "This destination is linked to a Room with no map location "
                    "yet — an admin must click the correct spot on the map "
                    "before a RoutePoint can be created."
                )
                summary["new_route_points_proposed"] += 1
                summary["needs_location_review"] += 1
        else:
            proposal["room_action"] = "create"
            proposal["route_point_action"] = "create"
            proposal["placement_source"] = "needs_manual_placement"
            proposal["needs_location_review"] = True
            proposal["warnings"].append(
                "No existing map location is linked to this item yet — an "
                "admin must click the correct location on the map during "
                "review before this destination can be created. No "
                "coordinate is ever invented (no door/boundary/centroid "
                "data exists for semantic items in this codebase)."
            )
            summary["new_rooms_proposed"] += 1
            summary["new_route_points_proposed"] += 1
            summary["needs_location_review"] += 1

        parent_external_id = item.get("inside_place_external_id") or item.get(
            "belongs_to_place_external_id"
        )
        if parent_external_id:
            parent_room = rooms_by_semantic_id.get(parent_external_id)
            proposal["nested_parent_candidate"] = {
                "semantic_item_id": parent_external_id,
                "name": all_names_by_id.get(parent_external_id, parent_external_id),
                "entity_kind": "place",
                "matched_room_id": str(parent_room.id) if parent_room else None,
            }
            proposal["pass_through_proposed"] = True
            summary["nested_relationships_proposed"] += 1

        proposals.append(proposal)

    return {
        "publication_id": publication.publication_id,
        "summary": summary,
        "proposals": proposals,
        "warnings": warnings,
    }


def _detect_parent_cycle(
    room_id: str,
    proposed_parent_id: str,
    parent_chain: Dict[str, str],
) -> bool:
    """True if walking proposed_parent_id's own chain of parents ever
    reaches back to room_id (or the chain looks corrupted/too deep) —
    covers both direct self-parent (room_id == proposed_parent_id, caught
    on the very first step) and deeper cycles (Section 16)."""

    current = proposed_parent_id
    depth = 0
    while current is not None and depth < _MAX_PARENT_CHAIN_DEPTH:
        if current == room_id:
            return True
        current = parent_chain.get(current)
        depth += 1
    return depth >= _MAX_PARENT_CHAIN_DEPTH


def _validate_accepted_item_for_batch(
    accepted: dict,
    *,
    items_by_id: Dict[str, Tuple[str, Dict[str, Any]]],
    rooms_by_semantic_id: Dict[str, Room],
    accepted_ids_in_batch: set,
    map_item: Map,
) -> Optional[str]:
    """Pure, read-only re-check of everything the real write pass
    (`_apply_one_item` + the Pass 2 nested-relationship loop below) would
    otherwise only discover DURING writes — used by the fast batch
    placement workflow's `all_or_nothing` pre-write validation so a batch
    either writes nothing or writes exactly what was already validated.
    Returns a human-readable error string, or None when the item is safe
    to apply. Never itself touches the database (no insert/save/delete)."""

    item_id = accepted.get("semantic_item_id")
    entry = items_by_id.get(item_id)
    if not entry:
        return (
            "Not found in this publication's approved places/facilities "
            "— it may have been unpublished or rejected since preview."
        )

    _entity_kind, item = entry

    review = item.get("review") or {}
    if review.get("status") not in ("accepted", "corrected"):
        return "Not accepted/corrected in the reviewed semantic analysis."

    selectable, reason = _selectable(item)
    if not selectable:
        return f"Excluded from destination creation ({reason})."

    existing_room = rooms_by_semantic_id.get(item_id)
    has_existing_point = bool(existing_room and existing_room.route_point_id)

    # Section 7: "validate all coordinates; reject coordinates outside the
    # map bounds; never invent coordinates" — only enforced when this item
    # doesn't already have an existing, reusable point (Section 8:
    # existing/linked destinations never require a new location).
    if not has_existing_point:
        x = accepted.get("x")
        y = accepted.get("y")
        if x is None or y is None:
            return (
                "No coordinates were provided and no existing map "
                "location is linked to this item yet."
            )
        try:
            x_val = float(x)
            y_val = float(y)
        except (TypeError, ValueError):
            return "Coordinates must be numeric."

        if x_val < 0 or y_val < 0:
            return "Coordinates must not be negative."
        if map_item.source_width and x_val > map_item.source_width:
            return (
                f"x={x_val} is outside this map's width "
                f"({map_item.source_width})."
            )
        if map_item.source_height and y_val > map_item.source_height:
            return (
                f"y={y_val} is outside this map's height "
                f"({map_item.source_height})."
            )

    parent_item_id = accepted.get("parent_semantic_item_id")
    if (
        parent_item_id
        and parent_item_id not in rooms_by_semantic_id
        and parent_item_id not in accepted_ids_in_batch
    ):
        return (
            f"Nested parent {parent_item_id} was not found among existing "
            "Rooms or among the items in this same batch."
        )

    return None


async def apply_semantic_destinations(
    map_id: str,
    *,
    publication_id: Optional[str],
    accepted_items: List[dict],
    all_or_nothing: bool = False,
) -> dict:
    """The only function in this module that writes to MongoDB. Every item
    is independently, fully revalidated here — the frontend's preview
    response is never trusted as-is.

    Default behavior (all_or_nothing=False) is unchanged from before that
    flag existed: one invalid/failed item never aborts the others — this
    is what the existing per-card "Accept" -> "Create Accepted
    Destinations" workflow still relies on.

    all_or_nothing=True (the fast batch placement workflow's single
    "Save All Destinations" confirmation) instead validates every accepted
    item FIRST, with zero writes, and only proceeds to the real write pass
    below if every single one is valid — otherwise nothing is written at
    all and `item_errors` reports exactly which item(s) failed and why
    (Section 7: "validate the entire batch before writing; if validation
    fails, return item-level errors without partially creating
    destinations"; "if the current MongoDB architecture cannot provide a
    true transaction, perform a complete validation pass before any
    writes" — mongomock/Motor here has no multi-document transaction
    support to reuse, so this pre-write validation pass is the mechanism)."""

    result = {
        "requested": len(accepted_items),
        "rooms_created": 0,
        "rooms_updated": 0,
        "route_points_created": 0,
        "route_points_updated": 0,
        "reused": 0,
        "nested_relationships_created": 0,
        "pass_through_flags_enabled": 0,
        "skipped": 0,
        "ambiguous": 0,
        "failed": 0,
        "warnings": [],
        "created_room_ids": [],
        "created_route_point_ids": [],
        "item_errors": {},
    }

    map_item = await Map.get(PydanticObjectId(map_id))
    if not map_item:
        result["failed"] = len(accepted_items)
        result["warnings"].append("Map not found.")
        return result

    publication = await _get_publication(map_id, publication_id)
    if not publication:
        result["failed"] = len(accepted_items)
        result["warnings"].append("No active semantic-analysis publication for this map.")
        return result

    reviewed = publication.reviewed_result or {}
    floor_to_map = _floor_map_lookup(publication)

    # Section 8: apply must actually REJECT (not just warn) when this
    # map's semantic floor code is stale — creating destinations under a
    # wrong floor_external_id would silently mis-tag them. The backend
    # computes the expected code itself from map_item.floor; it never
    # trusts whatever is already stored.
    floor_mismatch = _floor_code_mismatch(floor_to_map, map_id, map_item)
    if floor_mismatch:
        result["failed"] = len(accepted_items)
        result["warnings"].append(floor_mismatch)
        return result

    items_by_id: Dict[str, Tuple[str, Dict[str, Any]]] = {}
    for entity_kind, (array_name, id_field) in DESTINATION_ENTITY_ARRAYS.items():
        for item in reviewed.get(array_name, []) or []:
            if not isinstance(item, dict):
                continue
            item_id = item.get(id_field)
            if item_id:
                items_by_id[item_id] = (entity_kind, item)

    existing_rooms = await Room.find({"map_id": map_id}).to_list()
    rooms_by_semantic_id: Dict[str, Room] = {
        r.semantic_entity_external_id: r
        for r in existing_rooms
        if r.semantic_entity_external_id
    }
    # Full parent chain (room_id -> parent_room_id) across the WHOLE
    # building's existing data, not just this map, so a cycle spanning
    # earlier apply runs is still caught. Cheap: one extra query, never
    # per-item.
    all_rooms = await Room.find({}).to_list()
    parent_chain: Dict[str, str] = {
        str(r.id): r.parent_room_id for r in all_rooms if r.parent_room_id
    }

    # This batch's own newly-created/matched room ids, so a nested pair
    # accepted in the SAME apply call resolves correctly even though
    # neither side existed in the database a moment ago.
    room_by_semantic_id_this_batch: Dict[str, Room] = dict(rooms_by_semantic_id)

    if all_or_nothing:
        accepted_ids_in_batch = {
            a.get("semantic_item_id") for a in accepted_items if a.get("semantic_item_id")
        }
        item_errors: Dict[str, str] = {}
        for accepted in accepted_items:
            item_id = accepted.get("semantic_item_id")
            error = _validate_accepted_item_for_batch(
                accepted,
                items_by_id=items_by_id,
                rooms_by_semantic_id=rooms_by_semantic_id,
                accepted_ids_in_batch=accepted_ids_in_batch,
                map_item=map_item,
            )
            if error:
                item_errors[item_id or "(missing semantic_item_id)"] = error

        if item_errors:
            result["failed"] = len(item_errors)
            result["item_errors"] = item_errors
            result["warnings"].append(
                f"{len(item_errors)} item(s) failed validation — nothing was "
                "written. Fix the reported item(s) and submit the batch again."
            )
            return result

    # Pass 1 — create/update/reuse every Room + destination RoutePoint,
    # independent of any nested relationship.
    processed: List[Tuple[dict, Optional[Room], Optional[RoutePoint]]] = []

    for accepted in accepted_items:
        item_id = accepted.get("semantic_item_id")
        entry = items_by_id.get(item_id)

        if not entry:
            result["rejected_or_invalid"] = result.get("rejected_or_invalid", 0)
            result["ambiguous"] += 1
            result["warnings"].append(
                f"Semantic item {item_id} was not found in this publication's "
                "approved places/facilities — skipped."
            )
            processed.append((accepted, None, None))
            continue

        entity_kind, item = entry

        review = item.get("review") or {}
        if review.get("status") not in ("accepted", "corrected"):
            result["skipped"] += 1
            result["warnings"].append(
                f"Semantic item {item_id} is not accepted/corrected — skipped."
            )
            processed.append((accepted, None, None))
            continue

        selectable, _reason = _selectable(item)
        if not selectable:
            result["skipped"] += 1
            processed.append((accepted, None, None))
            continue

        item_floor_external_id = item.get("floor_external_id")
        if item_floor_external_id:
            item_map_id = floor_to_map.get(item_floor_external_id)
        elif len(set(floor_to_map.values())) == 1:
            item_map_id = next(iter(floor_to_map.values()))
        else:
            item_map_id = None
        if item_map_id != map_id:
            result["failed"] += 1
            result["warnings"].append(
                f"Semantic item {item_id} does not belong to map {map_id} — skipped."
            )
            processed.append((accepted, None, None))
            continue

        try:
            (
                room,
                was_room_created,
                was_room_updated,
                point,
                was_point_created,
            ) = await _apply_one_item(
                map_item=map_item,
                item=item,
                entity_kind=entity_kind,
                accepted=accepted,
                existing_room=room_by_semantic_id_this_batch.get(item_id),
                publication_id=publication.publication_id,
            )
        except Exception:
            result["failed"] += 1
            result["warnings"].append(
                f"Could not create/update a destination for semantic item {item_id}."
            )
            processed.append((accepted, None, None))
            continue

        if room is None:
            result["skipped"] += 1
            processed.append((accepted, None, None))
            continue

        room_by_semantic_id_this_batch[item_id] = room

        if was_room_created:
            result["rooms_created"] += 1
            result["created_room_ids"].append(str(room.id))
        elif was_room_updated:
            result["rooms_updated"] += 1
        else:
            result["reused"] += 1

        if point is not None:
            if was_point_created:
                result["route_points_created"] += 1
                result["created_route_point_ids"].append(str(point.id))
            else:
                result["route_points_updated"] += 1

        processed.append((accepted, room, point))

    # Pass 2 — nested-parent relationships, now that every accepted item
    # in this batch has a real Room id to reference.
    for accepted, room, point in processed:
        parent_item_id = accepted.get("parent_semantic_item_id")
        if not parent_item_id or room is None:
            continue

        parent_room = room_by_semantic_id_this_batch.get(parent_item_id)
        if not parent_room:
            result["failed"] += 1
            result["warnings"].append(
                f"Parent semantic item {parent_item_id} for "
                f"{accepted.get('semantic_item_id')} was not created/found in "
                "this apply — nested relationship skipped."
            )
            continue

        if str(parent_room.id) == str(room.id):
            result["failed"] += 1
            result["warnings"].append(
                f"Semantic item {accepted.get('semantic_item_id')} cannot be "
                "its own parent — skipped."
            )
            continue

        if _detect_parent_cycle(str(room.id), str(parent_room.id), parent_chain):
            result["failed"] += 1
            result["warnings"].append(
                f"Setting {parent_room.id} as the parent of {room.id} would "
                "create a circular containment chain — skipped."
            )
            continue

        if room.map_id != parent_room.map_id:
            result["failed"] += 1
            result["warnings"].append(
                "Nested parent/child must be on the same map — skipped for "
                f"{accepted.get('semantic_item_id')}."
            )
            continue

        parent_point = None
        if parent_room.route_point_id:
            parent_point = await RoutePoint.get(PydanticObjectId(parent_room.route_point_id))

        if not parent_point or not parent_point.is_active:
            result["failed"] += 1
            result["warnings"].append(
                f"Parent room {parent_room.id} has no active destination "
                "point yet — approve it (with a map location) before "
                "confirming this nested relationship."
            )
            continue

        # The parent's own accepted entry is what explicitly grants
        # allow_transit_through (Section 10: never enabled implicitly).
        parent_accepted = next(
            (
                a
                for a, r, _p in processed
                if r is not None and str(r.id) == str(parent_room.id)
            ),
            None,
        )
        parent_allows_transit = parent_point.allow_transit_through or bool(
            parent_accepted and parent_accepted.get("allow_transit_through")
        )

        if not parent_allows_transit:
            result["failed"] += 1
            result["warnings"].append(
                f"Parent room {parent_room.id} does not have "
                "allow_transit_through approved — nested relationship "
                f"skipped for {accepted.get('semantic_item_id')}."
            )
            continue

        if not parent_point.allow_transit_through:
            parent_point.allow_transit_through = True
            parent_point.updated_at = datetime.utcnow()
            await parent_point.save()
            result["pass_through_flags_enabled"] += 1

        if room.parent_room_id != str(parent_room.id):
            room.parent_room_id = str(parent_room.id)
            room.updated_at = datetime.utcnow()
            await room.save()

        parent_chain[str(room.id)] = str(parent_room.id)
        result["nested_relationships_created"] += 1

    return result


async def _apply_one_item(
    *,
    map_item: Map,
    item: Dict[str, Any],
    entity_kind: str,
    accepted: dict,
    existing_room: Optional[Room],
    publication_id: Optional[str] = None,
) -> Tuple[Optional[Room], bool, bool, Optional[RoutePoint], bool]:
    """Returns (room, was_room_created, was_room_updated, point,
    was_point_created). Mirrors routes/room_routes.py's
    _place_room_on_map + create_room
    exactly (Section 7: reuse existing conventions), just driven from a
    semantic item instead of an admin form. Manual name edits already
    applied by the admin in reviewed_result are respected as-is — this
    never re-derives a name from ai_result."""

    item_id = accepted["semantic_item_id"]
    names = item.get("names") or {}
    # `ai_name` is the REAL AI-provided name, or None if the item genuinely
    # has neither an English nor an "original" name — used for the
    # manual-edit-preservation decision below. `name_en` additionally falls
    # back to the item's own stable id, purely so Room.name_en (a required
    # field) always has *some* non-empty value when creating a brand-new
    # Room. Section 8 bug found during test-writing: reusing the item_id
    # fallback for the UPDATE decision too would treat "AI gave no name at
    # all" the same as "AI explicitly renamed this to its own internal id"
    # and silently overwrite an admin's manual rename — ai_name (without
    # the id fallback) is what the update-decision must use instead.
    ai_name = names.get("en") or names.get("original")
    name_en = ai_name or item_id
    room_type = _resolve_room_type(
        item.get("category") or item.get("facility_type"), item.get("subcategory")
    )

    room = existing_room
    was_room_created = False
    was_room_updated = False

    if room is None:
        room = Room(
            building_id=map_item.building_id or "",
            # ROOT CAUSE FIX (found via test_missing_coordinates_needs_
            # manual_placement_not_invented's IndexError): map_id was never
            # set here, only later inside the "point successfully created"
            # branch below. A brand-new Room created for an item with no
            # reviewed coordinates yet (point stays None, that branch never
            # runs) was therefore silently orphaned from every map-scoped
            # Room.find({"map_id": ...}) query used by preview/apply's own
            # semantic_id matching — invisible to itself on the very next
            # scan, and liable to be duplicated on a later apply. map_id
            # must always be set at creation time, regardless of whether a
            # RoutePoint could be placed yet.
            map_id=str(map_item.id),
            name_en=name_en,
            names={
                k: v
                for k, v in {"en": names.get("en"), "ar": names.get("ar"), "he": names.get("he")}.items()
                if v
            }
            or None,
            semantic_publication_id=publication_id,
            semantic_entity_external_id=item_id,
            semantic_entity_type=entity_kind,
            room_type=room_type,
            floor=map_item.floor,
        )
        await room.insert()
        was_room_created = True
    else:
        changed = False
        # Manual-edit preservation (Section 8): only ever update a field
        # from a NON-EMPTY *real* AI value, and never overwrite an existing
        # non-empty Room field with an empty one (or with a synthetic
        # fallback like the item's own id).
        if ai_name and room.name_en != ai_name:
            room.name_en = ai_name
            changed = True
        if not room.semantic_entity_external_id:
            room.semantic_entity_external_id = item_id
            room.semantic_entity_type = entity_kind
            changed = True
        if changed:
            room.updated_at = datetime.utcnow()
            await room.save()
            was_room_updated = True

    point: Optional[RoutePoint] = None
    was_point_created = False

    if room.route_point_id:
        point = await RoutePoint.get(PydanticObjectId(room.route_point_id))

    if point is None:
        x = accepted.get("x")
        y = accepted.get("y")
        if x is None or y is None:
            # No existing point and no admin-reviewed coordinate given —
            # cannot place this destination (Section 5: never invent a
            # centroid/door that doesn't exist). Room itself is still
            # created/kept so the admin can place it later without losing
            # the approved name/type.
            return room, was_room_created, was_room_updated, None, False

        point, was_point_reused = await find_or_create_route_point(
            map_id=str(map_item.id),
            name=name_en,
            # Only "room" is a destination-capable RoutePoint.point_type
            # (Section 3 — "place"/"facility" are semantic-layer concepts,
            # never a graph point_type); the richer semantic
            # category/subcategory lives on Room.room_type instead.
            point_type="room",
            x=float(x),
            y=float(y),
            floor=map_item.floor,
            building_id=map_item.building_id,
            room_id=str(room.id),
            is_accessible=True,
            # Section 14: nested pass-through instructions read
            # RoutePoint.display_name_{lang} (see
            # logic/instruction_generator.py's
            # resolve_localized_display_name) — never Room.names — so the
            # admin-approved multilingual names must be copied onto the
            # RoutePoint itself, not just kept on Room, or an AR/HE
            # navigation session would silently fall back to the raw
            # English `name` regardless of requested language.
            display_name=name_en,
            display_name_en=names.get("en"),
            display_name_ar=names.get("ar"),
            display_name_he=names.get("he"),
            semantic_publication_id=publication_id,
            semantic_entity_external_id=item_id,
            semantic_entity_type=entity_kind,
        )
        # find_or_create_route_point returns (point, was_reused) — invert
        # to the "was_point_created" sense this function's own return
        # contract promises (was a real bug during development: the raw
        # was_reused value was previously used as-is, which silently
        # swapped the created/reused counts in the apply summary).
        was_point_created = not was_point_reused
        # entity_kind "place"/"facility" is not itself a valid
        # RoutePoint.point_type (Section 3: only room/store are
        # destination-capable point types) — always store the
        # destination-capable type "room" here; the richer semantic
        # category lives on Room.room_type instead.
        if point.point_type != "room":
            point.point_type = "room"
            await point.save()

        if room.route_point_id != str(point.id):
            room.route_point_id = str(point.id)
            room.map_id = str(map_item.id)
            room.x = point.x
            room.y = point.y
            room.updated_at = datetime.utcnow()
            await room.save()
            was_room_updated = True

    # Backfill multilingual display names onto an EXISTING/reused point too
    # (not just a genuinely new one) — e.g. a legacy-matched Room whose
    # RoutePoint predates this feature and has display_name_ar/he still
    # empty. Manual-edit preservation (Section 8): only ever fills an
    # empty field, never overwrites an admin's own already-set value.
    point_names_changed = False
    if not point.display_name and name_en:
        point.display_name = name_en
        point_names_changed = True
    if not point.display_name_en and names.get("en"):
        point.display_name_en = names.get("en")
        point_names_changed = True
    if not point.display_name_ar and names.get("ar"):
        point.display_name_ar = names.get("ar")
        point_names_changed = True
    if not point.display_name_he and names.get("he"):
        point.display_name_he = names.get("he")
        point_names_changed = True
    if point_names_changed:
        point.updated_at = datetime.utcnow()
        await point.save()

    requested_allow_transit = bool(accepted.get("allow_transit_through"))
    if requested_allow_transit and not point.allow_transit_through:
        point.allow_transit_through = True
        point.updated_at = datetime.utcnow()
        await point.save()

    return room, was_room_created, was_room_updated, point, was_point_created
