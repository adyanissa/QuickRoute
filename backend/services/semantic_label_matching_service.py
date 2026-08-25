"""
Matching one semantic entity (what Claude understood) to one label
physically printed on the map (what the drawing actually says).

This is the join between the two halves of the hybrid pipeline, and it is
the only place where a name is allowed to influence geometry. It is
therefore written to REFUSE far more readily than it accepts:

  * every rule is exact on normalized text — there is no fuzzy distance,
    no edit distance, no "closest looking" fallback,
  * a tie between two labels is an `ambiguous_label` refusal, not a
    coin toss,
  * a refusal costs the admin one click; a wrong match puts a room in
    the wrong place and is silently wrong forever.

Nothing here reads or writes the database, and nothing here produces a
coordinate — it returns WHICH label matched, and the caller
(services/destination_auto_placement_service) decides what to do with
that label's box.

THE RULES, IN STRICT PRIORITY ORDER
-----------------------------------
  exact_normalized   1.00  the whole normalized name equals the whole
                           normalized label ("Office 428" == "OFFICE 428")
  number_and_token   0.90  same room number AND at least one shared word
                           ("Office 428" vs "OFFICE 428 STORAGE")
  number_only        0.75  same room number, no shared word
                           ("Reception" carrying number 428 vs "RM 428")
  name_token_subset  0.70  every word of the name appears in the label,
                           and at least one of them is a real word

A higher rule always wins outright: one number_and_token match beats any
number of name_token_subset matches, and the weaker matches are not even
considered as alternatives for tie-breaking.

MULTILINGUAL NAMES
------------------
Every one of names.en / names.ar / names.he / names.original is tried
independently, and the best result across all of them wins. Arabic and
Hebrew survive normalization (see map_label_extraction_service), so a map
drawn in Hebrew matches Hebrew names directly rather than through English.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

from services.map_label_extraction_service import (
    MapLabel,
    alphabetic_tokens,
    extract_room_number,
    normalize_label_text,
)


# Rule name -> (priority, confidence). Higher priority wins outright.
MATCH_RULES: Dict[str, Tuple[int, float]] = {
    "exact_normalized": (4, 1.0),
    "number_and_token": (3, 0.9),
    "number_only": (2, 0.75),
    "name_token_subset": (1, 0.7),
}

# A token has to be at least this long to carry a name_token_subset match
# on its own. Stops one-and two-letter fragments ("A", "OF", "B") from
# matching half the labels on a floor plan.
MIN_SUBSET_TOKEN_LENGTH = 3

# When a category/subcategory breaks a tie, the winning match is recorded
# at this share of its rule's normal confidence — it was ambiguous on
# name alone, and the diagnostics should say so.
CATEGORY_DISAMBIGUATION_PENALTY = 0.85


@dataclass
class LabelMatch:
    """The outcome of matching one semantic entity. Exactly one of
    `label` / `reason` is meaningful: `label` is None on a refusal."""

    status: str                     # "matched" | "ambiguous_label" | "no_label_match"
    label: Optional[MapLabel] = None
    rule: Optional[str] = None
    confidence: float = 0.0
    matched_name: Optional[str] = None      # which name variant matched
    matched_language: Optional[str] = None  # en | ar | he | original
    reason: Optional[str] = None
    # Every label that tied at the winning rule, when the tie could not be
    # broken. Named so the admin UI can show "3 labels say OFFICE".
    tied_label_texts: List[str] = None      # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.tied_label_texts is None:
            self.tied_label_texts = []

    @property
    def matched(self) -> bool:
        return self.status == "matched" and self.label is not None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "rule": self.rule,
            "confidence": round(self.confidence, 3),
            "matched_name": self.matched_name,
            "matched_language": self.matched_language,
            "matched_label": self.label.to_dict() if self.label else None,
            "reason": self.reason,
            "tied_label_texts": list(self.tied_label_texts),
        }


def _rule_for(
    name_normalized: str,
    name_number: Optional[str],
    name_tokens: Sequence[str],
    label: MapLabel,
) -> Optional[str]:
    """The single strongest rule this (name, label) pair satisfies."""

    if not name_normalized:
        return None

    if name_normalized == label.normalized:
        return "exact_normalized"

    if name_number and label.number and name_number == label.number:
        if set(name_tokens) & set(label.tokens):
            return "number_and_token"
        return "number_only"

    if name_tokens and set(name_tokens).issubset(set(label.tokens)):
        if any(len(token) >= MIN_SUBSET_TOKEN_LENGTH for token in name_tokens):
            return "name_token_subset"

    return None


def _leading_noun(label: MapLabel) -> Optional[str]:
    """A label's first real word — "OFFICE" in "OFFICE 428"."""

    return label.tokens[0] if label.tokens else None


def _break_tie_by_category(
    tied: List[Tuple[MapLabel, str, str]],
    category: Optional[str],
    subcategory: Optional[str],
) -> Optional[Tuple[MapLabel, str, str]]:
    """
    The ONE permitted tie-breaker: the semantic entity's own declared
    category or subcategory is exactly the leading noun of exactly one of
    the tied labels. "Exactly one" is the whole point — if the category
    fits two of them it has told us nothing and the tie stands.

    Deliberately not a similarity score. Either the drawing literally
    starts that label with the word Claude used for the category, or this
    returns None and the caller refuses.
    """

    for raw in (category, subcategory):
        target = normalize_label_text(raw)
        if not target:
            continue

        hits = [entry for entry in tied if _leading_noun(entry[0]) == target]

        if len(hits) == 1:
            return hits[0]

    return None


def _name_variants(entity: Dict[str, Any]) -> List[Tuple[str, str]]:
    """[(language, name)] for every non-empty name this entity carries."""

    names = entity.get("names")
    if isinstance(names, dict):
        candidates = [
            ("en", names.get("en")),
            ("ar", names.get("ar")),
            ("he", names.get("he")),
            ("original", names.get("original")),
        ]
    else:
        # The proposal shape produced by preview_semantic_destinations,
        # which flattens the same four names.
        candidates = [
            ("en", entity.get("name_en")),
            ("ar", entity.get("name_ar")),
            ("he", entity.get("name_he")),
            ("original", entity.get("name_original")),
        ]

    return [
        (language, str(value).strip())
        for language, value in candidates
        if value and str(value).strip()
    ]


def match_entity_to_label(
    entity: Dict[str, Any],
    labels: Sequence[MapLabel],
) -> LabelMatch:
    """
    `entity` is either a raw semantic item (with a `names` dict) or a
    proposal from preview_semantic_destinations (with flattened
    name_en/ar/he/original). Both also optionally carry
    detected_category/detected_subcategory (or category/subcategory).
    """

    variants = _name_variants(entity)

    if not variants:
        return LabelMatch(
            status="no_label_match",
            reason="This item has no usable name to match against the map.",
        )

    if not labels:
        return LabelMatch(
            status="no_label_match",
            reason="No text labels could be read from this map.",
        )

    # (label, rule, language) for every pair that matched anything.
    best_priority = 0
    best_entries: List[Tuple[MapLabel, str, str]] = []
    best_name_by_label_id: Dict[int, str] = {}

    for language, name in variants:
        name_normalized = normalize_label_text(name)
        name_number = extract_room_number(name_normalized)
        name_tokens = alphabetic_tokens(name_normalized)

        for label in labels:
            rule = _rule_for(name_normalized, name_number, name_tokens, label)
            if rule is None:
                continue

            priority = MATCH_RULES[rule][0]

            if priority > best_priority:
                best_priority = priority
                best_entries = [(label, rule, language)]
                best_name_by_label_id = {id(label): name}
            elif priority == best_priority:
                # The same label reached this rule through another
                # language — that is one match, not a tie.
                if any(existing[0] is label for existing in best_entries):
                    continue
                best_entries.append((label, rule, language))
                best_name_by_label_id[id(label)] = name

    if not best_entries:
        return LabelMatch(
            status="no_label_match",
            reason=(
                "No label printed on this map matches this item's name or "
                "room number."
            ),
        )

    if len(best_entries) == 1:
        label, rule, language = best_entries[0]
        return LabelMatch(
            status="matched",
            label=label,
            rule=rule,
            confidence=MATCH_RULES[rule][1],
            matched_name=best_name_by_label_id[id(label)],
            matched_language=language,
        )

    category = entity.get("detected_category") or entity.get("category")
    subcategory = entity.get("detected_subcategory") or entity.get("subcategory")

    resolved = _break_tie_by_category(best_entries, category, subcategory)

    if resolved is not None:
        label, rule, language = resolved
        return LabelMatch(
            status="matched",
            label=label,
            rule=f"{rule}+category_disambiguated",
            confidence=round(
                MATCH_RULES[rule][1] * CATEGORY_DISAMBIGUATION_PENALTY, 3
            ),
            matched_name=best_name_by_label_id[id(label)],
            matched_language=language,
            tied_label_texts=[entry[0].text for entry in best_entries],
        )

    return LabelMatch(
        status="ambiguous_label",
        rule=best_entries[0][1],
        reason=(
            f"{len(best_entries)} labels on this map match this item equally "
            "well — an admin must choose the right one rather than the "
            "system guessing."
        ),
        tied_label_texts=[entry[0].text for entry in best_entries],
    )
