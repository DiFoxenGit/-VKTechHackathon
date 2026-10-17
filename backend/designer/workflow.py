import json
import hashlib
import re
from pathlib import Path

PROMPTS = Path(__file__).parent / "prompts"

def workflow():
    manifest = json.loads((PROMPTS / "manifest.json").read_text())
    manifest["sha256"] = {
        p.name: hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(PROMPTS.iterdir())
        if p.is_file()
    }
    return manifest

def narrative(purpose):
    """Каркас повествования для этого типа презентации.

    Состав слайдов зависит от того, что за презентация: у продукта — рынок и
    ценность, у проекта — статус и риски. Каркас лежит конфигом рядом с промптами
    и версионируется вместе с ними.
    """
    manifest = workflow()
    path = PROMPTS / manifest.get("narratives", "narratives.v1.json")
    if not path.exists():
        return None
    frames = json.loads(path.read_text(encoding="utf-8"))
    return frames.get(purpose)

def narrative_beats():
    """Названия шагов всех каркасов повествования: ими нельзя начинать заголовок.

    От шага берётся часть до двоеточия: у «Что потребуется: ресурсы и сроки»
    это «Что потребуется». Длинные — первыми, чтобы короткий шаг не перехватил
    совпадение у длинного.
    """
    manifest = workflow()
    path = PROMPTS / manifest.get("narratives", "narratives.v1.json")
    if not path.exists():
        return []
    frames = json.loads(path.read_text(encoding="utf-8"))
    beats = set()
    for frame in frames.values():
        # В файле есть служебный "_comment" — это строка, а не каркас.
        if not isinstance(frame, dict):
            continue
        for beat in frame.get("beats") or []:
            head = re.split(r"[:—–]", str(beat))[0].strip()
            if len(head) > 3:
                beats.add(head)
    return sorted(beats, key=len, reverse=True)

