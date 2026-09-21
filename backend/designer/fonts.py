"""Resolve template fonts and check real character maps without rendering text."""

import io
import os
import struct
import unicodedata
from functools import lru_cache
from pathlib import Path

from fontTools.ttLib import TTCollection, TTFont, TTLibError


CYRILLIC = "АБВГДЕЁЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯабвгдеёжзийклмнопрстуфхцчшщъыьэюя"
# Used only when neither an embedded nor an installed font can be inspected.
LATIN_ONLY = ("poppins", "lato", "bebas neue", "raleway dots")
KNOWN_CYRILLIC = ("arial", "calibri", "aptos", "times new roman", "verdana", "tahoma", "dejavu sans", "liberation sans", "noto sans")


def resolve_font(name, scheme=None):
    if not name or not name.startswith("+"):
        return name
    scheme = scheme or {}
    family = "major" if name.startswith("+mj") else "minor"
    script = {"lt": "latin", "cs": "cs", "ea": "ea"}.get(name[-2:], "latin")
    fonts = scheme.get(family, {})
    return fonts.get(script) or fonts.get("latin") or None


def _ranges(points):
    result = []
    for point in sorted(points):
        if result and point == result[-1][1] + 1:
            result[-1][1] = point
        else:
            result.append([point, point])
    return result


def _font_record(font, source):
    names = set()
    for record in font["name"].names:
        if record.nameID in (1, 4, 6, 16):
            try:
                names.add(record.toUnicode())
            except (UnicodeError, AttributeError):
                pass
    points = set((font.getBestCmap() or {}).keys())
    return names, {"source": source, "ranges": _ranges(points), "cyrillic": all(ord(c) in points for c in CYRILLIC)}


def embedded_coverage(archive):
    """Read sfnt or uncompressed EOT fonts from PowerPoint's ppt/fonts parts."""
    coverage = {}
    for filename in archive.namelist():
        if not filename.startswith("ppt/fonts/"):
            continue
        raw = archive.read(filename)
        candidates = [raw]
        # EOT FontDataSize occupies bytes 4..7; its sfnt payload is last.
        if len(raw) >= 82 and raw[34:36] == b"LP":
            size = struct.unpack_from("<I", raw, 4)[0]
            if 0 < size <= len(raw) - 82:
                candidates.append(raw[-size:])
        for candidate in candidates:
            try:
                with TTFont(io.BytesIO(candidate), lazy=True) as font:
                    names, record = _font_record(font, "embedded")
                for name in names:
                    coverage[name.casefold()] = record
                break
            except (TTLibError, KeyError, ValueError, struct.error):
                continue
    return coverage


@lru_cache(maxsize=1)
def _system_fonts():
    directories = [Path(os.getenv("WINDIR", "C:/Windows")) / "Fonts", Path(os.getenv("LOCALAPPDATA", "")) / "Microsoft/Windows/Fonts", Path("/usr/share/fonts"), Path("/usr/local/share/fonts"), Path.home() / ".fonts", Path("/System/Library/Fonts"), Path("/Library/Fonts")]
    result = {}
    for directory in directories:
        if not directory.is_dir():
            continue
        for path in directory.rglob("*"):
            if path.suffix.lower() not in (".ttf", ".otf", ".ttc"):
                continue
            collection = None
            fonts = []
            try:
                if path.suffix.lower() == ".ttc":
                    collection = TTCollection(path, lazy=True)
                    fonts = collection.fonts
                else:
                    fonts = [TTFont(path, lazy=True)]
                for font in fonts:
                    names, record = _font_record(font, "system")
                    for name in names:
                        result.setdefault(name.casefold(), record)
            except (OSError, TTLibError, KeyError, ValueError, struct.error):
                continue
            finally:
                if collection:
                    collection.close()
                else:
                    for font in fonts:
                        font.close()
    return result


def font_coverage(name, embedded=None):
    key = (name or "").casefold()
    record = (embedded or {}).get(key) or _system_fonts().get(key)
    if record:
        return record
    if any(key == face or key.startswith(face + " ") for face in LATIN_ONLY):
        return {"source": "known-latin-font", "cyrillic": False}
    if any(key == face or key.startswith(face + " ") for face in KNOWN_CYRILLIC):
        return {"source": "known-cyrillic-font", "cyrillic": True}
    return {"source": "unavailable", "cyrillic": None}


def missing_glyphs(font_name, text, coverage=None):
    """Return only proven unsupported glyphs; unknown fonts are not false errors.

    ``coverage`` accepts the serialized ``tokens.font_coverage`` mapping, so the
    audit sees embedded fonts even when they are not installed on the server.
    """
    record = (coverage or {}).get(font_name) or (coverage or {}).get((font_name or "").casefold()) or font_coverage(font_name)
    characters = sorted({c for c in text if not c.isspace() and unicodedata.category(c) not in ("Cc", "Cf")})
    if "ranges" in record:
        return [c for c in characters if not any(start <= ord(c) <= end for start, end in record["ranges"])]
    if record.get("cyrillic") is False:
        return [c for c in characters if "CYRILLIC" in unicodedata.name(c, "")]
    return []


# Модель любит типографские символы, а фирменные гарнитуры часто их не содержат:
# в Play нет стрелки, в узких шрифтах — знака номера. Пустой прямоугольник на
# слайде виден зрителю, поэтому такой символ заменяется читаемым эквивалентом.
SAFE_SUBSTITUTES = {
    "→": "->",
    "←": "<-",
    "↔": "<->",
    "⇒": "=>",
    "⇐": "<=",
    "×": "x",
    "≤": "<=",
    "≥": ">=",
    "≠": "!=",
    "≈": "~",
    "—": "-",
    "–": "-",
    "…": "...",
    "№": "N",
    "•": "-",
    "·": "-",
    "′": "'",
    "″": '"',
    "«": '"',
    "»": '"',
    "“": '"',
    "”": '"',
    "„": '"',
    "™": "",
    "®": "",
    "©": "",
}


def printable(text, font_name, coverage=None):
    """Текст без символов, которых нет в гарнитуре слайда.

    Замена сама проверяется по той же гарнитуре: если и её нет, символ
    убирается. Переводы строк сохраняются — по ним разделены тезисы.
    """
    if not text:
        return text
    missing = set(missing_glyphs(font_name, text, coverage))
    if not missing:
        return text
    pieces = []
    for char in text:
        if char not in missing:
            pieces.append(char)
            continue
        replacement = SAFE_SUBSTITUTES.get(char, "")
        if replacement and missing_glyphs(font_name, replacement, coverage):
            replacement = ""
        pieces.append(replacement)
    lines = "".join(pieces).split("\n")
    return "\n".join(" ".join(line.split()) for line in lines)


def printable_visual(visual, font_name, coverage=None):
    """Подписи внутри визуализации — тот же текст на слайде, те же правила.

    Данные колоды и записанный файл должны совпадать: аудит и интерфейс
    показывают именно их.
    """
    if not isinstance(visual, dict):
        return visual
    for key in ("categories", "columns", "steps"):
        if visual.get(key):
            visual[key] = [printable(str(v), font_name, coverage) for v in visual[key]]
    if visual.get("rows"):
        visual["rows"] = [
            [printable(str(cell), font_name, coverage) for cell in row]
            for row in visual["rows"]
        ]
    if visual.get("unit"):
        visual["unit"] = printable(str(visual["unit"]), font_name, coverage)
    for series in visual.get("series") or []:
        if series.get("name"):
            series["name"] = printable(str(series["name"]), font_name, coverage)
    return visual


def choose_font(counts, fallback, coverage, language="ru"):
    ordered = [name for name, _ in counts.most_common() if name and name.casefold() not in ("wingdings", "symbol", "webdings")]
    ordered += [name for name in fallback if name and name not in ordered]
    records = {name: coverage.get(name) or font_coverage(name) for name in ordered}
    rejected = []
    for name in ordered:
        if language.startswith("ru") and records[name].get("cyrillic") is False:
            rejected.append(name)
            continue
        return {"selected": name, "reason": "cyrillic_fallback" if rejected else "character_weight", "rejected": rejected, "candidates": [{"font": candidate, "characters": counts.get(candidate, 0), "coverage": records[candidate]["source"]} for candidate in ordered]}
    # A Latin-only template has no usable Cyrillic face. Record the explicit
    # substitution so the audit can distinguish it from an accidental foreign font.
    return {"selected": "Arial", "reason": "no_template_font_with_cyrillic", "rejected": rejected, "candidates": []}
