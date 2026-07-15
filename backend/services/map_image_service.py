from __future__ import annotations

import base64
import math
import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple

import cv2
import fitz
import numpy as np
from dotenv import load_dotenv
from fastapi import UploadFile
from PIL import Image, ImageOps

try:
    from openai import OpenAI
except ImportError:
    OpenAI = None


# =========================================================
# Paths and environment
# =========================================================

BACKEND_DIR = Path(__file__).resolve().parents[1]

UPLOADS_DIR = BACKEND_DIR / "uploads"
MAPS_DIR = UPLOADS_DIR / "maps"

SOURCE_DIR = MAPS_DIR / "source"
DISPLAY_DIR = MAPS_DIR / "display"
TEMP_DIR = MAPS_DIR / "temporary"

load_dotenv(BACKEND_DIR / ".env")


# =========================================================
# Upload and processing settings
# =========================================================

ALLOWED_EXTENSIONS = {
    ".pdf",
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
}

MAX_UPLOAD_SIZE_MB = int(
    os.getenv("MAP_MAX_UPLOAD_SIZE_MB", "50")
)

MAX_UPLOAD_SIZE_BYTES = (
    MAX_UPLOAD_SIZE_MB * 1024 * 1024
)

PDF_RENDER_DPI = int(
    os.getenv("MAP_PDF_RENDER_DPI", "200")
)

OPENAI_IMAGE_MODEL = os.getenv(
    "OPENAI_IMAGE_MODEL",
    "gpt-image-2",
)

OPENAI_IMAGE_QUALITY = os.getenv(
    "OPENAI_IMAGE_QUALITY",
    "medium",
)

OPENAI_IMAGE_MAX_EDGE = int(
    os.getenv("OPENAI_IMAGE_MAX_EDGE", "2048")
)

AI_EDGE_SCORE_THRESHOLD = float(
    os.getenv("AI_EDGE_SCORE_THRESHOLD", "0.42")
)


# =========================================================
# AI instructions
# =========================================================

MAP_COLORING_PROMPT = """
Convert the supplied architectural floor plan into a clean,
simplified, professional indoor-navigation map for mall visitors.

This should no longer look like an engineering or construction drawing.
It should look like a modern digital mall wayfinding map.

Preserve the exact navigation-relevant layout:
- main walls and shop boundaries
- corridors and public walking areas
- entrances and exits
- stairs
- elevators
- escalators
- important service areas
- the relative location, orientation and proportions of all spaces

Remove or strongly simplify:
- construction measurements
- dimension lines
- engineering numbers
- grid coordinates
- technical annotations
- elevation values
- utility markings
- drafting guides
- repeated technical symbols
- tiny unreadable text
- stamps and engineering title blocks
- secondary lines that do not help indoor navigation

Text rules:
- keep only clearly readable labels that are useful to visitors
- remove small engineering labels and numbers
- do not invent store names
- do not invent room names
- do not rewrite unreadable text incorrectly

Visual style:
- clean modern mall-navigation map
- white or very light gray walking corridors
- shops and rooms in soft pastel colors
- clear dark-gray boundaries
- entrances and exits with subtle blue accents
- elevators and stairs clearly distinguishable
- outdoor landscaping in soft green
- bright uncluttered background
- simple, flat, accessible visual design
- easy to understand at a quick glance

Do not:
- add new shops, rooms, corridors or doors
- remove important navigation areas
- move walls, shops, stairs, elevators or entrances
- rotate or mirror the floor plan
- change the overall layout
- create a 3D scene
- create a realistic photograph
- draw a navigation route
- draw route arrows
- draw start or destination markers

The output must be suitable for displaying a colored route overlay
above it in an indoor-navigation web application.
"""


# =========================================================
# Processing result
# =========================================================

@dataclass
class MapImageProcessingResult:
    source_path: Path
    display_path: Path

    source_url: str
    display_url: str

    source_width: int
    source_height: int

    display_width: int
    display_height: int

    generation_method: str
    geometry_score: Optional[float] = None


# =========================================================
# Directory and file helpers
# =========================================================

def ensure_map_directories() -> None:
    SOURCE_DIR.mkdir(parents=True, exist_ok=True)
    DISPLAY_DIR.mkdir(parents=True, exist_ok=True)
    TEMP_DIR.mkdir(parents=True, exist_ok=True)


def delete_file_safely(file_path: Path) -> None:
    try:
        if file_path.exists():
            file_path.unlink()
    except OSError:
        pass


# =========================================================
# Save uploaded file
# =========================================================

async def save_upload_to_temporary_file(
    upload_file: UploadFile,
    map_id: str,
) -> Path:
    """
    Save the uploaded PDF/image temporarily.

    The file is read in chunks so large files are not loaded
    completely into memory.
    """

    ensure_map_directories()

    original_filename = upload_file.filename or ""
    extension = Path(original_filename).suffix.lower()

    if extension not in ALLOWED_EXTENSIONS:
        raise ValueError(
            "Unsupported map file type. "
            "Allowed types: PDF, PNG, JPG, JPEG, WEBP."
        )

    temporary_path = (
        TEMP_DIR / f"{map_id}_upload{extension}"
    )

    total_size = 0
    chunk_size = 1024 * 1024

    try:
        with temporary_path.open("wb") as output_file:
            while True:
                chunk = await upload_file.read(
                    chunk_size
                )

                if not chunk:
                    break

                total_size += len(chunk)

                if total_size > MAX_UPLOAD_SIZE_BYTES:
                    raise ValueError(
                        "Map file is too large. "
                        f"Maximum size is "
                        f"{MAX_UPLOAD_SIZE_MB} MB."
                    )

                output_file.write(chunk)

    except Exception:
        delete_file_safely(temporary_path)
        raise

    finally:
        await upload_file.close()

    if total_size == 0:
        delete_file_safely(temporary_path)

        raise ValueError(
            "The uploaded map file is empty."
        )

    return temporary_path


# =========================================================
# Normalize PDF/image to accurate PNG
# =========================================================

def normalize_uploaded_map(
    uploaded_path: Path,
    source_output_path: Path,
) -> Tuple[int, int]:
    """
    Convert the uploaded map to one accurate RGB PNG.

    PDF:
        Render the first page.

    Image:
        Correct EXIF rotation and save as PNG.
    """

    extension = uploaded_path.suffix.lower()

    if extension == ".pdf":
        return _convert_pdf_first_page_to_png(
            uploaded_path,
            source_output_path,
        )

    return _convert_image_to_png(
        uploaded_path,
        source_output_path,
    )


def _convert_pdf_first_page_to_png(
    pdf_path: Path,
    output_path: Path,
) -> Tuple[int, int]:
    document = None

    try:
        document = fitz.open(str(pdf_path))

        if document.page_count == 0:
            raise ValueError(
                "The uploaded PDF does not "
                "contain any pages."
            )

        page = document.load_page(0)

        pixmap = page.get_pixmap(
            dpi=PDF_RENDER_DPI,
            alpha=False,
        )

        pixmap.save(str(output_path))

    except Exception as error:
        delete_file_safely(output_path)

        raise ValueError(
            f"Could not convert the PDF map: {error}"
        ) from error

    finally:
        if document is not None:
            document.close()

    try:
        with Image.open(output_path) as image:
            normalized_image = image.convert("RGB")

            normalized_image.save(
                output_path,
                format="PNG",
                optimize=True,
            )

            return normalized_image.size

    except Exception as error:
        delete_file_safely(output_path)

        raise ValueError(
            "Could not read the converted "
            f"PDF image: {error}"
        ) from error


def _convert_image_to_png(
    image_path: Path,
    output_path: Path,
) -> Tuple[int, int]:
    try:
        with Image.open(image_path) as uploaded_image:
            corrected_image = ImageOps.exif_transpose(
                uploaded_image
            )

            normalized_image = (
                corrected_image.convert("RGB")
            )

            normalized_image.save(
                output_path,
                format="PNG",
                optimize=True,
            )

            return normalized_image.size

    except Exception as error:
        delete_file_safely(output_path)

        raise ValueError(
            "Could not read the uploaded "
            f"map image: {error}"
        ) from error


# =========================================================
# Build simplified architectural structure mask
# =========================================================

def _build_navigation_line_mask(
    gray_image: np.ndarray,
) -> np.ndarray:
    """
    Keep major walls, boundaries and long architectural lines.

    Remove a large portion of:
    - tiny engineering text
    - dimensions
    - isolated technical symbols
    - small drafting details
    """

    height, width = gray_image.shape[:2]
    total_pixels = width * height

    blurred_image = cv2.GaussianBlur(
        gray_image,
        (3, 3),
        0,
    )

    adaptive_dark_mask = cv2.adaptiveThreshold(
        blurred_image,
        255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY_INV,
        21,
        7,
    )

    _, otsu_dark_mask = cv2.threshold(
        blurred_image,
        0,
        255,
        cv2.THRESH_BINARY_INV
        + cv2.THRESH_OTSU,
    )

    dark_mask = cv2.bitwise_or(
        adaptive_dark_mask,
        otsu_dark_mask,
    )

    # Remove very small noise.
    dark_mask = cv2.morphologyEx(
        dark_mask,
        cv2.MORPH_OPEN,
        np.ones((2, 2), dtype=np.uint8),
        iterations=1,
    )

    # Extract long horizontal structures.
    horizontal_length = max(
        15,
        width // 220,
    )

    horizontal_kernel = cv2.getStructuringElement(
        cv2.MORPH_RECT,
        (horizontal_length, 1),
    )

    horizontal_lines = cv2.morphologyEx(
        dark_mask,
        cv2.MORPH_OPEN,
        horizontal_kernel,
        iterations=1,
    )

    # Extract long vertical structures.
    vertical_length = max(
        15,
        height // 180,
    )

    vertical_kernel = cv2.getStructuringElement(
        cv2.MORPH_RECT,
        (1, vertical_length),
    )

    vertical_lines = cv2.morphologyEx(
        dark_mask,
        cv2.MORPH_OPEN,
        vertical_kernel,
        iterations=1,
    )

    major_lines = cv2.bitwise_or(
        horizontal_lines,
        vertical_lines,
    )

    # Find remaining important connected structures,
    # including diagonal walls and larger shapes.
    component_count, labels, statistics, _ = (
        cv2.connectedComponentsWithStats(
            dark_mask,
            connectivity=8,
        )
    )

    filtered_components = np.zeros_like(
        dark_mask
    )

    minimum_area = max(
        18,
        int(total_pixels * 0.000003),
    )

    large_component_area = max(
        75,
        int(total_pixels * 0.000015),
    )

    minimum_line_length = max(
        28,
        int(min(width, height) * 0.009),
    )

    for component_id in range(
        1,
        component_count,
    ):
        area = int(
            statistics[
                component_id,
                cv2.CC_STAT_AREA,
            ]
        )

        component_width = int(
            statistics[
                component_id,
                cv2.CC_STAT_WIDTH,
            ]
        )

        component_height = int(
            statistics[
                component_id,
                cv2.CC_STAT_HEIGHT,
            ]
        )

        long_side = max(
            component_width,
            component_height,
        )

        short_side = max(
            1,
            min(
                component_width,
                component_height,
            ),
        )

        aspect_ratio = long_side / short_side

        keep_component = False

        # Thick architectural block.
        if area >= large_component_area:
            keep_component = True

        # Long thin wall or boundary.
        elif (
            area >= minimum_area
            and long_side >= minimum_line_length
            and aspect_ratio >= 2.0
        ):
            keep_component = True

        # Medium rectangular structural element.
        elif (
            area >= minimum_area * 3
            and (
                component_width
                >= minimum_line_length
                or component_height
                >= minimum_line_length
            )
        ):
            keep_component = True

        if keep_component:
            filtered_components[
                labels == component_id
            ] = 255

    navigation_mask = cv2.bitwise_or(
        major_lines,
        filtered_components,
    )

    # Reconnect nearby walls and boundaries.
    navigation_mask = cv2.morphologyEx(
        navigation_mask,
        cv2.MORPH_CLOSE,
        np.ones((3, 3), dtype=np.uint8),
        iterations=1,
    )

    # Slightly strengthen retained architecture.
    navigation_mask = cv2.dilate(
        navigation_mask,
        np.ones((2, 2), dtype=np.uint8),
        iterations=1,
    )

    return navigation_mask


# =========================================================
# Local simplified display map
# =========================================================

def create_local_display_map(
    source_path: Path,
    display_path: Path,
) -> Tuple[int, int]:
    """
    Produce a clean local navigation-style map.

    This is the fallback version used when:
    - no API key exists
    - OpenAI processing fails
    - AI geometry validation fails
    """

    source_image = cv2.imread(
        str(source_path),
        cv2.IMREAD_COLOR,
    )

    if source_image is None:
        raise ValueError(
            "Could not load the normalized source map."
        )

    height, width = source_image.shape[:2]
    total_pixels = width * height

    gray_image = cv2.cvtColor(
        source_image,
        cv2.COLOR_BGR2GRAY,
    )

    navigation_line_mask = (
        _build_navigation_line_mask(
            gray_image
        )
    )

    # Strengthen boundaries before discovering areas.
    line_mask_for_regions = cv2.dilate(
        navigation_line_mask,
        np.ones((2, 2), dtype=np.uint8),
        iterations=1,
    )

    free_space_mask = (
        line_mask_for_regions == 0
    ).astype(np.uint8)

    component_count, labels, statistics, _ = (
        cv2.connectedComponentsWithStats(
            free_space_mask,
            connectivity=8,
        )
    )

    # BGR colors because OpenCV uses BGR.
    background_color = (250, 250, 248)
    corridor_color = (249, 247, 243)
    outdoor_color = (231, 244, 234)
    wall_color = (58, 61, 67)

    pastel_palette = [
        (239, 232, 255),
        (247, 237, 222),
        (231, 246, 236),
        (233, 242, 252),
        (244, 233, 244),
        (234, 246, 246),
        (243, 239, 229),
        (231, 237, 252),
        (242, 235, 225),
        (237, 244, 231),
    ]

    display_map = np.full(
        (height, width, 3),
        background_color,
        dtype=np.uint8,
    )

    minimum_region_area = max(
        900,
        int(total_pixels * 0.00004),
    )

    maximum_room_area = int(
        total_pixels * 0.09
    )

    very_large_area = int(
        total_pixels * 0.20
    )

    outside_component = None

    if component_count > 1:
        component_areas = statistics[
            1:,
            cv2.CC_STAT_AREA,
        ]

        if len(component_areas) > 0:
            outside_component = (
                int(np.argmax(component_areas))
                + 1
            )

    palette_index = 0

    for component_id in range(
        1,
        component_count,
    ):
        area = int(
            statistics[
                component_id,
                cv2.CC_STAT_AREA,
            ]
        )

        if area < minimum_region_area:
            continue

        left = int(
            statistics[
                component_id,
                cv2.CC_STAT_LEFT,
            ]
        )

        top = int(
            statistics[
                component_id,
                cv2.CC_STAT_TOP,
            ]
        )

        component_width = int(
            statistics[
                component_id,
                cv2.CC_STAT_WIDTH,
            ]
        )

        component_height = int(
            statistics[
                component_id,
                cv2.CC_STAT_HEIGHT,
            ]
        )

        touches_border = (
            left <= 2
            or top <= 2
            or (
                left + component_width
                >= width - 2
            )
            or (
                top + component_height
                >= height - 2
            )
        )

        component_pixels = (
            labels == component_id
        )

        # Largest outside/background area.
        if (
            outside_component is not None
            and component_id
            == outside_component
        ):
            display_map[
                component_pixels
            ] = background_color

            continue

        # Outdoor or landscaping-like edge regions.
        if (
            touches_border
            and area < very_large_area
        ):
            display_map[
                component_pixels
            ] = outdoor_color

            continue

        # Large connected areas are normally corridors
        # or public walking spaces.
        if area >= maximum_room_area:
            display_map[
                component_pixels
            ] = corridor_color

            continue

        # Smaller enclosed areas are shops or rooms.
        selected_color = pastel_palette[
            palette_index
            % len(pastel_palette)
        ]

        display_map[
            component_pixels
        ] = selected_color

        palette_index += 1

    # Draw retained structural lines.
    display_map[
        navigation_line_mask > 0
    ] = wall_color

    # Softly smooth region fills.
    smoothed_map = cv2.GaussianBlur(
        display_map,
        (3, 3),
        0,
    )

    # Restore walls after smoothing.
    final_map = smoothed_map.copy()

    final_map[
        navigation_line_mask > 0
    ] = wall_color

    saved = cv2.imwrite(
        str(display_path),
        final_map,
    )

    if not saved:
        raise ValueError(
            "Could not save the local display map."
        )

    return width, height


# =========================================================
# OpenAI output dimensions
# =========================================================

def _round_to_multiple_of_16(
    value: float,
) -> int:
    rounded_value = int(
        round(value / 16.0) * 16
    )

    return max(
        16,
        rounded_value,
    )


def calculate_openai_dimensions(
    width: int,
    height: int,
) -> Optional[Tuple[int, int]]:
    """
    Calculate a GPT Image 2-compatible output size.

    Requirements:
    - dimensions divisible by 16
    - aspect ratio between 1:3 and 3:1
    - maximum edge up to 3840
    - use configured maximum edge by default
    """

    if width <= 0 or height <= 0:
        return None

    long_edge = max(width, height)
    short_edge = min(width, height)

    if short_edge == 0:
        return None

    aspect_ratio = long_edge / short_edge

    if aspect_ratio > 3.0:
        return None

    desired_max_edge = min(
        OPENAI_IMAGE_MAX_EDGE,
        3840,
    )

    resize_scale = min(
        1.0,
        desired_max_edge / long_edge,
    )

    output_width = _round_to_multiple_of_16(
        width * resize_scale
    )

    output_height = _round_to_multiple_of_16(
        height * resize_scale
    )

    if max(
        output_width,
        output_height,
    ) > 3840:
        return None

    final_short_edge = min(
        output_width,
        output_height,
    )

    if final_short_edge == 0:
        return None

    final_aspect_ratio = (
        max(output_width, output_height)
        / final_short_edge
    )

    if final_aspect_ratio > 3.0:
        return None

    return output_width, output_height


# =========================================================
# Prepare AI input
# =========================================================

def _prepare_openai_input(
    input_image_path: Path,
    output_path: Path,
    output_width: int,
    output_height: int,
) -> None:
    with Image.open(
        input_image_path
    ) as image:
        prepared_image = image.convert("RGB")

        prepared_image = prepared_image.resize(
            (
                output_width,
                output_height,
            ),
            Image.Resampling.LANCZOS,
        )

        prepared_image.save(
            output_path,
            format="PNG",
            optimize=True,
        )


# =========================================================
# Generate AI navigation map
# =========================================================

def generate_openai_display_map(
    input_path: Path,
    candidate_output_path: Path,
    source_width: int,
    source_height: int,
    api_width: int,
    api_height: int,
) -> None:
    api_key = os.getenv("OPENAI_API_KEY")

    if not api_key:
        raise ValueError(
            "OPENAI_API_KEY is not configured."
        )

    if OpenAI is None:
        raise ValueError(
            "The OpenAI Python package "
            "is not installed."
        )

    client = OpenAI(
        api_key=api_key
    )

    requested_size = (
        f"{api_width}x{api_height}"
    )

    with input_path.open("rb") as image_file:
        result = client.images.edit(
            model=OPENAI_IMAGE_MODEL,
            image=image_file,
            prompt=MAP_COLORING_PROMPT,
            size=requested_size,
            quality=OPENAI_IMAGE_QUALITY,
            output_format="png",
            background="opaque",
            n=1,
        )

    if not result.data:
        raise ValueError(
            "OpenAI returned no image result."
        )

    image_base64 = (
        result.data[0].b64_json
    )

    if not image_base64:
        raise ValueError(
            "OpenAI returned an empty image."
        )

    try:
        image_bytes = base64.b64decode(
            image_base64
        )

    except Exception as error:
        raise ValueError(
            "Could not decode the OpenAI "
            f"image result: {error}"
        ) from error

    raw_candidate_path = (
        candidate_output_path.parent
        / (
            f"{candidate_output_path.stem}"
            "_raw.png"
        )
    )

    try:
        raw_candidate_path.write_bytes(
            image_bytes
        )

        with Image.open(
            raw_candidate_path
        ) as ai_image:
            normalized_ai_image = (
                ai_image.convert("RGB")
            )

            # Restore the exact source canvas dimensions
            # so route coordinates can use the same ratio.
            normalized_ai_image = (
                normalized_ai_image.resize(
                    (
                        source_width,
                        source_height,
                    ),
                    Image.Resampling.LANCZOS,
                )
            )

            normalized_ai_image.save(
                candidate_output_path,
                format="PNG",
                optimize=True,
            )

    finally:
        delete_file_safely(
            raw_candidate_path
        )


# =========================================================
# Validate navigation geometry
# =========================================================

def calculate_geometry_preservation_score(
    source_path: Path,
    candidate_path: Path,
) -> float:
    """
    Check whether the AI retained the important navigation structure.

    Technical text and dimension lines are intentionally not required.
    Only the simplified structural mask is used for validation.
    """

    source_gray = cv2.imread(
        str(source_path),
        cv2.IMREAD_GRAYSCALE,
    )

    candidate_gray = cv2.imread(
        str(candidate_path),
        cv2.IMREAD_GRAYSCALE,
    )

    if (
        source_gray is None
        or candidate_gray is None
    ):
        return 0.0

    source_height, source_width = (
        source_gray.shape
    )

    if (
        candidate_gray.shape
        != source_gray.shape
    ):
        candidate_gray = cv2.resize(
            candidate_gray,
            (
                source_width,
                source_height,
            ),
            interpolation=cv2.INTER_AREA,
        )

    # Only important architectural structure.
    source_structure = (
        _build_navigation_line_mask(
            source_gray
        )
    )

    candidate_edges = cv2.Canny(
        candidate_gray,
        55,
        150,
    )

    comparison_kernel = np.ones(
        (7, 7),
        dtype=np.uint8,
    )

    dilated_source_structure = cv2.dilate(
        source_structure,
        comparison_kernel,
        iterations=1,
    )

    dilated_candidate_edges = cv2.dilate(
        candidate_edges,
        comparison_kernel,
        iterations=1,
    )

    source_pixels = (
        source_structure > 0
    )

    candidate_pixels = (
        candidate_edges > 0
    )

    source_count = int(
        np.count_nonzero(
            source_pixels
        )
    )

    candidate_count = int(
        np.count_nonzero(
            candidate_pixels
        )
    )

    if source_count == 0:
        return 0.0

    recall_matches = np.logical_and(
        source_pixels,
        dilated_candidate_edges > 0,
    )

    structure_recall = (
        np.count_nonzero(
            recall_matches
        )
        / source_count
    )

    if candidate_count == 0:
        candidate_precision = 0.0

    else:
        precision_matches = np.logical_and(
            candidate_pixels,
            dilated_source_structure > 0,
        )

        candidate_precision = (
            np.count_nonzero(
                precision_matches
            )
            / candidate_count
        )

    # Structure recall is more important because the AI is
    # intentionally expected to remove technical clutter.
    final_score = (
        0.85 * structure_recall
        + 0.15 * candidate_precision
    )

    return round(
        float(final_score),
        4,
    )


# =========================================================
# Complete processing pipeline
# =========================================================

def process_uploaded_map(
    uploaded_path: Path,
    map_id: str,
    use_openai: bool = True,
) -> MapImageProcessingResult:
    """
    Full Quick Route processing pipeline.

    1. Convert PDF/image to accurate source PNG.
    2. Create a simplified local navigation map.
    3. Optionally create a better AI navigation map.
    4. Validate the important architecture.
    5. Use AI only if it passes validation.
    """

    ensure_map_directories()

    source_output_path = (
        SOURCE_DIR / f"{map_id}.png"
    )

    display_output_path = (
        DISPLAY_DIR / f"{map_id}.png"
    )

    local_display_path = (
        TEMP_DIR / f"{map_id}_local.png"
    )

    openai_input_path = (
        TEMP_DIR
        / f"{map_id}_openai_input.png"
    )

    openai_candidate_path = (
        TEMP_DIR
        / f"{map_id}_openai_candidate.png"
    )

    geometry_score: Optional[float] = None
    generation_method = "local"

    try:
        source_width, source_height = (
            normalize_uploaded_map(
                uploaded_path,
                source_output_path,
            )
        )

        # Always create a safe local version.
        create_local_display_map(
            source_output_path,
            local_display_path,
        )

        shutil.copyfile(
            local_display_path,
            display_output_path,
        )

        api_dimensions = (
            calculate_openai_dimensions(
                source_width,
                source_height,
            )
        )

        can_use_openai = (
            use_openai
            and bool(
                os.getenv("OPENAI_API_KEY")
            )
            and OpenAI is not None
            and api_dimensions is not None
        )

        if can_use_openai:
            try:
                api_width, api_height = (
                    api_dimensions
                )

                # Send the accurate original map to AI.
                _prepare_openai_input(
                    source_output_path,
                    openai_input_path,
                    api_width,
                    api_height,
                )

                generate_openai_display_map(
                    input_path=openai_input_path,
                    candidate_output_path=(
                        openai_candidate_path
                    ),
                    source_width=source_width,
                    source_height=source_height,
                    api_width=api_width,
                    api_height=api_height,
                )

                geometry_score = (
                    calculate_geometry_preservation_score(
                        source_output_path,
                        openai_candidate_path,
                    )
                )

                if (
                    geometry_score
                    >= AI_EDGE_SCORE_THRESHOLD
                ):
                    shutil.copyfile(
                        openai_candidate_path,
                        display_output_path,
                    )

                    generation_method = "hybrid"

                else:
                    print(
                        "AI map was rejected because "
                        "the geometry score was too low:",
                        geometry_score,
                    )

                    generation_method = "local"

            except Exception as openai_error:
                # API failure must never block the map upload.
                print(
                    "OpenAI map processing failed. "
                    "Using the local display map:",
                    str(openai_error),
                )

                generation_method = "local"

        with Image.open(
            display_output_path
        ) as final_display_image:
            display_width, display_height = (
                final_display_image.size
            )

        return MapImageProcessingResult(
            source_path=source_output_path,
            display_path=display_output_path,

            source_url=(
                "/uploads/maps/source/"
                f"{source_output_path.name}"
            ),

            display_url=(
                "/uploads/maps/display/"
                f"{display_output_path.name}"
            ),

            source_width=source_width,
            source_height=source_height,

            display_width=display_width,
            display_height=display_height,

            generation_method=generation_method,
            geometry_score=geometry_score,
        )

    except Exception:
        delete_file_safely(
            source_output_path
        )

        delete_file_safely(
            display_output_path
        )

        raise

    finally:
        delete_file_safely(
            local_display_path
        )

        delete_file_safely(
            openai_input_path
        )

        delete_file_safely(
            openai_candidate_path
        )

        delete_file_safely(
            uploaded_path
        )