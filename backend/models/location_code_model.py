from datetime import datetime, timezone
from typing import Optional

from beanie import Document
from pydantic import Field
from pymongo import IndexModel


class LocationCode(Document):
    """
    A physical QR/barcode label mapped to one exact RoutePoint. Scanning the
    code (or typing it in) lets an end user start navigation from that exact
    point instead of always defaulting to the map's first entrance.
    """

    code: str = Field(..., min_length=1, max_length=64)

    building_id: str
    map_id: str
    route_point_id: str

    label: Optional[str] = None
    is_active: bool = True

    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    class Settings:
        name = "location_codes"
        indexes = [
            # Supports exactly one query:
            #
            #   LocationCode.find_one(LocationCode.code == code)
            #   -> {"code": "<CODE>"}
            #   routes/location_code_routes.py :: resolve_location_code
            #   GET /api/location-codes/resolve/{code}
            #
            # That is the anonymous entry point of the whole product — a
            # scanned QR (/?locationCode=CODE) and a hand-typed code both
            # land there — and it was a full collection scan.
            #
            # DELIBERATELY NOT UNIQUE. The resolver's behaviour, the stored
            # codes and the generation logic are all unchanged by this; a
            # unique constraint would be a data-integrity decision that
            # must first be validated against the existing records, and is
            # explicitly out of scope for this pass.
            IndexModel("code"),
        ]
