"""Schema failures must use bounded, validated recovery without paid loops."""
import asyncio
import json

import httpx
import pytest
from fastapi import HTTPException

from designer import ai
from designer.inference import inference_route
from designer.inference_trace import capture_inference, validated_content
from designer.models import Visual
from test_text_fallback import profiles, transport, CHAT


def test_diagram_schema_exposes_conditional_step_requirement():
    schema = Visual.model_json_schema()
    rule = next(rule for rule in schema['allOf'] if 'process' in rule['if']['properties']['kind']['enum'])
    assert rule['then']['required'] == ['steps']
    assert rule['then']['properties']['steps']['minItems'] == 1
    for kind in rule['if']['properties']['kind']['enum']:
        with pytest.raises(ValueError, match='Step diagrams require steps'):
            Visual(kind=kind)
        assert Visual(kind=kind, steps=['Подтверждённый этап']).steps
    assert Visual().kind == 'none'


def test_invalid_vk_content_switches_on_final_attempt_and_validates_reserve(transport, monkeypatch):
    monkeypatch.setattr(ai, 'RETRY_DELAY', 0)
    requests = transport(lambda r: httpx.Response(200, json=CHAT if r.url.host == 'vk.invalid'
        else {'response': [{**CHAT, 'choices': [{'message': {'content': '{"ok":true,"verified":true}'}}]}]}))
    def validate(value):
        if not value.get('verified'):
            raise ValueError('Missing verified content')
        return value
    async def run():
        with capture_inference() as trace:
            result = await ai.complete_json([], validate=validate, attempts=3)
            return result, trace, inference_route()
    result, trace, route = asyncio.run(run())
    assert result['verified'] and route['fallback_used']
    assert [r.url.host for r in requests] == ['vk.invalid', 'vk.invalid', 'api.gen-api.ru']
    assert validated_content(trace) and trace['provider'] == 'genapi'
    assert [c['validation'] for c in trace['calls']] == ['failed', 'failed', 'passed']
    assert trace['provider_fallback_reason'] == 'invalid_response'
    assert 'private' not in json.dumps(trace)


def test_invalid_reserve_content_is_not_paid_for_again(transport, monkeypatch):
    monkeypatch.setattr(ai, 'RETRY_DELAY', 0)
    requests = transport(lambda r: httpx.Response(500) if r.url.host == 'vk.invalid'
        else httpx.Response(200, json={'response': [CHAT]}))
    def reject(value):
        raise ValueError('Missing verified content')
    with pytest.raises(HTTPException):
        asyncio.run(ai.complete_json([], validate=reject, attempts=3))
    assert len(requests) == 2


def test_recovered_vk_reply_does_not_call_reserve(transport, monkeypatch):
    monkeypatch.setattr(ai, 'RETRY_DELAY', 0)
    calls = 0
    def handler(request):
        nonlocal calls
        calls += 1
        value = {'ok': True, 'verified': calls > 1}
        return httpx.Response(200, json={'choices': [{'message': {'content': json.dumps(value)}}]})
    requests = transport(handler)
    def validate(value):
        if not value['verified']:
            raise ValueError('Missing verified content')
        return value
    assert asyncio.run(ai.complete_json([], validate=validate))['verified']
    assert [r.url.host for r in requests] == ['vk.invalid', 'vk.invalid']


def test_missing_diagram_steps_recover_via_same_visual_validator(transport, monkeypatch):
    monkeypatch.setattr(ai, 'RETRY_DELAY', 0)
    def handler(request):
        visual = ({'kind': 'process', 'categories': ['Подготовка']} if request.url.host == 'vk.invalid'
                  else {'kind': 'process', 'steps': ['Подготовка', 'Проверка']})
        chat = {'choices': [{'message': {'content': json.dumps(visual)}}]}
        return httpx.Response(200, json=chat if request.url.host == 'vk.invalid' else {'response': [chat]})
    requests = transport(handler)
    result = asyncio.run(ai.complete_json([], validate=Visual.model_validate))
    assert result.kind == 'process' and result.steps == ['Подготовка', 'Проверка']
    assert len(requests) == 3 and requests[-1].url.host == 'api.gen-api.ru'


def test_no_configured_reserve_keeps_bounded_primary_retries(transport, monkeypatch):
    monkeypatch.delenv('DESIGNER_FALLBACK_PROVIDER')
    monkeypatch.setattr(ai, 'RETRY_DELAY', 0)
    requests = transport(lambda request: httpx.Response(200, json=CHAT))
    def reject(value):
        raise ValueError('Missing verified content')
    with pytest.raises(HTTPException):
        asyncio.run(ai.complete_json([], validate=reject))
    assert len(requests) == 3 and all(r.url.host == 'vk.invalid' for r in requests)
