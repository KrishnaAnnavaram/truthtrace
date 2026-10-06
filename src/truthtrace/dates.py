"""Date parsing for the formats the sources use, normalised to ``datetime.date``."""
from __future__ import annotations

import re
from datetime import date, datetime

_MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}
_ISO = re.compile(r"(\d{4})-(\d{2})-(\d{2})")
_MDY = re.compile(r"\b([A-Za-z]{3,9})\.?\s+(\d{1,2}),?\s+(\d{4})\b")
_DMY = re.compile(r"\b(\d{1,2})\s+([A-Za-z]{3,9})\.?,?\s+(\d{4})\b")
_NUMERIC = re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b")


def _month(name: str) -> int | None:
    return _MONTHS.get(name.lower()[:3])


def parse_date(value: str | date | datetime | None) -> date | None:
    """Parse ISO timestamps, "September 3, 2024", "Sept. 3, 2024", "3 Sep 2024", RFC 822 and 9/3/2024."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    candidates = []
    if m := _ISO.search(text):
        candidates.append((int(m.group(1)), int(m.group(2)), int(m.group(3))))
    if m := _MDY.search(text):
        if month := _month(m.group(1)):
            candidates.append((int(m.group(3)), month, int(m.group(2))))
    if m := _DMY.search(text):
        if month := _month(m.group(2)):
            candidates.append((int(m.group(3)), month, int(m.group(1))))
    if m := _NUMERIC.search(text):
        candidates.append((int(m.group(3)), int(m.group(1)), int(m.group(2))))
    for year, month, day in candidates:
        try:
            return date(year, month, day)
        except ValueError:
            continue
    return None
