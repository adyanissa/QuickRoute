from datetime import datetime
from typing import Optional

from beanie import Document
from pydantic import Field
from pymongo import IndexModel


CONNECTOR_TYPES = ("elevator", "stairs", "escalator", "ramp")


class VerticalConnector(Document):
    """
    A single physical connector (one elevator, one stairwell, one
    escalator, one ramp) that links two or more floors of the SAME
    MapGroup. This document stores only the connector's own metadata —
    name, type, accessibility, cost settings. It never stores per-floor
    coordinates itself; each serviced floor is a real RoutePoint (see
    RoutePoint.connector_id/connector_code) placed by an admin directly on
    that floor's own map image, and every pair of those stops is linked by
    an explicit RouteEdge transition (RouteEdge.connector_id) — see
    services/vertical_connector_service.py. A connector with zero or one
    stop is metadata-only and cannot be routed through yet; this is a
    normal, expected intermediate state while an admin is still placing
    its stops, not an error condition.

    Never inferred/auto-created from matching x/y coordinates across
    floors — every stop is placed by an explicit admin click on the real
    floor image it belongs to.
    """

    building_id: str
    map_group_id: str

    # Stable, unique, admin-facing identifier (e.g. "ELEVATOR-A"),
    # normalized (trimmed/uppercased) the same way MapGroup.code is (see
    # services/vertical_connector_service.py) — never regenerated once the
    # connector exists.
    connector_code: str
    name: str
    connector_type: str  # elevator | stairs | escalator | ramp

    # Whether travel is allowed in both directions. Elevators/ramps are
    # normally bidirectional; an escalator is frequently one-way — when
    # False, only forward travel from the FIRST stop (by floor order at
    # creation time; see service layer) is generated. Stairs are
    # bidirectional unless explicitly configured otherwise.
    is_bidirectional: bool = True

    # Whether a wheelchair user can use this connector at all. Elevators
    # and accessible ramps default True; stairs and non-accessible
    # escalators/ramps must be explicitly created with this False so
    # accessible-mode routing can exclude them.
    is_accessible: bool = True

    is_active: bool = True

    # Cost-model inputs (see logic/routing_cost.py) — configurable per
    # connector rather than hard-coded globally, with sane defaults so an
    # admin who doesn't touch these still gets a usable estimate.
    wait_time_seconds: float = Field(default=30.0, ge=0)
    seconds_per_floor: float = Field(default=6.0, ge=0)
    distance_per_floor_meters: float = Field(default=4.0, ge=0)

    description: Optional[str] = None

    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    class Settings:
        name = "vertical_connectors"
        indexes = [
            IndexModel("connector_code", unique=True),
        ]
