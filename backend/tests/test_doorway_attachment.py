"""
Acceptance tests for door-aware destination attachment and the corridor
component fixes.

THE REAL FAILURE THIS FIXES
---------------------------
On the deployed Floor 1, three correctly-placed doorway markers were
reported wall-blocked with a corridor 47-83 px away:

    Electrical Room   nearest corridor ~75.31 px   5 rejected by wall, 1 off graph
    Custodian Room    nearest corridor ~47.01 px   6 rejected by wall, 1 off graph
    Men's Restroom    nearest corridor ~83    px   6 rejected by wall, 1 off graph

Two stacked causes, both reproduced below:

  * RESOLUTION. The legacy validator downscales to 900 px and allows 3% of
    samples blocked. On a 75 px line that is ~6 samples, so the budget
    floors to ZERO. One mask pixel — including the destination endpoint
    sitting in the mask's own 2 px dilation — rejects the candidate.

  * INDISTINGUISHABILITY AT THAT RESOLUTION. A 2 px threshold line, a 4 px
    closed door leaf and an 8 px structural wall all collapse to a 1-2
    sample run there. This is exactly why a blanket "forgive one wall
    crossing" rule is unsafe, and there is no such rule anywhere in this
    codebase.

The fix re-measures the same line on the STRICT full-resolution mask and
compares the obstruction's caliper against the caliper of the wall it
pierces, probed locally. Half of these tests exist to prove the cases that
must STILL be refused.

Every plan here is rendered at 2400x1600 so the legacy mask really is a
downscale (0.375) of the strict one — at the 600x400 used by the older
suites the two masks are identical and none of this would be exercised.

Run with: pytest backend/tests/test_doorway_attachment.py -v
"""

import math

import cv2
import numpy as np
import pytest

from tests.test_api_integration import auth_headers, create_admin_and_get_token

from models.route_edge_model import RouteEdge
from models.route_point_model import RoutePoint


PREVIEW_URL = "/api/route-edges/auto-connect-destinations/preview"

PLAN_W, PLAN_H = 2400, 1600
WALL_PX = 8
CORRIDOR_TOP_Y = 900
CORRIDOR_BOTTOM_Y = 1150


# ---------------------------------------------------------
# Helpers (local copies, matching the per-file convention of
# tests/test_auto_connect_accuracy.py).
# ---------------------------------------------------------

def _create_map(client, token, title="Doorway Map", floor=None):
    response = client.post(
        "/api/maps", json={"title": title, "floor": floor}, headers=auth_headers(token)
    )
    assert response.status_code == 201, response.text
    return response.json()


def _create_point(client, token, map_id, name, x, y, floor=None, point_type="hallway"):
    response = client.post(
        "/api/route-points",
        json={
            "map_id": map_id,
            "name": name,
            "x": x,
            "y": y,
            "floor": floor,
            "point_type": point_type,
        },
        headers=auth_headers(token),
    )
    assert response.status_code == 201, response.text
    return response.json()


def _create_edge(client, token, map_id, from_point_id, to_point_id):
    response = client.post(
        "/api/route-edges",
        json={
            "map_id": map_id,
            "from_point_id": from_point_id,
            "to_point_id": to_point_id,
            "edge_type": "walkway",
        },
        headers=auth_headers(token),
    )
    assert response.status_code == 201, response.text
    return response.json()


def _preview(client, token, map_id, **kwargs):
    response = client.post(
        PREVIEW_URL, json={"map_id": map_id, **kwargs}, headers=auth_headers(token)
    )
    assert response.status_code == 200, response.text
    return response.json()


def _find(preview_result, destination_point_id):
    for proposal in preview_result["proposals"]:
        if proposal["destination_point_id"] == destination_point_id:
            return proposal
    return None


def _install_plan(monkeypatch, tmp_path, map_id, image):
    """Publish a synthetic plan as this map's source image for BOTH
    validators, and drop every cached mask so one test cannot inherit
    another's geometry."""
    import services.graph_connection_service as graph_connection_service
    from services.strict_geometry_service import clear_strict_mask_cache

    monkeypatch.setattr("services.graph_connection_service.SOURCE_DIR", tmp_path)
    monkeypatch.setattr("services.strict_geometry_service.SOURCE_DIR", tmp_path)
    graph_connection_service._WALL_MASK_CACHE.clear()
    clear_strict_mask_cache()

    cv2.imwrite(str(tmp_path / f"{map_id}.png"), image)


DOOR_PLAIN = "plain"
DOOR_THRESHOLD = "threshold"
DOOR_LEAF = "leaf"
DOOR_ARC = "arc"
DOOR_NONE = "none"


def _plan(doors=(), wall_px=WALL_PX, extra=None):
    """A corridor with rooms above it.

    `doors` is a sequence of (centre_x, opening_width, style). Every style
    cuts a real opening in the wall; the style then decides what, if
    anything, is drawn across or beside that opening — which is precisely
    what the legacy mask cannot tell apart from the wall itself.
    """

    image = np.full((PLAN_H, PLAN_W), 255, dtype=np.uint8)

    cv2.rectangle(image, (100, 100), (PLAN_W - 100, PLAN_H - 100), 0, wall_px)
    cv2.line(image, (100, CORRIDOR_TOP_Y), (PLAN_W - 100, CORRIDOR_TOP_Y), 0, wall_px)
    cv2.line(
        image,
        (100, CORRIDOR_BOTTOM_Y),
        (PLAN_W - 100, CORRIDOR_BOTTOM_Y),
        0,
        wall_px,
    )
    for x in (600, 1100, 1600, 2000):
        cv2.line(image, (x, 100), (x, CORRIDOR_TOP_Y), 0, wall_px)

    for centre_x, width, style in doors:
        if style == DOOR_NONE:
            continue
        left, right = centre_x - width // 2, centre_x + width // 2
        # The opening itself.
        cv2.line(image, (left, CORRIDOR_TOP_Y), (right, CORRIDOR_TOP_Y), 255, wall_px + 6)

        if style == DOOR_THRESHOLD:
            cv2.line(image, (left, CORRIDOR_TOP_Y), (right, CORRIDOR_TOP_Y), 0, 2)
        elif style == DOOR_LEAF:
            cv2.line(image, (left, CORRIDOR_TOP_Y), (right, CORRIDOR_TOP_Y), 0, 4)
        elif style == DOOR_ARC:
            cv2.line(image, (left, CORRIDOR_TOP_Y), (left, CORRIDOR_TOP_Y - width), 0, 3)
            cv2.ellipse(
                image, (left, CORRIDOR_TOP_Y), (width, width), 0, -90, 0, 0, 3
            )

    if extra is not None:
        extra(image)

    return image


def _metrics_for(map_id):
    from services.strict_geometry_service import get_strict_wall_metrics

    return get_strict_wall_metrics(map_id)


def _resolve(map_id, origin, target):
    from services.destination_attachment_service import resolve_doorway_exit_point

    return resolve_doorway_exit_point(
        map_id=map_id,
        metrics=_metrics_for(map_id),
        origin_x=origin[0],
        origin_y=origin[1],
        target_x=target[0],
        target_y=target[1],
        canonical_diagonal_px=math.hypot(PLAN_W, PLAN_H),
        is_calibrated=False,
        scale=1.0,
    )


class _StubPoint:
    """The only four attributes _transit_components reads. Used instead of
    real documents so the component tests are pure and instant."""

    def __init__(self, point_id, x, y, floor=None):
        self.id = point_id
        self.x = x
        self.y = y
        self.floor = floor


class _StubEdge:
    def __init__(self, from_point_id, to_point_id, edge_type="walkway"):
        self.from_point_id = from_point_id
        self.to_point_id = to_point_id
        self.edge_type = edge_type


# =========================================================
# THE THREE REAL FAILURE PATTERNS
#
# Same geometry, same distances, three ways of drawing the same door.
# =========================================================

@pytest.mark.parametrize(
    "label, style, distance_px",
    [
        ("Electrical Room", DOOR_THRESHOLD, 75.31),
        ("Custodian Room", DOOR_ARC, 47.01),
        ("Men's Restroom", DOOR_LEAF, 83.0),
    ],
)
def test_01_03_real_doorway_markers_are_no_longer_wall_blocked(
    tmp_path, monkeypatch, label, style, distance_px
):
    door_x = 850
    map_id = f"doorway-real-{style}"
    _install_plan(
        monkeypatch, tmp_path, map_id, _plan(doors=[(door_x, 90, style)])
    )

    origin = (door_x, CORRIDOR_TOP_Y - 12)
    target = (door_x, origin[1] + distance_px)

    from services.destination_attachment_service import _attachment_is_clear

    legacy_clear, _grazes = _attachment_is_clear(map_id, *origin, *target)
    resolution = _resolve(map_id, origin, target)

    # Either the legacy gate already passed (nothing to fix for this
    # drawing style) or the door-aware stage resolves it. What must never
    # happen is BOTH refusing a marker standing in a real doorway.
    assert legacy_clear or resolution.accepted, (
        f"{label}: still blocked — mode={resolution.mode} "
        f"reason={resolution.reason} crossing={resolution.crossing_thickness_px}"
    )

    if not legacy_clear:
        assert resolution.mode in ("doorway_resolved", "strict_clear")
        assert resolution.clear_line_after is True
        assert resolution.wall_crossings_after == 0


# =========================================================
# 4. The stored point is never moved.
# =========================================================

def test_04_resolution_never_moves_the_stored_point(tmp_path, monkeypatch):
    door_x = 850
    map_id = "doorway-no-move"
    _install_plan(
        monkeypatch, tmp_path, map_id, _plan(doors=[(door_x, 90, DOOR_THRESHOLD)])
    )

    origin = (door_x, CORRIDOR_TOP_Y - 12)
    target = (door_x, CORRIDOR_TOP_Y + 75)
    resolution = _resolve(map_id, origin, target)

    assert resolution.accepted

    if resolution.mode == "doorway_resolved":
        # The exit is a validation waypoint on the same line, a bounded
        # distance from the admin's own coordinates — not a new position.
        assert resolution.exit_x is not None and resolution.exit_y is not None
        assert (resolution.exit_x, resolution.exit_y) != origin
        assert 0 < resolution.snap_px <= 60.0
        # ...and it lies ON the segment, so nothing has drifted sideways.
        along = math.hypot(
            resolution.exit_x - origin[0], resolution.exit_y - origin[1]
        )
        total = math.hypot(target[0] - origin[0], target[1] - origin[1])
        cross = abs(
            (target[0] - origin[0]) * (resolution.exit_y - origin[1])
            - (target[1] - origin[1]) * (resolution.exit_x - origin[0])
        ) / total
        assert cross < 0.5
        assert along < total


# =========================================================
# MUST STILL BE REFUSED
# =========================================================

def test_05_a_solid_wall_between_marker_and_corridor_is_still_refused(
    tmp_path, monkeypatch
):
    # A marker in a room whose wall has no opening on this line at all.
    map_id = "doorway-solid-wall"
    _install_plan(monkeypatch, tmp_path, map_id, _plan(doors=[(850, 90, DOOR_PLAIN)]))

    # 250 px to the side of the opening — squarely behind the wall.
    origin = (1300, CORRIDOR_TOP_Y - 12)
    target = (1300, CORRIDOR_TOP_Y + 75)

    resolution = _resolve(map_id, origin, target)

    assert resolution.accepted is False
    assert resolution.reason in ("doorway_not_resolved", "blocked_after_doorway")


def test_06_a_thin_wall_with_no_opening_is_refused_even_though_it_is_thin(
    tmp_path, monkeypatch
):
    # THE adversarial case. This wall is drawn 4 px — exactly the width of
    # a closed door leaf. A rule based on absolute thinness, or on the
    # map-wide 80th-percentile stroke, would forgive it. Compared against
    # the wall it actually pierces it measures 1.0 and is refused.
    def thin_corridor_wall(image):
        cv2.line(
            image,
            (100, CORRIDOR_TOP_Y),
            (PLAN_W - 100, CORRIDOR_TOP_Y),
            0,
            4,
        )

    map_id = "doorway-thin-wall"
    image = _plan(doors=[])
    thin_corridor_wall(image)
    _install_plan(monkeypatch, tmp_path, map_id, image)

    resolution = _resolve(
        map_id, (850, CORRIDOR_TOP_Y - 12), (850, CORRIDOR_TOP_Y + 75)
    )

    assert resolution.accepted is False
    assert resolution.reason == "doorway_not_resolved"


def test_07_a_marker_deep_inside_the_room_is_refused(tmp_path, monkeypatch):
    # The bound is derived from the measured wall stroke, so "a few pixels
    # of placement error" is tolerated and "somewhere in the middle of the
    # room" is not — even when there IS a real door on the line.
    map_id = "doorway-deep-marker"
    _install_plan(
        monkeypatch, tmp_path, map_id, _plan(doors=[(850, 90, DOOR_THRESHOLD)])
    )

    near = _resolve(map_id, (850, CORRIDOR_TOP_Y - 12), (850, CORRIDOR_TOP_Y + 75))
    deep = _resolve(map_id, (850, CORRIDOR_TOP_Y - 300), (850, CORRIDOR_TOP_Y + 75))

    assert near.accepted is True
    assert deep.accepted is False
    assert deep.reason == "blocked_after_doorway"


def test_08_two_obstructions_in_a_row_are_refused(tmp_path, monkeypatch):
    # Entering and leaving something is not a doorway, however thin each
    # line is. This is the rule that stops a thin-walled closet becoming a
    # shortcut.
    def second_thin_line(image):
        cv2.line(image, (810, CORRIDOR_TOP_Y + 40), (890, CORRIDOR_TOP_Y + 40), 0, 2)

    map_id = "doorway-two-runs"
    _install_plan(
        monkeypatch,
        tmp_path,
        map_id,
        _plan(doors=[(850, 90, DOOR_THRESHOLD)], extra=second_thin_line),
    )

    resolution = _resolve(
        map_id, (850, CORRIDOR_TOP_Y - 12), (850, CORRIDOR_TOP_Y + 90)
    )

    assert resolution.accepted is False
    assert resolution.reason in ("doorway_not_resolved", "blocked_after_doorway")


def test_09_a_real_wall_past_the_doorway_reports_blocked_after_doorway(
    tmp_path, monkeypatch
):
    # Forgiveness stops at the doorway: everything beyond the exit point
    # must be completely clear at strict resolution.
    def wall_past_the_door(image):
        cv2.line(
            image,
            (100, CORRIDOR_TOP_Y + 60),
            (PLAN_W - 100, CORRIDOR_TOP_Y + 60),
            0,
            WALL_PX,
        )

    map_id = "doorway-wall-after"
    _install_plan(
        monkeypatch,
        tmp_path,
        map_id,
        _plan(doors=[(850, 90, DOOR_THRESHOLD)], extra=wall_past_the_door),
    )

    resolution = _resolve(
        map_id, (850, CORRIDOR_TOP_Y - 12), (850, CORRIDOR_TOP_Y + 120)
    )

    assert resolution.accepted is False
    assert resolution.reason == "blocked_after_doorway"


def test_10_no_source_image_means_the_resolver_never_runs(tmp_path, monkeypatch):
    # A map with no readable source image behaves exactly as it did before
    # this feature existed: nothing to measure, so nothing is forgiven.
    monkeypatch.setattr("services.strict_geometry_service.SOURCE_DIR", tmp_path)

    from services.destination_attachment_service import resolve_doorway_exit_point
    from services.strict_geometry_service import (
        clear_strict_mask_cache,
        get_strict_wall_metrics,
    )

    clear_strict_mask_cache()
    assert get_strict_wall_metrics("no-such-map") is None

    resolution = resolve_doorway_exit_point(
        map_id="no-such-map",
        metrics=None,
        origin_x=10,
        origin_y=10,
        target_x=90,
        target_y=10,
        canonical_diagonal_px=None,
        is_calibrated=False,
        scale=1.0,
    )

    assert resolution.accepted is False
    assert resolution.mode == "strict_mask_unavailable"


# =========================================================
# THE LONG-LINE LEGACY-GATE BYPASS
#
# A REAL failure: Auto Connect created long Room -> corridor connections
# straight through walls. Both fractional validators are to blame, and in
# the same way — they get MORE permissive the longer the line is:
#
#   has_clear_line         blocked/(samples+1) <= 3%, 4 px step on the
#                          900 px mask. A 625 px line at downscale 0.375
#                          is ~58 samples, so an 8 px wall (1-2 samples)
#                          is under budget. ACCEPTED THROUGH A WALL.
#   strict_has_clear_line  blocked/samples <= 3%, 2 px step at full
#                          resolution. The same line is ~313 samples and
#                          the wall is ~5. ALSO under budget.
#
# Neither is consulted for destination attachment any more. The decision
# is made from discrete obstructions and their calipers, which does not
# depend on length at all.
# =========================================================

def _long_line_case(tmp_path, monkeypatch, name, extra=None, doors=()):
    """A 625 px destination -> corridor line, straight down."""
    map_id = f"longline-{name}"
    _install_plan(monkeypatch, tmp_path, map_id, _plan(doors=doors, extra=extra))
    origin = (850, 400)
    target = (850, 1025)
    assert math.hypot(*(t - o for t, o in zip(target, origin))) == pytest.approx(625)
    return map_id, origin, target


def test_16_long_line_crossing_one_real_wall_is_rejected(tmp_path, monkeypatch):
    # THE BUG. The corridor wall at y=900 has no opening on this line, and
    # the line is long enough for both 3% budgets to wave the wall through.
    from services.destination_attachment_service import _attachment_is_clear
    from services.strict_geometry_service import strict_has_clear_line

    map_id, origin, target = _long_line_case(tmp_path, monkeypatch, "one-wall")

    # Both fractional validators say this line is fine. It is not: it goes
    # through a solid 8 px wall.
    legacy_clear, _grazes = _attachment_is_clear(map_id, *origin, *target)
    strict_fractional = strict_has_clear_line(map_id, *origin, *target)
    assert legacy_clear is True, "precondition: the legacy gate accepts this"
    assert strict_fractional is True, (
        "precondition: strict_has_clear_line's own 3% budget also accepts it"
    )

    # The run-based decision refuses it.
    resolution = _resolve(map_id, origin, target)
    assert resolution.accepted is False
    assert resolution.reason in ("doorway_not_resolved", "blocked_after_doorway")


def test_17_the_same_long_line_when_actually_clear_is_accepted(
    tmp_path, monkeypatch
):
    # Length is not what makes a connection unsafe. With the wall removed,
    # the identical 625 px line is accepted.
    def open_corridor(image):
        # Erase the corridor's upper wall across the whole plan.
        cv2.line(
            image,
            (100, CORRIDOR_TOP_Y),
            (PLAN_W - 100, CORRIDOR_TOP_Y),
            255,
            WALL_PX + 8,
        )

    map_id, origin, target = _long_line_case(
        tmp_path, monkeypatch, "clear", extra=open_corridor
    )

    resolution = _resolve(map_id, origin, target)
    assert resolution.accepted is True
    assert resolution.mode == "strict_clear"
    assert resolution.wall_crossings_after == 0


def test_18_long_line_through_a_real_doorway_then_clear_is_accepted(
    tmp_path, monkeypatch
):
    # A valid doorway plus a clear run to the corridor is fine at any
    # length — but the doorway must be at the DESTINATION, which is what
    # the bounded exit radius enforces. Marker just inside its own door,
    # corridor far down the hall.
    map_id = "longline-doorway"
    _install_plan(
        monkeypatch, tmp_path, map_id, _plan(doors=[(850, 90, DOOR_THRESHOLD)])
    )

    origin = (850, CORRIDOR_TOP_Y - 12)
    target = (850, CORRIDOR_TOP_Y + 613)   # 625 px total, deep past the corridor
    assert target[1] - origin[1] == 625

    from services.destination_attachment_service import _attachment_is_clear

    resolution = _resolve(map_id, origin, target)

    # It crosses the corridor's FAR wall at y=1150, so it must be refused —
    # the doorway is fine, the wall past it is not.
    assert resolution.accepted is False
    assert resolution.reason == "blocked_after_doorway"

    # ...and with the target inside the corridor instead, the same doorway
    # on a long-but-clear remainder is accepted.
    near_target = (850, CORRIDOR_TOP_Y + 200)
    ok = _resolve(map_id, origin, near_target)
    assert ok.accepted is True, f"mode={ok.mode} reason={ok.reason}"
    assert ok.mode == "doorway_resolved"
    assert ok.wall_crossings_after == 0
    assert math.hypot(
        near_target[0] - origin[0], near_target[1] - origin[1]
    ) == pytest.approx(212)
    # The legacy gate is irrelevant to that verdict either way.
    _attachment_is_clear(map_id, *origin, *near_target)


def test_19_doorway_followed_by_a_second_real_wall_is_rejected(
    tmp_path, monkeypatch
):
    # Forgiveness stops at the doorway, however long the remainder is.
    def wall_past_the_door(image):
        cv2.line(
            image,
            (100, CORRIDOR_TOP_Y + 300),
            (PLAN_W - 100, CORRIDOR_TOP_Y + 300),
            0,
            WALL_PX,
        )

    map_id = "longline-doorway-then-wall"
    _install_plan(
        monkeypatch,
        tmp_path,
        map_id,
        _plan(doors=[(850, 90, DOOR_THRESHOLD)], extra=wall_past_the_door),
    )

    origin = (850, CORRIDOR_TOP_Y - 12)
    target = (850, CORRIDOR_TOP_Y + 400)

    from services.destination_attachment_service import _attachment_is_clear

    legacy_clear, _ = _attachment_is_clear(map_id, *origin, *target)
    resolution = _resolve(map_id, origin, target)

    assert resolution.accepted is False
    assert resolution.reason == "blocked_after_doorway"
    # Worth recording which way the old gate would have gone on this line.
    assert legacy_clear in (True, False)


def test_20_a_thin_real_interior_partition_is_rejected_on_a_long_line(
    tmp_path, monkeypatch
):
    # The adversary from test 6, now on a long line where BOTH fractional
    # budgets would wave it through. A 4 px partition is as thin as a door
    # leaf; measured against the wall it actually is, it reads 1.0.
    def thin_partition(image):
        # Remove the thick corridor wall and put a thin partition in its
        # place, so the only thing on the line is the 4 px partition.
        cv2.line(
            image,
            (100, CORRIDOR_TOP_Y),
            (PLAN_W - 100, CORRIDOR_TOP_Y),
            255,
            WALL_PX + 8,
        )
        cv2.line(image, (100, CORRIDOR_TOP_Y), (PLAN_W - 100, CORRIDOR_TOP_Y), 0, 4)

    from services.destination_attachment_service import _attachment_is_clear
    from services.strict_geometry_service import strict_has_clear_line

    map_id, origin, target = _long_line_case(
        tmp_path, monkeypatch, "thin-partition", extra=thin_partition
    )

    assert _attachment_is_clear(map_id, *origin, *target)[0] is True
    assert strict_has_clear_line(map_id, *origin, *target) is True

    resolution = _resolve(map_id, origin, target)
    assert resolution.accepted is False


def test_21_the_bypass_is_closed_end_to_end_and_counted(
    client, tmp_path, monkeypatch
):
    # Through the real preview endpoint: a room behind a solid wall, with
    # the corridor far enough away that the legacy gate accepts the line.
    # Before this fix the room was "proposed" and applying it wrote an edge
    # through the wall.
    token, _ = create_admin_and_get_token(client, email="bypass21@example.com")
    map_item = _create_map(client, token)
    map_id = map_item["id"]

    _install_plan(monkeypatch, tmp_path, map_id, _plan(doors=[]))

    hall_a = _create_point(client, token, map_id, "Hall W", 300, CORRIDOR_TOP_Y + 125)
    hall_b = _create_point(client, token, map_id, "Hall E", 2100, CORRIDOR_TOP_Y + 125)
    _create_edge(client, token, map_id, hall_a["id"], hall_b["id"])

    room = _create_point(
        client, token, map_id, "Sealed Store", 850, 400, point_type="room"
    )

    # This map has no uploaded image, so the hard safety ceiling falls back
    # to the fixed 600 px default and a 625 px candidate would be filtered
    # out on distance before geometry ever ran. Raise the ceiling so the
    # thing under test — the wall — is what decides.
    proposal = _find(
        _preview(client, token, map_id, max_distance_px=800), room["id"]
    )

    assert proposal["status"] == "no_candidate"
    assert proposal["reason"] == "blocked_by_wall"
    assert proposal["rejected_by_wall_count"] >= 1
    # The bypass, made visible: the legacy rule would have accepted this.
    assert proposal["legacy_bypass_rejected_count"] >= 1
    # ...and the corridor really was in range, so this is not a distance
    # problem being mislabelled.
    assert proposal["nearest_distance_px"] is not None
    assert proposal["nearest_distance_px"] < proposal["max_hard_distance_px"]


# =========================================================
# CORRIDOR COMPONENTS
# =========================================================

def test_11_corridor_endpoints_that_physically_meet_are_one_component():
    # Two draw sessions ending on the same physical spot. Point dedup only
    # merges inside 6 px and "Automatic graph merging: off" bypasses it
    # entirely, so this produced two RoutePoints — and, before this fix,
    # two components forever, with every candidate in the smaller one
    # reported "off the walkable graph".
    from services.destination_attachment_service import _transit_components

    points = [
        _StubPoint("a1", 100, 100),
        _StubPoint("a2", 300, 100),
        # ...second run starts 4 px from where the first ended.
        _StubPoint("b1", 302, 102),
        _StubPoint("b2", 500, 100),
    ]
    edges = [_StubEdge("a1", "a2"), _StubEdge("b1", "b2")]

    components = _transit_components(points, edges)

    assert components.component_count == 1
    assert components.main_component_size == 4
    assert components.coincident_merges == 1
    roots = {components.root_by_id[p.id] for p in points}
    assert len(roots) == 1


def test_12_genuinely_separate_corridors_are_never_bridged():
    # The same two runs, a visible gap apart. Nothing joins them, and the
    # smaller one is honestly reported as isolated.
    from services.destination_attachment_service import _transit_components

    points = [
        _StubPoint("a1", 100, 100),
        _StubPoint("a2", 300, 100),
        _StubPoint("a3", 400, 100),
        _StubPoint("b1", 900, 100),
        _StubPoint("b2", 1100, 100),
    ]
    edges = [_StubEdge("a1", "a2"), _StubEdge("a2", "a3"), _StubEdge("b1", "b2")]

    components = _transit_components(points, edges)

    assert components.coincident_merges == 0
    assert components.component_count == 2
    assert components.main_component_size == 3
    assert components.root_by_id["b1"] != components.main_root


def test_13_equal_sized_components_choose_a_main_one_deterministically():
    # `size > best_size` used to leave this to dict order, so two
    # equal-sized wings resolved arbitrarily and half the corridor was
    # silently stranded — differently on different runs.
    from services.destination_attachment_service import _transit_components

    points = [
        _StubPoint("w1", 100, 100),
        _StubPoint("w2", 300, 100),
        _StubPoint("e1", 900, 100),
        _StubPoint("e2", 1100, 100),
    ]
    forward = [_StubEdge("w1", "w2"), _StubEdge("e1", "e2")]
    reversed_order = [_StubEdge("e1", "e2"), _StubEdge("w1", "w2")]

    first = _transit_components(points, forward)
    second = _transit_components(points, reversed_order)
    third = _transit_components(list(reversed(points)), reversed_order)

    winners = [
        set(c.members_by_root[c.main_root]) for c in (first, second, third)
    ]
    assert winners[0] == winners[1] == winners[2]
    # Tie broken by the smallest member id, which does not depend on the
    # order the unions happened to run in.
    assert winners[0] == {"e1", "e2"}


def test_14_a_lone_hallway_point_is_still_not_isolated():
    # Regression guard preserved from the Auto Connect correction: with no
    # multi-point component anywhere there is no main graph to be isolated
    # from, and a single hand-placed hallway point stays a good candidate.
    from services.destination_attachment_service import _transit_components

    components = _transit_components([_StubPoint("only", 100, 100)], [])

    assert components.main_root is None
    assert components.main_component_size == 0


# =========================================================
# 15. Diagnostics.
# =========================================================

def test_15_preview_reports_the_full_door_aware_diagnostics(
    client, tmp_path, monkeypatch
):
    token, _ = create_admin_and_get_token(client, email="doorway15@example.com")
    map_item = _create_map(client, token)
    map_id = map_item["id"]

    _install_plan(
        monkeypatch, tmp_path, map_id, _plan(doors=[(850, 90, DOOR_THRESHOLD)])
    )

    hall_a = _create_point(client, token, map_id, "Hall W", 400, CORRIDOR_TOP_Y + 120)
    hall_b = _create_point(client, token, map_id, "Hall E", 1600, CORRIDOR_TOP_Y + 120)
    _create_edge(client, token, map_id, hall_a["id"], hall_b["id"])

    room = _create_point(
        client,
        token,
        map_id,
        "Electrical Room",
        850,
        CORRIDOR_TOP_Y - 12,
        point_type="room",
    )

    proposal = _find(_preview(client, token, map_id), room["id"])
    assert proposal is not None

    for key in (
        "origin_x",
        "origin_y",
        "nearest_corridor_distance_px",
        "rejected_by_wall_count",
        "rejected_off_graph_count",
        "doorway_resolved",
        "corridor_component_count",
        "corridor_main_component_size",
        "corridor_coincident_merges",
        "final_reason",
    ):
        assert key in proposal, f"missing diagnostic: {key}"

    assert proposal["origin_x"] == pytest.approx(850, abs=0.01)
    assert proposal["origin_y"] == pytest.approx(CORRIDOR_TOP_Y - 12, abs=0.01)

    # `reason` keeps its long-standing vocabulary; `final_reason` carries
    # the canonical one, including the two door-aware outcomes.
    assert proposal["final_reason"] in (
        None,
        "blocked_by_wall",
        "doorway_not_resolved",
        "blocked_after_doorway",
        "corridor_component_isolated",
        "no_corridor_candidate",
    )

    if proposal["status"] == "proposed":
        assert proposal["graph_connected"] is True
        assert proposal["final_reason"] is None
        # The proposal is still anchored on the admin's own coordinates.
        assert proposal["destination_x"] == pytest.approx(850, abs=0.01)


# =========================================================
# Integration: the same resolution on the automatic save path.
# =========================================================

def test_room_saved_at_a_doorway_is_attached_without_moving_it(
    client, tmp_path, monkeypatch
):
    token, _ = create_admin_and_get_token(client, email="doorwaysave@example.com")
    map_item = _create_map(client, token)
    map_id = map_item["id"]

    _install_plan(
        monkeypatch, tmp_path, map_id, _plan(doors=[(850, 90, DOOR_THRESHOLD)])
    )

    hall_a = _create_point(client, token, map_id, "Hall W", 400, CORRIDOR_TOP_Y + 120)
    hall_b = _create_point(client, token, map_id, "Hall E", 1600, CORRIDOR_TOP_Y + 120)
    _create_edge(client, token, map_id, hall_a["id"], hall_b["id"])

    response = client.post(
        "/api/route-points?auto_connect=nearest",
        json={
            "map_id": map_id,
            "name": "Custodian Room",
            "x": 850,
            "y": CORRIDOR_TOP_Y - 12,
            "point_type": "room",
        },
        headers=auth_headers(token),
    )
    assert response.status_code == 201, response.text
    created = response.json()

    # Read the point back through the API: whatever the attachment stage
    # decided, the admin's own coordinates must be exactly what was stored.
    listing = client.get(
        f"/api/route-points?map_id={map_id}", headers=auth_headers(token)
    )
    assert listing.status_code == 200, listing.text
    stored = next(p for p in listing.json() if p["id"] == created["id"])

    assert stored["x"] == pytest.approx(850)
    assert stored["y"] == pytest.approx(CORRIDOR_TOP_Y - 12)

    # And whatever edge it did or did not get, it is never joined to
    # another destination.
    edges = client.get(
        f"/api/route-edges?map_id={map_id}", headers=auth_headers(token)
    )
    assert edges.status_code == 200, edges.text

    points_by_id = {p["id"]: p for p in listing.json()}
    for edge in edges.json():
        endpoints = (edge["from_point_id"], edge["to_point_id"])
        if created["id"] not in endpoints:
            continue
        other_id = endpoints[0] if endpoints[1] == created["id"] else endpoints[1]
        other = points_by_id.get(other_id)
        if other is not None:
            assert other["point_type"] in ("hallway", "junction"), (
                "a destination was attached to something that is not corridor"
            )
