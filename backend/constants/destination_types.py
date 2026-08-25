"""
Canonical Room/Destination type list — the single source of truth for
which `Room.room_type` machine values are currently offered/accepted.

QuickRoute is not hospital-only: this list intentionally spans shopping
malls, hospitals, universities, office buildings, and general public
buildings, replacing the old 10-value hospital-oriented list (emergency,
room, clinic, office, lab, waiting_area, reception, imaging, pharmacy,
operating).

Architecture decision — elevators/stairs/escalators/ramps are
DELIBERATELY NOT included here. This codebase already models vertical
transitions as VerticalConnector documents (see
models/vertical_connector_model.py, routes/vertical_connector_routes.py) —
a connector has its own CRUD, its own per-floor "stop" RoutePoints, and
its own transition-edge graph logic. Adding "elevator"/"stairs" as a Room
type would create a second, parallel, unconnected representation of the
same physical thing (a Room with no route_point tie to the real connector
graph), which is exactly the "duplicate connector record" the task
explicitly warns against. Anyone needing to search for "the elevator" as
a destination should search VerticalConnector data, not Room data — that
integration is a separate, future enhancement, not part of this change.

Preserving existing data: every OLD value except "operating" maps
one-to-one onto a current canonical value with the exact same spelling
(emergency, room, clinic, office, lab, waiting_area, reception, imaging,
pharmacy are themselves still canonical). "operating" has no exact match
(the new canonical medical name is "operating_room") — rather than
silently rewriting already-stored Room documents (forbidden — "do not
silently convert an existing value to another type"), "operating" is kept
as an explicitly accepted LEGACY_ALIAS so it round-trips safely forever;
it is just never offered as a new selection in the UI (the UI offers
"operating_room" instead going forward).
"""

# Ordered so the frontend can render these as <optgroup> sections in a
# stable, sensible order (General first, Medical/Retail/Public/Navigation/
# Education after) without hard-coding the order twice.
DESTINATION_TYPE_GROUPS: dict[str, list[str]] = {
    "general": [
        "room",
        "office",
        "reception",
        "waiting_area",
        "information_desk",
        "service",
        "other",
    ],
    "medical": [
        "emergency",
        "clinic",
        "lab",
        "imaging",
        "pharmacy",
        "operating_room",
        "treatment_room",
        "examination_room",
        "nurses_station",
    ],
    "retail": [
        "store",
        "supermarket",
        "convenience_store",
        "clothing_store",
        "electronics_store",
        "bookstore",
        "restaurant",
        "cafe",
        "bakery",
        "food_court",
        "kiosk",
        "bank",
        "atm",
    ],
    "public": [
        "restroom",
        "accessible_restroom",
        "prayer_room",
        "childcare",
        "security",
        "customer_service",
        "ticket_office",
    ],
    # Deliberately excludes elevator/stairs/escalator/ramp — see the
    # module docstring's architecture decision. entrance/exit/parking/
    # pickup_point are genuine standalone destinations (not vertical
    # connectors), so they stay.
    "navigation": [
        "entrance",
        "exit",
        "parking",
        "pickup_point",
    ],
    "education": [
        "classroom",
        "lecture_hall",
        "library",
        "computer_lab",
        "administration",
    ],
}

# Flat set of every currently-offered canonical value, across all groups.
CANONICAL_DESTINATION_TYPES: set[str] = {
    value
    for group_values in DESTINATION_TYPE_GROUPS.values()
    for value in group_values
}

# Old stored values that must keep working (never rejected, never
# silently rewritten) but are no longer offered as a fresh selection.
LEGACY_ALIAS_DESTINATION_TYPES: set[str] = {"operating"}

# Everything the backend will accept for a NEW/CHANGED room_type value.
ALL_ACCEPTED_DESTINATION_TYPES: set[str] = (
    CANONICAL_DESTINATION_TYPES | LEGACY_ALIAS_DESTINATION_TYPES
)


def is_accepted_destination_type(value) -> bool:
    """True for None (the field is optional) or any accepted string."""
    if value is None:
        return True
    return value in ALL_ACCEPTED_DESTINATION_TYPES
