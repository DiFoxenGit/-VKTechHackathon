"""Native charts for explicit, source-backed before/after measurements.

This deliberately handles a small grammar. Unclear units, inferred percentages,
unrelated numbers and comparisons absent from the cited material stay as text.
"""

import re

from .models import Series, Visual

UNITS = {
    "мин": "мин", "минута": "мин", "минуты": "мин", "минут": "мин",
    "сек": "с", "секунда": "с", "секунды": "с", "секунд": "с",
    "час": "ч", "часа": "ч", "часов": "ч",
    "день": "дней", "дня": "дней", "дней": "дней",
    "minute": "min", "minutes": "min", "min": "min",
    "second": "s", "seconds": "s", "hour": "hours", "hours": "hours",
    "day": "days", "days": "days",
}
UNIT = "(?:" + "|".join(sorted(UNITS, key=len, reverse=True)) + ")"
NUMBER = r"\d+(?:[.,]\d+)?"
PATTERNS = [
    re.compile(
        rf"(?<![\w.,-])(?P<after>{NUMBER})\s+(?P<unit>{UNIT})\b\.?\s+"
        rf"(?:вместо|instead of)\s+(?P<before>{NUMBER})"
        rf"(?:\s+(?P<other_unit>{UNIT})\b\.?)?(?=\s*(?:$|[.;,!?]))",
        re.I,
    ),
    re.compile(
        rf"\b(?:с|со|from)\s+(?P<before>{NUMBER})"
        rf"(?:\s+(?P<other_unit>{UNIT})\b\.?)?\s+(?:до|to)\s+"
        rf"(?P<after>{NUMBER})\s+(?P<unit>{UNIT})\b",
        re.I,
    ),
]


def comparisons(text):
    # Normalise number grouping without merging sentence or paragraph boundaries.
    text = re.sub(r"(?<=\d)[ \u00a0\u202f](?=\d{3}(?!\d))", "", text)
    for pattern in PATTERNS:
        for match in pattern.finditer(text):
            unit = UNITS[match["unit"].lower()]
            if match["other_unit"] and UNITS[match["other_unit"].lower()] != unit:
                continue
            before, after = (float(match[k].replace(",", ".")) for k in ("before", "after"))
            if before != after:
                yield before, after, unit


def add_comparison_charts(outline, sources, language="ru"):
    if language not in {"ru", "en"}:
        return outline
    evidence = {source["id"]: set(comparisons(source["text"])) for source in sources}
    for slide in outline.slides[1:]:
        if slide.visual.kind != "none":
            continue
        supported = set().union(*(evidence.get(ref, set()) for ref in slide.source_refs))
        found = set(comparisons("\n".join([slide.title, *slide.bullets]))) & supported
        if len(found) != 1:
            continue
        before, after, unit = found.pop()
        slide.visual = Visual(
            kind="bar", categories=["До", "После"] if language == "ru" else ["Before", "After"],
            series=[Series(name=slide.title[:100], values=[before, after])], unit=unit,
        )
    return outline
