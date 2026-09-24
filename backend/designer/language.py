"""Script checks shared by generation and audit."""

import re

CYRILLIC = re.compile(r"[А-Яа-яЁё]")
LATIN = re.compile(r"[A-Za-z]")
# Units, tickers and abbreviations that stay Latin inside a Russian deck.
LATIN_ALLOWED = {
    "kpi", "it", "ai", "ml", "b2b", "b2c", "api", "sla", "roi", "mvp", "crm", "erp",
    "usd", "eur", "rub", "gb", "tb", "mb", "ms", "vk", "q1", "q2", "q3", "q4", "na",
}


def technical_token(word):
    """Имя продукта или технический токен, который не меняет язык слайда.

    «vCPU», «gpt-oss-20b», «OpenAI», «VK» живут в русском тексте на своих местах
    и не делают слайд английским. Отличаем их по написанию, а не по словарю:
    цифра внутри, заглавная буква не на первом месте, аббревиатура целиком
    заглавными или знакомая единица измерения.
    """
    if not word:
        return True
    if word.lower() in LATIN_ALLOWED:
        return True
    if any(character.isdigit() for character in word):
        return True
    if word.isupper() and len(word) <= 5:
        return True
    return any(character.isupper() for character in word[1:])


def script_of(text):
    """Язык текста по письменности: "ru", "en" или None, если сказать нечего.

    Считаются только слова, которые действительно что-то говорят о языке:
    названия продуктов и технические токены выбрасываются.
    """
    if CYRILLIC.search(text):
        return "ru"
    words = [
        word
        for word in re.split(r"[^A-Za-zА-Яа-яЁё0-9_.-]+", text)
        if word and any(character.isalpha() for character in word)
    ]
    prose = [word for word in words if not technical_token(word)]
    return "en" if len(prose) >= 3 else None


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
        # Регистр сохраняется: по нему technical_token узнаёт «CPU», «vCPU» и
        # «gpt-oss-20b» — термины, которые промпт прямо разрешает писать
        # латиницей. Раньше проверка сверялась только со словарём сокращений и
        # отправляла модель переделывать подписи, в которых всё было верно.
        # Типографика ставит в «gpt‑oss‑20b» неразрывный дефис: для проверки он
        # такой же дефис, иначе название модели распадается на «gpt» и «oss».
        plain = re.sub(r"[\u2010-\u2015]", "-", label)
        words = [
            w
            for w in re.split(r"[^A-Za-z0-9_.-]+", plain)
            if w and any(c.isalpha() for c in w)
        ]
        if words and all(technical_token(word) for word in words):
            continue
        found.append(label)
    return found


