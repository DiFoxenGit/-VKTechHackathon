"""Explicit style tokens. Text PDFs require named tokens; scans are rejected."""
import copy
import io
import json
import re
import zipfile
from pathlib import Path
from pydantic import Field, field_validator
from .models import StrictModel


class StyleTokens(StrictModel):
    name: str = Field(default="Брендбук", max_length=100)
    colors: list[str] = Field(default_factory=list, max_length=8)
    font: str | None = Field(default=None, max_length=80)
    background: str | None = None
    text_color: str | None = None
    title_size: float | None = Field(default=None, ge=24, le=60)
    body_size: float | None = Field(default=None, ge=17, le=32)

    @field_validator("colors", "background", "text_color")
    @classmethod
    def valid_color(cls, value):
        if value is None:
            return value
        values = value if isinstance(value, list) else [value]
        if any(not re.fullmatch(r"#?[0-9a-fA-F]{6}", v) for v in values):
            raise ValueError("Цвет должен иметь формат #RRGGBB")
        cleaned = [v.lstrip("#").upper() for v in values]
        return cleaned if isinstance(value, list) else cleaned[0]


def parse_brandbook(data, name):
    suffix = Path(name).suffix.lower()
    warnings = []
    if suffix == ".zip":
        from .parsing import check_zip
        check_zip(data)
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            if "brandbook.json" not in archive.namelist():
                raise ValueError("ZIP брендбука должен содержать brandbook.json. Логотипы без правил стиля не определяют брендбук")
            raw = json.loads(archive.read("brandbook.json").decode("utf-8-sig"))
            warnings.append("Применены токены brandbook.json. Размещение логотипов и разбор примеров из ZIP пока не поддерживаются")
    elif suffix == ".json":
        raw = json.loads(data.decode("utf-8-sig"))
    elif suffix == ".pdf":
        from pypdf import PdfReader
        text = "\n".join(p.extract_text() or "" for p in PdfReader(io.BytesIO(data)).pages)
        if not text.strip():
            raise ValueError("Скан брендбука не поддерживается: нужен текстовый PDF или JSON-токены")
        # Deliberately only explicit labels, no guessed semantics or model parsing.
        colors = re.search(r"(?:palette|палитра)\s*:\s*((?:#[0-9a-fA-F]{6}[ ,;]*)+)", text, re.I)
        font = re.search(r"(?:font|шрифт)\s*:\s*([^\r\n]+)", text, re.I)
        if not colors and not font:
            raise ValueError("В PDF не найдены явные строки «Палитра: #RRGGBB, ...» или «Шрифт: ...». Используйте JSON для точного задания стиля")
        raw = dict(name=Path(name).stem, colors=re.findall(r"#[0-9a-fA-F]{6}", colors[1]) if colors else [], font=font[1].strip() if font else None)
        warnings.append("PDF: извлечены только явно подписанные палитра и шрифт; сетка, логотипы и примеры не разобраны")
    else:
        raise ValueError("Поддерживаются JSON-токены, текстовый PDF и ZIP с brandbook.json. .fig не поддерживается; экспортируйте токены Figma в описанную JSON-схему")
    return StyleTokens.model_validate(raw).model_dump(exclude_none=True), warnings


def apply_style(template, brandbook=None, overrides=None):
    if not brandbook and not overrides:
        return template
    tokens = {**(brandbook or {}), **{k: v for k, v in (overrides or {}).items() if v is not None}}
    rules = StyleTokens.model_validate(tokens).model_dump(exclude_none=True)
    result = copy.deepcopy(template)
    result["brandbook"] = rules
    result["branding"] = []
    target = result["tokens"]
    palette = rules.get("colors") or target.get("accents") or target["colors"]
    target.update(colors=palette, accents=palette)
    target.setdefault("theme", {}).update({f"accent{i + 1}": color for i, color in enumerate(palette)})
    background = rules.get("background", "FFFFFF")
    target["colors"] = list(dict.fromkeys([*palette,background,rules.get("text_color","243149"),"000000","FFFFFF"]))
    target["theme"].update(lt1=background, dk1=rules.get("text_color", "243149"))
    if rules.get("font"):
        target["fonts"] = [rules["font"]]
        target["font_choice"] = {role: {"selected": rules["font"]} for role in ("title", "body")}
    for pattern in result.get("patterns", []):
        pattern.update(background=background, background_kind="solid", reserved=[], image_cover=0, decoration_area=0, decoration_count=0, bg_luma=1, bg_spread=0)
        for slot in pattern.get("slots", []):
            if rules.get("font"):
                slot.setdefault("style", {})["font"] = rules["font"]
            size = rules.get("title_size" if slot.get("role") == "title" else "body_size")
            if size:
                slot.setdefault("style", {})["size"] = size
    return result
