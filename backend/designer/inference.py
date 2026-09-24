"""Environment profiles for the shared OpenAI-compatible transport."""

import math
import os
from dataclasses import dataclass, field

from fastapi import HTTPException


@dataclass(frozen=True)
class Inference:
    profile: str
    url: str
    model: str
    key: str = field(repr=False)
    max_tokens: int = 14000
    timeout: float = 150
    json_mode: bool = True

    @property
    def configured(self):
        return bool(self.url and self.model and (self.key or self.profile != "vk"))


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
    )


def require_llm():
    settings = llm_settings()
    if not settings.configured:
        prefix = "DESIGNER_VK" if settings.profile == "vk" else "DESIGNER_LLM"
        raise HTTPException(503, f"Configure {prefix}_BASE_URL, {prefix}_MODEL and {prefix}_API_KEY, or supply an explicit outline")
    return settings
