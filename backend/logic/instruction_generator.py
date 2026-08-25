"""
Centralized turn-by-turn instruction generator (PHASE 11).

All angle-threshold constants live here — nowhere else in the codebase
decides "is this a slight turn or a sharp turn". Handles the inverted
image Y-axis explicitly (see _classify_turn's docstring) and merges tiny
consecutive legs so a noisy corridor with several almost-collinear
drawn points doesn't produce "Continue 0.3 m" spam.

This module is intentionally pure/synchronous and framework-agnostic
(takes plain dicts/tuples in, returns plain dicts out) so it is trivially
unit-testable without a database.
"""

from __future__ import annotations

import math
import re
from typing import List, Optional, Sequence, TypedDict


# ── Turn classification thresholds (degrees) ────────────────────────────
# Widened from the original 20°/45° to the tolerant defaults requested by
# the end-user navigation redesign task's Section 5 ("absolute turn angle
# below 25°: continue straight; 25° to below 50°: slight left/right; 50°
# or more: turn left/right"). No existing test pinned the original 20/45
# values (grepped before changing), so this is a safe, direct adoption of
# the suggested tolerance — the only goal either way is the same one PHASE
# 11 already had: tiny coordinate imperfections must never manufacture an
# unnecessary turn instruction. NORMAL_MAX_DEGREES/SHARP_MAX_DEGREES (the
# turn/sharp-turn/u-turn boundaries) are unrelated to that ask and are
# left exactly as they were.
STRAIGHT_MAX_DEGREES = 25.0
SLIGHT_MAX_DEGREES = 50.0
NORMAL_MAX_DEGREES = 120.0
SHARP_MAX_DEGREES = 160.0
# Beyond SHARP_MAX_DEGREES => "u_turn"

# Classifications that never rise to a "real" turn worth its own callout —
# grouped together into one generic "continue straight through the
# corridor" instruction (Section 5: "group consecutive segments that
# continue in approximately the same direction"; Section 6: prefer a
# correct generic instruction over an incorrect/irrelevant landmark name).
# A genuine turn (left/right/sharp_left/sharp_right/u_turn) is NEVER a
# member of this set, so it always stays its own separate instruction and
# always ends whatever group is in progress — see
# _group_consecutive_straight_legs below.
GROUPABLE_TURN_TYPES = frozenset({"straight", "slight_left", "slight_right"})

# Legs shorter than this are folded into the following leg instead of
# generating their own "Continue N m" instruction — avoids noisy
# near-duplicate steps from admin-drawn corridor points that are only a
# few pixels/centimeters apart.
MIN_INSTRUCTION_LEG_METERS = 1.5

DISTANCE_ROUND_METERS = 1


class RoutePointLike(TypedDict, total=False):
    id: str
    x: float
    y: float
    name: str
    point_type: Optional[str]


# Bug-fix round: `is_auto_generated` alone is NOT a reliable signal that a
# raw `name` is safe to hide — it is only ever set by the internal
# auto-generation pipeline (services/graph_generation_service.py) and is
# not even an accepted field on the public RoutePointCreate request
# schema (schemas/route_point_schema.py), so any point created directly
# through the API, imported from legacy data, or otherwise typed with a
# technical-looking name NEVER gets is_auto_generated=True and previously
# leaked straight through to the user (e.g. "room_point_33"). This
# pattern matches the technical-identifier SHAPES themselves, independent
# of that flag, so detection works regardless of how/where the point was
# created:
#   - "room_point_33", "corridor_point_12", "route_point_123", "node_44"
#     (an optional run of lowercase word(s) followed by "point" or "node",
#     then an underscore/space and a numeric id, optionally with a
#     "-<digits>" suffix — also matches the system's own real generated
#     shape "Corridor Point 1784904901734-6");
#   - a bare MongoDB ObjectId (24 hex chars);
#   - a bare UUID (8-4-4-4-12 hex groups).
# Deliberately narrower than "any word followed by a number" (which would
# false-positive on legitimate short names like "Gate 7" or "Room 101") —
# every one of the required example shapes contains the literal word
# "point" or "node", which a genuine admin-facing destination/landmark
# name essentially never does.
_TECHNICAL_NAME_PATTERN = re.compile(
    r"^(?:"
    r"[0-9a-f]{24}"
    r"|[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
    r"|(?:[a-z]+[ _])*(?:point|node)[ _]\d+(?:-\d+)?"
    r")$",
    re.IGNORECASE,
)


def _looks_like_technical_name(value: str) -> bool:
    return bool(_TECHNICAL_NAME_PATTERN.match(value.strip()))


def resolve_display_name(
    name: Optional[str],
    display_name: Optional[str] = None,
    is_auto_generated: bool = False,
) -> Optional[str]:
    """
    Section 16 of the semantic-map-analysis spec: user-facing navigation
    text must prefer, in order: (1) an explicit RoutePoint.display_name
    (set by an admin, optionally copied from an approved published
    semantic entity — see semantic_publication_service.py), (2) a
    meaningful admin-defined RoutePoint.name — UNLESS it looks like a raw
    technical identifier (see _TECHNICAL_NAME_PATTERN), (3) nothing at all
    (the calling instruction templates already read gracefully as
    "Continue straight for N m." with no "at X" clause when name is
    falsy/None).

    Never returns a raw auto-generated technical name (e.g. "Corridor
    Point 1784904901734-6") — those exist only for admin-side debugging
    and must never reach a normal user. Suppressed on TWO independent
    signals, either one sufficient: `is_auto_generated` (the tracked
    provenance flag on every RoutePoint — see models/route_point_model.py)
    OR the name's own shape matching a known technical-identifier pattern
    — the flag alone is not trustworthy, since it is only set by the
    internal auto-generation pipeline and isn't even accepted on the
    public point-creation request schema.
    """

    if display_name and display_name.strip():
        return display_name.strip()

    if is_auto_generated:
        return None

    if name and name.strip():
        stripped = name.strip()
        if _looks_like_technical_name(stripped):
            return None
        return stripped

    return None


def classify_turn(
    incoming: Sequence[float], outgoing: Sequence[float]
) -> tuple[str, float]:
    """
    Classifies the turn at the vertex between an incoming vector and an
    outgoing vector, both given as (dx, dy) in ORIGINAL-IMAGE pixel
    coordinates (x increases right, y increases DOWN — the same
    convention every RoutePoint.x/y already uses).

    Because the image's Y-axis is inverted relative to standard math/
    screen-up coordinates, the usual "positive cross product = left turn"
    rule is flipped here: in this y-down system, a POSITIVE cross product
    dx1*dy2 - dy1*dx2 corresponds to a RIGHT turn and a NEGATIVE cross
    product corresponds to a LEFT turn (verified against a concrete
    compass example: walking east then turning to walk south on the map
    image is a real-world right turn, and that pair of vectors produces a
    positive cross product under this formula).

    Returns (classification, abs_angle_degrees) where classification is
    one of: "straight", "slight_left", "slight_right", "left", "right",
    "sharp_left", "sharp_right", "u_turn".
    """

    dx1, dy1 = incoming
    dx2, dy2 = outgoing

    mag1 = math.hypot(dx1, dy1)
    mag2 = math.hypot(dx2, dy2)

    if mag1 == 0 or mag2 == 0:
        return "straight", 0.0

    cross = dx1 * dy2 - dy1 * dx2
    dot = dx1 * dx2 + dy1 * dy2

    # atan2(cross, dot) with THIS cross-product sign convention already
    # yields positive angles for right turns and negative for left turns
    # in y-down image coordinates (see docstring above).
    angle_deg = math.degrees(math.atan2(cross, dot))
    abs_angle = abs(angle_deg)
    is_right = angle_deg > 0

    if abs_angle <= STRAIGHT_MAX_DEGREES:
        return "straight", abs_angle
    if abs_angle <= SLIGHT_MAX_DEGREES:
        return ("slight_right" if is_right else "slight_left"), abs_angle
    if abs_angle <= NORMAL_MAX_DEGREES:
        return ("right" if is_right else "left"), abs_angle
    if abs_angle <= SHARP_MAX_DEGREES:
        return ("sharp_right" if is_right else "sharp_left"), abs_angle

    return "u_turn", abs_angle


def merge_tiny_legs(
    points: List[RoutePointLike], leg_distances_m: List[float]
) -> List[RoutePointLike]:
    """
    Drops intermediate points whose leg (to the NEXT point) is shorter
    than MIN_INSTRUCTION_LEG_METERS, so a run of near-duplicate points
    becomes one instruction leg instead of several near-zero-distance
    ones. Never drops the first or last point. Distances are assumed
    already computed leg-by-leg (len(leg_distances_m) == len(points) - 1).
    """

    if len(points) <= 2:
        return list(points)

    merged = [points[0]]

    for i in range(1, len(points) - 1):
        if leg_distances_m[i - 1] < MIN_INSTRUCTION_LEG_METERS:
            continue
        merged.append(points[i])

    merged.append(points[-1])
    return merged



# Static instruction phrasing per UI language (Section 11 of the
# multilingual content spec — "Continue straight", "Turn left", etc. are
# STATIC UI text and stay entirely separate from dynamic entity names).
# Every `name`/`connector_name` value passed into these templates is
# resolved elsewhere (see resolve_localized_display_name below /
# multi_floor_routing.py's segment building) from MongoDB-stored,
# admin-approved translations — no sentence is ever stored pre-composed
# in the database, only the ingredients (this static template plus the
# dynamic name) are combined at request time. Only "en" existed before
# this addition; "ar"/"he" are additive and never change the "en" text.
TEXT_TEMPLATES = {
    "en": {
        # Bug-fix round — "Proceed toward the destination" is the required
        # generic, multilingual fallback for when no trustworthy name is
        # available (technical name suppressed, or none ever set), used
        # instead of a bare "Start walking." that used to lose the
        # route-relative "proceed toward" framing entirely.
        "start": lambda name: f"Proceed toward {name}." if name else "Proceed toward the destination.",
        # Section 6 — generic, never a landmark name: "It is better to use
        # a correct generic instruction than an incorrect room landmark."
        # Used for every straight leg AND for a merged run of consecutive
        # straight/slight legs (see _group_consecutive_straight_legs) —
        # the " for {dist} m." suffix is stripped by the frontend's
        # display layer exactly like every other instruction (see
        # frontend/src/utils/multiFloorRouteHelpers.js's
        # stripInstructionDistanceClause), leaving the exact required
        # "Continue straight through the corridor."
        "straight": lambda dist: f"Continue straight through the corridor for {dist} m.",
        "slight_left": lambda dist, name: f"Bear slightly left{f' at {name}' if name else ''}, then continue {dist} m.",
        "slight_right": lambda dist, name: f"Bear slightly right{f' at {name}' if name else ''}, then continue {dist} m.",
        "left": lambda dist, name: f"Turn left{f' at {name}' if name else ''}, then continue {dist} m.",
        "right": lambda dist, name: f"Turn right{f' at {name}' if name else ''}, then continue {dist} m.",
        "sharp_left": lambda dist, name: f"Turn sharply left{f' at {name}' if name else ''}, then continue {dist} m.",
        "sharp_right": lambda dist, name: f"Turn sharply right{f' at {name}' if name else ''}, then continue {dist} m.",
        "u_turn": lambda dist, name: f"Make a U-turn{f' at {name}' if name else ''}, then continue {dist} m.",
        "arrive_left": lambda name: f"Your destination, {name}, is on the left.",
        "arrive_right": lambda name: f"Your destination, {name}, is on the right.",
        # A safe generic fallback for the rare case a destination has no
        # trustworthy name at all (technical name suppressed, or none
        # ever set) — never a broken "You have arrived at ." with a blank
        # landmark, and never the raw technical identifier either.
        "arrive": lambda name: f"You have arrived at {name}." if name else "You have arrived at your destination.",
        "transition_elevator": lambda connector_name, to_floor_label: f"Use {connector_name} and go to {to_floor_label}.",
        "transition_stairs": lambda connector_name, to_floor_label: f"Take {connector_name} to {to_floor_label}.",
        "transition_escalator": lambda connector_name, to_floor_label: f"Take {connector_name} to {to_floor_label}.",
        "transition_ramp": lambda connector_name, to_floor_label: f"Use {connector_name} to {to_floor_label}.",
        "exit_transition": lambda direction: (
            f"Exit and turn {direction}." if direction in ("left", "right") else "Continue forward."
        ),
    },
    "ar": {
        # Bug-fix round — required generic multilingual fallback ("تابعي
        # باتجاه الوجهة") when no trustworthy name is available.
        "start": lambda name: f"توجه نحو {name}." if name else "تابعي باتجاه الوجهة.",
        # Section 6's exact required generic phrase ("تابعي مستقيمًا عبر
        # الممر") plus the same stripped-by-the-frontend distance suffix
        # every other instruction uses.
        "straight": lambda dist: f"تابعي مستقيمًا عبر الممر لمسافة {dist} م.",
        "slight_left": lambda dist, name: f"انحرف قليلاً إلى اليسار{f' عند {name}' if name else ''}، ثم تابع {dist} م.",
        "slight_right": lambda dist, name: f"انحرف قليلاً إلى اليمين{f' عند {name}' if name else ''}، ثم تابع {dist} م.",
        "left": lambda dist, name: f"انعطف يسارًا{f' عند {name}' if name else ''}، ثم تابع {dist} م.",
        "right": lambda dist, name: f"انعطف يمينًا{f' عند {name}' if name else ''}، ثم تابع {dist} م.",
        "sharp_left": lambda dist, name: f"انعطف بحدة إلى اليسار{f' عند {name}' if name else ''}، ثم تابع {dist} م.",
        "sharp_right": lambda dist, name: f"انعطف بحدة إلى اليمين{f' عند {name}' if name else ''}، ثم تابع {dist} م.",
        "u_turn": lambda dist, name: f"قم بالدوران للخلف{f' عند {name}' if name else ''}، ثم تابع {dist} م.",
        "arrive_left": lambda name: f"وجهتك، {name}، على اليسار.",
        "arrive_right": lambda name: f"وجهتك، {name}، على اليمين.",
        "arrive": lambda name: f"لقد وصلت إلى {name}." if name else "لقد وصلت إلى وجهتك.",
        "transition_elevator": lambda connector_name, to_floor_label: f"استخدم {connector_name} وتوجه إلى {to_floor_label}.",
        "transition_stairs": lambda connector_name, to_floor_label: f"استخدم {connector_name} للوصول إلى {to_floor_label}.",
        "transition_escalator": lambda connector_name, to_floor_label: f"استخدم {connector_name} للوصول إلى {to_floor_label}.",
        "transition_ramp": lambda connector_name, to_floor_label: f"استخدم {connector_name} للوصول إلى {to_floor_label}.",
        "exit_transition": lambda direction: (
            f"اخرج وانعطف {'يسارًا' if direction == 'left' else 'يمينًا'}."
            if direction in ("left", "right")
            else "تابع إلى الأمام."
        ),
    },
    "he": {
        # Bug-fix round — required generic multilingual fallback ("המשך
        # לכיוון היעד") when no trustworthy name is available.
        "start": lambda name: f"המשך לכיוון {name}." if name else "המשך לכיוון היעד.",
        # Section 6's exact required generic phrase ("המשך ישר במסדרון")
        # plus the same stripped-by-the-frontend distance suffix every
        # other instruction uses.
        "straight": lambda dist: f"המשך ישר במסדרון למרחק {dist} מ׳.",
        "slight_left": lambda dist, name: f"פנה מעט שמאלה{f' ליד {name}' if name else ''}, ולאחר מכן המשך {dist} מ׳.",
        "slight_right": lambda dist, name: f"פנה מעט ימינה{f' ליד {name}' if name else ''}, ולאחר מכן המשך {dist} מ׳.",
        "left": lambda dist, name: f"פנה שמאלה{f' ליד {name}' if name else ''}, ולאחר מכן המשך {dist} מ׳.",
        "right": lambda dist, name: f"פנה ימינה{f' ליד {name}' if name else ''}, ולאחר מכן המשך {dist} מ׳.",
        "sharp_left": lambda dist, name: f"פנה בחדות שמאלה{f' ליד {name}' if name else ''}, ולאחר מכן המשך {dist} מ׳.",
        "sharp_right": lambda dist, name: f"פנה בחדות ימינה{f' ליד {name}' if name else ''}, ולאחר מכן המשך {dist} מ׳.",
        "u_turn": lambda dist, name: f"בצע פניית פרסה{f' ליד {name}' if name else ''}, ולאחר מכן המשך {dist} מ׳.",
        "arrive_left": lambda name: f"היעד שלך, {name}, נמצא בצד שמאל.",
        "arrive_right": lambda name: f"היעד שלך, {name}, נמצא בצד ימין.",
        "arrive": lambda name: f"הגעת אל {name}." if name else "הגעת ליעד שלך.",
        "transition_elevator": lambda connector_name, to_floor_label: f"השתמש ב-{connector_name} ועבור אל {to_floor_label}.",
        "transition_stairs": lambda connector_name, to_floor_label: f"השתמש ב-{connector_name} כדי להגיע אל {to_floor_label}.",
        "transition_escalator": lambda connector_name, to_floor_label: f"השתמש ב-{connector_name} כדי להגיע אל {to_floor_label}.",
        "transition_ramp": lambda connector_name, to_floor_label: f"השתמש ב-{connector_name} כדי להגיע אל {to_floor_label}.",
        "exit_transition": lambda direction: (
            f"צא ופנה {'שמאלה' if direction == 'left' else 'ימינה'}."
            if direction in ("left", "right")
            else "המשך קדימה."
        ),
    },
}

_FLOOR_LABEL_TEMPLATES = {
    "en": {
        "next": "the next floor",
        "ground": "the Ground Floor",
        "basement": lambda n: f"Basement {n}",
        "floor": lambda n: f"Floor {n}",
    },
    "ar": {
        "next": "الطابق التالي",
        "ground": "الطابق الأرضي",
        "basement": lambda n: f"الطابق تحت الأرضي {n}",
        "floor": lambda n: f"الطابق {n}",
    },
    "he": {
        "next": "הקומה הבאה",
        "ground": "קומת הקרקע",
        "basement": lambda n: f"מרתף {n}",
        "floor": lambda n: f"קומה {n}",
    },
}


def _floor_label(
    floor: Optional[int], floor_label: Optional[str], lang: str = "en"
) -> str:
    if floor_label:
        return floor_label
    templates = _FLOOR_LABEL_TEMPLATES.get(lang, _FLOOR_LABEL_TEMPLATES["en"])
    if floor is None:
        return templates["next"]
    if floor == 0:
        return templates["ground"]
    if floor < 0:
        return templates["basement"](abs(floor))
    return templates["floor"](floor)


def resolve_localized_display_name(
    name: Optional[str],
    *,
    display_name: Optional[str] = None,
    display_name_en: Optional[str] = None,
    display_name_ar: Optional[str] = None,
    display_name_he: Optional[str] = None,
    is_auto_generated: bool = False,
    lang: str = "en",
) -> Optional[str]:
    """
    Language-aware sibling of resolve_display_name() (kept fully intact
    above/unchanged for backward compatibility with any existing caller
    that only ever wants the single-string legacy behavior). Priority:

      1. the per-language display_name_{lang} field for the REQUESTED
         language, if it has a real value;
      2. the fallback chain across the other stored per-language values
         (en, then ar, then he) — see schemas/localization_schema's
         identical fallback order, mirrored here to avoid importing a
         schemas module into this framework-agnostic pure-logic module;
      3. the legacy single `display_name` field;
      4. None if the point is auto-generated (never show a raw technical
         name like "Corridor Point 178" to a normal user), OR if the raw
         `name` itself matches a known technical-identifier shape
         regardless of that flag (see _TECHNICAL_NAME_PATTERN /
         resolve_display_name's docstring — the flag alone is not a
         reliable signal, since it's only set by the internal
         auto-generation pipeline and isn't even accepted on the public
         point-creation request schema);
      5. the raw admin-typed `name` as a last resort, once it's passed
         that technical-shape check.

    Never invents a translation — a point missing translations for the
    requested language transparently falls through to whatever IS
    actually stored, exactly like get_localized_text().
    """

    per_language = {"en": display_name_en, "ar": display_name_ar, "he": display_name_he}

    requested = per_language.get(lang)
    if requested and requested.strip():
        return requested.strip()

    for fallback_lang in ("en", "ar", "he"):
        value = per_language.get(fallback_lang)
        if value and value.strip():
            return value.strip()

    if display_name and display_name.strip():
        return display_name.strip()

    if is_auto_generated:
        return None

    if name and name.strip():
        stripped = name.strip()
        if _looks_like_technical_name(stripped):
            return None
        return stripped

    return None


def generate_floor_instructions(
    points: List[RoutePointLike], lang: str = "en"
) -> List[dict]:
    """
    Builds instructions for ONE floor segment's ordered point list
    (already merged for tiny legs by the caller if desired). Always
    starts with a route-relative "Proceed toward X" instruction rather
    than a claimed absolute/compass left-right direction (PHASE 12 — the
    app has no device-orientation input, so an initial instruction never
    claims to know which way the user is physically facing).
    """

    templates = TEXT_TEMPLATES.get(lang, TEXT_TEMPLATES["en"])

    if len(points) < 2:
        return []

    def _leg_distance(a, b) -> float:
        return math.hypot(b["x"] - a["x"], b["y"] - a["y"])

    def _pid(point):
        return point.get("point_id", point.get("id"))

    instructions: List[dict] = [
        {
            "type": "start",
            "text": templates["start"](points[1].get("name") or points[0].get("name") or ""),
            "point_id": _pid(points[0]),
        }
    ]

    # Pass 1 — classify every intermediate vertex into a "leg" (the turn
    # made AT points[i], and the distance of the segment AFTER it, up to
    # points[i + 1]). Kept as raw, unrounded distances here; rounding
    # happens only once, after grouping, so a group's summed distance
    # doesn't accumulate independent per-leg rounding error.
    legs: List[dict] = []
    for i in range(1, len(points) - 1):
        incoming = (points[i]["x"] - points[i - 1]["x"], points[i]["y"] - points[i - 1]["y"])
        outgoing = (points[i + 1]["x"] - points[i]["x"], points[i + 1]["y"] - points[i]["y"])

        turn_type, _angle = classify_turn(incoming, outgoing)
        leg_distance = _leg_distance(points[i], points[i + 1])

        legs.append(
            {
                "turn_type": turn_type,
                "distance": leg_distance,
                "point_id": _pid(points[i]),
                "name": points[i].get("name") or "",
            }
        )

    # Pass 2 — Section 5: "If multiple consecutive segments continue in
    # approximately the same direction, group them into one meaningful
    # instruction." Only continue-straight/slight-left/slight-right legs
    # are ever merged (GROUPABLE_TURN_TYPES); any genuine turn (left,
    # right, sharp_left, sharp_right, u_turn) is never merged and always
    # ends the current group, since it is itself a hard boundary between
    # meaningfully different instructions. Floor transitions and arrival
    # are never part of `legs` at all — they're built entirely outside
    # this function (via _build_segments / generate_transition_instruction
    # and the "arrive" instruction below) — so grouping can never cross
    # those boundaries either.
    grouped_legs: List[dict] = []
    i = 0
    while i < len(legs):
        leg = legs[i]
        if leg["turn_type"] in GROUPABLE_TURN_TYPES:
            run_distance = 0.0
            run_end = i
            while (
                run_end < len(legs)
                and legs[run_end]["turn_type"] in GROUPABLE_TURN_TYPES
            ):
                run_distance += legs[run_end]["distance"]
                run_end += 1

            grouped_legs.append(
                {
                    "turn_type": "straight",
                    "distance": run_distance,
                    # Anchor the merged instruction's point_id at the LAST
                    # vertex of the run — the point closest to where the
                    # next real turn/transition/arrival actually happens.
                    "point_id": legs[run_end - 1]["point_id"],
                    # A merged, generic corridor instruction never carries
                    # a landmark name (Section 6 — "better to use a
                    # correct generic instruction than an incorrect room
                    # landmark").
                    "name": "",
                }
            )
            i = run_end
        else:
            grouped_legs.append(leg)
            i += 1

    for leg in grouped_legs:
        turn_type = leg["turn_type"]
        leg_distance = round(leg["distance"])
        name = leg["name"]

        if turn_type == "straight":
            text = templates["straight"](leg_distance)
        else:
            text = templates[turn_type](leg_distance, name)

        instructions.append(
            {
                "type": turn_type,
                "text": text,
                "point_id": leg["point_id"],
                "distance_meters": leg_distance,
            }
        )

    last = points[-1]
    instructions.append(
        {
            "type": "arrive",
            "text": templates["arrive"](last.get("name") or ""),
            "point_id": _pid(last),
        }
    )

    return instructions


def generate_transition_instruction(
    *,
    connector_type: str,
    connector_name: Optional[str],
    to_floor: Optional[int],
    to_floor_label: Optional[str],
    lang: str = "en",
) -> dict:
    templates = TEXT_TEMPLATES.get(lang, TEXT_TEMPLATES["en"])
    key = f"transition_{connector_type}" if f"transition_{connector_type}" in templates else "transition_elevator"

    label = _floor_label(to_floor, to_floor_label, lang)
    name = connector_name or connector_type.capitalize()

    return {
        "type": "transition",
        "transition_type": connector_type,
        "text": templates[key](name, label),
    }


# Nested-room navigation (Section 14 of the Approved Semantic Analysis ->
# Automatic Destinations spec). Deliberately just these three required
# exact-ish phrasings, not routed through TEXT_TEMPLATES — this only ever
# fires for the one specific situation (an approved pass-through room that
# is not the final destination), so a small dedicated table is clearer
# than threading a new case through the generic template dict.
_PASS_THROUGH_TEMPLATES = {
    "en": lambda outer, inner: f"Enter {outer} and continue toward {inner}.",
    "ar": lambda outer, inner: f"ادخلي إلى {outer} وتابعي باتجاه {inner}.",
    "he": lambda outer, inner: f"היכנס ל{outer} והמשך אל {inner}.",
}


def annotate_pass_through_instructions(
    instructions: List[dict], points: List[dict], lang: str = "en"
) -> List[dict]:
    """
    Section 14 — when the ACTUAL returned route passes through an approved
    pass-through room (RoutePoint.allow_transit_through True) that is not
    itself the final destination, replace whatever generic instruction
    already exists for that point with a truthful "Enter X and continue
    toward Y" phrase, using the real multilingual display names already
    resolved onto `points` (see multi_floor_routing.py's
    resolve_localized_display_name call) — never a raw point id, never a
    fabricated "nearby landmark". Never touches any other instruction, and
    never changes distances/turn classification — purely a text override
    for the specific matched point_id(s).
    """

    if len(points) < 2:
        return instructions

    # point_id -> (outer room's display name, the next real point's name).
    # The LAST point is deliberately excluded — a pass-through room that
    # happens to also be the actual selected destination is a normal
    # arrival, never "enter and continue toward" phrasing.
    pass_through_next_name: dict = {}
    for i in range(len(points) - 1):
        point = points[i]
        if point.get("point_type") in ("room", "store") and point.get(
            "allow_transit_through"
        ):
            outer_name = point.get("name")
            inner_name = points[i + 1].get("name")
            if outer_name and inner_name:
                pass_through_next_name[point.get("point_id")] = (
                    outer_name,
                    inner_name,
                )

    if not pass_through_next_name:
        return instructions

    template = _PASS_THROUGH_TEMPLATES.get(lang, _PASS_THROUGH_TEMPLATES["en"])

    annotated: List[dict] = []
    for instruction in instructions:
        point_id = instruction.get("point_id")
        if point_id in pass_through_next_name:
            outer_name, inner_name = pass_through_next_name[point_id]
            instruction = {
                **instruction,
                "type": "pass_through",
                "text": template(outer_name, inner_name),
            }
        annotated.append(instruction)

    return annotated


def generate_instructions_for_route(segments: List[dict], lang: str = "en") -> List[dict]:
    """
    Full ordered instruction list for a segmented multi-floor route (the
    same `segments` shape logic/multi_floor_routing.py returns): a
    same-floor instruction list per floor segment, with a transition
    instruction inserted between floors.
    """

    all_instructions: List[dict] = []

    for segment in segments:
        if segment["segment_type"] == "floor":
            points = segment.get("coordinates", [])
            floor_instructions = generate_floor_instructions(points, lang=lang)
            floor_instructions = annotate_pass_through_instructions(
                floor_instructions, points, lang=lang
            )
            all_instructions.extend(floor_instructions)
        elif segment["segment_type"] == "transition":
            all_instructions.append(
                generate_transition_instruction(
                    connector_type=segment.get("transition_type", "elevator"),
                    connector_name=segment.get("connector_name"),
                    to_floor=segment.get("to_floor"),
                    to_floor_label=None,
                    lang=lang,
                )
            )

    return all_instructions
