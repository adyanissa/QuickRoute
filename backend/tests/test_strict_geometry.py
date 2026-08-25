"""
Tests for services/strict_geometry_service — the high-resolution safety
proof used by the automatic navigation build.

The most important test in this file is
`test_strict_sees_a_thin_wall_the_legacy_mask_misses`. That is the B4
regression: the legacy collision mask downscales every map to 900 px and
`_build_navigation_line_mask` derives its retention thresholds from the
array it is handed, so a thin interior partition simply is not in the
legacy mask and `has_clear_line` reports a clear path straight through it.
Everything automatic in this pipeline rests on that not being the final
word.

The second most important is
`test_legacy_validator_behaviour_is_unchanged`, which pins the promise
that adding this module changed nothing about existing Auto Connect
decisions.

Run with: pytest backend/tests/test_strict_geometry.py -v
"""

import cv2
import numpy as np
import pytest

import services.graph_connection_service as legacy
import services.strict_geometry_service as strict
from services.map_image_service import SOURCE_DIR, ensure_map_directories


def _write_plan(map_id, image):
    ensure_map_directories()
    path = SOURCE_DIR / f"{map_id}.png"
    cv2.imwrite(str(path), image)
    legacy._WALL_MASK_CACHE.pop(map_id, None)
    strict.clear_strict_mask_cache()
    return path


def _plan_with_thin_partition(width=2400, height=1800, length=30, thickness=4):
    """
    A large sheet with a big enclosing boundary and one SHORT, THIN
    interior partition in the middle — the kind of thing a 900 px working
    image cannot represent.
    """

    image = np.full((height, width), 255, dtype=np.uint8)
    cv2.rectangle(image, (100, 100), (width - 100, height - 100), 0, 10)

    cx, cy = width // 2, height // 2
    cv2.line(image, (cx, cy - length // 2), (cx, cy + length // 2), 0, thickness)

    return image, cx, cy


# ===========================================================
# The B4 regression
# ===========================================================

# 1.
def test_strict_sees_a_thin_wall_the_legacy_mask_misses(tmp_path):
    image, cx, cy = _plan_with_thin_partition()
    map_id = "strict_thin_wall"
    path = _write_plan(map_id, image)

    try:
        # A short horizontal probe straight through the partition.
        legacy_verdict = legacy.has_clear_line(map_id, cx - 80, cy, cx + 80, cy)
        strict_verdict = strict.strict_has_clear_line(map_id, cx - 80, cy, cx + 80, cy)

        assert legacy_verdict is True, (
            "This test is only meaningful while the legacy mask still misses "
            "this wall; if legacy now catches it, B4 was fixed elsewhere."
        )
        assert strict_verdict is False
    finally:
        path.unlink(missing_ok=True)


# 2.
def test_strict_mask_is_higher_resolution_than_legacy(tmp_path):
    image, _cx, _cy = _plan_with_thin_partition()
    map_id = "strict_resolution"
    path = _write_plan(map_id, image)

    try:
        legacy_mask, legacy_downscale = legacy._get_wall_mask(map_id)
        strict_mask, strict_downscale = strict.get_strict_wall_mask(map_id)

        assert max(legacy_mask.shape) <= 900
        assert max(strict_mask.shape) == 1800 or max(strict_mask.shape) == 2400
        assert strict_downscale > legacy_downscale
        assert strict_downscale == 1.0
    finally:
        path.unlink(missing_ok=True)


# ===========================================================
# Backward compatibility — the promise to Auto Connect
# ===========================================================

# 3.
def test_legacy_validator_behaviour_is_unchanged(tmp_path):
    """
    Existing Auto Connect decisions must not move because this module
    exists. The legacy mask, its downscale and its verdicts are compared
    before and after the strict mask has been built for the same map.
    """

    image, cx, cy = _plan_with_thin_partition()
    map_id = "strict_no_side_effects"
    path = _write_plan(map_id, image)

    try:
        before_mask, before_downscale = legacy._get_wall_mask(map_id)
        before_snapshot = before_mask.copy()
        before_verdict = legacy.has_clear_line(map_id, cx - 80, cy, cx + 80, cy)

        strict.get_strict_wall_mask(map_id)
        strict.strict_has_clear_line(map_id, cx - 80, cy, cx + 80, cy)
        strict.strict_is_wall_pixel(map_id, cx, cy, 4.0)

        after_mask, after_downscale = legacy._get_wall_mask(map_id)

        assert after_downscale == before_downscale
        assert np.array_equal(after_mask, before_snapshot)
        assert legacy.has_clear_line(map_id, cx - 80, cy, cx + 80, cy) is before_verdict
    finally:
        path.unlink(missing_ok=True)


# ===========================================================
# Fail closed
# ===========================================================

# 4.
def test_strict_fails_closed_when_there_is_no_source_image():
    strict.clear_strict_mask_cache()

    assert strict.get_strict_wall_mask("no_such_map_at_all") is None
    assert strict.strict_mask_available("no_such_map_at_all") is False
    # None, NOT True. The legacy validator returns True here on purpose;
    # for automatic placement that would be a silent disaster.
    assert strict.strict_has_clear_line("no_such_map_at_all", 0, 0, 10, 10) is None
    assert strict.strict_is_wall_pixel("no_such_map_at_all", 5, 5) is None
    assert legacy.has_clear_line("no_such_map_at_all", 0, 0, 10, 10) is True


# ===========================================================
# Short-link tolerance (B8)
# ===========================================================

# 5.
def test_a_short_link_is_not_rejected_by_one_stray_pixel():
    """
    The legacy rule needs ~34 samples before it tolerates a single blocked
    one, so one antialiased pixel on a doorway jamb kills a short corridor
    link. Below the sample floor the strict rule allows a small absolute
    number instead.
    """

    mask = np.zeros((200, 200), dtype=np.uint8)
    mask[100, 60] = 255  # exactly one wall pixel on the path

    # ~20 px long -> ~11 samples at a 2 px step, under the floor.
    assert (
        strict._clear_line_on_mask(mask, 1.0, 50.0, 100.0, 70.0, 100.0) is True
    )


# 6.
def test_a_real_wall_crossing_is_still_rejected_on_a_short_link():
    mask = np.zeros((200, 200), dtype=np.uint8)
    mask[95:105, 58:64] = 255  # a genuine wall, several samples thick

    assert (
        strict._clear_line_on_mask(mask, 1.0, 50.0, 100.0, 70.0, 100.0) is False
    )


# 7.
def test_out_of_bounds_counts_as_blocked():
    mask = np.zeros((100, 100), dtype=np.uint8)

    assert strict._clear_line_on_mask(mask, 1.0, 50.0, 50.0, 400.0, 50.0) is False


# ===========================================================
# Cache
# ===========================================================

# 8.
def test_the_strict_cache_is_bounded(tmp_path):
    """
    A full-resolution mask is ~12 MB. The legacy cache is unbounded and
    never evicts; copying that here would leak one mask per map previewed
    for the life of the process.
    """

    strict.clear_strict_mask_cache()
    written = []

    try:
        for index in range(strict.STRICT_CACHE_ENTRIES + 2):
            image, _cx, _cy = _plan_with_thin_partition(width=600, height=400)
            map_id = f"strict_cache_{index}"
            written.append(_write_plan(map_id, image))
            # _write_plan clears the cache, so warm it after writing.
            strict.get_strict_wall_mask(map_id)
            assert len(strict._STRICT_MASK_CACHE) <= strict.STRICT_CACHE_ENTRIES
    finally:
        for path in written:
            path.unlink(missing_ok=True)
        strict.clear_strict_mask_cache()


# ===========================================================
# Stroke thickness
# ===========================================================

# 9.
def test_wall_stroke_thickness_tracks_the_drawing(tmp_path):
    """
    The gap-sealing kernel is derived from this rather than from a fixed
    pixel constant, because Map.scale defaults to 1.0 and almost every map
    in the system is uncalibrated — a constant would behave completely
    differently at 150 DPI and at 400 DPI.
    """

    thin = np.full((800, 800), 255, dtype=np.uint8)
    cv2.rectangle(thin, (100, 100), (700, 700), 0, 4)

    thick = np.full((800, 800), 255, dtype=np.uint8)
    cv2.rectangle(thick, (100, 100), (700, 700), 0, 16)

    from services.map_image_service import _build_navigation_line_mask

    thin_measure = strict.measure_wall_stroke_thickness(
        _build_navigation_line_mask(thin)
    )
    thick_measure = strict.measure_wall_stroke_thickness(
        _build_navigation_line_mask(thick)
    )

    assert thick_measure > thin_measure
    assert thin_measure >= strict.MIN_STROKE_THICKNESS_PX


# 10.
def test_stroke_thickness_of_an_empty_mask_is_zero():
    assert strict.measure_wall_stroke_thickness(np.zeros((50, 50), np.uint8)) == 0.0
    assert strict.measure_wall_stroke_thickness(None) == 0.0
