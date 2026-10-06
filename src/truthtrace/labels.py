"""A fixed verdict scale. Source ratings are mapped onto it; no made-up percentages anywhere."""
from __future__ import annotations

import re
from enum import Enum


class Label(str, Enum):
    TRUE = "true"
    MOSTLY_TRUE = "mostly_true"
    HALF_TRUE = "half_true"
    MOSTLY_FALSE = "mostly_false"
    FALSE = "false"
    PANTS_ON_FIRE = "pants_on_fire"
    UNVERIFIABLE = "unverifiable"

    @property
    def display(self) -> str:
        return DISPLAY[self]

    @property
    def coarse(self) -> str:
        """Three-way grouping used for evaluation and conflict detection."""
        return COARSE[self]


SCALE = [Label.TRUE, Label.MOSTLY_TRUE, Label.HALF_TRUE, Label.MOSTLY_FALSE, Label.FALSE, Label.PANTS_ON_FIRE]

DISPLAY = {
    Label.TRUE: "True", Label.MOSTLY_TRUE: "Mostly true", Label.HALF_TRUE: "Half true",
    Label.MOSTLY_FALSE: "Mostly false", Label.FALSE: "False", Label.PANTS_ON_FIRE: "Pants on fire",
    Label.UNVERIFIABLE: "Can't verify",
}
COARSE = {
    Label.TRUE: "supported", Label.MOSTLY_TRUE: "supported", Label.HALF_TRUE: "mixed",
    Label.MOSTLY_FALSE: "refuted", Label.FALSE: "refuted", Label.PANTS_ON_FIRE: "refuted",
    Label.UNVERIFIABLE: "unverifiable",
}

_ALIASES = {
    "true": Label.TRUE,
    "mostly true": Label.MOSTLY_TRUE,
    "half true": Label.HALF_TRUE,
    "mostly false": Label.MOSTLY_FALSE,
    "barely true": Label.MOSTLY_FALSE,  # PolitiFact's former name for "mostly false"
    "false": Label.FALSE,
    "pants on fire": Label.PANTS_ON_FIRE,
    "pants fire": Label.PANTS_ON_FIRE,
    "unverifiable": Label.UNVERIFIABLE,
    "cant verify": Label.UNVERIFIABLE,
    "can't verify": Label.UNVERIFIABLE,
}
# Flip-O-Meter ratings describe consistency, not truth, so they are deliberately not mapped.
NOT_TRUTH_RATINGS = {"full flop", "half flip", "no flip"}


def normalize_rating(raw: str | None) -> Label | None:
    """Map a source rating ("pants-fire", "Mostly True", "barely-true") onto the scale."""
    if not raw:
        return None
    key = re.sub(r"[-_!./]+", " ", raw.strip().lower())
    key = re.sub(r"\s+", " ", key).strip()
    if key in NOT_TRUTH_RATINGS:
        return None
    if key in _ALIASES:
        return _ALIASES[key]
    try:
        return Label(key.replace(" ", "_"))
    except ValueError:
        return None
