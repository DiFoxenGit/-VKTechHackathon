import asyncio
import json

import httpx
import pytest

from designer import ai
from designer.inference import (fallback_settings, inference_route,
                                reset_inference_route)
from designer import text_genapi

CHAT = {"choices": [{"finish_reason": "stop", "message": {"content": '{"ok":true}'}}]}


@pytest.fixture(autouse=True)
def profiles(monkeypatch):
    import os
    for name in list(os.environ):
        if name.startswith(("DESIGNER_LLM_", "DESIGNER_VK_", "DESIGNER_FALLBACK_")):
            monkeypatch.delenv(name)
    for k, v in {"LLM_PROVIDER":"vk", "VK_BASE_URL":"https://vk.invalid/v1",
                 "VK_MODEL":"qwen38-27b-fp8", "VK_API_KEY":"vk-private",
                 "VK_PROJECT_ID":"project-private", "FALLBACK_PROVIDER":"genapi",
                 "FALLBACK_MODEL":"gemma-4-31b", "FALLBACK_API_KEY":"fallback-private"}.items():
        monkeypatch.setenv("DESIGNER_" + k, v)
    reset_inference_route()


@pytest.fixture
def transport(monkeypatch):
    real = httpx.AsyncClient
    def install(handler):
        requests = []
        def capture(r):
            requests.append(r)
            return handler(r)
        monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(capture), **kw))
        return requests
    return install


def test_vk_first_then_genapi_uses_separate_credentials_and_records_actual_model(transport):
    requests = transport(lambda r: httpx.Response(500, json={"error":"vk-private"})
                         if r.url.host == "vk.invalid" else httpx.Response(200, json={"response":[CHAT]}))
    async def call():
        answer = await ai.ask([{"role":"user", "content":"JSON"}])
        return answer, inference_route()
    answer, route = asyncio.run(call())
    assert json.loads(answer) == {"ok":True}
    assert route == {"primary":"vk", "provider":"genapi", "model":"gemma-4-31b", "fallback_used":True}
    assert [r.url.host for r in requests] == ["vk.invalid", "api.gen-api.ru"]
    assert requests[0].headers['Authorization'] == 'Bearer vk-private'
    assert requests[0].headers['Project-ID'] == 'project-private'
    assert requests[1].headers['Authorization'] == 'Bearer fallback-private'
    assert 'Project-ID' not in requests[1].headers
    body = json.loads(requests[1].content)
    assert body['model'] == 'gemma-4-31b' and body['is_sync'] is True
    assert 'callback_url' not in body
    assert body['messages'] == [{"role":"user", "content":"JSON"}]


def test_vk_success_does_not_call_paid_fallback(transport):
    requests = transport(lambda r: httpx.Response(200, json=CHAT))
    async def call():
        await ai.ask([])
        return inference_route()
    assert asyncio.run(call())["fallback_used"] is False
    assert len(requests) == 1


@pytest.mark.parametrize('status', [408,429,500,502,503])
def test_retryable_vk_errors_use_fallback(status, transport):
    requests = transport(lambda r: httpx.Response(status) if r.url.host=='vk.invalid'
                         else httpx.Response(200,json={'response':[CHAT]}))
    assert json.loads(asyncio.run(ai.ask([]))) == {'ok':True}
    assert len(requests)==2


@pytest.mark.parametrize('status', [400,401,403,422])
def test_nonretryable_vk_errors_do_not_hide_configuration_problems(status, transport):
    requests = transport(lambda r: httpx.Response(status))
    with pytest.raises(httpx.HTTPStatusError): asyncio.run(ai.ask([]))
    assert len(requests)==1


def test_network_timeout_switches_once(transport):
    def handler(r):
        if r.url.host=='vk.invalid': raise httpx.ReadTimeout('private details',request=r)
        return httpx.Response(200,json={'response':[CHAT]})
    requests=transport(handler)
    asyncio.run(ai.ask([]))
    assert len(requests)==2


def test_invalid_primary_json_uses_fallback(transport):
    broken={'choices':[{'message':{'content':'not JSON'}}]}
    requests=transport(lambda r: httpx.Response(200,json=broken if r.url.host=='vk.invalid' else {'response':[CHAT]}))
    assert json.loads(asyncio.run(ai.ask([]))) == {'ok':True}
    assert len(requests)==2


def test_fallback_disabled_is_backward_compatible(monkeypatch,transport):
    monkeypatch.delenv('DESIGNER_FALLBACK_PROVIDER')
    requests=transport(lambda r: httpx.Response(500))
    with pytest.raises(httpx.HTTPStatusError): asyncio.run(ai.ask([]))
    assert len(requests)==1


@pytest.mark.parametrize('field,value', [('MODEL','qwen-max'),('API_KEY',''),('TIMEOUT','nan'),('MAX_TOKENS','1024')])
def test_invalid_fallback_configuration_fails_without_request(field,value,monkeypatch):
    from fastapi import HTTPException
    monkeypatch.setenv('DESIGNER_FALLBACK_'+field,value)
    with pytest.raises(HTTPException): fallback_settings()


def test_genapi_async_response_is_polled_without_reposting(transport,monkeypatch):
    async def no_wait(_): pass
    monkeypatch.setattr(text_genapi.asyncio,'sleep',no_wait)
    requests=transport(lambda r: httpx.Response(200,json={'request_id':7,'status':'processing'}) if r.method=='POST'
                       else httpx.Response(200,json={'status':'success','full_response':[CHAT]}))
    assert asyncio.run(text_genapi.generate([],fallback_settings())) == CHAT
    assert [r.method for r in requests]==['POST','GET']


def test_genapi_failure_hides_body_and_does_not_retry(transport):
    requests=transport(lambda r: httpx.Response(500,json={'error':'fallback-private'}))
    with pytest.raises(text_genapi.GenApiTextError) as error:
        asyncio.run(text_genapi.generate([],fallback_settings()))
    assert str(error.value)=='GenAPI text HTTP 500' and len(requests)==1


def test_genapi_timeout_does_not_resubmit(transport,monkeypatch):
    monkeypatch.setenv('DESIGNER_FALLBACK_TIMEOUT','0.01')
    requests=transport(lambda r: httpx.Response(200,json={'request_id':7}))
    with pytest.raises(text_genapi.GenApiTextError,match='timed out'):
        asyncio.run(text_genapi.generate([],fallback_settings()))
    assert len(requests)==1


def test_parallel_calls_keep_inference_route_isolated(transport):
    transport(lambda r: httpx.Response(500) if r.url.host=='vk.invalid' else httpx.Response(200,json={'response':[CHAT]}))
    async def call():
        async def generation():
            await ai.ask([])
            return inference_route()['fallback_used']
        reset_inference_route()
        values=await asyncio.gather(generation(),generation())
        assert inference_route() is None
        return values
    assert asyncio.run(call())==[True,True]
