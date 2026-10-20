"""Environment profiles for the shared OpenAI-compatible transport."""

import math
import os
from contextvars import ContextVar
from contextlib import contextmanager
from dataclasses import dataclass, field

from fastapi import HTTPException

_route = ContextVar("text_inference_route", default=None)


def inference_route():
    return _route.get()


def reset_inference_route():
    _route.set(None)


@contextmanager
def isolated_inference_route():
    """An optional planning call must not relabel the content model."""
    token = _route.set(None)
    try:
        yield
    finally:
        _route.reset(token)


def record_inference(settings, primary):
    _route.set({"primary": primary.profile, "provider": settings.profile,
                "model": settings.model, "fallback_used": settings.profile != primary.profile})


def fallback_settings():
    """Explicit opt-in; never reuse primary or image credentials implicitly."""
    profile = os.getenv("DESIGNER_FALLBACK_PROVIDER", "").strip().lower()
    if not profile:
        return None
    if profile != "genapi":
        raise HTTPException(503, "DESIGNER_FALLBACK_PROVIDER must be genapi")
    model = os.getenv("DESIGNER_FALLBACK_MODEL", "").strip()
    key = os.getenv("DESIGNER_FALLBACK_API_KEY", "").strip()
    if model not in {"gemma-4-31b", "gemma-4-26b"} or not key:
        raise HTTPException(503, "Configure a supported GenAPI fallback model and its separate API key")
    try:
        tokens = int(os.getenv("DESIGNER_FALLBACK_MAX_TOKENS", "14000"))
        timeout = float(os.getenv("DESIGNER_FALLBACK_TIMEOUT", "220"))
        if tokens <= 1024 or not math.isfinite(timeout) or timeout <= 0:
            raise ValueError
    except ValueError:
        raise HTTPException(503, "Invalid GenAPI fallback token limit or timeout") from None
    return Inference(profile="genapi", url="https://api.gen-api.ru/api/v1",
                     model=model, key=key, max_tokens=tokens, timeout=timeout)


@dataclass(frozen=True)
class Inference:
    profile: str
    url: str
    model: str
    key: str = field(repr=False)
    max_tokens: int = 14000
    timeout: float = 150
    json_mode: bool = True
    project_id: str = ""

    @property
    def configured(self):
        return bool(self.url and self.model and (self.key and self.project_id or self.profile != "vk"))


def llm_settings():
    profile = os.getenv("DESIGNER_LLM_PROVIDER", "openai").strip().lower()
    if profile not in {"openai", "vk"}:
        raise HTTPException(503, "DESIGNER_LLM_PROVIDER must be openai or vk")
    prefix = "DESIGNER_VK" if profile == "vk" else "DESIGNER_LLM"
    try:
        tokens = int(os.getenv(prefix + "_MAX_TOKENS") or "14000")
        timeout = float(os.getenv(prefix + "_TIMEOUT") or "150")
        mode = (os.getenv(prefix + "_JSON_MODE") or "1").strip()
        if tokens <= 0 or not math.isfinite(timeout) or timeout <= 0 or mode not in {"0", "1"}:
            raise ValueError
    except ValueError:
        raise HTTPException(503, f"Invalid {prefix} token limit, timeout or JSON mode") from None
    return Inference(
        profile=profile,
        url=os.getenv(prefix + "_BASE_URL", "").strip().rstrip("/"),
        model=os.getenv(prefix + "_MODEL", "").strip(),
        key=os.getenv(prefix + "_API_KEY", "" if profile == "vk" else "local"),
        max_tokens=tokens,
        timeout=timeout,
        json_mode=mode == "1",
        project_id=os.getenv("DESIGNER_VK_PROJECT_ID", "").strip() if profile == "vk" else "",
    )


def require_llm():
    settings = llm_settings()
    if not settings.configured:
        prefix = "DESIGNER_VK" if settings.profile == "vk" else "DESIGNER_LLM"
        raise HTTPException(503, f"Configure {prefix}_BASE_URL, {prefix}_MODEL, {prefix}_API_KEY and VK PROJECT_ID when applicable, or supply an explicit outline")
    return settings
