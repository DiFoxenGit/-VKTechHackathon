import asyncio
import json

import httpx
import pytest

from designer import ai
from designer import image_genapi as gen

PNG = b"\x89PNG\r\n\x1a\nimage-bytes"
ASSET = "https://gen-api.storage.yandexcloud.net/test.png"


@pytest.fixture
def transport(monkeypatch):
    real_client = httpx.AsyncClient
    requests = []
    def install(handler):
        def dispatch(request):
            requests.append(request)
            return handler(request)
        monkeypatch.setattr(gen.httpx, "AsyncClient", lambda **kw: real_client(transport=httpx.MockTransport(dispatch), **kw))
        monkeypatch.setattr(gen, "POLL_SECONDS", 0)
        return requests
    return install


def test_submit_poll_and_download_without_leaking_key(transport):
    polls = 0
    def handler(request):
        nonlocal polls
        if request.method == "POST": return httpx.Response(200, json={"request_id": 7, "status": "processing"})
        if request.url.host == "api.gen-api.ru":
            polls += 1
            return httpx.Response(200, json={"status": "processing"} if polls == 1 else {"status": "success", "result": [ASSET]})
        return httpx.Response(200, content=PNG)
    requests = transport(handler)
    assert asyncio.run(gen.generate("A blue server, no letters", "1024x1024", "image-secret")) == PNG
    assert len([r for r in requests if r.method == "POST"]) == 1
    body = json.loads(requests[0].content)
    assert body["model"] == "turbo" and body["num_images"] == 1 and body["num_inference_steps"] == 8
    assert body["guidance_scale"] == 0 and body["enable_prompt_expansion"] is False
    assert body["enable_safety_checker"] is True and "callback_url" not in body
    assert (body["width"], body["height"]) == (1024, 1024)
    assert all(r.headers["Authorization"] == "Bearer image-secret" for r in requests[:-1])
    assert "Authorization" not in requests[-1].headers


@pytest.mark.parametrize("response", [
    {"request_id": 3, "status": "success", "output": [{"url": ASSET}]},
    {"request_id": 3, "status": "success", "output": ASSET},
])
def test_immediate_output_does_not_poll(response, transport):
    requests = transport(lambda r: httpx.Response(200, json=response) if r.method == "POST" else httpx.Response(200, content=PNG))
    assert asyncio.run(gen.generate("scene", "1024x1024", "key")) == PNG
    assert len(requests) == 2


@pytest.mark.parametrize("response", [{"request_id": True}, {"request_id": "../user"}, {"request_id": 0}, {"request_id": 1, "status": "failed"}])
def test_invalid_submission_is_never_retried(response, transport):
    requests = transport(lambda r: httpx.Response(200, json=response))
    with pytest.raises(gen.GenApiError): asyncio.run(gen.generate("scene", "1024x1024", "key"))
    assert len(requests) == 1


@pytest.mark.parametrize("url", ["http://127.0.0.1/a.png", "https://169.254.169.254/a", "https://evil.invalid/a.png", "https://key@gen-api.ru/a.png"])
def test_untrusted_result_never_fetched(url, transport):
    requests = transport(lambda r: httpx.Response(200, json={"request_id": 1, "output": [url]}))
    with pytest.raises(gen.GenApiError): asyncio.run(gen.generate("scene", "1024x1024", "key"))
    assert len(requests) == 1


@pytest.mark.parametrize("status", [401, 402, 422, 429, 500])
def test_errors_hide_provider_body_and_do_not_retry(status, transport):
    requests = transport(lambda r: httpx.Response(status, json={"error": "image-secret"}))
    with pytest.raises(gen.GenApiError) as exc: asyncio.run(gen.generate("scene", "1024x1024", "key"))
    assert "image-secret" not in str(exc.value) and len(requests) == 1


def test_download_size_limit(transport, monkeypatch):
    transport(lambda r: httpx.Response(200, json={"request_id": 1, "output": [ASSET]}) if r.method == "POST" else httpx.Response(200, content=PNG))
    monkeypatch.setattr(gen, "MAX_IMAGE_BYTES", 8)
    with pytest.raises(gen.GenApiError, match="exceeds"): asyncio.run(gen.generate("scene", "1024x1024", "key"))


@pytest.mark.parametrize("status", ["failed", "error", "unknown"])
def test_terminal_poll_failure_does_not_resubmit(status, transport):
    requests = transport(lambda r: httpx.Response(200, json={"request_id": 1, "status": "processing"} if r.method == "POST" else {"status": status}))
    with pytest.raises(gen.GenApiError): asyncio.run(gen.generate("scene", "1024x1024", "key"))
    assert len(requests) == 2


@pytest.mark.parametrize("status,content", [(302, b""), (200, b"<html>not an image</html>")])
def test_download_does_not_follow_redirect_or_accept_html(status, content, transport):
    requests = transport(lambda r: httpx.Response(200, json={"request_id": 1, "output": [ASSET]}) if r.method == "POST" else httpx.Response(status, content=content, headers={"Location": "https://evil.invalid/a"}))
    with pytest.raises(gen.GenApiError): asyncio.run(gen.generate("scene", "1024x1024", "key"))
    assert len(requests) == 2 and "Authorization" not in requests[-1].headers


def test_malformed_result_port_is_safe_error():
    with pytest.raises(gen.GenApiError): gen._result_url({"result": ["https://gen-api.ru:bad/a.png"]})


def test_timeout_does_not_resubmit(transport, monkeypatch):
    requests = transport(lambda r: httpx.Response(200, json={"request_id": 1, "status": "processing"}))
    monkeypatch.setattr(gen, "TIMEOUT_SECONDS", .01)
    monkeypatch.setattr(gen, "POLL_SECONDS", .1)
    with pytest.raises(gen.GenApiError, match="timed out"): asyncio.run(gen.generate("scene", "1024x1024", "key"))
    assert len(requests) == 1


@pytest.mark.parametrize("size", ["bad", "1000x1000", "9999x9999", "128x128", "256x256"])
def test_invalid_dimensions_fail_before_charge(size, transport):
    requests = transport(lambda r: pytest.fail("must not call provider"))
    with pytest.raises(gen.GenApiError): asyncio.run(gen.generate("scene", size, "key"))
    assert not requests


def test_profile_uses_image_key_and_keeps_text_settings(monkeypatch):
    monkeypatch.setenv("DESIGNER_IMAGE_PROVIDER", "genapi")
    monkeypatch.setenv("DESIGNER_IMAGE_MODEL", "z-image")
    monkeypatch.delenv("DESIGNER_IMAGE_API_KEY", raising=False)
    monkeypatch.setenv("DESIGNER_LLM_API_KEY", "text-secret")
    assert ai.image_available() is False
    monkeypatch.setenv("DESIGNER_IMAGE_API_KEY", "image-secret")
    assert ai.image_available() is True
    assert ai.image_provider() == (gen.BASE_URL, "z-image")
    async def fake(prompt, size, key):
        assert key == "image-secret"
        return PNG
    monkeypatch.setattr(gen, "generate", fake)
    assert asyncio.run(ai.draw_image("scene")) == PNG
