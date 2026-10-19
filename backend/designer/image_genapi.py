"""GenAPI Z-Image Turbo transport. Submit once; poll without duplicate charges."""
import asyncio
import re
from urllib.parse import urlsplit

import httpx

BASE_URL = "https://api.gen-api.ru/api/v1"
MAX_IMAGE_BYTES = 20 * 1024 * 1024
POLL_SECONDS = 2
TIMEOUT_SECONDS = 150


class GenApiError(ValueError):
    """Safe diagnostic: contains neither credentials nor provider response bodies."""


def _json(response):
    if response.status_code >= 400:
        raise GenApiError(f"GenAPI HTTP {response.status_code}")
    if len(response.content) > 1024 * 1024:
        raise GenApiError("GenAPI response exceeds limit")
    try:
        value = response.json()
    except ValueError:
        raise GenApiError("GenAPI returned invalid JSON") from None
    if not isinstance(value, dict):
        raise GenApiError("GenAPI returned invalid object")
    return value


def _result_url(value):
    result = value.get("result") or value.get("output") or value.get("full_response")
    if isinstance(result, list):
        result = result[0] if result else None
    if isinstance(result, dict):
        result = result.get("url")
    if not isinstance(result, str):
        raise GenApiError("GenAPI completed without an image")
    try:
        parsed = urlsplit(result)
        port = parsed.port
    except ValueError:
        raise GenApiError("GenAPI returned an invalid image URL") from None
    host = (parsed.hostname or "").lower()
    # Only the provider and its documented storage; never fetch arbitrary hosts.
    trusted = host in {"gen-api.storage.yandexcloud.net", "gen-api.ru"} or host.endswith(".gen-api.ru")
    if parsed.scheme != "https" or not trusted or parsed.username or parsed.password or port not in (None, 443):
        raise GenApiError("GenAPI returned an untrusted image URL")
    return result


async def _download(client, url):
    chunks = []
    count = 0
    # Client has no default Authorization header: credentials never go to storage.
    async with client.stream("GET", url) as response:
        if response.status_code != 200:
            raise GenApiError(f"GenAPI image HTTP {response.status_code}")
        async for chunk in response.aiter_bytes():
            count += len(chunk)
            if count > MAX_IMAGE_BYTES:
                raise GenApiError("GenAPI image exceeds limit")
            chunks.append(chunk)
    blob = b"".join(chunks)
    if not blob.startswith(b"\x89PNG\r\n\x1a\n"):
        raise GenApiError("GenAPI image is not PNG")
    return blob


async def generate(prompt, size, key):
    if not key or not key.strip():
        raise GenApiError("GenAPI image key is missing")
    match = re.fullmatch(r"([0-9]{3,4})x([0-9]{3,4})", size)
    if not match:
        raise GenApiError("Invalid GenAPI image size")
    width, height = map(int, match.groups())
    if not all(256 <= side <= 2048 and side % 16 == 0 for side in (width, height)):
        raise GenApiError("Invalid GenAPI image dimensions")
    headers = {"Authorization": "Bearer " + key, "Accept": "application/json"}
    payload = {"callback_url": None, "prompt": prompt, "model": "turbo", "width": width,
               "height": height, "num_images": 1, "output_format": "png", "num_inference_steps": 8,
               "guidance_scale": 0, "enable_safety_checker": True,
               "translate_input": False, "enable_prompt_expansion": False}
    try:
        async with asyncio.timeout(TIMEOUT_SECONDS):
            async with httpx.AsyncClient(timeout=httpx.Timeout(30, connect=15), follow_redirects=False) as client:
                created = _json(await client.post(BASE_URL + "/networks/z-image", headers=headers, json=payload))
                identifier = created.get("request_id")
                if isinstance(identifier, bool) or not re.fullmatch(r"[1-9][0-9]{0,19}", str(identifier)):
                    raise GenApiError("GenAPI returned invalid request ID")
                if created.get("status") in {"failed", "error", "cancelled", "canceled"}:
                    raise GenApiError("GenAPI rejected generation")
                if any(created.get(k) for k in ("result", "output", "full_response")):
                    return await _download(client, _result_url(created))
                while True:
                    await asyncio.sleep(POLL_SECONDS)
                    result = _json(await client.get(BASE_URL + "/request/get/" + str(identifier), headers=headers))
                    status = result.get("status")
                    if status == "success":
                        return await _download(client, _result_url(result))
                    if status not in {"processing", "pending", "queued", "created", "starting", "in_progress"}:
                        raise GenApiError("GenAPI generation did not succeed")
    except TimeoutError:
        raise GenApiError("GenAPI generation timed out; task may still be running") from None
    except httpx.HTTPError:
        raise GenApiError("GenAPI transport failed") from None
