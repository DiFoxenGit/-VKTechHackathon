"""Script checks shared by generation and audit."""

import re

CYRILLIC = re.compile(r"[А-Яа-яЁё]")
LATIN = re.compile(r"[A-Za-z]")
# Units, tickers and abbreviations that stay Latin inside a Russian deck.
LATIN_ALLOWED = {
    "kpi", "it", "ai", "ml", "b2b", "b2c", "api", "sla", "roi", "mvp", "crm", "erp",
    "usd", "eur", "rub", "gb", "tb", "mb", "ms", "vk", "q1", "q2", "q3", "q4", "na",
}


def visual_labels(visual):
    """Every piece of text a viewer reads inside a chart, table or diagram."""
    labels = [*visual.get("categories", []), *visual.get("columns", []), *visual.get("steps", [])]
    labels += [series["name"] for series in visual.get("series", [])]
    labels += [cell for row in visual.get("rows", []) for cell in row]
    if visual.get("unit"):
        labels.append(visual["unit"])
    return [str(label) for label in labels if str(label).strip()]


def foreign_labels(labels, cyrillic_deck):
    """Labels written in the wrong script for this deck.

    The brief asks for one language per deck, and chart labels are exactly where a
    model silently switches back to English. Deterministic: script, not meaning.
    """
    if not cyrillic_deck:
        return []
    found = []
    for label in labels:
        if CYRILLIC.search(label) or not LATIN.search(label):
            continue
        # Digits stay with their word so "Q1" is recognised as an abbreviation.
        words = [
            w
            for w in re.split(r"[^A-Za-z0-9]+", label.lower())
            if w and any(c.isalpha() for c in w)
        ]
        if words and all(word in LATIN_ALLOWED for word in words):
            continue
        found.append(label)
    return found


