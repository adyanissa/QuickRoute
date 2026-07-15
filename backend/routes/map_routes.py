from __future__ import annotations

import asyncio
import shutil
import uuid
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from beanie import PydanticObjectId
from fastapi import (
    APIRouter,
    BackgroundTasks,
    File,
    Form,
    HTTPException,
    UploadFile,
    status,
)

from models.map_model import Map
from schemas.map_schema import (
    MapCreate,
    MapProcessingResponse,
    MapResponse,
    MapUpdate,
)
from services.map_image_service import (
    DISPLAY_DIR,
    SOURCE_DIR,
    TEMP_DIR,
    delete_file_safely,
    process_uploaded_map,
    save_upload_to_temporary_file,
)


router = APIRouter(
    prefix="/api/maps",
    tags=["Map Management"],
)


# ---------------------------------------------------------
# Helpers
# ---------------------------------------------------------

def clean_optional_text(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None

    cleaned_value = value.strip()
    return cleaned_value if cleaned_value else None


def map_to_response(map_item: Map) -> MapResponse:
    return MapResponse(
        id=str(map_item.id),
        title=map_item.title,
        campus=map_item.campus,
        address=map_item.address,
        description=map_item.description,

        image_url=map_item.image_url,
        source_image_url=map_item.source_image_url,
        display_image_url=map_item.display_image_url,

        source_filename=map_item.source_filename,
        source_content_type=map_item.source_content_type,

        processing_status=map_item.processing_status,
        processing_progress=map_item.processing_progress,
        processing_error=map_item.processing_error,
        generation_method=map_item.generation_method,

        source_width=map_item.source_width,
        source_height=map_item.source_height,
        display_width=map_item.display_width,
        display_height=map_item.display_height,

        scale=map_item.scale,
        floor_scales=map_item.floor_scales,

        is_current=map_item.is_current,

        processed_at=map_item.processed_at,
        created_at=map_item.created_at,
        updated_at=map_item.updated_at,
    )


def map_to_processing_response(
    map_item: Map,
) -> MapProcessingResponse:
    return MapProcessingResponse(
        id=str(map_item.id),
        processing_status=map_item.processing_status,
        processing_progress=map_item.processing_progress,
        processing_error=map_item.processing_error,
        generation_method=map_item.generation_method,
        source_image_url=map_item.source_image_url,
        display_image_url=map_item.display_image_url,
        processed_at=map_item.processed_at,
    )


async def set_map_as_current(map_item: Map) -> None:
    """
    Make this map current and deactivate all other current maps.
    """

    await Map.find(
        Map.is_current == True
    ).update(
        {
            "$set": {
                "is_current": False,
            }
        }
    )

    map_item.is_current = True
    map_item.updated_at = datetime.utcnow()

    await map_item.save()


def remove_map_files(map_id: str) -> None:
    """
    Delete generated source, display and temporary files.
    """

    delete_file_safely(
        SOURCE_DIR / f"{map_id}.png"
    )

    delete_file_safely(
        DISPLAY_DIR / f"{map_id}.png"
    )

    for temporary_file in TEMP_DIR.glob(
        f"{map_id}_*"
    ):
        delete_file_safely(temporary_file)


# ---------------------------------------------------------
# Background map processing
# ---------------------------------------------------------

async def process_map_in_background(
    map_id: str,
    uploaded_path_string: str,
    use_openai: bool,
) -> None:
    """
    Process the uploaded map after the upload endpoint responds.

    The CPU-heavy image processing runs in another thread so it
    does not block the FastAPI event loop.
    """

    uploaded_path = Path(uploaded_path_string)

    try:
        map_item = await Map.get(
            PydanticObjectId(map_id)
        )

        if not map_item:
            delete_file_safely(uploaded_path)
            return

        map_item.processing_status = "processing"
        map_item.processing_progress = 15
        map_item.processing_error = None
        map_item.updated_at = datetime.utcnow()

        await map_item.save()

        result = await asyncio.to_thread(
            process_uploaded_map,
            uploaded_path,
            map_id,
            use_openai,
        )

        # Read the map again in case it was deleted while processing.
        map_item = await Map.get(
            PydanticObjectId(map_id)
        )

        if not map_item:
            remove_map_files(map_id)
            return

        map_item.source_image_url = result.source_url
        map_item.display_image_url = result.display_url

        # Keep the old image field working with old frontend code.
        map_item.image_url = result.display_url

        map_item.source_width = result.source_width
        map_item.source_height = result.source_height

        map_item.display_width = result.display_width
        map_item.display_height = result.display_height

        map_item.generation_method = (
            result.generation_method
        )

        map_item.processing_status = "completed"
        map_item.processing_progress = 100
        map_item.processing_error = None

        map_item.processed_at = datetime.utcnow()
        map_item.updated_at = datetime.utcnow()

        await map_item.save()

    except Exception as error:
        try:
            failed_map = await Map.get(
                PydanticObjectId(map_id)
            )

            if failed_map:
                failed_map.processing_status = "failed"
                failed_map.processing_progress = 0
                failed_map.processing_error = str(error)
                failed_map.updated_at = datetime.utcnow()

                await failed_map.save()

        except Exception as database_error:
            print(
                "Could not save map processing failure:",
                str(database_error),
            )

        print(
            f"Map processing failed for map {map_id}:",
            str(error),
        )

    finally:
        delete_file_safely(uploaded_path)


# ---------------------------------------------------------
# Normal JSON map creation
# ---------------------------------------------------------

@router.post(
    "",
    response_model=MapResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_map(map_data: MapCreate):
    legacy_image_url = (
        map_data.image_url
        or map_data.display_image_url
        or map_data.source_image_url
    )

    already_has_display_image = bool(
        map_data.display_image_url
    )

    new_map = Map(
        title=map_data.title.strip(),
        campus=clean_optional_text(
            map_data.campus
        ),
        address=clean_optional_text(
            map_data.address
        ),
        description=clean_optional_text(
            map_data.description
        ),

        image_url=legacy_image_url,
        source_image_url=map_data.source_image_url,
        display_image_url=map_data.display_image_url,

        processing_status=(
            "completed"
            if already_has_display_image
            else "not_started"
        ),
        processing_progress=(
            100
            if already_has_display_image
            else 0
        ),
        processed_at=(
            datetime.utcnow()
            if already_has_display_image
            else None
        ),

        scale=map_data.scale,
        floor_scales=map_data.floor_scales,

        is_current=False,
    )

    await new_map.insert()
    await set_map_as_current(new_map)

    return map_to_response(new_map)


# ---------------------------------------------------------
# Upload PDF/image and automatically process it
# Important: this route must be before /{map_id}
# ---------------------------------------------------------

@router.post(
    "/upload",
    response_model=MapResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_map(
    background_tasks: BackgroundTasks,

    file: UploadFile = File(...),

    title: str = Form(...),
    campus: Optional[str] = Form(default=None),
    address: Optional[str] = Form(default=None),
    description: Optional[str] = Form(default=None),

    scale: float = Form(default=1.0, gt=0),

    # True means:
    # try OpenAI when an API key exists.
    # Otherwise local processing is used automatically.
    use_openai: bool = Form(default=True),
):
    cleaned_title = title.strip()

    if len(cleaned_title) < 2:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "Map title must contain at least "
                "2 characters."
            ),
        )

    source_filename = (
        file.filename or "uploaded-map"
    )

    source_content_type = (
        file.content_type
        or "application/octet-stream"
    )

    # Temporary token is used before MongoDB creates the map ID.
    upload_token = uuid.uuid4().hex

    try:
        uploaded_path = (
            await save_upload_to_temporary_file(
                upload_file=file,
                map_id=upload_token,
            )
        )

    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(error),
        ) from error

    except Exception as error:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=(
                f"Could not save the uploaded map: {error}"
            ),
        ) from error

    try:
        new_map = Map(
            title=cleaned_title,
            campus=clean_optional_text(campus),
            address=clean_optional_text(address),
            description=clean_optional_text(
                description
            ),

            image_url=None,
            source_image_url=None,
            display_image_url=None,

            source_filename=source_filename,
            source_content_type=source_content_type,

            processing_status="pending",
            processing_progress=0,
            processing_error=None,
            generation_method=None,

            source_width=None,
            source_height=None,
            display_width=None,
            display_height=None,

            scale=scale,
            floor_scales={},

            is_current=False,
        )

        await new_map.insert()
        await set_map_as_current(new_map)

    except Exception as error:
        delete_file_safely(uploaded_path)

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=(
                f"Could not create the map record: {error}"
            ),
        ) from error

    background_tasks.add_task(
        process_map_in_background,
        str(new_map.id),
        str(uploaded_path),
        use_openai,
    )

    return map_to_response(new_map)


# ---------------------------------------------------------
# Get all/current maps
# ---------------------------------------------------------

@router.get(
    "",
    response_model=List[MapResponse],
)
async def get_all_maps():
    maps = await Map.find_all().to_list()

    return [
        map_to_response(map_item)
        for map_item in maps
    ]


@router.get(
    "/current",
    response_model=MapResponse,
)
async def get_current_map():
    current_map = await Map.find_one(
        Map.is_current == True
    )

    if not current_map:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No current map found",
        )

    return map_to_response(current_map)


# ---------------------------------------------------------
# Processing status
# Must also be before /{map_id}
# ---------------------------------------------------------

@router.get(
    "/{map_id}/processing-status",
    response_model=MapProcessingResponse,
)
async def get_map_processing_status(
    map_id: PydanticObjectId,
):
    map_item = await Map.get(map_id)

    if not map_item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Map not found",
        )

    return map_to_processing_response(map_item)


# ---------------------------------------------------------
# Retry processing
# ---------------------------------------------------------

@router.post(
    "/{map_id}/retry-processing",
    response_model=MapProcessingResponse,
)
async def retry_map_processing(
    map_id: PydanticObjectId,
    background_tasks: BackgroundTasks,
    use_openai: bool = True,
):
    map_item = await Map.get(map_id)

    if not map_item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Map not found",
        )

    if map_item.processing_status in {
        "pending",
        "processing",
    }:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "This map is already being processed."
            ),
        )

    source_path = (
        SOURCE_DIR / f"{map_id}.png"
    )

    if not source_path.exists():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "The original processed source image "
                "does not exist. Upload the map again."
            ),
        )

    retry_input_path = (
        TEMP_DIR / f"{map_id}_retry_input.png"
    )

    try:
        shutil.copyfile(
            source_path,
            retry_input_path,
        )

    except Exception as error:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=(
                f"Could not prepare the map for retry: "
                f"{error}"
            ),
        ) from error

    map_item.processing_status = "pending"
    map_item.processing_progress = 0
    map_item.processing_error = None
    map_item.generation_method = None
    map_item.processed_at = None
    map_item.updated_at = datetime.utcnow()

    await map_item.save()

    background_tasks.add_task(
        process_map_in_background,
        str(map_item.id),
        str(retry_input_path),
        use_openai,
    )

    return map_to_processing_response(map_item)


# ---------------------------------------------------------
# Get map by ID
# ---------------------------------------------------------

@router.get(
    "/{map_id}",
    response_model=MapResponse,
)
async def get_map_by_id(
    map_id: PydanticObjectId,
):
    map_item = await Map.get(map_id)

    if not map_item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Map not found",
        )

    return map_to_response(map_item)


# ---------------------------------------------------------
# Update map
# ---------------------------------------------------------

@router.put(
    "/{map_id}",
    response_model=MapResponse,
)
async def update_map(
    map_id: PydanticObjectId,
    map_data: MapUpdate,
):
    map_item = await Map.get(map_id)

    if not map_item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Map not found",
        )

    update_data = map_data.model_dump(
        exclude_unset=True
    )

    if "title" in update_data:
        update_data["title"] = (
            update_data["title"].strip()
        )

    for optional_field in [
        "campus",
        "address",
        "description",
    ]:
        if optional_field in update_data:
            update_data[optional_field] = (
                clean_optional_text(
                    update_data[optional_field]
                )
            )

    should_be_current = (
        update_data.pop(
            "is_current",
            None,
        )
    )

    for field, value in update_data.items():
        setattr(map_item, field, value)

    # Keep compatibility with old frontend code.
    if (
        "display_image_url" in update_data
        and map_item.display_image_url
    ):
        map_item.image_url = (
            map_item.display_image_url
        )

    map_item.updated_at = datetime.utcnow()

    if should_be_current is True:
        await set_map_as_current(map_item)

    else:
        if should_be_current is False:
            map_item.is_current = False

        await map_item.save()

    return map_to_response(map_item)


# ---------------------------------------------------------
# Delete map
# ---------------------------------------------------------

@router.delete(
    "/{map_id}",
    status_code=status.HTTP_200_OK,
)
async def delete_map(
    map_id: PydanticObjectId,
):
    map_item = await Map.get(map_id)

    if not map_item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Map not found",
        )

    was_current = map_item.is_current

    await map_item.delete()

    remove_map_files(str(map_id))

    # When the current map is deleted, select another map.
    if was_current:
        replacement_map = await Map.find_one()

        if replacement_map:
            await set_map_as_current(
                replacement_map
            )

    return {
        "message": "Map deleted successfully",
    }