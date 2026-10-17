from copy import deepcopy
import math
from ..models import Outline
from .content import numbers_in, tidy_line


def balance_plan(outline, capacity):
    if not math.isfinite(capacity) or capacity <= 0:
        raise ValueError('Slide capacity must be finite and positive')
    heavy = outline_overflow(outline, capacity)
    return {"capacity_chars": capacity, "slides": [
        {"index": index, "title": outline["slides"][index]["title"],
         "bullets": list(outline["slides"][index]["bullets"]),
         "limit_chars": room, "max_bullets": 6}
        for index, room in heavy
    ]}


def apply_condensation(outline, result, payload):
    """Validate the complete AI patch atomically; metadata cannot be replaced."""
    if not isinstance(result, dict) or not isinstance(result.get('slides'), list):
        raise ValueError('Condense must return a slides array')
    allowed = {item['index'] for item in payload['slides']}
    seen = set()
    balanced = deepcopy(outline)
    for item in result['slides']:
        if not isinstance(item, dict) or type(item.get('index')) is not int:
            raise ValueError('Condense slide needs an integer index')
        index = item['index']
        if index not in allowed or index in seen:
            raise ValueError('Condense returned an unknown or duplicate slide')
        seen.add(index)
        slide = balanced['slides'][index]
        title = item.get('title', slide['title'])
        bullets = item.get('bullets')
        if not isinstance(title, str) or not title.strip() or len(title) > 240:
            raise ValueError('Invalid condensed title')
        if not isinstance(bullets, list) or not 1 <= len(bullets) <= 6 or any(
                not isinstance(text, str) or not text.strip() for text in bullets):
            raise ValueError('Invalid condensed bullets')
        original_numbers = numbers_in(slide['title'] + ' ' + ' '.join(slide['bullets']))
        if numbers_in(title + ' ' + ' '.join(bullets)) - original_numbers:
            raise ValueError('Condensation introduced unsupported numbers')
        slide.update(title=tidy_line(title), bullets=[tidy_line(text) for text in bullets])
    if seen != allowed:
        raise ValueError('Condense omitted overloaded slides')
    return Outline.model_validate(balanced).model_dump()


def finish_balance(original, candidate, payload, warnings=None):
    """Keep full original content in speaker notes whenever shortening is needed.

    When notes cannot hold the source, retain the slide and surface overflow to
    the audit rather than silently losing content to a character limit.
    """
    balanced = deepcopy(candidate)
    for item in payload['slides']:
        index, room = item['index'], item['limit_chars']
        slide = balanced['slides'][index]
        before = original['slides'][index]
        if len(slide['title']) + sum(map(len, slide['bullets'])) > room or len(slide['bullets']) > 6:
            trim_slide(slide, room)
        if slide['title'] != before['title'] or slide['bullets'] != before['bullets']:
            full_text = '\n'.join([before['title'], *before['bullets']])
            notes = '\n\n'.join(filter(None, [before.get('notes', ''), 'Исходное содержание:\n' + full_text]))
            if len(notes) <= 4000:
                slide['notes'] = notes
                message = f'Слайд {index + 1}: текст сокращён, исходное содержание сохранено в заметках.'
            else:
                balanced['slides'][index] = deepcopy(before)
                message = f'Слайд {index + 1}: текст не сокращён — исходное содержание не помещается в заметки. Разделите слайд вручную.'
            if warnings is not None:
                warnings.append(message)
    return balanced

def outline_overflow(outline, capacity, max_bullets=6):
    """Слайды, где текста заметно больше, чем помещается."""
    heavy = []
    for index, slide in enumerate(outline["slides"]):
        text = len(slide["title"]) + sum(len(b) for b in slide["bullets"])
        # Визуализация занимает место: под текст остаётся примерно половина.
        room = capacity if slide["visual"]["kind"] == "none" else capacity * 0.45
        if text > room or len(slide["bullets"]) > max_bullets:
            heavy.append((index, int(room)))
    return heavy

def trim_slide(slide, room, max_bullets=6):
    """Детерминированный запас: подрезать по предложениям, не теряя первых мыслей."""
    bullets = slide["bullets"][:max_bullets]
    budget = max(40, int(room) - len(slide["title"]))
    kept = []
    for bullet in bullets:
        if budget <= 0:
            break
        if len(bullet) > budget:
            cut = bullet[:budget].rstrip()
            cut = cut[: cut.rfind(" ")] if " " in cut else cut
            if len(cut) >= 20:
                kept.append(cut)
            break
        kept.append(bullet)
        budget -= len(bullet)
    slide["bullets"] = kept or bullets[:1]
    return slide

