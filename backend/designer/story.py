"""Source-grounded narrative around canonical analytical slides, without LLM arithmetic."""
import re
from .models import SlideContent


def add_story(slides, sources, limit):
    if not sources or not sources[0].get('_story'):
        return slides
    # Keep every source paragraph; split long paragraphs instead of dropping tails.
    context = []
    for source in sources:
        if source.get('datasets') or source.get('id') == 'brief':
            continue
        paragraphs = [re.sub(r'^#+\s*', '', p.strip()) for p in re.split(r'\n\s*\n', source.get('text', '')) if p.strip()]
        for paragraph in paragraphs:
            for start in range(0, len(paragraph), 420):
                context.append((paragraph[start:start+420], source['id']))
    goal = sources[0]['_story'].get('goal', '').strip()
    intro = SlideContent(title='Задача анализа', bullets=[goal[:420]] if goal else [], source_refs=['brief'])
    opening = [intro.model_dump()]
    for start in range(0, len(context), 3):
        part = context[start:start+3]
        opening.append(SlideContent(title='Контекст и условия' + (f' · {start//3+1}' if len(context)>3 else ''),
            bullets=[p for p, _ in part], source_refs=list(dict.fromkeys(ref for _,ref in part))).model_dump())
    # Summary repeats verified findings verbatim, never invents a recommendation.
    findings = list(dict.fromkeys(s['title'].split(' · часть ')[0] for s in slides if s.get('visual', {}).get('kind') != 'table'))
    closing = []
    for start in range(0,len(findings),4):
        closing.append(SlideContent(title='Выводы по данным', bullets=findings[start:start+4],
            source_refs=list(dict.fromkeys(ref for s in slides for ref in s['source_refs']))).model_dump())
    actions = [(p, ref) for p,ref in context if re.match(r'(?:следующий шаг|действие|рекомендация)\s*:',p,re.I)]
    if actions:
        closing.append(SlideContent(title='Следующие действия',bullets=[p for p,_ in actions[:4]],source_refs=list(dict.fromkeys(ref for _,ref in actions[:4]))).model_dump())
    result = opening + slides + closing
    if len(result)>limit:
        raise ValueError(f'Для истории с полными данными нужно {len(result)} слайдов, выбран лимит {limit}. Увеличьте лимит, сократите материалы или отключите связную историю. Данные не обрезаны')
    return result
