import asyncio
import json

import httpx
import pytest
from fastapi import HTTPException

from designer import generation
from designer.inference import llm_settings, require_llm


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    import os
    for name in list(os.environ):
        if name.startswith(("DESIGNER_LLM_", "DESIGNER_VK_", "DESIGNER_VLM_")):
            monkeypatch.delenv(name)
    monkeypatch.setenv("DESIGNER_LLM_BASE_URL", "https://old.invalid/v1")
    monkeypatch.setenv("DESIGNER_LLM_MODEL", "old-model")
    monkeypatch.setenv("DESIGNER_LLM_API_KEY", "old-key")
    monkeypatch.setenv("DESIGNER_VK_BASE_URL", "https://vk.invalid/v1/")
    monkeypatch.setenv("DESIGNER_VK_MODEL", "issued-model-id")
    monkeypatch.setenv("DESIGNER_VK_API_KEY", "vk-test-key")


@pytest.mark.parametrize("profile", ["openai", "vk"])
def test_request_uses_whole_selected_profile(monkeypatch, profile):
    monkeypatch.setenv("DESIGNER_LLM_PROVIDER", profile)
    captured = []
    real_client = httpx.AsyncClient

    def handler(request):
        captured.append(request)
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"ok":true}'}}]})

    monkeypatch.setattr(generation.httpx, "AsyncClient", lambda **kw: real_client(
        transport=httpx.MockTransport(handler), **kw))
    assert json.loads(asyncio.run(generation.ask([{"role": "user", "content": "JSON"}]))) == {"ok": True}
    request = captured[0]
    assert str(request.url) == ("https://vk.invalid/v1/chat/completions" if profile == "vk" else "https://old.invalid/v1/chat/completions")
    assert request.headers["Authorization"] == ("Bearer vk-test-key" if profile == "vk" else "Bearer old-key")
    payload = json.loads(request.content)
    assert payload["model"] == ("issued-model-id" if profile == "vk" else "old-model")
    assert payload["response_format"] == {"type": "json_object"}
    assert payload["max_tokens"] == 14000
    assert request.extensions["timeout"]["read"] == 150


def test_vk_options_and_vision_override(monkeypatch):
    monkeypatch.setenv("DESIGNER_LLM_PROVIDER", "vk")
    monkeypatch.setenv("DESIGNER_VK_MAX_TOKENS", "4096")
    monkeypatch.setenv("DESIGNER_VK_TIMEOUT", "75")
    monkeypatch.setenv("DESIGNER_VK_JSON_MODE", "0")
    settings = require_llm()
    assert (settings.max_tokens, settings.timeout, settings.json_mode) == (4096, 75, False)
    assert "vk-test-key" not in repr(settings)
    monkeypatch.setenv("DESIGNER_VLM_MODEL", "vision-model")
    assert generation.vision_provider() == (settings.url, "vision-model")
    monkeypatch.setenv("DESIGNER_VLM_BASE_URL", "https://vision.invalid/v1")
    assert generation.vision_provider() == ("https://vision.invalid/v1", "vision-model")


@pytest.mark.parametrize("field", ["BASE_URL", "MODEL", "API_KEY"])
def test_incomplete_vk_never_falls_back_to_old_provider(monkeypatch, field):
    monkeypatch.setenv("DESIGNER_LLM_PROVIDER", "vk")
    monkeypatch.delenv("DESIGNER_VK_" + field)
    assert not llm_settings().configured
    with pytest.raises(HTTPException) as error:
        require_llm()
    assert error.value.status_code == 503


@pytest.mark.parametrize("name,value", [("PROVIDER", "typo"), ("MAX_TOKENS", "0"), ("TIMEOUT", "nan"), ("TIMEOUT", "-1"), ("JSON_MODE", "yes")])
def test_invalid_configuration_fails_clearly(monkeypatch, name, value):
    monkeypatch.setenv("DESIGNER_LLM_" + name, value)
    with pytest.raises(HTTPException):
        llm_settings()


def test_json_mode_can_be_disabled_without_changing_validation(monkeypatch):
    monkeypatch.setenv("DESIGNER_LLM_PROVIDER", "vk")
    monkeypatch.setenv("DESIGNER_VK_JSON_MODE", "0")
    real_client = httpx.AsyncClient

    def handler(request):
        assert "response_format" not in json.loads(request.content)
        return httpx.Response(200, json={"choices": [{"message": {"content": "```json\n{\"ok\":true}\n```"}}]})

    monkeypatch.setattr(generation.httpx, "AsyncClient", lambda **kw: real_client(
        transport=httpx.MockTransport(handler), **kw))
    assert generation.parse_json(asyncio.run(generation.ask([]))) == {"ok": True}


def test_health_reports_selected_profile_readiness(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient
    from designer.app import create_app

    monkeypatch.setenv("DESIGNER_LLM_PROVIDER", "vk")
    monkeypatch.delenv("DESIGNER_TEMPLATE_DIR", raising=False)
    with TestClient(create_app(tmp_path)) as client:
        assert client.get("/health").json()["llm_configured"] is True
        monkeypatch.delenv("DESIGNER_VK_API_KEY")
        assert client.get("/health").json()["llm_configured"] is False


def test_profile_switch_is_reversible(monkeypatch):
    before = require_llm()
    monkeypatch.setenv("DESIGNER_LLM_PROVIDER", "vk")
    assert generation.provider() == ("https://vk.invalid/v1", "issued-model-id")
    monkeypatch.setenv("DESIGNER_LLM_PROVIDER", "openai")
    assert require_llm() == before
