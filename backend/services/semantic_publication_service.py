"""
Publication workflow (Section 15) — the only code path allowed to move
admin-reviewed semantic data (Layer B) into the permanent, read-only
reference layer (Layer C's non-graph half: SemanticMapPublication /
SemanticEntity). Never touches Maps, RoutePoints, RouteEdges, Rooms, or
connectors. Never runs automatically — only POST
/api/semantic-analyses/{id}/publish (an explicit admin action) calls
`publish_analysis`.

Also owns the "authoritative semantic floor code" fix: the AI is
explicitly told (prompt Section Z, "TEMPORARY EXTERNAL IDS") to invent its
own placeholder ids like "floor_001" for internal cross-referencing —
that text has no relationship to which REAL physical floor a Map
represents, so every single-floor analysis tends to produce the exact
same "floor_001" regardless of the map it was run against. The one
authoritative source of "which floor is this" is (and always was)
Map.floor (see models/map_model.py) — `normalize_floor_codes` below
derives the correct `floor_{NNN}` code from that field and renames the
AI's own text (and every place/facility/etc that references it) to match,
without ever requiring the AI to be re-run and without ever mutating a
SemanticMapAnalysis's own `ai_result` (which the model's own docstring
promises is "never rewritten once status becomes completed").
"""

from __future__ import annotations

import copy
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from beanie import PydanticObjectId

from models.map_model import Map
from models.semantic_map_analysis_model import SemanticMapAnalysis
from models.semantic_map_publication_model import (
    SemanticEntity,
    SemanticMapPublication,
)
from schemas.localization_schema import localized_text_to_dict
from schemas.semantic_analysis_schema import FORBIDDEN_ROUTING_FIELD_NAMES

# entity_type -> (array key in reviewed_result, external-id field name)
ENTITY_ARRAYS = {
    "place": ("places", "place_external_id"),
    "facility": ("facilities", "facility_external_id"),
    "access_point": ("access_points", "access_external_id"),
    "public_area": ("public_areas", "area_external_id"),
    "vertical_connection": ("vertical_connections", "connection_external_id"),
    "outdoor_area": ("outdoor_areas", "outdoor_external_id"),
    "parking_area": ("parking_areas", "parking_external_id"),
    "parking_space": ("parking_spaces", "parking_space_external_id"),
}

# Every top-level array whose items may carry a `floor_external_id`
# reference to a `Floor` entity — derived from ENTITY_ARRAYS' own array
# names so this can never silently drift out of sync with the set of
# entity types the rest of this module already knows about.
_FLOOR_REFERENCING_ARRAYS = [array_name for array_name, _id_field in ENTITY_ARRAYS.values()]


def compute_authoritative_floor_code(floor_number: int) -> str:
    """The one and only place this format string is allowed to appear —
    every caller that needs a semantic floor code must go through this
    function rather than re-implementing the padding rule."""

    return f"floor_{floor_number:03d}"


def normalize_floor_codes(
    reviewed: Optional[Dict[str, Any]],
    *,
    floor_number: Optional[int],
) -> Tuple[Optional[Dict[str, Any]], List[str]]:
    """
    Renames the single floor entity's `floor_external_id` (and every
    place/facility/access_point/public_area/vertical_connection/
    outdoor_area/parking_area/parking_space that references it) to the
    authoritative code derived from the Map's own physical floor number —
    never trusts whatever temporary id text the AI invented.

    Pure and idempotent: returns a NEW dict (the input is never mutated
    in place — safe to call on `ai_result` for a display-only view
    without ever touching the persisted, "never rewritten" original).
    Returns `(reviewed, [])` unchanged when:
      - `reviewed` isn't a dict (nothing to normalize yet), or
      - `floor_number` is None (Map hasn't been assigned a physical
        floor yet — cannot compute an authoritative code, so nothing is
        guessed), or
      - this analysis has zero floor entities (nothing to rename), or
      - it has MORE than one floor entity — ambiguous which one
        corresponds to this single Map; same boundary
        `derive_floor_links` already uses to require an admin to supply
        explicit floor_links instead of guessing, or
      - the floor entity's code already matches (no-op, so callers can
        safely call this on every load/save without spurious "changed"
        signals).
    """

    if not isinstance(reviewed, dict):
        return reviewed, []
    if floor_number is None:
        return reviewed, []

    floors = reviewed.get("floors")
    if not isinstance(floors, list) or len(floors) != 1:
        return reviewed, []

    floor_entity = floors[0]
    if not isinstance(floor_entity, dict):
        return reviewed, []

    old_code = floor_entity.get("floor_external_id")
    new_code = compute_authoritative_floor_code(floor_number)
    if old_code == new_code:
        return reviewed, []

    updated = copy.deepcopy(reviewed)
    updated["floors"][0]["floor_external_id"] = new_code

    changed_references = 0
    for array_name in _FLOOR_REFERENCING_ARRAYS:
        for item in updated.get(array_name, []) or []:
            if isinstance(item, dict) and item.get("floor_external_id") == old_code:
                item["floor_external_id"] = new_code
                changed_references += 1

    messages = [
        f"Normalized semantic floor code: '{old_code}' -> '{new_code}' "
        f"(derived from this map's physical floor {floor_number}); "
        f"updated {changed_references} place/facility/entity reference(s) "
        "to keep the floor entity and its places consistent."
    ]
    return updated, messages


async def _authoritative_floor_number_for_map_scope(
    scope_type: str, map_id: Optional[str]
) -> Optional[int]:
    """Only meaningful for a single-map analysis (scope_type == "map") —
    a map-group analysis has no single Map to be authoritative for here;
    each floor within it maps to a DIFFERENT Map, which repair_floor_
    codes_for_map (scoped to one map at a time) handles instead."""

    if scope_type != "map" or not map_id or not PydanticObjectId.is_valid(map_id):
        return None
    map_item = await Map.get(PydanticObjectId(map_id))
    return map_item.floor if map_item else None


def _scan_forbidden_fields(node: Any, path: str = "$") -> List[str]:
    found: List[str] = []
    if isinstance(node, dict):
        for key, value in node.items():
            if key in FORBIDDEN_ROUTING_FIELD_NAMES:
                found.append(f"{path}.{key}")
            found.extend(_scan_forbidden_fields(value, f"{path}.{key}"))
    elif isinstance(node, list):
        for index, item in enumerate(node):
            found.extend(_scan_forbidden_fields(item, f"{path}[{index}]"))
    return found


def validate_reviewed_result_for_publish(
    reviewed: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Publish-readiness validation — deliberately distinct from
    run_local_validation() in semantic_analysis_service.py, which checks
    RAW AI OUTPUT (where every review.status MUST be "pending"). Here the
    admin has (hopefully) already changed many of those to accepted/
    corrected/rejected, so this checks the opposite things: no entity is
    still "pending", no unresolved blocking review_items, structurally
    still forbids any routing-graph field, and the top-level shape is
    intact.
    """

    errors: List[str] = []
    warnings: List[str] = []
    blocking_items: List[str] = []

    if not isinstance(reviewed, dict):
        return {
            "valid": False,
            "errors": ["No reviewed result has been saved yet."],
            "warnings": [],
            "blocking_review_items": [],
        }

    forbidden = _scan_forbidden_fields(reviewed)
    if forbidden:
        errors.append(
            "Reviewed result contains forbidden routing-graph field(s): "
            + ", ".join(forbidden[:10])
        )

    required_keys = {
        "schema_version",
        "site",
        "buildings",
        "zones",
        "floors",
        "places",
        "facilities",
        "access_points",
        "public_areas",
        "vertical_connections",
        "outdoor_areas",
        "parking_areas",
        "parking_spaces",
        "cross_building_connections",
        "review_items",
    }
    missing = required_keys - set(reviewed.keys())
    if missing:
        errors.append(
            "Reviewed result is missing required top-level key(s): "
            + ", ".join(sorted(missing))
        )
        return {
            "valid": False,
            "errors": errors,
            "warnings": warnings,
            "blocking_review_items": blocking_items,
        }

    pending_count = 0
    for entity_type, (array_name, id_field) in ENTITY_ARRAYS.items():
        for item in reviewed.get(array_name, []) or []:
            if not isinstance(item, dict):
                continue
            review = item.get("review") or {}
            if review.get("status", "pending") == "pending":
                pending_count += 1

    if pending_count:
        errors.append(
            f"{pending_count} entit(y/ies) still have review.status "
            "'pending' — every entity must be accepted, corrected, or "
            "rejected before publication."
        )

    for review_item in reviewed.get("review_items", []) or []:
        if not isinstance(review_item, dict):
            continue
        if not review_item.get("blocks_publication"):
            continue
        review = review_item.get("review") or {}
        if review.get("status", "pending") == "pending":
            blocking_items.append(
                review_item.get("review_item_external_id", "unknown")
            )

    if blocking_items:
        errors.append(
            f"{len(blocking_items)} blocking review item(s) are still "
            "unresolved: " + ", ".join(blocking_items)
        )

    return {
        "valid": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
        "blocking_review_items": blocking_items,
    }


async def _reject_floor_link_overrides(
    floor_links: List[Dict[str, Any]],
) -> Optional[str]:
    """Section 8 of the floor-code fix: never trust a frontend/admin-
    supplied floor_links entry that contradicts the Map it claims to
    describe — the semantic floor code is always DERIVED from that Map's
    own physical floor number, never something a caller gets to assert.
    Entries whose map_id doesn't resolve to a real Map, or whose Map has
    no floor number set yet, are left unchecked (there's nothing
    authoritative to compare against) rather than blocked."""

    for link in floor_links:
        link_map_id = link.get("map_id")
        link_code = link.get("floor_external_id")
        if not link_map_id or not link_code or not PydanticObjectId.is_valid(link_map_id):
            continue
        map_item = await Map.get(PydanticObjectId(link_map_id))
        if not map_item or map_item.floor is None:
            continue
        expected_code = compute_authoritative_floor_code(map_item.floor)
        if link_code != expected_code:
            return (
                f"Provided floor_links claims floor code '{link_code}' for "
                f"map {link_map_id}, but that map's physical floor "
                f"(floor {map_item.floor}) requires '{expected_code}'. The "
                "semantic floor code is always derived from the map's own "
                "floor number and can never be overridden by the request."
            )
    return None


def derive_floor_links(
    reviewed: Dict[str, Any],
    *,
    scope_type: str,
    map_id: Optional[str],
    provided_links: Optional[Dict[str, Any]],
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """
    Resolves {"building_links": [...], "floor_links": [...]} (Section 14).
    Returns (links, error_message). For a single-map analysis with
    exactly one floor object and no admin-supplied links, the one floor
    is auto-linked to the analysis's own map_id (the only sane mapping).
    Every other case requires the admin to have supplied `floor_links`
    covering every floor_external_id actually referenced by a used
    entity — publication fails with a clear message otherwise.

    Caller's responsibility (see publish_analysis): `reviewed` must
    already have been passed through `normalize_floor_codes` so the
    auto-derive branch below reads the AUTHORITATIVE code, and any
    `provided_links` must already have been passed through
    `_reject_floor_link_overrides` so this function is never handed a
    contradicting override in the first place.
    """

    if provided_links and provided_links.get("floor_links"):
        return provided_links, None

    floors = reviewed.get("floors") or []

    if scope_type == "map" and map_id and len(floors) <= 1:
        floor_external_id = (
            floors[0].get("floor_external_id") if floors else None
        )
        links = {
            "building_links": (provided_links or {}).get("building_links", []),
            "floor_links": (
                [{"floor_external_id": floor_external_id, "map_id": map_id}]
                if floor_external_id
                else []
            ),
        }
        return links, None

    return None, (
        "This analysis covers multiple floors (or no map_id/floor could "
        "be safely inferred). An administrator must confirm floor_links "
        "(mapping each AI floor_external_id to a real QuickRoute map_id) "
        "before publishing."
    )


async def publish_analysis(
    analysis: SemanticMapAnalysis,
    *,
    published_by: Optional[str],
    quickroute_links: Optional[Dict[str, Any]] = None,
) -> SemanticMapPublication:
    validation = validate_reviewed_result_for_publish(analysis.reviewed_result)
    if not validation["valid"]:
        raise ValueError("; ".join(validation["errors"]))

    reviewed = analysis.reviewed_result
    assert reviewed is not None

    # Authoritative semantic floor code (see this module's own docstring):
    # normalize BEFORE deriving floor_links so both floor_links and the
    # SemanticEntity index below are built from the correct code, without
    # requiring the AI to be re-run. Persisted back onto the analysis too
    # — publish is exactly a "saving" moment for reviewed_result.
    floor_number = await _authoritative_floor_number_for_map_scope(
        analysis.scope_type, analysis.map_id
    )
    reviewed, floor_fix_messages = normalize_floor_codes(reviewed, floor_number=floor_number)
    if floor_fix_messages:
        analysis.reviewed_result = reviewed

    # Never trust an admin/frontend-supplied floor_links override that
    # contradicts the Map it claims to describe (Section 8).
    if quickroute_links and quickroute_links.get("floor_links"):
        override_error = await _reject_floor_link_overrides(
            quickroute_links["floor_links"]
        )
        if override_error:
            raise ValueError(override_error)

    links, link_error = derive_floor_links(
        reviewed,
        scope_type=analysis.scope_type,
        map_id=analysis.map_id,
        provided_links=quickroute_links,
    )
    if link_error:
        raise ValueError(link_error)

    # Supersede any previous active publication for this exact map,
    # never deleting it — full audit history is preserved.
    previous_active = await SemanticMapPublication.find(
        {"map_id": analysis.map_id, "is_active": True}
    ).to_list()

    publication = SemanticMapPublication(
        analysis_id=analysis.analysis_id,
        prompt_version=analysis.prompt_version,
        prompt_sha256=analysis.prompt_sha256,
        reviewed_result=reviewed,
        quickroute_links=links or {},
        map_id=analysis.map_id,
        map_group_id=analysis.map_group_id,
        building_id=analysis.building_id,
        publication_revision=len(previous_active) + 1,
        published_by=published_by,
        is_active=True,
    )
    await publication.insert()

    for previous in previous_active:
        previous.is_active = False
        previous.superseded_by_publication_id = publication.publication_id
        await previous.save()
        await SemanticEntity.find(
            {"publication_id": previous.publication_id}
        ).update({"$set": {"active": False}})

    await _build_semantic_entity_index(publication, reviewed)

    analysis.published_analysis_id = publication.publication_id
    analysis.published_at = datetime.utcnow()
    analysis.review_status = "published"
    analysis.updated_at = datetime.utcnow()
    await analysis.save()

    return publication


async def _build_semantic_entity_index(
    publication: SemanticMapPublication, reviewed: Dict[str, Any]
) -> None:
    floor_to_map = {
        link.get("floor_external_id"): link.get("map_id")
        for link in (publication.quickroute_links.get("floor_links") or [])
        if link.get("floor_external_id")
    }

    for entity_type, (array_name, id_field) in ENTITY_ARRAYS.items():
        for item in reviewed.get(array_name, []) or []:
            if not isinstance(item, dict):
                continue
            review = item.get("review") or {}
            review_status = review.get("status", "pending")
            # Only accepted/corrected entities enter the searchable index
            # — rejected and (should never happen post-validation)
            # pending entities are excluded from the ACTIVE index.
            if review_status not in ("accepted", "corrected"):
                continue

            names = item.get("names") or {}
            floor_external_id = item.get("floor_external_id")

            entity = SemanticEntity(
                publication_id=publication.publication_id,
                analysis_id=publication.analysis_id,
                entity_external_id=item.get(id_field, ""),
                entity_type=entity_type,
                building_id=publication.building_id,
                map_id=floor_to_map.get(floor_external_id) or publication.map_id,
                floor_external_id=floor_external_id,
                names_original=names.get("original"),
                names_en=names.get("en"),
                names_ar=names.get("ar"),
                names_he=names.get("he"),
                # Nested canonical shape (Section 5) — the exact same
                # admin-approved translations as the four flat fields
                # above, never a second copy that could drift out of
                # sync (both are written from this one `names` dict in
                # the same insert).
                names=localized_text_to_dict(names),
                category=item.get("category") or item.get(f"{entity_type}_type"),
                subcategory=item.get("subcategory"),
                displayed_number=item.get("displayed_number"),
                confidence=item.get("confidence"),
                review_status=review_status,
                source_document_ids=item.get("source_document_ids", []) or [],
                active=True,
            )
            await entity.insert()


async def repair_floor_codes_for_map(map_id: str) -> Dict[str, Any]:
    """
    Admin-confirmed, scoped-to-exactly-one-Map repair action for semantic
    floor codes on data that predates this fix (Section 7: "do not
    require rerunning AI analysis just to correct the floor code" / "make
    it admin-confirmed and scoped to one selected Map"). Only ever called
    from an explicit POST — never automatically.

    Fixes, in place:
      - every "map"-scope SemanticMapAnalysis for this map_id whose
        reviewed_result already exists (never touches ai_result, and
        never initializes a still-None reviewed_result — an analysis
        nobody has reviewed yet already gets the correct code for free
        via the normalized VIEW returned by GET .../result);
      - the map's currently ACTIVE SemanticMapPublication, if any: its
        own reviewed_result snapshot, its quickroute_links["floor_links"]
        entry for this map, and its SemanticEntity search index (rebuilt
        from scratch for this publication only).

    Never touches Rooms, RoutePoints, RouteEdges, or any other map's
    data, and never touches a superseded (non-active) publication —
    audit history is preserved exactly as everywhere else in this
    module.
    """

    if not PydanticObjectId.is_valid(map_id):
        return {"changed": False, "reason": "invalid_map_id"}

    map_item = await Map.get(PydanticObjectId(map_id))
    if not map_item:
        return {"changed": False, "reason": "map_not_found"}
    if map_item.floor is None:
        return {"changed": False, "reason": "map_floor_not_set"}

    messages: List[str] = []
    changed_analysis_ids: List[str] = []
    changed_publication_id: Optional[str] = None

    analyses = await SemanticMapAnalysis.find(
        {"map_id": map_id, "scope_type": "map"}
    ).to_list()
    for analysis in analyses:
        if analysis.reviewed_result is None:
            continue
        normalized, msgs = normalize_floor_codes(
            analysis.reviewed_result, floor_number=map_item.floor
        )
        if msgs:
            analysis.reviewed_result = normalized
            analysis.updated_at = datetime.utcnow()
            await analysis.save()
            changed_analysis_ids.append(analysis.analysis_id)
            messages.extend(msgs)

    publication = await SemanticMapPublication.find_one(
        {"map_id": map_id, "is_active": True}
    )
    if publication:
        normalized, msgs = normalize_floor_codes(
            publication.reviewed_result, floor_number=map_item.floor
        )
        if msgs:
            expected_code = compute_authoritative_floor_code(map_item.floor)
            old_links = publication.quickroute_links or {}
            new_floor_links = [
                {**link, "floor_external_id": expected_code}
                if link.get("map_id") == map_id
                else link
                for link in (old_links.get("floor_links") or [])
            ]
            publication.reviewed_result = normalized
            publication.quickroute_links = {
                **old_links,
                "floor_links": new_floor_links,
            }
            await publication.save()

            # Rebuild this publication's own search index from the
            # corrected reviewed_result — never touches any OTHER
            # publication's entities, and never touches the superseded/
            # inactive publications this one already replaced.
            await SemanticEntity.find(
                {"publication_id": publication.publication_id}
            ).delete()
            await _build_semantic_entity_index(publication, normalized)

            changed_publication_id = publication.publication_id
            messages.extend(msgs)

    return {
        "changed": bool(changed_analysis_ids) or bool(changed_publication_id),
        "changed_analysis_ids": changed_analysis_ids,
        "changed_publication_id": changed_publication_id,
        "messages": messages,
    }
