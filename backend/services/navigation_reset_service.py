"""
Navigation-data reset workflows (RoutePoint/RouteEdge problem cleanup task).

Two distinct, deliberately separate destructive actions, both scoped to
Map(s) the caller explicitly selected — NEVER triggered automatically:

  1. Generated-only cleanup (see graph_generation_service.
     preview_generated_graph_cleanup / apply_generated_graph_cleanup) —
     deletes ONLY records proven auto-generated (is_auto_generated=True).
     Already existed before this module; left untouched here.

  2. Full navigation reset (this module) — deletes EVERY RoutePoint and
     RouteEdge on one explicitly selected Map, regardless of provenance.
     Intended for maps whose entire stored navigation graph predates the
     "manual-only" policy and is unwanted in bulk (hundreds of points
     scattered over title blocks/margins/legends, inaccurate edges, etc.)
     — reviewing/deleting them one by one through the ordinary RoutePoint
     management UI would be impractical.

Both are strictly read-only in their preview form and both require an
explicit, non-bypassable confirmation step before anything is written.

Never touches: the Map document itself, Building/MapGroup/Room documents,
calibration (Map.scale/floor_scales), semantic-analysis results/
publications, users, or invitation codes. Rooms/LocationCodes that
reference a deleted RoutePoint have ONLY their link field cleared/
deactivated — the Room/LocationCode record itself is preserved. Vertical
connectors are metadata-only documents (see models/vertical_connector_
model.py) that carry no direct RoutePoint reference of their own to clean
up; a connector's "stops" are simply RoutePoints tagged with
connector_id/connector_code, so deleting those RoutePoints (reported in
the summary by connector) already fully removes the stop — the
VerticalConnector document is never touched or deleted.
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional

from beanie import PydanticObjectId

from models.building_model import Building
from models.location_code_model import LocationCode
from models.map_model import Map
from models.room_model import Room
from models.route_edge_model import RouteEdge
from models.route_point_model import RoutePoint
# VerticalConnector itself is never read/written here — see the module
# docstring above for why (a connector's stops are just RoutePoints, not
# a reference array on the VerticalConnector document).


# Duplicated on purpose, not imported from routes.route_point_routes —
# services intentionally never import from the routes layer (see that
# module's own classify_route_point_source docstring / the identical
# _LEGACY_AUTO_POINT_NAME_RE duplication note in route_point_routes.py).
# Keep in sync with routes/route_point_routes.py's classify_route_point_source
# if either changes.
_LEGACY_AUTO_POINT_NAME_RE = re.compile(r"^Auto Point \d+$")


def classify_point_source(point: RoutePoint) -> str:
    """manual | generated | semantic_destination | vertical_connector |
    unknown_legacy — never inferred from name alone when a real
    provenance field already settles the question (Part 5 requirement:
    generated-only cleanup must never accidentally delete a real manual
    point just because it happens to be named like a legacy generator
    output)."""

    if point.is_auto_generated:
        return "generated"
    if point.semantic_entity_external_id:
        return "semantic_destination"
    if point.connector_id:
        return "vertical_connector"
    if point.name and _LEGACY_AUTO_POINT_NAME_RE.match(point.name.strip()):
        return "unknown_legacy"
    return "manual"


async def _map_or_404_dict(map_id: str) -> Optional[Map]:
    try:
        return await Map.get(PydanticObjectId(map_id))
    except Exception:
        return None


def _source_breakdown(points: List[RoutePoint]) -> Dict[str, int]:
    breakdown = {
        "manual": 0,
        "generated": 0,
        "semantic_destination": 0,
        "vertical_connector": 0,
        "unknown_legacy": 0,
    }
    for point in points:
        breakdown[classify_point_source(point)] += 1
    return breakdown


async def _gather_map_navigation_data(map_id: str):
    points = await RoutePoint.find({"map_id": map_id}).to_list()
    point_ids = [str(p.id) for p in points]

    edges = (
        await RouteEdge.find(
            {
                "$or": [
                    {"map_id": map_id},
                    {"from_point_id": {"$in": point_ids}},
                    {"to_point_id": {"$in": point_ids}},
                ]
            }
        ).to_list()
        if point_ids
        else await RouteEdge.find({"map_id": map_id}).to_list()
    )

    return points, point_ids, edges


# ---------------------------------------------------------
# B. Full navigation reset for ONE selected Map
# ---------------------------------------------------------

async def preview_full_map_reset(map_id: str) -> dict:
    """Read-only. Never deletes anything. Reports EVERY RoutePoint/
    RouteEdge on this map (unlike generated-only cleanup, which only ever
    reports proven-generated records)."""

    map_item = await _map_or_404_dict(map_id)
    if not map_item:
        return {"found": False}

    points, point_ids, edges = await _gather_map_navigation_data(map_id)
    breakdown = _source_breakdown(points)

    rooms_linked = (
        await Room.find({"route_point_id": {"$in": point_ids}}).to_list()
        if point_ids
        else []
    )

    location_codes_linked = (
        await LocationCode.find({"route_point_id": {"$in": point_ids}}).to_list()
        if point_ids
        else []
    )

    connector_codes = sorted(
        {p.connector_code for p in points if p.connector_code}
    )

    return {
        "found": True,
        "map_id": map_id,
        "map_name": map_item.title,
        "floor": map_item.floor,
        "total_point_count": len(points),
        "total_edge_count": len(edges),
        "point_source_breakdown": breakdown,
        "rooms_linked_count": len(rooms_linked),
        "room_ids_linked": [str(r.id) for r in rooms_linked],
        "vertical_connectors_linked_count": len(connector_codes),
        "vertical_connector_codes_linked": connector_codes,
        "location_code_count": len(location_codes_linked),
        "location_codes_linked": [lc.code for lc in location_codes_linked],
        "point_ids": sorted(point_ids),
        "edge_ids": sorted(str(e.id) for e in edges),
        "warning": (
            "This deletes ALL route points and connections on this map, "
            "including any manually added ones. Public navigation on this "
            "map will be unavailable until an admin manually adds new "
            "route points. This cannot be undone."
        ),
    }


async def apply_full_map_reset(map_id: str) -> dict:
    """Deletes every RoutePoint/RouteEdge on this one map. Never deletes
    the Map, Building, MapGroup, Room, LocationCode, VerticalConnector,
    semantic-analysis data, or calibration. Idempotent: a second call on
    an already-reset map finds nothing left and returns zero counts."""

    map_item = await _map_or_404_dict(map_id)
    if not map_item:
        return {"found": False}

    points, point_ids, edges = await _gather_map_navigation_data(map_id)

    # 1. Clear (never delete) Room links to a point about to be removed —
    #    the Room record itself, including any manually-entered
    #    description/category, is fully preserved.
    rooms_linked = (
        await Room.find({"route_point_id": {"$in": point_ids}}).to_list()
        if point_ids
        else []
    )
    for room in rooms_linked:
        room.route_point_id = None
        room.is_active = False
        await room.save()

    # 2. Deactivate (never delete) LocationCodes whose start point is
    #    about to be removed — route_point_id is a required field on that
    #    model, so it cannot be nulled out; deactivating is the safe,
    #    reversible equivalent (mirrors how a deactivated Room stops
    #    appearing as a selectable destination without losing its data).
    location_codes_linked = (
        await LocationCode.find({"route_point_id": {"$in": point_ids}}).to_list()
        if point_ids
        else []
    )
    for code in location_codes_linked:
        code.is_active = False
        await code.save()

    # 3. Vertical connectors: nothing to null out on the VerticalConnector
    #    document itself (see module docstring) — just report which
    #    connector codes lose a stop as a result, computed BEFORE deletion.
    connector_codes_affected = sorted(
        {p.connector_code for p in points if p.connector_code}
    )

    breakdown = _source_breakdown(points)

    # 4. Delete edges first (never leave an edge referencing an
    #    already-deleted point, even transiently within this request).
    edge_ids_deleted = [str(e.id) for e in edges]
    for edge in edges:
        await edge.delete()

    point_ids_deleted = [str(p.id) for p in points]
    for point in points:
        await point.delete()

    return {
        "found": True,
        "map_id": map_id,
        "map_name": map_item.title,
        "applied": True,
        "points_deleted": len(point_ids_deleted),
        "edges_deleted": len(edge_ids_deleted),
        "point_ids_deleted": point_ids_deleted,
        "edge_ids_deleted": edge_ids_deleted,
        "point_source_breakdown_deleted": breakdown,
        "rooms_unlinked_count": len(rooms_linked),
        "room_ids_unlinked": [str(r.id) for r in rooms_linked],
        "location_codes_deactivated_count": len(location_codes_linked),
        "location_codes_deactivated": [lc.code for lc in location_codes_linked],
        "vertical_connectors_affected_count": len(connector_codes_affected),
        "vertical_connector_codes_affected": connector_codes_affected,
    }


# ---------------------------------------------------------
# Part 4 — multi-Map overview + multi-Map cleanup
# ---------------------------------------------------------

async def list_maps_navigation_overview() -> List[dict]:
    """Read-only summary of every Map's navigation-data footprint, for the
    Super Admin multi-Map cleanup screen. One query pass per map is
    avoided by loading every RoutePoint/RouteEdge/Building once and
    grouping in memory — this endpoint is expected to run over the whole
    system's maps, so a per-map round trip would not scale."""

    maps = await Map.find_all().to_list()
    all_points = await RoutePoint.find_all().to_list()
    all_edges = await RouteEdge.find_all().to_list()
    buildings = await Building.find_all().to_list()
    building_names = {str(b.id): b.name_en for b in buildings}

    points_by_map: Dict[str, List[RoutePoint]] = {}
    for point in all_points:
        points_by_map.setdefault(point.map_id, []).append(point)

    edge_count_by_map: Dict[str, int] = {}
    for edge in all_edges:
        edge_count_by_map[edge.map_id] = edge_count_by_map.get(edge.map_id, 0) + 1

    overview = []
    for map_item in maps:
        map_id = str(map_item.id)
        points = points_by_map.get(map_id, [])
        breakdown = _source_breakdown(points)

        overview.append(
            {
                "map_id": map_id,
                "map_name": map_item.title,
                "building_id": map_item.building_id,
                "building_name": (
                    building_names.get(map_item.building_id)
                    if map_item.building_id
                    else None
                ),
                "map_group_id": map_item.map_group_id,
                "floor": map_item.floor,
                "total_point_count": len(points),
                "generated_point_count": breakdown["generated"],
                "manual_point_count": breakdown["manual"],
                "semantic_destination_point_count": breakdown["semantic_destination"],
                "vertical_connector_point_count": breakdown["vertical_connector"],
                "unknown_legacy_point_count": breakdown["unknown_legacy"],
                "total_edge_count": edge_count_by_map.get(map_id, 0),
            }
        )

    return overview


async def _validate_selected_map_ids(map_ids: List[str]) -> List[str]:
    """Never trust a client-cached selection list — re-fetches and returns
    only ids that genuinely exist right now, so a stale selection can never
    silently include an already-deleted Map."""

    valid_ids = []
    for map_id in map_ids:
        map_item = await _map_or_404_dict(map_id)
        if map_item:
            valid_ids.append(map_id)
    return valid_ids


async def preview_multi_map_generated_cleanup(map_ids: List[str]) -> dict:
    from services.graph_generation_service import preview_generated_graph_cleanup

    valid_ids = await _validate_selected_map_ids(map_ids)
    per_map = [await preview_generated_graph_cleanup(mid) for mid in valid_ids]

    return {
        "requested_map_ids": map_ids,
        "valid_map_ids": valid_ids,
        "skipped_map_ids": [mid for mid in map_ids if mid not in valid_ids],
        "per_map": per_map,
        "total_generated_point_count": sum(p["generated_point_count"] for p in per_map),
        "total_generated_edge_count": sum(p["generated_edge_count"] for p in per_map),
    }


async def apply_multi_map_generated_cleanup(map_ids: List[str]) -> dict:
    """Revalidates every Map fresh (never trusts the preview's cached id
    list) and only ever touches the explicitly selected, still-existing
    Maps — never a silent global deletion across every Map in the system."""

    from services.graph_generation_service import apply_generated_graph_cleanup

    valid_ids = await _validate_selected_map_ids(map_ids)
    per_map = [await apply_generated_graph_cleanup(mid) for mid in valid_ids]

    return {
        "requested_map_ids": map_ids,
        "applied_map_ids": valid_ids,
        "skipped_map_ids": [mid for mid in map_ids if mid not in valid_ids],
        "per_map": per_map,
        "total_points_deleted": sum(p["points_deleted"] for p in per_map),
        "total_edges_deleted": sum(p["edges_deleted"] for p in per_map),
    }


async def preview_multi_map_full_reset(map_ids: List[str]) -> dict:
    valid_ids = await _validate_selected_map_ids(map_ids)
    per_map = [await preview_full_map_reset(mid) for mid in valid_ids]

    return {
        "requested_map_ids": map_ids,
        "valid_map_ids": valid_ids,
        "skipped_map_ids": [mid for mid in map_ids if mid not in valid_ids],
        "per_map": per_map,
        "total_point_count": sum(p["total_point_count"] for p in per_map),
        "total_edge_count": sum(p["total_edge_count"] for p in per_map),
    }


async def apply_multi_map_full_reset(map_ids: List[str]) -> dict:
    """Strictly limited to the explicitly selected, still-existing Maps —
    revalidated fresh here (never trusts a prior preview call), so a Map
    that was deleted (or whose scope changed) between preview and apply is
    simply skipped and reported, never silently included."""

    valid_ids = await _validate_selected_map_ids(map_ids)
    per_map = [await apply_full_map_reset(mid) for mid in valid_ids]

    return {
        "requested_map_ids": map_ids,
        "applied_map_ids": valid_ids,
        "skipped_map_ids": [mid for mid in map_ids if mid not in valid_ids],
        "per_map": per_map,
        "total_points_deleted": sum(p["points_deleted"] for p in per_map),
        "total_edges_deleted": sum(p["edges_deleted"] for p in per_map),
    }
