"""
"Auto Connect Destinations to Corridors": proposes, and — only once an
admin explicitly accepts each one — creates, ordinary same-floor walkway
RouteEdges between an unconnected Room/Store RoutePoint and a nearby valid
corridor/hallway/junction RoutePoint.

Two entry points, matching the required preview/apply split:
  - preview_auto_connect_destinations(): 100% read-only. Never inserts,
    updates, or deletes anything. Safe to call as often as needed.
  - apply_auto_connect_destinations(): the ONLY function in this module
    that writes to MongoDB, and only for the exact accepted pairs it is
    given — every pair is fully revalidated here from fresh database
    reads, never trusting whatever the frontend's preview state claims.

Deliberately does not touch: Dijkstra/shortest-path logic (logic/), Room
documents, QR/location codes, vertical connectors, calibration, semantic
analysis results, or any existing RouteEdge/RoutePoint. The only database
writes this module ever performs are brand-new RouteEdge inserts, one per
explicitly accepted pair, in apply_auto_connect_destinations().

Performance: for potentially thousands of destination points, this
deliberately avoids the O(destinations x transit_points) "compare every
Room to every corridor point" approach (and the per-point-DB-query
approach graph_connection_service.find_connection_candidates() uses, which
is fine for one point at a time but does not scale to a bulk scan). All
active RoutePoints/RouteEdges for the scanned map(s) are fetched from
MongoDB exactly once, up front; nearest-transit-candidate lookups are then
done entirely in memory against a small stdlib-only uniform spatial grid
(_SpatialGrid below) — no new third-party dependency.
"""

from __future__ import annotations

import math
from collections import defaultdict
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from beanie import PydanticObjectId

from constants.route_point_types import (
    DESTINATION_CAPABLE_POINT_TYPES,
    TRANSIT_CANDIDATE_POINT_TYPES,
    transit_candidate_priority_rank,
)
from logic.instruction_generator import resolve_localized_display_name
from models.map_model import Map
from models.room_model import Room
from models.route_edge_model import RouteEdge
from models.route_point_model import RoutePoint
from services.room_location_code_service import (
    ensure_room_location_codes,
    merge_into_apply_result,
)
from services.graph_connection_service import (
    _ensure_map_source_available,
    _get_wall_mask,
)
from services.graph_connectivity_service import FloorGraphIndex

# THE candidate search, the geometry and the edge splitter all live in
# services/destination_attachment_service now — this module is the
# preview/apply presentation on top of them, not a second algorithm. The
# names are re-exported here because navigation_build_preview_service and
# the existing test suite import _effective_bounds from this module.
from services.destination_attachment_service import (  # noqa: F401
    EDGE_SPLIT_GENERATION_METHOD,
    HARD_SAFETY_FRACTION_OF_DIAGONAL,
    HIGH_CONFIDENCE_FRACTION_OF_DIAGONAL,
    HIGH_CONFIDENCE_MAX_PX,
    MAX_DISTANCE_PX_DEFAULT,
    MEDIUM_CONFIDENCE_FRACTION_OF_DIAGONAL,
    MEDIUM_CONFIDENCE_MAX_PX,
    _attachment_is_clear,
    _canonical_diagonal_px,
    _confidence_tier,
    _effective_bounds,
    _get_scale_for_floor,
    MAX_CANDIDATES_PER_PROPOSAL,
    _split_corridor_edge_for_attachment,
    canonical_final_reason,
    find_attachment_candidates,
    load_corridor_floor_context,
    resolve_doorway_exit_point,
    _floors_are_compatible,
)
from services.strict_geometry_service import get_strict_wall_metrics


def _display_name(point: RoutePoint, lang: str) -> str:
    resolved = resolve_localized_display_name(
        point.name,
        display_name=point.display_name,
        display_name_en=point.display_name_en,
        display_name_ar=point.display_name_ar,
        display_name_he=point.display_name_he,
        is_auto_generated=point.is_auto_generated,
        lang=lang,
    )
    # Every candidate/destination shown in the preview must have SOME
    # human-facing label (never a raw technical id as the primary label,
    # per this feature's spec) — resolve_localized_display_name can
    # legitimately return None for a suppressed technical name, so this
    # falls back to the raw name rather than ever showing nothing.
    return resolved or point.name or str(point.id)


def _corridor_edge_label(point_a: RoutePoint, point_b: RoutePoint, lang: str) -> str:
    """Human-facing label for an attachment onto a corridor RUN rather than
    onto one of its endpoint nodes — the review UI must never show a raw
    edge id as the primary label."""
    return f"{_display_name(point_a, lang)} \u2194 {_display_name(point_b, lang)}"


async def _resolve_scan_maps(map_id: str, scope: str) -> List[Map]:
    origin_map = await Map.get(PydanticObjectId(map_id))
    if not origin_map:
        return []

    if scope != "map_group" or not origin_map.map_group_id:
        return [origin_map]

    group_maps = await Map.find(
        {
            "map_group_id": origin_map.map_group_id,
            "is_current_for_floor": True,
        }
    ).to_list()

    # Always include the origin map itself even if, for some legacy data
    # reason, it didn't come back from the is_current_for_floor query —
    # never silently drop the map the admin actually selected.
    if not any(str(m.id) == str(origin_map.id) for m in group_maps):
        group_maps.append(origin_map)

    return group_maps


def _no_candidate_proposal(
    *,
    map_id: str,
    destination: RoutePoint,
    destination_name: str,
    reason: str,
    is_calibrated: bool,
    has_existing_invalid_edges: bool,
    hard_safety_max_px: float,
    nearest_distance_px: Optional[float] = None,
    status: str = "no_candidate",
    diagnostics: Optional[dict] = None,
) -> dict:
    """One shape for every "nothing was proposed" outcome, so a new reason
    can never accidentally omit the diagnostics the review UI relies on."""

    payload = {
        "map_id": map_id,
        "floor": destination.floor,
        "destination_point_id": str(destination.id),
        "destination_name": destination_name,
        "destination_point_type": destination.point_type,
        "status": status,
        "confidence": None,
        "reason": reason,
        # The canonical name for the same outcome. `reason` keeps the exact
        # strings it has always emitted so nothing matching on them breaks;
        # `final_reason` is the single vocabulary the review UI reads, and
        # is the only place the two new door-aware outcomes appear.
        "final_reason": canonical_final_reason(reason),
        "has_existing_invalid_edges": has_existing_invalid_edges,
        "is_calibrated": is_calibrated,
        "proposed_candidate_id": None,
        "proposed_candidate_key": None,
        "candidates": [],
        "destination_x": round(float(destination.x), 2),
        "destination_y": round(float(destination.y), 2),
        "nearest_distance_px": nearest_distance_px,
        "max_hard_distance_px": round(hard_safety_max_px, 2),
    }
    payload.update(diagnostics or {})
    return payload


async def _scan_one_map(
    map_item: Map,
    floor: Optional[int],
    max_distance_px_override: Optional[float],
    lang: str,
) -> Tuple[dict, List[dict]]:
    # ONE shared context and ONE shared candidate search — see
    # services/destination_attachment_service. This function used to build
    # the grid, the components, the corridor segments and the candidate
    # ranking itself, which is precisely how the saved-room path and the
    # Auto Connect path drifted into two different algorithms.
    context = await load_corridor_floor_context(
        map_item, floor=floor, max_distance_px_override=max_distance_px_override
    )

    map_id = context.map_id
    high_max_px = context.high_max_px
    medium_max_px = context.medium_max_px
    hard_safety_max_px = context.hard_safety_max_px

    all_points = context.all_points
    edges = context.edges
    rooms = context.rooms
    destinations = context.destinations
    transit_points = context.transit_points
    points_by_id = context.points_by_id
    rooms_by_route_point_id = context.rooms_by_route_point_id
    rooms_by_id = context.rooms_by_id
    has_any_edge = context.has_any_edge
    transit_network_has_internal_edges = context.transit_network_has_internal_edges

    # CONNECTED STATUS — one shared authority.
    #
    # This scan used to decide "already connected" with its own local rule
    # while routes/room_routes.py used a different one, and on real data
    # they disagreed: Auto Connect reported rooms as already connected that
    # the Rooms page showed as having no valid graph connection. Both now
    # ask services/graph_connectivity_service the same question, so the two
    # screens cannot drift again.
    connectivity = FloorGraphIndex(map_id, all_points, edges, rooms)

    wall_mask_available = context.wall_mask_available
    is_calibrated = context.is_calibrated
    scale = context.scale

    summary = {
        "scanned": len(destinations),
        "already_connected": 0,
        "proposed": 0,
        "needs_review": 0,
        "no_candidate": 0,
    }
    proposals: List[dict] = []

    for destination in destinations:
        destination_id = str(destination.id)
        destination_name = _display_name(destination, lang)
        has_existing_invalid_edges = bool(has_any_edge.get(destination_id))

        # ── NESTED ROOMS ────────────────────────────────────────────────
        # An approved inner destination proposes ONLY its confirmed parent
        # Room's own destination point — never a random nearby Room, and
        # never the ordinary hallway/junction search. Confirmed
        # containment (Room.parent_room_id, set only via explicit admin
        # approval in services/semantic_destination_service.py) is
        # required; a merely-nearby Room is never treated as a parent
        # because it happens to be close.
        destination_room = rooms_by_route_point_id.get(destination_id)
        if destination_room and destination_room.parent_room_id:
            parent_room = rooms_by_id.get(destination_room.parent_room_id)
            parent_point = (
                points_by_id.get(parent_room.route_point_id)
                if parent_room and parent_room.route_point_id
                else None
            )

            nested_diagnostics = {
                "is_nested_access": True,
                "nested_parent_room_id": destination_room.parent_room_id,
                "nested_parent_room_name": (
                    _display_name(parent_point, lang) if parent_point else None
                ),
                "parent_pass_through": bool(
                    parent_point and parent_point.allow_transit_through
                ),
                "connection_type": "nested_room_via_parent",
            }

            if (
                parent_point
                and parent_point.is_active
                and parent_point.allow_transit_through
            ):
                parent_point_id = str(parent_point.id)
                already_linked_to_parent = any(
                    (
                        edge.from_point_id == destination_id
                        and edge.to_point_id == parent_point_id
                    )
                    or (
                        edge.to_point_id == destination_id
                        and edge.from_point_id == parent_point_id
                    )
                    for edge in edges
                )
                if already_linked_to_parent:
                    summary["already_connected"] += 1
                    continue

                distance_px = math.hypot(
                    float(parent_point.x) - float(destination.x),
                    float(parent_point.y) - float(destination.y),
                )
                distance_meters = (
                    round(distance_px * scale, 2) if is_calibrated else None
                )
                summary["proposed"] += 1
                proposals.append(
                    {
                        "map_id": map_id,
                        "floor": destination.floor,
                        "destination_point_id": destination_id,
                        "destination_name": destination_name,
                        "destination_point_type": destination.point_type,
                        "status": "proposed",
                        # Declared/approved, not distance-derived — always
                        # "high" rather than running through the ordinary
                        # distance-based tiers, since this is a confirmed
                        # relationship, not a geometric guess.
                        "confidence": "high",
                        "reason": None,
                        "has_existing_invalid_edges": has_existing_invalid_edges,
                        "is_calibrated": is_calibrated,
                        "proposed_candidate_id": parent_point_id,
                        "proposed_candidate_key": parent_point_id,
                        "candidates": [
                            {
                                "candidate_key": parent_point_id,
                                "point_id": parent_point_id,
                                "name": _display_name(parent_point, lang),
                                "point_type": parent_point.point_type,
                                "target_type": "nested_parent",
                                "corridor_edge_id": None,
                                "x": round(float(parent_point.x), 2),
                                "y": round(float(parent_point.y), 2),
                                "attachment_x": round(float(parent_point.x), 2),
                                "attachment_y": round(float(parent_point.y), 2),
                                "distance_px": round(distance_px, 2),
                                "distance_meters": distance_meters,
                                "blocked_by_wall": False,
                                "clear_line": True,
                                "doorway_crossing": False,
                                "graph_connected": True,
                            }
                        ],
                        "destination_x": round(float(destination.x), 2),
                        "destination_y": round(float(destination.y), 2),
                        "nearest_distance_px": round(distance_px, 2),
                        "max_hard_distance_px": round(hard_safety_max_px, 2),
                        "target_type": "nested_parent",
                        "graph_connected": True,
                        "clear_line": True,
                        "doorway_crossing": False,
                        **nested_diagnostics,
                    }
                )
                continue

            # A parent relationship is declared but not usable. This is
            # NEEDS REVIEW, not "no candidate": the data is nearly right
            # and an admin can fix it in one click, and it must never fall
            # through to an ordinary nearby-hallway proposal for a
            # destination that is known to require its specific approved
            # parent.
            if parent_point is None or not parent_point.is_active:
                nested_reason = "nested_parent_no_point"
            else:
                nested_reason = "nested_parent_not_pass_through"

            summary["needs_review"] += 1
            proposals.append(
                _no_candidate_proposal(
                    map_id=map_id,
                    destination=destination,
                    destination_name=destination_name,
                    reason=nested_reason,
                    is_calibrated=is_calibrated,
                    has_existing_invalid_edges=has_existing_invalid_edges,
                    hard_safety_max_px=hard_safety_max_px,
                    status="needs_review",
                    diagnostics={
                        **nested_diagnostics,
                        "final_reason": canonical_final_reason(nested_reason),
                    },
                )
            )
            continue

        destination_connected, _connection_reason = connectivity.connection_state(
            destination_id
        )
        if destination_connected:
            summary["already_connected"] += 1
            continue

        # The most fundamental problem first: no corridor graph exists at
        # all on this map/floor.
        if not transit_points:
            summary["no_candidate"] += 1
            proposals.append(
                _no_candidate_proposal(
                    map_id=map_id,
                    destination=destination,
                    destination_name=destination_name,
                    reason="no_transit_points_on_map",
                    is_calibrated=is_calibrated,
                    has_existing_invalid_edges=has_existing_invalid_edges,
                    hard_safety_max_px=hard_safety_max_px,
                )
            )
            continue

        destination_x = float(destination.x)
        destination_y = float(destination.y)

        # ── CANDIDATE POOL ──────────────────────────────────────────────
        # THE shared search (services/destination_attachment_service):
        # corridor nodes plus the nearest point along every drawn corridor
        # edge, ranked connected-first then by distance with the
        # hallway-before-junction tie-break, each validated against strict
        # clear-line geometry. Room/store points are not in the transit set
        # at all, so a normal destination can never see another
        # destination here.
        #
        # Exactly the same call the automatic attach-on-save and the bulk
        # retry make — that is the point: one algorithm, three callers.
        search = find_attachment_candidates(
            context,
            destination,
            limit=MAX_CANDIDATES_PER_PROPOSAL,
            label_for=lambda candidate: _display_name(candidate, lang),
        )

        blocked_count = search.blocked_count
        isolated_count = search.isolated_count
        nearest_found_px = search.nearest_found_px

        valid_candidates = [
            {
                "candidate_key": candidate["candidate_key"],
                "point_id": candidate["point_id"],
                "name": candidate["name"],
                "point_type": candidate["point_type"],
                "target_type": candidate["target_type"],
                "corridor_edge_id": candidate["corridor_edge_id"],
                "x": round(candidate["x"], 2),
                "y": round(candidate["y"], 2),
                "attachment_x": round(candidate["attachment_x"], 2),
                "attachment_y": round(candidate["attachment_y"], 2),
                "distance_px": round(candidate["distance_px"], 2),
                "distance_meters": candidate["distance_meters"],
                "blocked_by_wall": False,
                "clear_line": True,
                "doorway_crossing": candidate["doorway_crossing"],
                "graph_connected": True,
                # Door-aware validation detail. `doorway_exit_*` is the
                # temporary waypoint the geometry was proven through — the
                # destination's own stored x/y are unchanged and are what
                # the edge is actually written from.
                "doorway_resolved": candidate["doorway_resolved"],
                "doorway_exit_x": candidate["doorway_exit_x"],
                "doorway_exit_y": candidate["doorway_exit_y"],
                "doorway_snap_px": candidate["doorway_snap_px"],
                "doorway_crossing_thickness_px": candidate[
                    "doorway_crossing_thickness_px"
                ],
                "wall_stroke_thickness_px": candidate["wall_stroke_thickness_px"],
                "clear_line_after_doorway": candidate["clear_line_after_doorway"],
                "wall_crossings_after_doorway": candidate[
                    "wall_crossings_after_doorway"
                ],
            }
            for candidate in search.candidates
        ]

        if not valid_candidates:
            # PREVIEW DIAGNOSTICS: each of these is a genuinely different
            # problem with a genuinely different fix, and conflating them
            # is what made "no corridor point close enough" appear for a
            # room with a corridor drawn right beside it.
            no_candidate_reason = search.reason or "no_transit_point_within_range"

            summary["no_candidate"] += 1
            proposals.append(
                _no_candidate_proposal(
                    map_id=map_id,
                    destination=destination,
                    destination_name=destination_name,
                    reason=no_candidate_reason,
                    is_calibrated=is_calibrated,
                    has_existing_invalid_edges=has_existing_invalid_edges,
                    hard_safety_max_px=hard_safety_max_px,
                    nearest_distance_px=nearest_found_px,
                    diagnostics={
                        "blocked_candidate_count": blocked_count,
                        "isolated_candidate_count": isolated_count,
                        # Everything the door-aware stage measured, so an
                        # admin can tell "a wall is genuinely in the way"
                        # from "the marker is a few pixels inside the room"
                        # from "this corridor is a separate island".
                        **search.diagnostics,
                    },
                )
            )
            continue

        best = valid_candidates[0]
        nearest_px = best["distance_px"]

        # Without a real wall mask for this map, the segment's walkability
        # was never actually checked — this must never be reported as a
        # distance-based high/medium/low confidence proposal, only
        # "needs_review", regardless of how close the nearest candidate is.
        confidence = (
            "needs_review"
            if not wall_mask_available
            else _confidence_tier(nearest_px, high_max_px, medium_max_px)
        )

        if confidence == "needs_review":
            summary["needs_review"] += 1
        summary["proposed"] += 1

        proposals.append(
            {
                "map_id": map_id,
                "floor": destination.floor,
                "destination_point_id": destination_id,
                "destination_name": destination_name,
                "destination_point_type": destination.point_type,
                "status": "proposed",
                "confidence": confidence,
                "reason": None,
                "has_existing_invalid_edges": has_existing_invalid_edges,
                "is_calibrated": is_calibrated,
                "proposed_candidate_id": best["point_id"],
                "proposed_candidate_key": best["candidate_key"],
                "candidates": valid_candidates,
                "destination_x": round(destination_x, 2),
                "destination_y": round(destination_y, 2),
                "nearest_distance_px": nearest_px,
                "max_hard_distance_px": round(hard_safety_max_px, 2),
                "target_type": best["target_type"],
                "graph_connected": True,
                "clear_line": True,
                "doorway_crossing": best["doorway_crossing"],
                "connection_type": (
                    "corridor_edge_split"
                    if best["target_type"] == "corridor_edge"
                    else "corridor_node"
                ),
                "blocked_candidate_count": blocked_count,
                "isolated_candidate_count": isolated_count,
                **search.diagnostics,
            }
        )

    return summary, proposals


async def preview_auto_connect_destinations(
    map_id: str,
    floor: Optional[int] = None,
    max_distance_px: Optional[float] = None,
    scope: str = "map",
    lang: str = "en",
) -> dict:
    """
    Entirely read-only. Never calls .insert()/.save()/.delete() on
    anything — only RoutePoint.find()/RouteEdge.find()/Map.get()/Map.find()
    reads.
    """

    maps_to_scan = await _resolve_scan_maps(map_id, scope)

    overall_summary = {
        "scanned": 0,
        "already_connected": 0,
        "proposed": 0,
        "needs_review": 0,
        "no_candidate": 0,
    }
    all_proposals: List[dict] = []

    for map_item in maps_to_scan:
        summary, proposals = await _scan_one_map(
            map_item, floor, max_distance_px, lang
        )
        for key in overall_summary:
            overall_summary[key] += summary[key]
        all_proposals.extend(proposals)

    return {"summary": overall_summary, "proposals": all_proposals}


# Why a pair was refused at apply time.
#
# `rejected_invalid` used to be a bare counter with no accompanying
# warning, so an admin who accepted three proposals and got "Created 0 ·
# Rejected invalid 3" had nothing to act on and no way to tell the failure
# apart from a no-op. Every refusal below now says which check it failed;
# the reasons are the same vocabulary the preview reports.
REJECT_REASON_LABELS = {
    "floor_mismatch": "the two points are recorded on different floors",
    "blocked_by_wall": "a wall is in the way",
    "doorway_not_resolved": "a wall is in the way and it is not a doorway",
    "blocked_after_doorway": "a wall stands between the doorway and the corridor",
    "corridor_edge_no_longer_valid": "the corridor edge is no longer a valid walkway",
    "not_a_destination": "the point is not a room or store",
    "corridor_not_found": "the corridor point no longer exists",
    "corridor_inactive": "the corridor point is inactive",
    "wrong_map": "the point belongs to a different map",
    "connector_stop": "a stair/elevator stop cannot be used here",
    "not_transit": "the target is not a corridor point",
    "same_point": "the destination and the corridor point are the same point",
    "missing_attachment_position": "no attachment position was supplied",
    "edge_split_failed": "the corridor edge could not be split",
    "destination_not_found": "the destination point no longer exists",
    "destination_inactive": "the destination point is inactive",
    "no_target": "exactly one corridor point or corridor edge is required",
}


def _reject(result: dict, destination_id: Optional[str], reason: str) -> None:
    """Count a refused pair AND say why, so apply is never silent."""

    result["rejected_invalid"] += 1
    label = REJECT_REASON_LABELS.get(reason, reason)
    result["warnings"].append(
        f"Could not connect destination {destination_id}: {label}."
    )
    result.setdefault("rejected_reasons", []).append(
        {"destination_point_id": destination_id, "reason": reason}
    )


async def apply_auto_connect_destinations(
    map_id: str,
    accepted_pairs: List[dict],
) -> dict:
    """
    The only function in this module that writes to MongoDB. Every pair is
    independently, fully revalidated from a fresh database read here —
    the frontend's preview response is never trusted as-is. One invalid or
    failed pair never aborts the others (Section 12: continue safely with
    other independent accepted proposals).

    Reuses the EXISTING route_edge_routes.py validation/duplicate/distance
    helpers (validate_edge_ids, find_duplicate_edge, calculate_edge_distance)
    via a function-scoped import — deferred specifically so this module
    never has a circular top-level import with routes/route_edge_routes.py
    (which imports THIS module for its two new endpoints). By the time
    apply_auto_connect_destinations() actually runs, the app has already
    fully imported both modules, so this import is always cheap and safe.
    """

    from routes.route_edge_routes import (  # noqa: PLC0415 (deferred: see docstring)
        calculate_edge_distance,
        find_duplicate_edge,
    )

    result = {
        "requested": len(accepted_pairs),
        "created": 0,
        "skipped_existing": 0,
        "rejected_invalid": 0,
        "failed": 0,
        "created_edge_ids": [],
        "warnings": [],
        # Edge-split attachments performed (a room whose nearest valid
        # corridor point was partway along a drawn corridor edge rather
        # than at one of its endpoint nodes).
        "corridor_junctions_created": 0,
        "created_point_ids": [],
        # One entry per refused pair, so "Rejected invalid 3" is always
        # accompanied by which check each one failed.
        "rejected_reasons": [],
    }

    map_item = await Map.get(PydanticObjectId(map_id))
    if not map_item:
        result["rejected_invalid"] = len(accepted_pairs)
        result["warnings"].append("Map not found.")
        return result

    for pair in accepted_pairs:
        destination_id = pair.get("destination_point_id")
        corridor_id = pair.get("corridor_point_id")
        corridor_edge_id = pair.get("corridor_edge_id")
        attachment_x = pair.get("attachment_x")
        attachment_y = pair.get("attachment_y")
        created_junction_id: Optional[str] = None

        try:
            if not destination_id:
                _reject(result, destination_id, "no_target")
                continue

            # Exactly one attachment target: an existing corridor point, or
            # a position along an existing corridor edge. Never both, never
            # neither.
            if bool(corridor_id) == bool(corridor_edge_id):
                _reject(result, destination_id, "no_target")
                continue

            destination = await RoutePoint.get(PydanticObjectId(destination_id))

            if not destination:
                _reject(result, destination_id, "destination_not_found")
                continue

            if destination.map_id != map_id or not destination.is_active:
                _reject(result, destination_id, "destination_inactive")
                continue

            if destination.point_type not in DESTINATION_CAPABLE_POINT_TYPES:
                _reject(result, destination_id, "not_a_destination")
                continue

            # ── EDGE ATTACHMENT ─────────────────────────────────────────
            # Revalidated from a fresh read exactly like a point pair: the
            # edge must still be an active same-map walkway between two
            # real transit points, and the requested attachment must still
            # have a clear line from the destination. Only then is the
            # junction created.
            if corridor_edge_id:
                if attachment_x is None or attachment_y is None:
                    _reject(result, destination_id, "missing_attachment_position")
                    continue

                corridor_edge = await RouteEdge.get(PydanticObjectId(corridor_edge_id))

                if (
                    not corridor_edge
                    or not corridor_edge.is_active
                    or corridor_edge.map_id != map_id
                    or corridor_edge.edge_type != "walkway"
                    or corridor_edge.to_map_id is not None
                ):
                    _reject(result, destination_id, "corridor_edge_no_longer_valid")
                    continue

                edge_from = await RoutePoint.get(
                    PydanticObjectId(corridor_edge.from_point_id)
                )
                edge_to = await RoutePoint.get(
                    PydanticObjectId(corridor_edge.to_point_id)
                )

                if (
                    not edge_from
                    or not edge_to
                    or not edge_from.is_active
                    or not edge_to.is_active
                    or edge_from.point_type not in TRANSIT_CANDIDATE_POINT_TYPES
                    or edge_to.point_type not in TRANSIT_CANDIDATE_POINT_TYPES
                ):
                    _reject(result, destination_id, "corridor_edge_no_longer_valid")
                    continue

                # Floor compatibility uses the SHARED rule, not a raw
                # comparison. This is the same silent-loop shape as the
                # duplicate-edge bug: the preview proposes with
                # _floors_are_compatible (which, when Map.floor is set,
                # knows every RoutePoint on the map is on that floor by
                # construction and ignores stale/None per-point values),
                # and apply used to refuse with `!=`. On a Floor 2 map
                # holding any legacy point whose own `floor` was never
                # stamped, every such proposal came back forever.
                if not (
                    _floors_are_compatible(
                        edge_from.floor, destination.floor, map_item.floor
                    )
                    and _floors_are_compatible(
                        edge_to.floor, destination.floor, map_item.floor
                    )
                ):
                    _reject(result, destination_id, "floor_mismatch")
                    continue

                # GEOMETRY REVALIDATION — from a fresh read, and through
                # the SAME authority the preview used.
                #
                # This used to call the legacy _attachment_is_clear only.
                # Since destination attachment moved onto the strict,
                # full-resolution path, that made apply disagree with
                # preview in both directions: a doorway-resolved proposal
                # was proposed and then silently refused here, and a long
                # line the legacy 3% budget waved through would have been
                # accepted here after the search had rejected it. Asking
                # resolve_doorway_exit_point — exactly what
                # find_attachment_candidates asks — keeps the write path
                # neither weaker nor stricter than the proposal it is
                # applying. Nothing is trusted from the client: the
                # coordinates are re-read from the database above.
                await _ensure_map_source_available(map_id)
                metrics = get_strict_wall_metrics(map_id)

                if metrics is not None:
                    verdict = resolve_doorway_exit_point(
                        map_id=map_id,
                        metrics=metrics,
                        origin_x=float(destination.x),
                        origin_y=float(destination.y),
                        target_x=float(attachment_x),
                        target_y=float(attachment_y),
                        canonical_diagonal_px=_canonical_diagonal_px(map_item),
                        is_calibrated=bool(map_item.is_calibrated),
                        scale=_get_scale_for_floor(map_item, destination.floor),
                    )
                    if not verdict.accepted:
                        _reject(
                            result,
                            destination_id,
                            verdict.reason or "blocked_by_wall",
                        )
                        continue
                elif _get_wall_mask(map_id) is not None:
                    # No strict mask for this map — fall back to exactly
                    # the previous behaviour.
                    is_clear, _ = _attachment_is_clear(
                        map_id,
                        float(destination.x),
                        float(destination.y),
                        float(attachment_x),
                        float(attachment_y),
                    )
                    if not is_clear:
                        _reject(result, destination_id, "blocked_by_wall")
                        continue

                junction = await _split_corridor_edge_for_attachment(
                    map_id,
                    corridor_edge,
                    float(attachment_x),
                    float(attachment_y),
                    calculate_edge_distance,
                )
                if junction is None:
                    _reject(result, destination_id, "edge_split_failed")
                    continue

                corridor = junction
                corridor_id = str(junction.id)
                created_junction_id = corridor_id
                result["corridor_junctions_created"] += 1
                result["created_point_ids"].append(corridor_id)
            else:
                corridor = await RoutePoint.get(PydanticObjectId(corridor_id))

            if destination_id == corridor_id:
                _reject(result, destination_id, "same_point")
                continue

            if not corridor:
                _reject(result, destination_id, "corridor_not_found")
                continue

            if not corridor.is_active:
                _reject(result, destination_id, "corridor_inactive")
                continue

            # The corridor side must genuinely belong to the exact map this
            # apply call was scoped to — never trust a stale/forged pair
            # that has since drifted, even if both points still exist.
            if corridor.map_id != map_id:
                _reject(result, destination_id, "wrong_map")
                continue

            if not _floors_are_compatible(
                destination.floor, corridor.floor, map_item.floor
            ):
                _reject(result, destination_id, "floor_mismatch")
                continue

            # Nested-room navigation (Section 12.B): the "corridor" side of
            # an approved nested pair is actually the destination's own
            # confirmed parent Room's destination point (point_type
            # "room"/"store"), never a hallway/junction — so the ordinary
            # transit-candidate check is deliberately widened, but ONLY
            # when there is a real, explicit, approved containment
            # relationship AND the parent has allow_transit_through set.
            # An unrelated nearby Room can never slip through this check
            # just because it happens to be destination-capable.
            is_nested_pair = False
            if corridor.point_type not in TRANSIT_CANDIDATE_POINT_TYPES:
                if corridor.point_type in DESTINATION_CAPABLE_POINT_TYPES:
                    destination_room = await Room.find_one(
                        {"route_point_id": destination_id}
                    )
                    corridor_room = await Room.find_one(
                        {"route_point_id": corridor_id}
                    )
                    if (
                        destination_room
                        and corridor_room
                        and destination_room.parent_room_id == str(corridor_room.id)
                        and corridor.allow_transit_through
                    ):
                        is_nested_pair = True

                if not is_nested_pair:
                    _reject(result, destination_id, "not_transit")
                    continue

            # Never a vertical-connector stop on either side.
            if destination.connector_id is not None or corridor.connector_id is not None:
                _reject(result, destination_id, "connector_stop")
                continue

            duplicate = await find_duplicate_edge(
                map_id=map_id,
                from_point_id=destination_id,
                to_point_id=corridor_id,
                edge_type="walkway",
            )
            if duplicate:
                result["skipped_existing"] += 1
                continue

            distance = await calculate_edge_distance(
                map_id=map_id,
                from_point_id=destination_id,
                to_point_id=corridor_id,
                edge_type="walkway",
            )

            new_edge = RouteEdge(
                map_id=map_id,
                from_point_id=destination_id,
                to_point_id=corridor_id,
                edge_type="walkway",
                distance=distance,
                is_bidirectional=True,
                is_accessible=True,
                description=(
                    "Auto Connect: approved nested-room access"
                    if is_nested_pair
                    else "Auto Connect Destinations to Corridors"
                ),
                access_relation="nested" if is_nested_pair else None,
            )
            await new_edge.insert()

            result["created"] += 1
            result["created_edge_ids"].append(str(new_edge.id))

        except Exception as error:  # noqa: BLE001 — one bad pair must never
            # abort the batch, and the raw exception must never reach the
            # admin — only a safe, generic warning does.
            result["failed"] += 1
            if created_junction_id:
                # A junction was created before the failure. The corridor
                # itself is intact (the original edge is only deactivated
                # once both replacements exist), so this is a harmless
                # leftover — but say so rather than leaving it unexplained.
                result["warnings"].append(
                    f"Could not attach destination {destination_id} to the "
                    f"corridor; a corridor junction was created and left in "
                    f"place."
                )
            else:
                result["warnings"].append(
                    f"Could not connect destination {destination_id} to corridor "
                    f"point {corridor_id}."
                )

    # "Every accepted navigable room gets its own QR", stage 2 of 2 — and in
    # practice the one that actually issues most of them.
    #
    # This is the moment a destination stops being an isolated point and
    # becomes reachable, which is exactly the condition
    # ensure_room_location_codes() requires before it will mint a code. The
    # identical call also runs at the end of
    # services/semantic_destination_service.apply_semantic_destinations for
    # the rooms whose arrival point was already connected; the function is
    # idempotent, so whichever of the two runs first wins and the other
    # simply reports the code as reused.
    #
    # Never raises: the edges above are already written and must stand on
    # their own even if QR issuing has a problem.
    try:
        qr_summary = await ensure_room_location_codes(map_id)
        merge_into_apply_result(result, qr_summary)
    except Exception as error:  # noqa: BLE001 - never fails the apply
        result["warnings"].append(
            f"Connections were applied, but automatic QR issuing failed: {error}"
        )

    return result