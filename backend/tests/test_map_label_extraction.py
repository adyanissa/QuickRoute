"""
Tests for services/map_label_extraction_service — reading the text
PRINTED ON a floor map, with real positions.

Everything here is about COORDINATES, not text quality. The whole feature
downstream of this module turns these boxes into RoutePoint positions, so
the tests that matter most are the ones asserting that a box lands where
the drawing says it does, and that the module REFUSES rather than
producing an approximate box when it cannot prove the transform.

Real PDFs are generated with PyMuPDF (already a hard dependency) rather
than committed as fixtures, so the expected pixel positions are computed
from the same page geometry the assertions check.

OCR tests are skipped when no tesseract binary is installed — that is a
real deployment state the code already handles, not a test failure.

Run with: pytest backend/tests/test_map_label_extraction.py -v
"""

import math
from pathlib import Path

import pytest

from services.map_image_service import PDF_RENDER_DPI
from services.map_label_extraction_service import (
    DIMENSION_TOLERANCE_PX,
    MIN_ROOM_NUMBER_DIGITS,
    POINTS_PER_INCH,
    alphabetic_tokens,
    extract_labels_from_pdf,
    extract_room_number,
    group_words_into_labels,
    normalize_label_text,
)
from services.ocr_service import extract_word_boxes, is_ocr_available


PAGE_WIDTH_PT = 400.0
PAGE_HEIGHT_PT = 300.0
SCALE = PDF_RENDER_DPI / POINTS_PER_INCH


def _rendered_size(width_pt: float, height_pt: float):
    """
    The pixel size PyMuPDF's get_pixmap(dpi=...) actually produces for a
    page this size — computed the same way the renderer does rather than
    hard-coded, so this test does not silently encode one DPI setting.
    """

    return (
        int(math.ceil(width_pt * SCALE)),
        int(math.ceil(height_pt * SCALE)),
    )


def _write_pdf(path: Path, entries, width_pt=PAGE_WIDTH_PT, height_pt=PAGE_HEIGHT_PT):
    """entries: [(text, x_pt, y_pt)] — y is the text baseline, PDF style."""

    import fitz

    document = fitz.open()
    page = document.new_page(width=width_pt, height=height_pt)

    for text, x_pt, y_pt in entries:
        page.insert_text((x_pt, y_pt), text, fontsize=12)

    document.save(str(path))
    document.close()
    return path


def _word(text, x0, y0, x1, y1, line_key=(0, 0, 0), confidence=1.0):
    return {
        "line_key": line_key,
        "text": text,
        "x0": x0,
        "y0": y0,
        "x1": x1,
        "y1": y1,
        "confidence": confidence,
    }


# ===========================================================
# Normalization
# ===========================================================

# 1.
def test_normalization_collapses_punctuation_and_case():
    assert normalize_label_text("Office-428 ") == "OFFICE 428"
    assert normalize_label_text("office_428") == "OFFICE 428"
    assert normalize_label_text("  ") == ""
    assert normalize_label_text(None) == ""


# 2. Hebrew and Arabic must survive normalization — a map drawn in either
#    has to match its own names directly, not through English.
def test_normalization_preserves_hebrew_and_arabic():
    assert normalize_label_text("חדר 428") == "חדר 428"
    assert normalize_label_text("غرفة-428") == "غرفة 428"


# 3. A single digit is never a room number: floor plans are full of scale
#    bars, north arrows and revision marks.
def test_room_number_requires_enough_digits():
    assert extract_room_number("OFFICE 428") == "428"
    assert extract_room_number("ROOM 4") is None
    assert MIN_ROOM_NUMBER_DIGITS == 2
    # Longest run wins over the first one seen.
    assert extract_room_number("WING 4 ROOM 1204") == "1204"


# 4.
def test_alphabetic_tokens_drops_pure_digits():
    assert alphabetic_tokens("OFFICE 428 STORAGE") == ("OFFICE", "STORAGE")


# ===========================================================
# Word grouping
# ===========================================================

# 5.
def test_adjacent_words_on_one_line_become_one_label():
    labels = group_words_into_labels(
        [
            _word("OFFICE", 100, 100, 160, 112),
            _word("428", 165, 100, 190, 112),
        ],
        "vector_pdf",
    )

    assert len(labels) == 1
    assert labels[0].normalized == "OFFICE 428"
    assert labels[0].number == "428"
    assert labels[0].x0 == 100
    assert labels[0].x1 == 190


# 6. A wide gap means two labels, even on one reported line — otherwise
#    two neighbouring rooms fuse into one string.
def test_distant_words_on_one_line_stay_separate():
    labels = group_words_into_labels(
        [
            _word("OFFICE", 100, 100, 160, 112),
            _word("LOBBY", 600, 100, 660, 112),
        ],
        "vector_pdf",
    )

    assert sorted(label.normalized for label in labels) == ["LOBBY", "OFFICE"]


# 7. THE REGRESSION THAT MATTERS: two words the extractor mis-grouped onto
#    one line, but which are physically on different rows, must never be
#    joined — on a floor plan that means two different rooms.
def test_words_on_different_rows_are_never_joined():
    labels = group_words_into_labels(
        [
            _word("OFFICE", 100, 100, 160, 112),
            _word("STORAGE", 162, 400, 230, 412),
        ],
        "ocr",
    )

    assert sorted(label.normalized for label in labels) == ["OFFICE", "STORAGE"]


# 8.
def test_label_centre_and_confidence_are_derived_from_the_group():
    labels = group_words_into_labels(
        [
            _word("ROOM", 100, 100, 140, 120, confidence=0.8),
            _word("101", 145, 100, 170, 120, confidence=0.6),
        ],
        "ocr",
    )

    label = labels[0]
    assert label.center_x == pytest.approx(135.0)
    assert label.center_y == pytest.approx(110.0)
    assert label.height == pytest.approx(20.0)
    assert label.confidence == pytest.approx(0.7)


# ===========================================================
# Vector PDF extraction — the coordinate contract
# ===========================================================

# 9. The whole feature rests on this: a word's box in PDF points must
#    arrive as the right box in source-PNG pixels.
def test_pdf_word_boxes_are_converted_to_source_png_pixels(tmp_path):
    pdf_path = _write_pdf(tmp_path / "plan.pdf", [("OFFICE 428", 100.0, 150.0)])
    width_px, height_px = _rendered_size(PAGE_WIDTH_PT, PAGE_HEIGHT_PT)

    result = extract_labels_from_pdf(
        pdf_path, source_width=width_px, source_height=height_px
    )

    assert result.available, result.reason
    assert result.source == "vector_pdf"
    assert result.scale == pytest.approx(SCALE)

    label = next(l for l in result.labels if l.number == "428")

    # The text starts at x=100pt on the baseline y=150pt, so its box must
    # start at 100*scale px, and the baseline must fall inside the box's
    # vertical extent (the box also covers ascenders and descenders).
    assert label.x0 == pytest.approx(100.0 * SCALE, abs=2.0)
    assert label.y0 <= 150.0 * SCALE <= label.y1
    assert 0 < label.center_x < width_px
    assert 0 < label.center_y < height_px


# 10. Two labels far apart on the page stay two labels after conversion.
def test_pdf_labels_keep_their_relative_positions(tmp_path):
    pdf_path = _write_pdf(
        tmp_path / "plan.pdf",
        [("OFFICE 428", 60.0, 80.0), ("STORAGE 429", 260.0, 240.0)],
    )
    width_px, height_px = _rendered_size(PAGE_WIDTH_PT, PAGE_HEIGHT_PT)

    result = extract_labels_from_pdf(
        pdf_path, source_width=width_px, source_height=height_px
    )

    by_number = {label.number: label for label in result.labels if label.number}

    assert set(by_number) == {"428", "429"}
    assert by_number["428"].center_x < by_number["429"].center_x
    assert by_number["428"].center_y < by_number["429"].center_y


# 11. THE REFUSAL. A PNG that cannot be explained by "this page at this
#     DPI" means every box would be silently offset — so we return none.
def test_extraction_refuses_when_image_size_disagrees(tmp_path):
    pdf_path = _write_pdf(tmp_path / "plan.pdf", [("OFFICE 428", 100.0, 150.0)])
    width_px, height_px = _rendered_size(PAGE_WIDTH_PT, PAGE_HEIGHT_PT)

    result = extract_labels_from_pdf(
        pdf_path,
        source_width=width_px + 200,   # e.g. a rotated or cropped page
        source_height=height_px,
    )

    assert not result.available
    assert result.labels == []
    assert result.source == "unavailable"
    assert "does not match" in (result.reason or "")


# 12. A discrepancy inside the rounding tolerance is fine — PyMuPDF rounds
#     fractional page sizes up to whole pixels.
def test_extraction_accepts_sub_pixel_rounding(tmp_path):
    pdf_path = _write_pdf(tmp_path / "plan.pdf", [("OFFICE 428", 100.0, 150.0)])
    width_px, height_px = _rendered_size(PAGE_WIDTH_PT, PAGE_HEIGHT_PT)

    assert abs(PAGE_WIDTH_PT * SCALE - width_px) <= DIMENSION_TOLERANCE_PX

    result = extract_labels_from_pdf(
        pdf_path, source_width=width_px, source_height=height_px
    )

    assert result.available


# 13. No recorded image size is also a refusal, not an assumption.
def test_extraction_refuses_without_recorded_image_size(tmp_path):
    pdf_path = _write_pdf(tmp_path / "plan.pdf", [("OFFICE 428", 100.0, 150.0)])

    result = extract_labels_from_pdf(pdf_path, source_width=None, source_height=None)

    assert not result.available
    assert "cannot be verified" in (result.reason or "")


# 14. A scanned PDF has no selectable text — reported as such, never as an
#     empty success.
def test_pdf_without_selectable_text_reports_why(tmp_path):
    pdf_path = _write_pdf(tmp_path / "blank.pdf", [])
    width_px, height_px = _rendered_size(PAGE_WIDTH_PT, PAGE_HEIGHT_PT)

    result = extract_labels_from_pdf(
        pdf_path, source_width=width_px, source_height=height_px
    )

    assert not result.available
    assert "no selectable text" in (result.reason or "")


# 15. A corrupt file never raises out of this module.
def test_unreadable_pdf_returns_a_reason_instead_of_raising(tmp_path):
    broken = tmp_path / "broken.pdf"
    broken.write_bytes(b"this is not a pdf")

    result = extract_labels_from_pdf(broken, source_width=100, source_height=100)

    assert not result.available
    assert result.reason


# ===========================================================
# OCR word boxes
# ===========================================================

# 16.
def test_missing_image_reports_a_reason_and_never_raises(tmp_path):
    words, error = extract_word_boxes(tmp_path / "nope.png")

    assert words == []
    assert error


# 17. The geometry contract for the raster path: boxes come back in the
#     image's OWN pixels, with no crop and no un-recorded upscale.
@pytest.mark.skipif(not is_ocr_available(), reason="tesseract is not installed")
def test_ocr_boxes_are_in_native_image_pixels(tmp_path):
    import cv2
    import numpy as np

    width, height = 900, 400
    image = np.full((height, width), 255, dtype=np.uint8)
    cv2.putText(
        image, "OFFICE 428", (500, 300), cv2.FONT_HERSHEY_SIMPLEX, 2.0, 0, 4
    )

    image_path = tmp_path / "source.png"
    cv2.imwrite(str(image_path), image)

    words, error = extract_word_boxes(image_path)

    assert error is None
    assert words, "OCR found nothing at all in a clean synthetic image"

    for word in words:
        assert 0 <= word["x0"] < word["x1"] <= width
        assert 0 <= word["y0"] < word["y1"] <= height
        assert 0.0 <= word["confidence"] <= 1.0

    # The text was drawn in the lower-right quadrant, so every box must be
    # there too — this is what catches a crop or an unrecorded rescale.
    assert all(word["x1"] > width / 2 for word in words)
    assert all(word["y1"] > height / 2 for word in words)
