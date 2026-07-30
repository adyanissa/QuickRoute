from datetime import datetime
from typing import Optional

from beanie import Document
from pydantic import Field


class RouteEdge(Document):
    # The edge's "owning" map — for a normal walkway edge this is the one
    # map both points belong to. For a cross-floor stairs/elevator
    # transition edge (see route_edge_routes.calculate_edge_distance), this
    # is specifically the FROM point's map; `to_map_id` below records the
    # other floor's map. Every existing map_id-scoped query (RouteEdge
    # lookups, cascade-delete-on-map-delete, etc.) keeps working exactly as
    # before since this field's meaning for same-floor edges is unchanged.
    map_id: str

    # Only set (non-None) for a cross-floor transition edge whose two
    # points live on two different Map documents within the same
    # map_group_id — i.e. exactly the vertical stairs/elevator/escalator
    # case this task must prepare the model for. None for every ordinary
    # same-map walkway/stairs/elevator edge, which is everything created
    # before this feature and the overwhelming majority of edges after it.
    to_map_id: Optional[str] = None

    from_point_id: str
    to_point_id: str

    # walkway / stairs / elevator / escalator / ramp
    edge_type: str = "walkway"

    # final calculated distance in meters
    distance: float

    # optional manual distance for stairs/elevator
    distance_override: Optional[float] = None

    # Set only for a transition edge generated between two stops of the
    # same VerticalConnector (see models/vertical_connector_model.py and
    # services/vertical_connector_service.py). None for every ordinary
    # same-floor walkway edge and for a legacy manually-created
    # stairs/elevator edge that predates connectors. Lets the multi-floor
    # router and turn-by-turn instruction generator recognize "this edge
    # is a named connector transition" without guessing from edge_type
    # alone, and lets connector deletion find exactly the edges it owns.
    connector_id: Optional[str] = None

    # Total travel cost of this edge in seconds, independent of `distance`
    # (which stays a physical-distance/manual-override field). For a
    # same-floor walkway this is normally left unset and callers estimate
    # walking time from distance instead (see logic/routing_cost.py); for
    # a connector transition edge this is the authoritative wait+travel
    # time (e.g. elevator wait + per-floor travel), since "distance" alone
    # is a poor proxy for how long an elevator ride actually takes.
    estimated_time_seconds: Optional[float] = None

    is_bidirectional: bool = True
    is_accessible: bool = True
    is_active: bool = True

    description: Optional[str] = None

    # Nested-room navigation (Approved Semantic Analysis -> Automatic
    # Destinations spec, Section 11). None for every ordinary walkway edge
    # (ALL edges created before this feature, and every ordinary
    # Room/Store <-> Hallway/Junction connection created after it). Set to
    # "nested" ONLY for the one edge connecting an approved inner Room's
    # destination RoutePoint to its approved outer (pass-through) Room's
    # destination RoutePoint — created exclusively by
    # services/semantic_destination_service.py after explicit admin
    # confirmation of the parent/child relationship. This is metadata
    # only: edge_type stays "walkway" and distance is calculated with the
    # exact same calculate_edge_distance() every other walkway edge uses —
    # this field exists purely so callers can distinguish an intentional,
    # approved nested-access connection from what would otherwise look
    # like an accidental Room-to-Room edge, without introducing a new edge
    # type that would require touching distance/Dijkstra/edge-usability
    # logic.
    access_relation: Optional[str] = None

    # Same generation-provenance fields as RoutePoint — see that model for
    # why this matters for safe regeneration.
    is_auto_generated: bool = False
    generation_method: Optional[str] = None
    generation_confidence: Optional[float] = None
    generation_version: Optional[int] = None

    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    class Settings:
        name = "route_edges"