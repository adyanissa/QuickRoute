"""
The automatic navigation build — READ-ONLY preview (Phase A).

Turns an uploaded floor plan plus an approved semantic analysis into a
proposed hidden transit graph and a set of room arrival points, so an
admin never has to draw hallway points by hand.

THIS MODULE WRITES NOTHING. No Room, RoutePoint, RouteEdge, LocationCode,
semantic review or publication record is created, updated or deleted
anywhere in this file or anything it calls. Persistence is Phase B and
does not exist yet.

--------------------------------------------------------------------
THE CHICKEN-AND-EGG, AND HOW IT IS BROKEN
--------------------------------------------------------------------
The strongest evidence that a piece of free space is inside the building
is a VALIDATED ARRIVAL POINT — a coordinate already proven off-wall and
line-of-sight connected. Not a label centre: a room label's bounding box
sits inside the room it names, which says nothing about whether the space
around it is circulation, and a dense cluster of labels is at least as
likely to be a legend.

But destination_auto_placement_service can only validate an arrival point
against corridor nodes that already exist. On a freshly uploaded map there
are none. So the region wants arrival points, and arrival points want a
graph.

The cycle is broken by building a PROVISIONAL graph from weak geometric
evidence, using it purely to obtain arrival points, and then throwing it
away.

--------------------------------------------------------------------
PROVISIONAL EVIDENCE NEVER BECOMES FINAL EVIDENCE
--------------------------------------------------------------------
This is a hard invariant of this module, not an optimisation.

  Pass 1  provisional region   weak signals only: enclosure, border,
                               shape, furniture. No arrival points.
  Pass 2  provisional graph    in-memory, never persisted, never trusted.
  Pass 3  provisional arrivals placement validated against the
                               provisional nodes, with the STRICT
                               validator.
  Pass 4  refined region       re-decided WITH arrival evidence. The
                               provisional arrival coordinates inform this
                               decision and nothing else.
  ----  everything provisional is discarded here  ----
  Pass 5  FINAL graph          rebuilt from scratch out of the refined
                               region. Not filtered, not patched, not
                               inherited — recomputed. Every edge is
                               re-proven with strict_has_clear_line.
  Pass 6  FINAL arrivals and   recomputed from scratch against the FINAL
          FINAL attachments    nodes. No provisional node id, attachment,
                               edge or connectivity decision survives into
                               the response.

So every node, edge, arrival point and attachment the admin sees has been
independently proven from the refined geometry. The provisional pass
survives only as counts in the diagnostics block, for comparison.

--------------------------------------------------------------------
OCR IS OPTIONAL
--------------------------------------------------------------------
Vector-PDF label extraction needs no tesseract. When the map is a raster
and tesseract is absent, the pipeline reports label_source "unavailable"
with the reason, rather than silently behaving as though the drawing had
no text on it. A missing OCR binary is never a startup requirement.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np
from beanie import PydanticObjectId

from models.location_code_model import LocationCode
from models.map_model import Map
from models.semantic_map_publication_model import SemanticMapPublication
from services.auto_connect_destinations_service import _effective_bounds
from services.building_region_service import (
    classify_regions,
    region_contours,
)
from services.circulation_region_service import (
    CirculationResult,
    identify_circulation,
)
from services.corridor_graph_service import CorridorGraph, extract_corridor_graph
from services.destination_auto_placement_service import (
    GeometryValidator,
    preview_destination_auto_placement,
)
from services.map_label_extraction_service import extract_map_labels
from services.semantic_label_matching_service import match_entity_to_label
from services.page_furniture_service import detect_page_furniture
from services.strict_geometry_service import (
    get_strict_wall_mask,
    measure_wall_stroke_thickness,
    strict_has_clear_line,
    strict_is_wall_pixel,
    strict_mask_available,
)


# Region polygons returned for the overlay are simplified by this many
# source pixels — enough to keep the payload small, fine enough that the
# admin can still see whether the outline follows the real walls.
REGION_CONTOUR_SIMPLIFY_PX = 3.0

# Cap on rejected edges reported, so one pathological map cannot return a
# multi-megabyte response. The COUNT is always exact and unclamped.
MAX_REJECTED_EDGES_REPORTED = 200

# public_areas[].area_type values that mean shared circulation. Drawn from
# the EXISTING taxonomy in the semantic prompt's section U — no new schema
# value is introduced. Anything not in this set (waiting_area, plaza,
# open_to_below, ...) is not treated as corridor evidence.
CIRCULATION_AREA_TYPES = frozenset(
    {
        "main_corridor",
        "secondary_corridor",
        "service_corridor",
        "emergency_corridor",
        "internal_corridor",
        "passage",
        "hall",
        "connecting_hall",
        "lobby",
        "shared_lobby",
        "residential_lobby",
        "vestibule",
        "public_concourse",
        "pedestrian_path",
        "covered_walkway",
        "external_walkway",
    }
)

# A public_area is only used as circulation evidence when the analysis and
# the reviewer both stand behind it.
CIRCULATION_ACCEPTED_REVIEW = frozenset({"accepted", "corrected"})
CIRCULATION_ACCEPTED_STATUS = frozenset({"confirmed", "probable"})


@dataclass
class _ProvisionalNode:
    """
    Quacks like a RoutePoint for exactly the attributes
    destination_auto_placement_service reads, so the provisional graph can
    stand in as a corridor candidate set without any of it being a
    database document. Deliberately not a Beanie model: nothing here can
    be saved even by accident.
    """

    id: str
    x: float
    y: float
    point_type: str = "hallway"
    floor: Optional[int] = None
    is_active: bool = True
    name: str = "Generated transit node"
    display_name: Optional[str] = None
    display_name_en: Optional[str] = None
    display_name_ar: Optional[str] = None
    display_name_he: Optional[str] = None
    is_auto_generated: bool = True
    room_id: Optional[str] = None
    connector_id: Optional[str] = None
    building_id: Optional[str] = None
    allow_transit_through: bool = False


def _nodes_as_candidates(
    graph: CorridorGraph, floor: Optional[int], prefix: str
) -> List[_ProvisionalNode]:
    return [
        _ProvisionalNode(
            id=f"{prefix}-{node.index}",
            x=node.x,
            y=node.y,
            floor=floor,
            name=f"Generated transit node {node.index}",
        )
        for node in graph.nodes
    ]


def _strict_geometry() -> GeometryValidator:
    return GeometryValidator(
        mask_available=strict_mask_available,
        wall_pixel=strict_is_wall_pixel,
        clear_line=strict_has_clear_line,
    )


def _arrival_points_from(placement: Dict[str, Any]) -> List[Tuple[float, float]]:
    points: List[Tuple[float, float]] = []
    for proposal in placement.get("proposals") or []:
        point = proposal.get("suggested_arrival_point")
        if isinstance(point, (list, tuple)) and len(point) >= 2:
            points.append((float(point[0]), float(point[1])))
    return points


async def _circulation_anchors_from_semantics(
    map_id: str, labels
) -> Tuple[List[Tuple[float, float]], Dict[str, Any]]:
    """
    Where the reviewed semantic analysis says the corridors are.

    The semantic contract deliberately carries NO coordinates — that
    separation is load-bearing and is not being relaxed here. So the
    spatial association is derived deterministically instead: a
    public_area's NAME is matched against the text actually printed on
    the map, using the same exact-rule matcher the room placement uses,
    and the matched label's position becomes the anchor.

    That means this evidence is only available when the map has readable
    labels. On a raster map with no OCR there are simply no circulation
    anchors, and the geometry falls back to door-adjacency alone — which
    is why circulation_region_service never requires them.
    """

    diagnostics: Dict[str, Any] = {
        "public_areas_in_publication": 0,
        "public_areas_circulation_typed": 0,
        "public_areas_matched_to_labels": 0,
        "matched_area_names": [],
        "unmatched_reason": None,
    }

    if not labels.available:
        diagnostics["unmatched_reason"] = (
            "No labels could be read from this map, so no public area could "
            "be located on it."
        )
        return [], diagnostics

    publication = await SemanticMapPublication.find_one(
        {"map_id": map_id, "is_active": True}
    )

    if not publication:
        diagnostics["unmatched_reason"] = "No active semantic publication."
        return [], diagnostics

    reviewed = publication.reviewed_result or {}
    areas = reviewed.get("public_areas") or []
    diagnostics["public_areas_in_publication"] = len(areas)

    anchors: List[Tuple[float, float]] = []

    for area in areas:
        if not isinstance(area, dict):
            continue

        area_type = (area.get("area_type_normalized") or area.get("area_type") or "")
        if str(area_type).strip().lower() not in CIRCULATION_AREA_TYPES:
            continue

        review_status = ((area.get("review") or {}).get("status") or "").lower()
        entity_status = (area.get("status") or "confirmed").lower()

        if review_status and review_status not in CIRCULATION_ACCEPTED_REVIEW:
            continue
        if entity_status not in CIRCULATION_ACCEPTED_STATUS:
            continue

        diagnostics["public_areas_circulation_typed"] += 1

        match = match_entity_to_label(area, labels.labels)

        if not match.matched or match.label is None:
            continue

        diagnostics["public_areas_matched_to_labels"] += 1
        diagnostics["matched_area_names"].append(match.label.text)
        anchors.append((match.label.center_x, match.label.center_y))

    if not anchors and diagnostics["public_areas_circulation_typed"]:
        diagnostics["unmatched_reason"] = (
            "Circulation areas were published, but none of their names "
            "matched a label printed on this map."
        )

    return anchors, diagnostics


def _room_label_anchors(placement: Dict[str, Any]) -> List[Tuple[float, float]]:
    """
    Matched ROOM label centres.

    A room label sits inside the room it names, which makes it exactly the
    right evidence for "this enclosed cell is a room" — the negative
    signal. It is deliberately NOT used as evidence that anything is a
    corridor; that would be the failure the label rules warn about.
    """

    anchors: List[Tuple[float, float]] = []

    for proposal in placement.get("proposals") or []:
        centre = (proposal.get("diagnostics") or {}).get("label_center")
        if isinstance(centre, (list, tuple)) and len(centre) >= 2:
            anchors.append((float(centre[0]), float(centre[1])))

    return anchors


def _label_boxes(labels) -> List[Tuple[float, float, float, float]]:
    return [(label.x0, label.y0, label.x1, label.y1) for label in labels.labels]


def _empty_response(map_id: str, stage: str, reason: str, diagnostics) -> Dict[str, Any]:
    return {
        "map_id": map_id,
        "publication_id": None,
        "available": False,
        "reason": reason,
        "failed_stage": stage,
        "region_polygons": [],
        "graph_nodes": [],
        "graph_edges": [],
        "rejected_edges": [],
        "rooms": [],
        "location_codes_would_be_created": 0,
        "diagnostics": diagnostics,
        "warnings": [],
    }


async def preview_navigation_build(
    map_id: str,
    *,
    item_external_ids: Optional[List[str]] = None,
    lang: str = "en",
) -> Dict[str, Any]:
    """Returns the NavigationBuildPreviewResponse shape. Writes nothing."""

    timings: Dict[str, int] = {}
    refusals: List[Dict[str, str]] = []
    warnings: List[str] = []

    diagnostics: Dict[str, Any] = {
        "strict_geometry_resolution": {},
        "topology_working_resolution": {},
        "source_resolution": {},
        "wall_stroke_thickness_px": 0.0,
        "topology_closing_kernel_px": 0,
        "gap_seal_backoffs": 0,
        "label_source": "unavailable",
        "label_source_reason": None,
        "label_count": 0,
        "ocr_available": False,
        "region_component_count": 0,
        "interior_component_count": 0,
        "rejected_component_count": 0,
        "region_components": [],
        "page_furniture": [],
        "skeleton_node_count_before_simplification": 0,
        "proposed_node_count": 0,
        "proposed_edge_count": 0,
        "subdivided_edge_count": 0,
        "rejected_edge_count": 0,
        "pruned_component_count": 0,
        "pruned_node_count": 0,
        "accepted_semantic_room_count": 0,
        "provisional_arrival_count": 0,
        "final_auto_positioned_room_count": 0,
        "final_auto_connected_room_count": 0,
        "rooms_requiring_review": [],
        "circulation": {},
        "semantic_circulation_evidence": {},
        "provisional_node_count": 0,
        "provisional_edge_count": 0,
        "provisional_interior_component_count": 0,
        "region_changed_after_refinement": False,
        "provisional_graph_discarded": True,
        "timings_ms": timings,
        "stage_refusals": refusals,
    }

    from services.ocr_service import is_ocr_available

    diagnostics["ocr_available"] = bool(is_ocr_available())

    map_item = await Map.get(PydanticObjectId(map_id))

    if not map_item:
        return _empty_response(map_id, "map", "Map not found.", diagnostics)

    diagnostics["source_resolution"] = {
        "width": int(map_item.source_width or 0),
        "height": int(map_item.source_height or 0),
    }

    # ---------------------------------------------------------------
    # Stage 0 — strict geometry
    # ---------------------------------------------------------------
    started = time.perf_counter()
    strict = get_strict_wall_mask(map_id)
    timings["strict_mask_ms"] = int((time.perf_counter() - started) * 1000)

    if strict is None:
        reason = (
            "This map has no processed source image, so no wall geometry can "
            "be checked. Nothing can be generated automatically without it."
        )
        refusals.append({"stage": "strict_geometry", "reason": reason})
        return _empty_response(map_id, "strict_geometry", reason, diagnostics)

    strict_mask, strict_downscale = strict
    diagnostics["strict_geometry_resolution"] = {
        "width": int(strict_mask.shape[1]),
        "height": int(strict_mask.shape[0]),
    }

    stroke_thickness = measure_wall_stroke_thickness(strict_mask)
    diagnostics["wall_stroke_thickness_px"] = round(stroke_thickness, 2)

    # ---------------------------------------------------------------
    # Stage 1 — labels (vector PDF first; OCR only if available)
    # ---------------------------------------------------------------
    started = time.perf_counter()
    labels = extract_map_labels(map_item)
    timings["labels_ms"] = int((time.perf_counter() - started) * 1000)

    diagnostics["label_source"] = labels.source
    diagnostics["label_source_reason"] = labels.reason
    diagnostics["label_count"] = len(labels.labels)

    if not labels.available and labels.reason:
        warnings.append(labels.reason)

    # ---------------------------------------------------------------
    # Stage 2 — page furniture (title blocks, legends, frames)
    # ---------------------------------------------------------------
    started = time.perf_counter()
    furniture = detect_page_furniture(
        strict_mask, _label_boxes(labels), mask_scale=strict_downscale
    )
    timings["furniture_ms"] = int((time.perf_counter() - started) * 1000)
    diagnostics["page_furniture"] = [item.to_dict() for item in furniture]

    # ---------------------------------------------------------------
    # PASS 1 — PROVISIONAL region, weak evidence only
    # ---------------------------------------------------------------
    started = time.perf_counter()
    provisional_region = classify_regions(
        strict_mask,
        stroke_thickness,
        arrival_points=(),
        label_boxes=_label_boxes(labels),
        furniture=furniture,
        mask_scale=strict_downscale,
    )
    timings["provisional_region_ms"] = int((time.perf_counter() - started) * 1000)

    diagnostics["topology_closing_kernel_px"] = provisional_region.topology_kernel_px
    diagnostics["gap_seal_backoffs"] = provisional_region.gap_seal_backoffs
    diagnostics["provisional_interior_component_count"] = len(
        provisional_region.interior_components
    )

    if not provisional_region.available:
        refusals.append(
            {"stage": "building_region", "reason": provisional_region.reason or ""}
        )
        diagnostics["region_component_count"] = len(provisional_region.components)
        diagnostics["region_components"] = [
            component.to_dict() for component in provisional_region.components
        ]
        return _empty_response(
            map_id, "building_region", provisional_region.reason or "", diagnostics
        )

    # ---------------------------------------------------------------
    # PASS 2 — PROVISIONAL graph. In memory. Never persisted. Never
    #          trusted as output.
    # ---------------------------------------------------------------
    started = time.perf_counter()

    # Circulation for the provisional pass, with no semantic anchors yet.
    # Door-adjacency alone is enough to keep the provisional graph out of
    # room interiors, which matters because the arrival points validated
    # against it should be reaching toward a corridor, not toward a node
    # that happens to sit in the middle of a storage room.
    provisional_circulation = identify_circulation(
        strict_mask,
        provisional_region.interior_mask,
        stroke_thickness_px=stroke_thickness,
        mask_scale=strict_downscale,
    )

    provisional_graph = extract_corridor_graph(
        strict_mask,
        provisional_circulation.circulation_mask
        if provisional_circulation.available
        else provisional_region.interior_mask,
        mask_scale=strict_downscale,
        stroke_thickness_px=stroke_thickness,
        map_id=map_id,
        strict_mask=strict_mask,
        strict_downscale=strict_downscale,
    )
    timings["provisional_graph_ms"] = int((time.perf_counter() - started) * 1000)

    diagnostics["provisional_node_count"] = len(provisional_graph.nodes)
    diagnostics["provisional_edge_count"] = len(provisional_graph.edges)

    geometry = _strict_geometry()

    # ---------------------------------------------------------------
    # PASS 3 — PROVISIONAL arrival points, validated against the
    #          provisional nodes with the STRICT validator.
    # ---------------------------------------------------------------
    provisional_arrivals: List[Tuple[float, float]] = []
    # Matched ROOM LABEL centres. These come from name-to-label matching,
    # which does not consult the graph at all, so unlike the arrival
    # points they are not provisional-graph evidence and survive the
    # discard below. They are used for one thing only: marking the cell a
    # room sits in as a room.
    room_label_anchors: List[Tuple[float, float]] = []

    if provisional_graph.available:
        started = time.perf_counter()
        provisional_placement = await preview_destination_auto_placement(
            map_id,
            item_external_ids=item_external_ids,
            lang=lang,
            corridor_candidates=_nodes_as_candidates(
                provisional_graph, map_item.floor, "provisional"
            ),
            geometry=geometry,
        )
        timings["provisional_placement_ms"] = int(
            (time.perf_counter() - started) * 1000
        )
        provisional_arrivals = _arrival_points_from(provisional_placement)
        room_label_anchors = _room_label_anchors(provisional_placement)
    else:
        refusals.append(
            {
                "stage": "provisional_graph",
                "reason": provisional_graph.reason or "No provisional graph.",
            }
        )

    diagnostics["provisional_arrival_count"] = len(provisional_arrivals)

    # ---------------------------------------------------------------
    # PASS 4 — REFINED region, now with strong semantic evidence.
    # ---------------------------------------------------------------
    started = time.perf_counter()
    refined_region = classify_regions(
        strict_mask,
        stroke_thickness,
        arrival_points=provisional_arrivals,
        label_boxes=_label_boxes(labels),
        furniture=furniture,
        mask_scale=strict_downscale,
    )
    timings["refined_region_ms"] = int((time.perf_counter() - started) * 1000)

    if not refined_region.available:
        refusals.append(
            {"stage": "refined_region", "reason": refined_region.reason or ""}
        )
        diagnostics["region_component_count"] = len(refined_region.components)
        diagnostics["region_components"] = [
            component.to_dict() for component in refined_region.components
        ]
        return _empty_response(
            map_id, "refined_region", refined_region.reason or "", diagnostics
        )

    diagnostics["region_changed_after_refinement"] = not np.array_equal(
        provisional_region.interior_mask, refined_region.interior_mask
    )
    diagnostics["region_component_count"] = len(refined_region.components)
    diagnostics["interior_component_count"] = len(refined_region.interior_components)
    diagnostics["rejected_component_count"] = len(refined_region.rejected_components)
    diagnostics["region_components"] = [
        component.to_dict() for component in refined_region.components
    ]

    # ===============================================================
    # EVERYTHING PROVISIONAL IS DISCARDED HERE.
    #
    # The provisional graph and its arrival points informed the region
    # decision above and nothing else. Nothing below reads them: the
    # final graph is recomputed from the refined region, not filtered or
    # patched from the provisional one, and the final arrival points and
    # attachments are recomputed from scratch against the final nodes.
    # ===============================================================
    provisional_graph = None      # noqa: F841 - explicit, not decorative
    provisional_circulation = None  # noqa: F841
    provisional_arrivals = []     # noqa: F841

    # ---------------------------------------------------------------
    # PASS 5 — FINAL circulation, then the FINAL graph on it.
    #
    # Room interiors are NEGATIVE evidence and reviewed circulation areas
    # are POSITIVE evidence, but neither can conjure geometry: the cells
    # come from real wall constrictions, and every edge is still proven
    # against the unmodified wall mask afterwards.
    # ---------------------------------------------------------------
    started = time.perf_counter()

    circulation_anchors, semantic_evidence = await _circulation_anchors_from_semantics(
        map_id, labels
    )
    diagnostics["semantic_circulation_evidence"] = semantic_evidence

    final_circulation = identify_circulation(
        strict_mask,
        refined_region.interior_mask,
        stroke_thickness_px=stroke_thickness,
        room_anchors=room_label_anchors,
        circulation_anchors=circulation_anchors,
        mask_scale=strict_downscale,
    )
    timings["circulation_ms"] = int((time.perf_counter() - started) * 1000)
    diagnostics["circulation"] = final_circulation.diagnostics()

    if not final_circulation.available:
        refusals.append(
            {"stage": "circulation", "reason": final_circulation.reason or ""}
        )
        response = _empty_response(
            map_id, "circulation", final_circulation.reason or "", diagnostics
        )
        response["region_polygons"] = _region_polygons(
            refined_region, strict_downscale
        )
        response["warnings"] = warnings
        return response

    started = time.perf_counter()
    final_graph = extract_corridor_graph(
        strict_mask,
        final_circulation.circulation_mask,
        mask_scale=strict_downscale,
        stroke_thickness_px=stroke_thickness,
        map_id=map_id,
        strict_mask=strict_mask,
        strict_downscale=strict_downscale,
    )
    timings["final_graph_ms"] = int((time.perf_counter() - started) * 1000)

    graph_diagnostics = final_graph.diagnostics()
    diagnostics["topology_working_resolution"] = graph_diagnostics[
        "topology_working_resolution"
    ]
    diagnostics["skeleton_node_count_before_simplification"] = graph_diagnostics[
        "skeleton_node_count_before_simplification"
    ]
    diagnostics["proposed_node_count"] = len(final_graph.nodes)
    diagnostics["proposed_edge_count"] = len(final_graph.edges)
    diagnostics["subdivided_edge_count"] = final_graph.subdivided_edge_count
    diagnostics["rejected_edge_count"] = len(final_graph.rejected_edges)
    diagnostics["pruned_component_count"] = final_graph.pruned_component_count
    diagnostics["pruned_node_count"] = final_graph.pruned_node_count

    region_polygons = _region_polygons(refined_region, strict_downscale)

    if not final_graph.available:
        refusals.append(
            {"stage": "final_graph", "reason": final_graph.reason or ""}
        )
        response = _empty_response(
            map_id, "final_graph", final_graph.reason or "", diagnostics
        )
        response["region_polygons"] = region_polygons
        response["warnings"] = warnings
        return response

    # ---------------------------------------------------------------
    # PASS 6 — FINAL arrival points and attachments, from scratch.
    # ---------------------------------------------------------------
    started = time.perf_counter()
    final_placement = await preview_destination_auto_placement(
        map_id,
        item_external_ids=item_external_ids,
        lang=lang,
        corridor_candidates=_nodes_as_candidates(
            final_graph, map_item.floor, "final"
        ),
        geometry=geometry,
    )
    timings["final_placement_ms"] = int((time.perf_counter() - started) * 1000)

    warnings.extend(final_placement.get("warnings") or [])

    rooms, needing_review, positioned, connected = _rooms_from_placement(
        final_placement, final_graph
    )

    diagnostics["accepted_semantic_room_count"] = int(
        (final_placement.get("summary") or {}).get("scanned", 0)
    )
    diagnostics["final_auto_positioned_room_count"] = positioned
    diagnostics["final_auto_connected_room_count"] = connected
    diagnostics["rooms_requiring_review"] = needing_review

    # ---------------------------------------------------------------
    # How many QR codes an apply WOULD create. Reads only.
    # ---------------------------------------------------------------
    would_create = await _count_location_codes_that_would_be_created(map_id, rooms)

    return {
        "map_id": map_id,
        "publication_id": final_placement.get("publication_id"),
        "available": True,
        "reason": None,
        "failed_stage": None,
        "region_polygons": region_polygons,
        "graph_nodes": [node.to_dict() for node in final_graph.nodes],
        "graph_edges": [edge.to_dict() for edge in final_graph.edges],
        "rejected_edges": [
            {
                "from_point": edge.to_dict()["from"],
                "to_point": edge.to_dict()["to"],
                "reason": edge.reason,
            }
            for edge in final_graph.rejected_edges[:MAX_REJECTED_EDGES_REPORTED]
        ],
        "rooms": rooms,
        "location_codes_would_be_created": would_create,
        "diagnostics": diagnostics,
        "warnings": warnings,
    }


def _region_polygons(region, mask_scale: float) -> List[Dict[str, Any]]:
    """
    Interior outlines plus the rejected components and why they were
    rejected. Showing what was thrown away is how an operator judges
    whether the region decision was right on a real drawing.
    """

    polygons: List[Dict[str, Any]] = [
        {"points": points, "decision": "interior", "reason": None}
        for points in region_contours(
            region.interior_mask, mask_scale, simplify_px=REGION_CONTOUR_SIMPLIFY_PX
        )
    ]

    inverse = 1.0 / mask_scale if mask_scale else 1.0

    for component in region.rejected_components:
        x0, y0, x1, y1 = component.bbox
        polygons.append(
            {
                "points": [
                    [round(x0 * inverse, 1), round(y0 * inverse, 1)],
                    [round(x1 * inverse, 1), round(y0 * inverse, 1)],
                    [round(x1 * inverse, 1), round(y1 * inverse, 1)],
                    [round(x0 * inverse, 1), round(y1 * inverse, 1)],
                ],
                "decision": "rejected",
                "reason": component.reason,
            }
        )

    return polygons


def _rooms_from_placement(
    placement: Dict[str, Any], graph: CorridorGraph
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], int, int]:
    """
    Convert the placement proposals into the preview's room shape, mapping
    each attachment back onto a FINAL graph node index.
    """

    node_by_id = {f"final-{node.index}": node for node in graph.nodes}

    rooms: List[Dict[str, Any]] = []
    needing_review: List[Dict[str, Any]] = []
    positioned = 0
    connected = 0

    for proposal in placement.get("proposals") or []:
        status = proposal.get("status")
        diagnostics = proposal.get("diagnostics") or {}
        point = proposal.get("suggested_arrival_point")

        arrival = None
        if isinstance(point, (list, tuple)) and len(point) >= 2:
            arrival = {"x": float(point[0]), "y": float(point[1])}
            positioned += 1

        attachment = None
        element = proposal.get("matched_graph_element")

        if element:
            node = node_by_id.get(element.get("route_point_id"))
            attachment = {
                "node_index": node.index if node else None,
                "node_x": float(element.get("x")) if element.get("x") is not None else None,
                "node_y": float(element.get("y")) if element.get("y") is not None else None,
                "distance_px": element.get("distance_px"),
                "confidence_tier": element.get("confidence_tier"),
                # The placement service only ever emits a matched element
                # after its clear-line gate passed, and this run was given
                # the strict validator.
                "strict_clear_line": True,
            }
            connected += 1

        would_create_code = status == "auto_connectable" and attachment is not None

        rooms.append(
            {
                "semantic_item_id": proposal.get("semantic_item_id"),
                "room_name": proposal.get("room_name"),
                "room_number": proposal.get("room_number"),
                "matched_room_id": proposal.get("matched_room_id"),
                "status": status,
                "message": proposal.get("message"),
                "matched_label": diagnostics.get("matched_label"),
                "label_bbox": diagnostics.get("label_bbox"),
                "arrival_point": arrival,
                "attachment": attachment,
                "semantic_match_confidence": proposal.get(
                    "semantic_match_confidence", 0.0
                ),
                "geometry_confidence": proposal.get("geometry_confidence", 0.0),
                "would_create_location_code": would_create_code,
                "diagnostics": diagnostics,
            }
        )

        if status != "auto_connectable":
            needing_review.append(
                {
                    "semantic_item_id": proposal.get("semantic_item_id"),
                    "room_name": proposal.get("room_name"),
                    "status": status,
                    "reason": proposal.get("message") or status,
                }
            )

    return rooms, needing_review, positioned, connected


async def _count_location_codes_that_would_be_created(
    map_id: str, rooms: Sequence[Dict[str, Any]]
) -> int:
    """
    Mirrors room_location_code_service's rule — a room gets a code when it
    has an arrival point that is joined to its own floor's graph — without
    creating anything. Rooms whose existing arrival point already holds an
    active code are excluded, so the number is what an apply would ADD.
    """

    candidates = [room for room in rooms if room.get("would_create_location_code")]

    if not candidates:
        return 0

    existing = await LocationCode.find(
        {"map_id": map_id, "is_active": True}
    ).to_list()
    coded_room_ids = {code.route_point_id for code in existing}

    # A proposed room has no RoutePoint yet, so it cannot already hold a
    # code unless it was matched to an existing room whose point does.
    already = 0
    if coded_room_ids:
        from models.room_model import Room

        for room in candidates:
            matched_room_id = room.get("matched_room_id")
            if not matched_room_id:
                continue
            existing_room = await Room.get(PydanticObjectId(matched_room_id))
            if (
                existing_room
                and existing_room.route_point_id
                and existing_room.route_point_id in coded_room_ids
            ):
                already += 1

    return max(0, len(candidates) - already)
