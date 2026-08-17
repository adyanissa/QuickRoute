"""
Deterministic extraction of the text labels PRINTED ON a floor map, with
their real positions.

This is the geometry half of the hybrid semantic+geometry pipeline. Claude
tells QuickRoute WHAT a place is (names/type); this module reads WHERE a
matching label physically sits on the map. Nothing here talks to any AI
provider, and nothing here writes to the database.

TWO SOURCES, IN PRIORITY ORDER
------------------------------
1. VECTOR PDF — the map's preserved original (uploads/maps/originals/
   {map_id}.pdf, guaranteed to exist for every map uploaded since the
   source-durability fix). PyMuPDF's page.get_text("words") returns each
   word with its exact bounding box in PDF points.

2. RASTER FALLBACK — the normalized source PNG, through the project's
   EXISTING tesseract/pytesseract integration (services/ocr_service.py).
   No second OCR engine is introduced.

THE COORDINATE CONTRACT
-----------------------
Every bbox this module returns is in **normalized source-PNG pixels** —
the one coordinate space the whole system already uses for RoutePoint.x/y,
Room.x/y and services/graph_connection_service's wall mask. A caller can
use a returned centre directly as a RoutePoint coordinate with no further
conversion.

For the PDF path that means converting PDF points to source-PNG pixels.
services/map_image_service._convert_pdf_first_page_to_png renders page 0
with page.get_pixmap(dpi=MAP_PDF_RENDER_DPI) and Pillow then re-saves it at
identical dimensions, so the mapping is a pure uniform scale plus the
page-rect origin offset:

    scale = MAP_PDF_RENDER_DPI / 72
    px    = (pdf_x - page.rect.x0) * scale
    py    = (pdf_y - page.rect.y0) * scale

That scale is never assumed. It is cross-checked against the Map document's
own recorded source_width/source_height, and extraction REFUSES (returning
an explicit reason rather than approximate boxes) whenever the two
disagree — a rotated page, a cropped MediaBox, a map whose PNG was produced
by some other route, or a changed DPI setting all surface as a refusal
instead of silently shifted coordinates.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from services.map_image_service import (
    PDF_RENDER_DPI,
    SOURCE_DIR,
    get_preserved_original_path,
)


# PDF user-space units are points; 72 of them per inch.
POINTS_PER_INCH = 72.0

# The rendered PNG must agree with the DPI-derived scale to within this
# many pixels on each axis. One pixel of slack absorbs the rounding
# PyMuPDF applies when it turns a fractional page size into integer pixmap
# dimensions; anything larger means the PNG did not come from this page the
# way we think it did, and we refuse rather than guess.
DIMENSION_TOLERANCE_PX = 2.0

# Words on the same text line are joined into one label when the
# horizontal gap between them is at most this multiple of the line's
# height ("OFFICE" + "428" -> "OFFICE 428"). Deliberately small: joining
# too eagerly would fuse two neighbouring rooms' labels into one string.
MAX_WORD_GAP_RATIO = 1.6

# Two words are only ever joined if their vertical extents actually
# overlap by at least this fraction of the shorter one. Both extractors
# report line membership themselves, but that grouping is theirs, not
# ours: this is the independent check that a single mis-grouped line can
# never fuse text from two different rows — which on a floor plan means
# two different rooms.
MIN_VERTICAL_OVERLAP_RATIO = 0.5

# A digit run must be at least this long to be treated as a room NUMBER.
# Single digits are far too ambiguous on a floor plan (scale bars, north
# arrows, drawing revisions) to key a match on.
MIN_ROOM_NUMBER_DIGITS = 2

# pytesseract per-word confidences are 0-100. Below this the word is
# dropped entirely rather than offered as a low-quality label.
MIN_OCR_WORD_CONFIDENCE = 40.0


@dataclass
class MapLabel:
    """One text label physically printed on the map."""

    text: str                      # exactly as printed
    normalized: str                # uppercased, punctuation collapsed
    number: Optional[str]          # the room-number digit run, if any
    tokens: Tuple[str, ...]        # normalized alphabetic tokens
    x0: float
    y0: float
    x1: float
    y1: float
    source: str                    # "vector_pdf" | "ocr"
    confidence: float = 1.0        # 1.0 for vector text; OCR word average

    @property
    def center_x(self) -> float:
        return (self.x0 + self.x1) / 2.0

    @property
    def center_y(self) -> float:
        return (self.y0 + self.y1) / 2.0

    @property
    def height(self) -> float:
        return abs(self.y1 - self.y0)

    @property
    def width(self) -> float:
        return abs(self.x1 - self.x0)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "text": self.text,
            "normalized": self.normalized,
            "number": self.number,
            "bbox": [
                round(self.x0, 2),
                round(self.y0, 2),
                round(self.x1, 2),
                round(self.y1, 2),
            ],
            "center": [round(self.center_x, 2), round(self.center_y, 2)],
            "source": self.source,
            "confidence": round(self.confidence, 3),
        }


@dataclass
class LabelExtractionResult:
    labels: List[MapLabel] = field(default_factory=list)
    source: str = "unavailable"    # "vector_pdf" | "ocr" | "unavailable"
    reason: Optional[str] = None   # why nothing was extracted
    scale: Optional[float] = None  # PDF points -> source-PNG px, when used

    @property
    def available(self) -> bool:
        return bool(self.labels)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source": self.source,
            "reason": self.reason,
            "scale": round(self.scale, 6) if self.scale is not None else None,
            "label_count": len(self.labels),
        }


# =========================================================
# Normalization
# =========================================================


_NON_ALNUM = re.compile(r"[^0-9A-Z֐-׿؀-ۿ]+")
_DIGIT_RUN = re.compile(r"\d+")


def normalize_label_text(value: Optional[str]) -> str:
    """
    Uppercase, collapse every run of punctuation/whitespace to one space,
    and trim. Hebrew and Arabic ranges are preserved so a map labelled in
    those scripts normalizes just as usefully as a Latin one.

    "Office-428 " -> "OFFICE 428"      "office_428" -> "OFFICE 428"
    """

    if not value:
        return ""
    return _NON_ALNUM.sub(" ", value.upper()).strip()


def extract_room_number(value: Optional[str]) -> Optional[str]:
    """
    The longest digit run of at least MIN_ROOM_NUMBER_DIGITS digits, or
    None. Length-gated on purpose — see MIN_ROOM_NUMBER_DIGITS.
    """

    if not value:
        return None
    runs = [run for run in _DIGIT_RUN.findall(value) if len(run) >= MIN_ROOM_NUMBER_DIGITS]
    if not runs:
        return None
    return max(runs, key=len)


def alphabetic_tokens(normalized: str) -> Tuple[str, ...]:
    """Normalized tokens that are not pure digits."""

    return tuple(token for token in normalized.split() if not token.isdigit())


def _build_label(
    text: str,
    x0: float,
    y0: float,
    x1: float,
    y1: float,
    source: str,
    confidence: float = 1.0,
) -> Optional[MapLabel]:
    normalized = normalize_label_text(text)
    if not normalized:
        return None
    return MapLabel(
        text=text.strip(),
        normalized=normalized,
        number=extract_room_number(normalized),
        tokens=alphabetic_tokens(normalized),
        x0=float(x0),
        y0=float(y0),
        x1=float(x1),
        y1=float(y1),
        source=source,
        confidence=float(confidence),
    )


# =========================================================
# Word grouping
# =========================================================


def _vertically_aligned(a: Dict[str, Any], b: Dict[str, Any]) -> bool:
    """Do these two words share a row, not just a reported line number?"""

    overlap = min(a["y1"], b["y1"]) - max(a["y0"], b["y0"])
    shorter = min(a["y1"] - a["y0"], b["y1"] - b["y0"])

    if shorter <= 0:
        return False

    return (overlap / shorter) >= MIN_VERTICAL_OVERLAP_RATIO


def group_words_into_labels(
    words: List[Dict[str, Any]], source: str
) -> List[MapLabel]:
    """
    Joins words that the extractor already reported as belonging to the
    same text line (both PyMuPDF and tesseract provide real line grouping —
    this is never inferred from pixel proximity alone) AND that sit close
    enough horizontally to be one label rather than two.

    Each `words` entry: {line_key, text, x0, y0, x1, y1, confidence}.
    """

    by_line: Dict[Any, List[Dict[str, Any]]] = {}
    for word in words:
        by_line.setdefault(word["line_key"], []).append(word)

    labels: List[MapLabel] = []

    for line_words in by_line.values():
        line_words.sort(key=lambda w: w["x0"])

        current: List[Dict[str, Any]] = []

        def flush(group: List[Dict[str, Any]]) -> None:
            if not group:
                return
            text = " ".join(w["text"] for w in group)
            confidences = [w.get("confidence", 1.0) for w in group]
            label = _build_label(
                text,
                min(w["x0"] for w in group),
                min(w["y0"] for w in group),
                max(w["x1"] for w in group),
                max(w["y1"] for w in group),
                source,
                sum(confidences) / len(confidences),
            )
            if label is not None:
                labels.append(label)

        for word in line_words:
            if not current:
                current = [word]
                continue

            previous = current[-1]
            line_height = max(
                previous["y1"] - previous["y0"], word["y1"] - word["y0"], 1.0
            )
            gap = word["x0"] - previous["x1"]

            if gap <= line_height * MAX_WORD_GAP_RATIO and _vertically_aligned(
                previous, word
            ):
                current.append(word)
            else:
                flush(current)
                current = [word]

        flush(current)

    return labels


# =========================================================
# Vector PDF extraction
# =========================================================


def _pdf_scale_or_refusal(
    page, source_width: Optional[int], source_height: Optional[int]
) -> Tuple[Optional[float], Optional[str]]:
    """
    The DPI-derived scale, verified against the Map's own recorded PNG
    dimensions. Returns (scale, None) or (None, refusal_reason).

    This is the guard that keeps the whole feature honest: if the source
    PNG cannot be explained by "this page rendered at MAP_PDF_RENDER_DPI",
    every bbox we produced would be silently offset or stretched, and a
    wrong coordinate is far worse than no coordinate.
    """

    rect = page.rect
    if rect.width <= 0 or rect.height <= 0:
        return None, "The PDF page has no usable size."

    scale = PDF_RENDER_DPI / POINTS_PER_INCH

    if not source_width or not source_height:
        return None, (
            "This map has no recorded source image size, so the PDF-to-image "
            "coordinate transform cannot be verified."
        )

    expected_width = rect.width * scale
    expected_height = rect.height * scale

    if (
        abs(expected_width - float(source_width)) > DIMENSION_TOLERANCE_PX
        or abs(expected_height - float(source_height)) > DIMENSION_TOLERANCE_PX
    ):
        return None, (
            "The map image does not match this PDF page rendered at "
            f"{PDF_RENDER_DPI} DPI (expected about "
            f"{expected_width:.0f}x{expected_height:.0f} px, the stored image "
            f"is {source_width}x{source_height} px). Label positions cannot "
            "be transformed reliably, so none were extracted."
        )

    return scale, None


def _roi_scale_or_refusal(
    roi: Tuple[float, float, float, float],
    source_width: Optional[int],
    source_height: Optional[int],
) -> Tuple[Optional[float], Optional[str]]:
    """The DPI scale, verified against the CROP's recorded size."""

    scale = PDF_RENDER_DPI / POINTS_PER_INCH

    roi_width = float(roi[2]) - float(roi[0])
    roi_height = float(roi[3]) - float(roi[1])

    if roi_width <= 0 or roi_height <= 0:
        return None, "The crop region has no usable size."

    if not source_width or not source_height:
        return None, (
            "This map has no recorded image size, so the crop's coordinate "
            "transform cannot be verified."
        )

    if (
        abs(roi_width - float(source_width)) > DIMENSION_TOLERANCE_PX
        or abs(roi_height - float(source_height)) > DIMENSION_TOLERANCE_PX
    ):
        return None, (
            "The stored image does not match the crop region it is supposed "
            f"to come from (crop is {roi_width:.0f}x{roi_height:.0f} px, the "
            f"stored image is {source_width}x{source_height} px). Label "
            "positions cannot be transformed reliably, so none were "
            "extracted."
        )

    return scale, None


def extract_labels_from_pdf(
    pdf_path: Path,
    *,
    source_width: Optional[int],
    source_height: Optional[int],
    roi: Optional[Tuple[float, float, float, float]] = None,
) -> LabelExtractionResult:
    """
    Page 0 only — the source PNG *is* page 0 (see
    map_image_service._convert_pdf_first_page_to_png), so any other page's
    coordinates would refer to an image that does not exist.

    `roi` is (x0, y0, x1, y1) in FULL rendered-page pixels: the crop
    window that produced the image being analysed. When given, only
    labels intersecting that window are returned and their coordinates
    are rebased onto the crop's own origin, so a cropped map keeps the
    vector text it always had.

    This exists so cropping never has to destroy selectable text. A crop
    that rasterises a vector PDF throws away exact glyph positions that
    were already available, and then the only way to get them back is OCR
    — which may not be installed, and which is strictly worse than the
    data that was discarded. With an ROI the text survives the crop and
    arrives already in the cropped image's coordinate system.
    """

    try:
        import fitz  # PyMuPDF, already a hard dependency of this project
    except ImportError:
        return LabelExtractionResult(
            source="unavailable", reason="PyMuPDF is not installed."
        )

    document = None
    try:
        document = fitz.open(str(pdf_path))

        if document.page_count == 0:
            return LabelExtractionResult(
                source="unavailable", reason="The PDF has no pages."
            )

        page = document.load_page(0)

        if roi is None:
            scale, refusal = _pdf_scale_or_refusal(
                page, source_width, source_height
            )
        else:
            # With a crop, the recorded image size describes the CROP, not
            # the page, so the page-size check would always refuse. Verify
            # the ROI against the recorded size instead and derive the
            # scale from the DPI as usual.
            scale, refusal = _roi_scale_or_refusal(roi, source_width, source_height)

        if scale is None:
            return LabelExtractionResult(source="unavailable", reason=refusal)

        origin_x = page.rect.x0
        origin_y = page.rect.y0

        roi_x0, roi_y0 = (roi[0], roi[1]) if roi else (0.0, 0.0)
        roi_x1, roi_y1 = (roi[2], roi[3]) if roi else (None, None)

        raw_words = page.get_text("words")

        words: List[Dict[str, Any]] = []
        for entry in raw_words:
            # (x0, y0, x1, y1, text, block_no, line_no, word_no)
            x0, y0, x1, y1, text = entry[0], entry[1], entry[2], entry[3], entry[4]
            block_no = entry[5] if len(entry) > 5 else 0
            line_no = entry[6] if len(entry) > 6 else 0

            if not str(text).strip():
                continue

            px0 = (float(x0) - origin_x) * scale
            py0 = (float(y0) - origin_y) * scale
            px1 = (float(x1) - origin_x) * scale
            py1 = (float(y1) - origin_y) * scale

            if roi is not None:
                # Keep only words that actually fall inside the crop, then
                # rebase onto the crop's origin.
                if px1 <= roi_x0 or px0 >= roi_x1 or py1 <= roi_y0 or py0 >= roi_y1:
                    continue
                px0 -= roi_x0
                px1 -= roi_x0
                py0 -= roi_y0
                py1 -= roi_y0

            words.append(
                {
                    "line_key": (block_no, line_no),
                    "text": str(text),
                    "x0": px0,
                    "y0": py0,
                    "x1": px1,
                    "y1": py1,
                    "confidence": 1.0,
                }
            )

        if not words:
            return LabelExtractionResult(
                source="unavailable",
                scale=scale,
                reason=(
                    "This PDF contains no selectable text (it is most likely a "
                    "scan), so no label positions could be read from it."
                ),
            )

        return LabelExtractionResult(
            labels=group_words_into_labels(words, "vector_pdf"),
            source="vector_pdf",
            scale=scale,
        )

    except Exception as error:  # noqa: BLE001 - extraction is best-effort
        return LabelExtractionResult(
            source="unavailable", reason=f"Could not read the PDF: {error}"
        )
    finally:
        if document is not None:
            try:
                document.close()
            except Exception:
                pass


# =========================================================
# Raster (OCR) extraction
# =========================================================


def extract_labels_from_source_image(map_id: str) -> LabelExtractionResult:
    """
    Whole-image OCR through the project's EXISTING tesseract integration.
    Coordinates come back in the source PNG's own pixels, which is already
    the target space, so there is no transform to verify here.
    """

    from services.ocr_service import extract_word_boxes, is_ocr_available

    if not is_ocr_available():
        return LabelExtractionResult(
            source="unavailable",
            reason=(
                "No selectable text was available and the OCR engine "
                "(tesseract) is not installed on this server, so no map "
                "labels could be read."
            ),
        )

    source_path = SOURCE_DIR / f"{map_id}.png"
    if not source_path.exists():
        return LabelExtractionResult(
            source="unavailable",
            reason="This map has no processed source image to read text from.",
        )

    raw_words, error = extract_word_boxes(source_path)
    if error:
        return LabelExtractionResult(source="unavailable", reason=error)

    words = [
        {
            "line_key": word["line_key"],
            "text": word["text"],
            "x0": word["x0"],
            "y0": word["y0"],
            "x1": word["x1"],
            "y1": word["y1"],
            "confidence": word["confidence"],
        }
        for word in raw_words
        if word["confidence"] * 100.0 >= MIN_OCR_WORD_CONFIDENCE
    ]

    if not words:
        return LabelExtractionResult(
            source="unavailable",
            reason="OCR found no legible text on this map image.",
        )

    return LabelExtractionResult(
        labels=group_words_into_labels(words, "ocr"), source="ocr"
    )


# =========================================================
# Entry point
# =========================================================


def extract_map_labels(map_item) -> LabelExtractionResult:
    """
    Best available label set for one Map, vector PDF first.

    `map_item` is a models.map_model.Map document (or anything exposing
    id / source_width / source_height / analysis_source_type).
    """

    map_id = str(map_item.id)
    source_width = getattr(map_item, "source_width", None)
    source_height = getattr(map_item, "source_height", None)

    original = get_preserved_original_path(map_id)

    if original is not None and original.suffix.lower() == ".pdf":
        pdf_result = extract_labels_from_pdf(
            original, source_width=source_width, source_height=source_height
        )
        if pdf_result.available:
            return pdf_result

        # A scanned PDF has no selectable text — fall through to OCR rather
        # than giving up. A REFUSED transform also falls through, because
        # OCR reads the PNG directly and needs no transform at all.
        raster = extract_labels_from_source_image(map_id)
        if raster.available:
            return raster
        return pdf_result if pdf_result.reason else raster

    return extract_labels_from_source_image(map_id)
