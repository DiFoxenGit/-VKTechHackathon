"""Optional model enrichment for the deterministic asset library."""
import hashlib
import logging
from pathlib import Path
from .assets import (illustration_targets, illustration_prompt, inspect_image,
                     words, tag_roots, save_assets, contact_sheet, TAG_BATCH)
LOGGER = logging.getLogger("designer.ai_assets")

async def generate_illustrations(slides, palette, folder: Path, owner, limit=3, size=None):
    """Нарисовать иллюстрации к слайдам и сохранить их как ассеты колоды.

    Возвращает метаданные в том же виде, в каком их отдаёт библиотека: вёрстка
    подбирает картинку по тегам, а теги здесь — слова самого слайда, поэтому
    сгенерированная картинка встаёт именно на тот слайд, для которого нарисована.
    Ошибка генератора не роняет колоду: слайд просто останется без картинки.
    """
    import asyncio

    from .ai import draw_image, image_available

    if not image_available():
        return []
    targets = illustration_targets(slides, limit)
    if not targets:
        return []

    async def one(index, content):
        prompt = illustration_prompt(content.get("title"), content.get("bullets"), palette)
        try:
            blob = await draw_image(prompt, size)
            info = inspect_image(blob)
        except Exception as exc:  # noqa: BLE001 - без картинки слайд собирается как раньше
            LOGGER.warning("Illustration for slide %s failed (%s)", index, type(exc).__name__)
            return None
        identifier = hashlib.sha256(blob).hexdigest()[:24]
        label = [w for w in words(content.get("title") or "") if len(w) > 2][:5]
        return (
            {
                "id": identifier,
                "kind": "illustration",
                "format": "png",
                "file": f"{identifier}.png",
                "ratio": round((info["w"] or 1) / (info["h"] or 1), 4),
                "mono": False,
                "color": info.get("color"),
                "slide": index,
                "target_title": content.get('title', ''),
                "label": label,
                "tags": tag_roots(label),
                "prompt": prompt,
            },
            blob,
        )

    drawn = await asyncio.gather(*(one(index, content) for index, content in targets))
    harvested = [item for item in drawn if item]
    if not harvested:
        return []
    metas = save_assets(folder, harvested)
    for meta in metas:
        meta["source"] = "generated"
        meta["family"] = "generated:" + owner
        meta["ref"] = f"generated:{owner}:{meta['file']}"
    return metas


async def drop_lettered(metas, folder: Path):
    """Убрать картинки, на которых генератор всё-таки написал текст.

    Буквы на иллюстрации — это чужой язык, опечатки и бессмысленные слова рядом
    с выверенным текстом слайда. Проверяет мультимодальная модель, та же, что
    смотрит слайды в аудите; без неё картинки остаются как есть.
    """
    import asyncio

    from .ai import PROMPTS, vision_available, vision_completion, workflow

    if not metas or not vision_available():
        return metas
    agent = workflow()["agents"].get("image_check")
    if not agent:
        return metas
    prompt = (PROMPTS / agent).read_text(encoding="utf-8")

    async def check(meta):
        try:
            answer = await vision_completion(
                prompt, {"id": meta["id"]}, (folder / meta["file"]).read_bytes()
            )
        except Exception as exc:  # noqa: BLE001 - проверка не должна ронять колоду
            LOGGER.warning("Cannot check illustration %s: %s", meta["id"], exc)
            return True
        return not bool(answer.get("has_text"))

    keep = await asyncio.gather(*(check(meta) for meta in metas))
    clean = []
    for meta, ok in zip(metas, keep):
        if ok:
            clean.append(meta)
            continue
        LOGGER.info("Illustration %s dropped: generator wrote text on it", meta["id"])
        (folder / meta["file"]).unlink(missing_ok=True)
    return clean


async def tag_assets(assets, load, budget=None):
    """Подписать картинки шаблона: что на них изображено, по-русски.

    Без подписи иконку не подобрать к тезису. Модель видит лист из 16
    пронумерованных картинок и возвращает по два-четыре слова на каждую.
    Картинки, которые не удалось подписать, помечаются и больше не отправляются.
    `load(meta)` возвращает байты картинки.
    """
    import asyncio

    from .ai import PROMPTS, vision_available, vision_completion, workflow

    if not vision_available():
        return 0
    pending = [a for a in assets if not a.get("tags") and not a.get("tag_tried")]
    if budget is not None:
        pending = pending[:budget]
    if not pending:
        return 0
    prompt = (PROMPTS / workflow()["agents"]["assets"]).read_text()
    limit = asyncio.Semaphore(4)
    tagged = 0

    async def batch(items):
        nonlocal tagged
        blobs = []
        for meta in items:
            try:
                blobs.append((load(meta), meta.get("mono")))
            except OSError:
                blobs.append((b"", False))
        sheet = contact_sheet(blobs)
        async with limit:
            try:
                answer = await vision_completion(prompt, {"count": len(items)}, sheet)
            except Exception as exc:  # noqa: BLE001 - подписи не критичны для колоды
                LOGGER.warning("Asset tagging failed: %s", exc)
                answer = {}
        entries = answer.get("items") if isinstance(answer, dict) else None
        by_number = {}
        for entry in entries or []:
            if isinstance(entry, dict) and isinstance(entry.get("n"), int):
                by_number[entry["n"]] = [str(t)[:40] for t in entry.get("tags") or []][:5]
        for number, meta in enumerate(items, start=1):
            meta["tag_tried"] = True
            label = by_number.get(number) or []
            if label:
                meta["label"] = label
                meta["tags"] = tag_roots(label)
                tagged += 1

    await asyncio.gather(
        *(batch(pending[i : i + TAG_BATCH]) for i in range(0, len(pending), TAG_BATCH))
    )
    return tagged
