"""Validated model decisions; geometry and paid generation remain deterministic."""
import hashlib
import json
from typing import Literal

from pydantic import Field, StrictInt, model_validator, field_validator

from .models import StrictModel


class Illustration(StrictModel):
    slide: StrictInt = Field(ge=1, le=30)
    prompt: str = Field(min_length=20, max_length=1600)
    placement: Literal['left', 'right']
    style: Literal['illustration', 'photo']

    @field_validator('style', mode='before')
    @classmethod
    def normalize_photo_style(cls, value):
        aliases = {'photorealistic': 'photo', 'photograph': 'photo', 'photography': 'photo',
                   'photorealistic photograph': 'photo', 'фото': 'photo', 'фотография': 'photo'}
        return aliases.get(value.casefold().strip(), value) if isinstance(value, str) else value


class IllustrationPlan(StrictModel):
    images: list[Illustration] = Field(max_length=12)
    reason: str = Field(min_length=1, max_length=600)

    @model_validator(mode='after')
    def coherent(self):
        for slide in {x.slide for x in self.images}:
            items = [x for x in self.images if x.slide == slide]
            if len(items) > 2 or len({x.placement for x in items}) != 1:
                raise ValueError('At most two images sharing one side per slide')
        if len({(x.slide, x.prompt.casefold()) for x in self.images}) != len(self.images):
            raise ValueError('Duplicate illustration')
        return self


def target_key(content):
    data = {k: content.get(k) for k in ('title', 'bullets', 'source_refs')}
    return hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def eligible(content):
    return (content.get('role') != 'cover' and (content.get('visual') or {}).get('kind', 'none') == 'none'
            and len(content.get('bullets') or []) <= 4
            and sum(map(len, content.get('bullets') or [])) <= 800)


def validate_plan(value, slides, limit):
    plan = IllustrationPlan.model_validate(value)
    if len(plan.images) > limit:
        raise ValueError('Image plan exceeds server budget')
    for image in plan.images:
        if image.slide > len(slides) or not eligible(slides[image.slide - 1]):
            raise ValueError('Image targets a missing, dense or data slide')
    return plan


async def plan_illustrations(brief, slides, limit, requested=None, language='ru'):
    from .ai import complete_json, PROMPTS, workflow
    prompt = (PROMPTS / workflow()['agents']['illustration_plan']).read_text(encoding='utf-8')
    payload = dict(brief=brief, language=language, max_images=limit,
                   response_schema=IllustrationPlan.model_json_schema(),
                   mode='required' if requested is True else 'auto',
                   slides=[dict(number=i + 1, title=s['title'], bullets=s.get('bullets', []),
                                eligible=eligible(s), visual=(s.get('visual') or {}).get('kind', 'none'))
                           for i, s in enumerate(slides)])
    return await complete_json([{'role': 'system', 'content': prompt},
                                {'role': 'user', 'content': json.dumps(payload, ensure_ascii=False)}],
                               validate=lambda v: validate_plan(v, slides, limit),
                               agent='illustration_plan', attempts=1)
