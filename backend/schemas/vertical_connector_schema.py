from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


class VerticalConnectorCreate(BaseModel):
    building_id: str = Field(..., min_length=1)
    map_group_id: str = Field(..., min_length=1)

    connector_code: Optional[str] = Field(default=None, max_length=40)
    name: str = Field(..., min_length=2, max_length=120)
    connector_type: str = Field(..., pattern="^(elevator|stairs|escalator|ramp)$")

    is_bidirectional: bool = True
    is_accessible: bool = True

    wait_time_seconds: float = Field(default=30.0, ge=0)
    seconds_per_floor: float = Field(default=6.0, ge=0)
    distance_per_floor_meters: float = Field(default=4.0, ge=0)

    description: Optional[str] = None


class VerticalConnectorUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=2, max_length=120)
    is_bidirectional: Optional[bool] = None
    is_accessible: Optional[bool] = None
    is_active: Optional[bool] = None
    wait_time_seconds: Optional[float] = Field(default=None, ge=0)
    seconds_per_floor: Optional[float] = Field(default=None, ge=0)
    distance_per_floor_meters: Optional[float] = Field(default=None, ge=0)
    description: Optional[str] = None


class ConnectorStopCreate(BaseModel):
    """
    Places (or reuses) this connector's stop on ONE floor. map_id/x/y are
    always taken from an explicit admin click on that floor's own map
    image — never inferred from another floor's coordinates.
    """

    map_id: str = Field(..., min_length=1)
    x: float
    y: float
    name: Optional[str] = None
    # "off" never auto-connects to the local corridor graph; "nearest"
    # (default) connects to the single closest valid same-floor neighbor,
    # matching the same auto-connect semantics used for Room placement.
    auto_connect: str = Field(default="nearest", pattern="^(off|nearest|all_valid)$")


class ConnectorStopResponse(BaseModel):
    route_point_id: str
    map_id: str
    floor: Optional[int] = None
    x: float
    y: float
    name: str
    # True once this stop has at least one same-floor walkway edge to the
    # local corridor graph — the connector is not usable through this
    # floor until this is True (see PHASE 5 requirement).
    connected_to_floor_graph: bool = False


class VerticalConnectorResponse(BaseModel):
    id: str
    building_id: str
    map_group_id: str
    connector_code: str
    name: str
    connector_type: str
    is_bidirectional: bool
    is_accessible: bool
    is_active: bool
    wait_time_seconds: float
    seconds_per_floor: float
    distance_per_floor_meters: float
    description: Optional[str] = None
    stops: List[ConnectorStopResponse] = Field(default_factory=list)
    # True only when every stop is connected to its own floor's corridor
    # graph AND there are at least two stops — mirrors the "Status:
    # Connected" / not-yet-usable admin UI requirement.
    is_fully_connected: bool = False
    created_at: datetime
    updated_at: datetime
