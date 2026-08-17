"""
Canonical RoutePoint.point_type values and which of them are
"destination-capable" — i.e. which ones represent a real place a normal
user should be able to pick as a destination, as opposed to a purely
technical graph node (a hallway junction, an entrance, a vertical
connector stop).

This is intentionally a SEPARATE, much smaller list than
constants/destination_types.py's ALL_ACCEPTED_DESTINATION_TYPES (which is
the rich Room.room_type taxonomy — "clinic", "pharmacy", "restroom", etc).
RoutePoint.point_type is a structural/graph classification, not a
category — the frontend's Add Route Point selector (AdminMapScreen.jsx)
currently offers exactly: entrance, hallway, junction, stairs, elevator,
room, store. Of those, only "room" and "store" are destination-capable —
this exactly matches AdminMapScreen.jsx's own pre-existing
`isPlaceType = pointType === 'room' || pointType === 'store'` frontend
check (the "Connect Place: link a room/store point to a building + room"
feature), so this constant is simply that same, already-established
distinction made available to the backend.

Deliberately excludes "entrance": an entrance is where a user STARTS a
navigation session (via a QR/location code), never something they pick as
a destination — see Section 7 of the destination-data-flow task ("the
start RoutePoint itself should not appear as its own destination unless
explicitly intended"). Also excludes "hallway"/"junction" (pure graph
nodes) and "stairs"/"elevator" (vertical-connector stops — see
models/vertical_connector_model.py; a Room type for these would create a
second, disconnected representation of the same physical connector,
exactly the architecture decision constants/destination_types.py's own
docstring already warns against).

`point_type` itself has no backend enum validation (RoutePointCreate/
RoutePointUpdate both leave it as a free `Optional[str]`) — unlike
Room.room_type, it's the frontend selector's own fixed list, and this
module does not change that. It only defines which of those values this
feature treats as "auto-create/sync a linked Room for this point".
"""

# Kept in the same order as AdminMapScreen.jsx's <select> for readability
# when this list is read alongside that file.
ALL_KNOWN_ROUTE_POINT_TYPES: set[str] = {
    "entrance",
    "hallway",
    "junction",
    "stairs",
    "elevator",
    "room",
    "store",
}

# The only point_type values this feature ever creates/updates/deactivates
# a linked Room for.
DESTINATION_CAPABLE_POINT_TYPES: set[str] = {"room", "store"}


def is_destination_capable_point_type(point_type) -> bool:
    """True only for a real, currently-recognized destination-capable
    value. None/unknown/legacy values are never treated as
    destination-capable — a RoutePoint with a point_type this codebase
    doesn't recognize at all (e.g. a very old or hand-edited record) is
    left alone rather than guessed at."""
    return point_type in DESTINATION_CAPABLE_POINT_TYPES


# The only point_type values "Auto Connect Destinations to Corridors"
# (services/auto_connect_destinations_service.py) ever treats as a valid
# corridor/transit connection target. Deliberately just the two confirmed,
# already-established pure-graph-node values from ALL_KNOWN_ROUTE_POINT_TYPES
# above — "hallway" and "junction". There is no separate "corridor" value
# anywhere in this codebase (AdminMapScreen.jsx's Add Route Point selector
# never offers one), so this set intentionally does not include it.
#
# "entrance" is excluded on purpose: while structurally a walkable node, an
# entrance is where a navigation session STARTS (via a QR/location code),
# and treating it as an interchangeable corridor waypoint risks silently
# routing a generated destination connection through a building's actual
# front door rather than its internal corridor graph — a real behavioral
# change this feature must never make on its own. "stairs"/"elevator" are
# excluded because those are vertical-connector stops (see
# models/vertical_connector_model.py / RoutePoint.connector_id) — never a
# same-floor walkway target. "room"/"store" are excluded because they are
# themselves destination-capable, and this feature must never propose a
# Room→Room, Store→Store, or Room→Store connection.
TRANSIT_CANDIDATE_POINT_TYPES: set[str] = {"hallway", "junction"}


def is_transit_candidate_point_type(point_type) -> bool:
    """True only for a real, currently-recognized transit/corridor value a
    destination RoutePoint may be auto-connected to. None/unknown/legacy
    values are never treated as valid transit candidates."""
    return point_type in TRANSIT_CANDIDATE_POINT_TYPES


# Candidate priority for automatic destination attachment, best first.
# "hallway" and "junction" are both already in TRANSIT_CANDIDATE_POINT_TYPES
# above and are equally valid targets — this ordering only decides which
# one wins when two candidates are otherwise comparable, so a real corridor
# run is preferred over a junction node, and a junction over anything else
# that might be added to the transit set later.
#
# Anything in TRANSIT_CANDIDATE_POINT_TYPES but not listed here sorts last
# rather than being excluded, so adding a new transit type to that set can
# never silently make it unusable.
TRANSIT_CANDIDATE_PRIORITY: tuple[str, ...] = ("hallway", "junction")


def transit_candidate_priority_rank(point_type) -> int:
    """Lower is better. Unlisted-but-valid transit types sort after every
    listed one; non-transit types sort last of all."""
    try:
        return TRANSIT_CANDIDATE_PRIORITY.index(point_type)
    except ValueError:
        return len(TRANSIT_CANDIDATE_PRIORITY) + (
            0 if point_type in TRANSIT_CANDIDATE_POINT_TYPES else 1
        )
