"""
Optional OCR-based name suggestion for map-based destination placement.

This is a *suggestion only* — nothing in this module ever writes to the
database, and it is never invoked as part of saving a Room (see
room_routes.py, which has no dependency on this file at all). The admin
always confirms or edits the suggested text before anything is saved
(AdminRoomsScreen.jsx). If OCR isn't available in the current environment
(no system `tesseract` binary — pytesseract is a thin Python wrapper
around it, not a bundled OCR engine) or fails for any reason, this
returns an "unavailable" result instead of raising, so the map-based
placement flow always still works with a manually typed name — exactly
the fallback the product rule requires.
"""

from __future__ import annotations

from typing import NamedTuple, Optional

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
