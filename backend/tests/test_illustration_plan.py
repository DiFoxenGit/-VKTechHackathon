import asyncio
import copy
import io
import json

import pytest
from PIL import Image

from designer.illustration_plan import (eligible, plan_illustrations, target_key, validate_plan)
from test_pipeline import client, template_bytes, wait_job


def content(title='Solar office'):
    return dict(title=title, bullets=['A concise fact'], source_refs=[], visual={'kind': 'none'})


def image(slide=1, placement='left', **kw):
    return dict(slide=slide, placement=placement, style='photo',
                prompt='A modern office surrounded by trees, entire building visible', **kw)


def test_validated_plan_keeps_count_scene_and_placement():
    slides = [content(), content('Closing')]
    plan = validate_plan({'images': [image(), image(2, 'right')], 'reason': 'Two requested scenes'}, slides, 2)
    assert len(plan.images) == 2 and plan.images[0].placement == 'left'
    assert plan.images[1].slide == 2
    assert validate_plan({'images': [], 'reason': 'No new imagery requested'}, slides, 2).images == []


@pytest.mark.parametrize('style', ['photorealistic', 'photograph', 'photography', 'Фотография'])
def test_unambiguous_photo_names_are_normalized(style):
    plan = validate_plan(dict(images=[{**image(), 'style': style}], reason='Photo'), [content()], 1)
    assert plan.images[0].style == 'photo'


@pytest.mark.parametrize('images,limit', [([image(3)], 2), ([image()], 0),
    ([image(), image()], 2), ([image(placement='background')], 2),
    ([image(), image(placement='right')], 2), ([{**image(), 'slide': True}], 2),
    ([{**image(), 'url': 'https://untrusted.invalid'}], 2)])
def test_invalid_plan_rejected_before_paid_generation(images, limit):
    with pytest.raises(ValueError):
        validate_plan(dict(images=images, reason='Test'), [content(), content()], limit)


def test_data_and_dense_slides_are_protected():
    chart = {**content(), 'visual': {'kind': 'bar'}}
    dense = {**content(), 'bullets': ['Long text'] * 5}
    for slide in [chart, dense]:
        assert not eligible(slide)
        with pytest.raises(ValueError):
            validate_plan(dict(images=[image()], reason='Test'), [slide], 1)


def test_planner_receives_brief_budget_and_eligibility_once(monkeypatch):
    from designer import ai
    calls = []
    async def complete(messages, validate, **kw):
        calls.append((json.loads(messages[1]['content']), kw))
        return validate(dict(images=[image()], reason='User requested a photograph on the cover'))
    monkeypatch.setattr(ai, 'complete_json', complete)
    plan = asyncio.run(plan_illustrations('One photo on cover, on the left', [content()], 2, True))
    assert len(plan.images) == 1 and len(calls) == 1
    payload, kwargs = calls[0]
    assert payload['brief'].startswith('One photo') and payload['slides'][0]['eligible']
    assert payload['max_images'] == 2 and kwargs['attempts'] == 1
    assert payload['response_schema']['$defs']['Illustration']['properties']['style']['enum'] == ['illustration', 'photo']


def test_optional_plan_cannot_change_content_inference_route():
    from designer.inference import Inference, record_inference, inference_route, isolated_inference_route
    primary = Inference(profile='vk', url='https://vk.invalid', model='content', key='private')
    secondary = Inference(profile='genapi', url='https://api.invalid', model='planner', key='private')
    record_inference(primary, primary)
    with isolated_inference_route():
        record_inference(secondary, primary)
        assert inference_route()['model'] == 'planner'
    assert inference_route()['model'] == 'content'


def test_generation_uses_planned_scenes_without_changing_source(tmp_path, monkeypatch):
    from designer import ai
    from designer.ai_assets import generate_illustrations
    monkeypatch.setenv('DESIGNER_IMAGE_MODEL', 'fixture')
    monkeypatch.setenv('DESIGNER_IMAGE_BASE_URL', 'https://images.invalid/v1')
    prompts = []
    async def draw(prompt, size=None):
        prompts.append(prompt)
        buf = io.BytesIO(); Image.new('RGB', (128, 128), 'blue').save(buf, format='PNG')
        return buf.getvalue()
    monkeypatch.setattr(ai, 'draw_image', draw)
    slides = [content(), content('Final')]; original = copy.deepcopy(slides)
    plan = dict(images=[image(), image(2, 'right')], reason='Two scenes')
    metas = asyncio.run(generate_illustrations(slides, {'accent': '#0077FF'}, tmp_path, 'a' * 32, limit=2, plan=plan))
    assert len(prompts) == len(metas) == 2 and slides == original
    assert 'entire building visible' in prompts[0] and 'photo' in prompts[0]
    assert metas[0]['placement'] == 'left' and metas[1]['target_key'] == target_key(slides[1])
    assert asyncio.run(generate_illustrations(slides, {}, tmp_path, 'a' * 32, plan=dict(images=[], reason='No images'))) == []
    assert len(prompts) == 2


@pytest.mark.parametrize('variant', ['classic', 'split', 'focus'])
def test_cover_final_gallery_and_left_placement_survive_layout(variant):
    from designer.assets import library
    from designer.layout import compose
    from test_pipeline import template_bytes
    from designer.parsing import parse_template
    template = parse_template(template_bytes(), 'fixture.pptx')
    slides = [content('Cover'), content('Closing')]
    base = next(a for a in library() if a['kind'] == 'illustration')
    assets = [{**base, 'id': f'new{i}', 'source': 'generated', 'target_key': target_key(slides[0]),
               'placement': 'left', 'ref': f'generated:{"a" * 32}:new{i}.png'} for i in range(2)]
    assets.append({**base, 'id': 'final', 'source': 'generated', 'target_key': target_key(slides[1]),
                   'placement': 'right'})
    deck = compose(dict(title='Test', slides=slides), template, variant, assets)
    pics = [e for e in deck['slides'][0]['elements'] if e.get('asset', {}).get('source') == 'generated']
    assert len(pics) == 2
    assert pics[0]['box'][1] + pics[0]['box'][3] <= pics[1]['box'][1]
    body = next(e for e in deck['slides'][0]['elements'] if e.get('id') in {'body', 'lead'})
    assert all(e['box'][0] + e['box'][2] <= body['box'][0] for e in pics)
    assert any(e.get('asset', {}).get('id') == 'final' for e in deck['slides'][1]['elements'])


@pytest.mark.parametrize('mode,invalid,expected', [(None, False, 2), (False, False, 0), (None, True, 0)])
def test_service_plans_once_shares_images_and_exports(client, monkeypatch, mode, invalid, expected):
    from designer import ai
    from pptx import Presentation
    monkeypatch.setenv('DESIGNER_IMAGE_MODEL', 'fixture')
    monkeypatch.setenv('DESIGNER_IMAGE_BASE_URL', 'https://images.invalid/v1')
    monkeypatch.delenv('DESIGNER_VLM_MODEL', raising=False)
    calls, draws = [], []
    async def ask(messages):
        calls.append(messages)
        return json.dumps(dict(images=[image(30 if invalid else 1), image(3, 'right')], reason='Two scenes on requested pages'))
    async def draw(prompt, size=None):
        draws.append(prompt); stream = io.BytesIO()
        Image.new('RGB', (160, 100), 'red' if len(draws) == 1 else 'blue').save(stream, format='PNG')
        return stream.getvalue()
    monkeypatch.setattr(ai, 'ask', ask); monkeypatch.setattr(ai, 'draw_image', draw)
    template = client.post('/api/v1/templates', files={'file': ('fixture.pptx', template_bytes())}).json()
    request = dict(template_id=template['id'], brief='Two photographs: cover left and closing right',
                   slide_count=3, outline=dict(title='Test', slides=[content('Cover'), content('Middle'), content('Closing')]))
    if mode is not None: request['generate_images'] = mode
    job = wait_job(client, client.post('/api/v1/generations', json=request).json()['id'])
    assert len(calls) == (0 if mode is False else 1)
    assert len(draws) == expected
    for identifier in job['presentation_ids']:
        record = client.get('/api/v1/presentations/' + identifier).json()
        pictures = [e for slide in record['deck']['slides'] for e in slide['elements']
                    if e.get('asset', {}).get('source') == 'generated']
        assert len(pictures) == expected
        assert record['image_generation']['status'] == ('failed' if invalid else 'ready' if expected else 'not_requested')
        if expected:
            assert len(record['image_generation']['plan']['images']) == 2
            pptx = client.get(f'/api/v1/presentations/{identifier}/export/pptx')
            assert pptx.status_code == 200
            assert len(Presentation(io.BytesIO(pptx.content)).slides) == 3
