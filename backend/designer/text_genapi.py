"""Bounded native GenAPI chat transport; exactly one paid submission per call."""
import asyncio
import re

import httpx


class GenApiTextError(ValueError):
    """Safe diagnostic without credentials, prompts or provider bodies."""

    def __init__(self, message, code='provider_error'):
        super().__init__(message)
        self.code = code


def _object(response):
    if response.status_code != 200:
        raise GenApiTextError(f"GenAPI text HTTP {response.status_code}")
    if len(response.content) > 1024 * 1024:
        raise GenApiTextError("GenAPI text response exceeds limit")
    try:
        value = response.json()
    except ValueError:
        raise GenApiTextError("GenAPI text returned invalid JSON") from None
    if not isinstance(value, dict):
        raise GenApiTextError("GenAPI text returned invalid object")
    return value


def _completion(value):
    result = value.get("response") or value.get("full_response") or value.get("result")
    if isinstance(result, list):
        result = result[0] if result else None
    if not isinstance(result, dict) or not isinstance(result.get("choices"), list) or not result["choices"]:
        raise GenApiTextError("GenAPI text completed without a chat response")
    return result


async def generate(messages, settings, on_submission=None):
    payload = {"model": settings.model, "messages": messages, "is_sync": False,
               "max_tokens": settings.max_tokens, "temperature": 0.2,
               "response_format": {"type": "json_object"}, "reasoning_effort": "low"}
    headers = {"Authorization": "Bearer " + settings.key, "Accept": "application/json"}
    identifier = None
    try:
        async with asyncio.timeout(settings.timeout):
            async with httpx.AsyncClient(timeout=httpx.Timeout(settings.timeout, connect=15), follow_redirects=False) as client:
                value = _object(await client.post(settings.url + "/networks/gemma-4", headers=headers, json=payload))
                if value.get("response"):
                    return _completion(value)
                identifier = value.get("request_id")
                if isinstance(identifier, bool) or not re.fullmatch(r"[1-9][0-9]{0,19}", str(identifier)):
                    raise GenApiTextError("GenAPI text returned invalid request ID")
                if on_submission is not None:
                    on_submission(str(identifier))
                while True:
                    if value.get("status") in {"failed", "error", "cancelled", "canceled"}:
                        raise GenApiTextError("GenAPI text task failed")
                    await asyncio.sleep(2)
                    value = _object(await client.get(settings.url + "/request/get/" + str(identifier), headers=headers))
                    if value.get("status") == "success":
                        return _completion(value)
                    if value.get("status") not in {"processing", "pending", "queued", "created", "starting", "in_progress"}:
                        raise GenApiTextError("GenAPI text task returned an invalid status")
    except TimeoutError:
        raise GenApiTextError(f"GenAPI text timed out; task {identifier} may still be running", code='timeout') from None
    except httpx.HTTPError:
        raise GenApiTextError("GenAPI text transport failed") from None
