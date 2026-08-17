"""
Optional OCR for map text. Two independent, non-overlapping uses:

1. suggest_destination_name(map_id, x, y) — a *suggestion only* for
   map-based destination placement. Nothing in this module ever writes to
   the database, and it is never invoked as part of saving a Room (see
   room_routes.py, which has no dependency on this file at all). The admin
   always confirms or edits the suggested text before anything is saved
   (AdminRoomsScreen.jsx).

2. extract_word_boxes(source_path) — every word on the WHOLE image, with
   its real bounding box, for services/map_label_extraction_service. This
   one is about geometry, not text quality: it must never crop, pad,
   rotate or rescale the image, because its callers turn the boxes it
   returns straight into source-image coordinates.

Both are best effort. If OCR isn't available in the current environment
(no system `tesseract` binary — pytesseract is a thin Python wrapper
around it, not a bundled OCR engine) or fails for any reason, they report
that instead of raising, so every flow that uses them still works without
OCR — exactly the fallback the product rule requires.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, NamedTuple, Optional, Tuple

import cv2

from services.map_image_service import SOURCE_DIR

try:
    import pytesseract
    from pytesseract import TesseractNotFoundError
except Exception:  # pytesseract itself isn't installed in this environment
    pytesseract = None

    class TesseractNotFoundError(Exception):
        pass


# Bounded region around the clicked point, in the map's original-image
# pixels — large enough to usually catch a short map label near the click,
# small enough to stay a "this one destination's name" crop rather than
# picking up neighboring labels.
DEFAULT_CROP_WIDTH_PX = 260.0
DEFAULT_CROP_HEIGHT_PX = 160.0

# Tesseract per-word confidences are 0-100; below this (as a 0-1 fraction)
# the suggestion is still returned (never withheld) but callers must treat
# it as low-confidence — the admin UI leaves the name field editable and
# never pre-fills it as if it were certain. See AdminRoomsScreen.jsx.
LOW_CONFIDENCE_THRESHOLD = 0.45


class OcrSuggestionResult(NamedTuple):
    available: bool
    text: str
    confidence: float
    low_confidence: bool
    reason: Optional[str]


def _unavailable(reason: str) -> OcrSuggestionResult:
    return OcrSuggestionResult(
        available=False,
        text="",
        confidence=0.0,
        low_confidence=True,
        reason=reason,
    )


def is_ocr_available() -> bool:
    if pytesseract is None:
        return False

    try:
        pytesseract.get_tesseract_version()
        return True
    except Exception:
        return False


def extract_word_boxes(
    source_path: Path,
) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    """
    Every legible word on one map image, with its bounding box in that
    image's OWN pixels.

    Returns (words, error_reason). Never raises — an unreadable file, a
    missing OCR engine or a tesseract crash all come back as
    ([], "<human-readable reason>") so the caller can report the failure
    instead of handling an exception. An image with no legible text is
    ([], None): that is a successful read that found nothing.

    Each word:
        {
          "line_key":   (block, paragraph, line) as reported by tesseract,
          "text":       str,
          "x0","y0","x1","y1": float, image pixels, top-left origin,
          "confidence": float in 0.0-1.0,
        }

    GEOMETRY CONTRACT — the reason this exists separately from
    suggest_destination_name, which crops a 260x160 window and upscales it
    without recording the factor:

      * the image is passed to tesseract at its native size,
      * no crop, no resize, no rotation, no padding,
      * only a grayscale conversion, which moves nothing.

    So a returned box needs no back-transform: it is already in the same
    space as Map.source_width/source_height, RoutePoint.x/y and the wall
    mask in services/graph_connection_service.

    Page segmentation is left at tesseract's default rather than sparse
    mode. Sparse mode finds more isolated text on a floor plan but reports
    almost every word as its own line, and real line grouping is what lets
    the caller join "OFFICE" + "428" into one label without guessing.
    Missing a label costs one admin click; inventing one by fusing two
    rooms' text would place a room in the wrong place.
    """

    if not is_ocr_available():
        return [], "OCR engine (tesseract) is not installed on this server."

    try:
        if not Path(source_path).exists():
            return [], "This map has no processed source image to read text from."
    except Exception as error:  # noqa: BLE001 - path may be anything
        return [], f"The map's source image could not be located: {error}"

    image = cv2.imread(str(source_path), cv2.IMREAD_GRAYSCALE)

    if image is None:
        return [], "The map's source image could not be read."

    try:
        data = pytesseract.image_to_data(
            image, output_type=pytesseract.Output.DICT
        )
    except TesseractNotFoundError:
        return [], "OCR engine (tesseract) is not installed on this server."
    except Exception as error:  # noqa: BLE001 - OCR is best-effort
        return [], f"OCR failed: {error}"

    texts = data.get("text", [])
    words: List[Dict[str, Any]] = []

    for i, raw_text in enumerate(texts):
        text = str(raw_text).strip()

        if not text:
            continue

        try:
            confidence = float(data["conf"][i])
        except (KeyError, IndexError, TypeError, ValueError):
            continue

        # Tesseract reports -1 for structural rows that carry no word.
        if confidence < 0:
            continue

        try:
            left = float(data["left"][i])
            top = float(data["top"][i])
            width = float(data["width"][i])
            height = float(data["height"][i])
        except (KeyError, IndexError, TypeError, ValueError):
            continue

        if width <= 0 or height <= 0:
            continue

        def _index(field: str) -> int:
            try:
                return int(data[field][i])
            except (KeyError, IndexError, TypeError, ValueError):
                return 0

        words.append(
            {
                "line_key": (
                    _index("block_num"),
                    _index("par_num"),
                    _index("line_num"),
                ),
                "text": text,
                "x0": left,
                "y0": top,
                "x1": left + width,
                "y1": top + height,
                "confidence": max(0.0, min(1.0, confidence / 100.0)),
            }
        )

    return words, None


def suggest_destination_name(
    map_id: str,
    x: float,
    y: float,
    crop_width: float = DEFAULT_CROP_WIDTH_PX,
    crop_height: float = DEFAULT_CROP_HEIGHT_PX,
) -> OcrSuggestionResult:
    """
    Crops a bounded region of this map's processed source image around
    (x, y) and runs local OCR (tesseract via pytesseract) on it. Never
    raises — every failure mode (OCR engine missing, no source image,
    point outside the image, no legible text) returns
    available/low_confidence flags the caller can act on instead of an
    exception, since this is explicitly a best-effort suggestion, not a
    required step.
    """

    if not is_ocr_available():
        return _unavailable(
            "OCR engine (tesseract) is not installed on this server."
        )

    source_path = SOURCE_DIR / f"{map_id}.png"

    if not source_path.exists():
        return _unavailable(
            "This map has no processed source image to read text from."
        )

    image = cv2.imread(str(source_path), cv2.IMREAD_COLOR)

    if image is None:
        return _unavailable("The map's source image could not be read.")

    height, width = image.shape[:2]

    half_w = crop_width / 2.0
    half_h = crop_height / 2.0

    x1 = max(0, int(round(x - half_w)))
    y1 = max(0, int(round(y - half_h)))
    x2 = min(width, int(round(x + half_w)))
    y2 = min(height, int(round(y + half_h)))

    if x2 <= x1 or y2 <= y1:
        return OcrSuggestionResult(
            available=True,
            text="",
            confidence=0.0,
            low_confidence=True,
            reason="Selected point is outside the map image bounds.",
        )

    crop = image[y1:y2, x1:x2]
    crop_h, crop_w = crop.shape[:2]

    # Upscale small crops — tesseract reads small map-label text far more
    # reliably at a larger effective size than the crop's native pixels.
    scale = max(1.0, 400.0 / max(crop_w, 1))

    if scale > 1.0:
        crop = cv2.resize(
            crop,
            (max(1, int(crop_w * scale)), max(1, int(crop_h * scale))),
            interpolation=cv2.INTER_CUBIC,
        )

    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)

    # A light Otsu threshold helps isolate printed map labels from
    # whatever background fill color that part of the map uses, without
    # assuming any particular map color scheme.
    _, thresholded = cv2.threshold(
        gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU
    )

    try:
        data = pytesseract.image_to_data(
            thresholded, output_type=pytesseract.Output.DICT
        )
    except TesseractNotFoundError:
        return _unavailable(
            "OCR engine (tesseract) is not installed on this server."
        )
    except Exception as error:
        return _unavailable(f"OCR failed: {error}")

    words = []
    confidences = []

    for i, word in enumerate(data.get("text", [])):
        cleaned = word.strip()

        if not cleaned:
            continue

        try:
            conf = float(data["conf"][i])
        except (ValueError, KeyError, IndexError):
            conf = -1.0

        if conf < 0:
            continue

        words.append(cleaned)
        confidences.append(conf)

    if not words:
        return OcrSuggestionResult(
            available=True,
            text="",
            confidence=0.0,
            low_confidence=True,
            reason="No legible text found at the selected location.",
        )

    suggested_text = " ".join(words)
    average_confidence = (sum(confidences) / len(confidences)) / 100.0
    normalized_confidence = round(max(0.0, min(1.0, average_confidence)), 3)

    return OcrSuggestionResult(
        available=True,
        text=suggested_text,
        confidence=normalized_confidence,
        low_confidence=normalized_confidence < LOW_CONFIDENCE_THRESHOLD,
        reason=None,
    )
