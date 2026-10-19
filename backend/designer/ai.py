"""Model transport, prompt calls and retries. Content decisions live in algorithms/."""
import asyncio
import base64
import json
import logging
import os
import time
import hashlib
import math
import httpx
from fastapi import HTTPException
from .inference import (llm_settings, require_llm, fallback_settings,
                        record_inference)
from .workflow import PROMPTS, workflow
from .inference_trace import current_trace, mark_validated, publish
LOGGER = logging.getLogger("designer.ai")
MAX_ATTEMPTS = min(3, max(1, int(os.getenv("DESIGNER_LLM_ATTEMPTS", "3"))))
RETRY_DELAY = max(0.0, float(os.getenv("DESIGNER_LLM_RETRY_DELAY", "0.4")))

class InvalidCompletion(Exception):
    """The provider answered, but the answer cannot be used as is."""

def provider():
    settings = require_llm()
    return settings.url, settings.model

def message_text(message):
    """Текст ответа, в какой бы форме его ни прислал провайдер.

    Модели с режимом рассуждений возвращают content = null и кладут ответ в
    reasoning_content, а часть провайдеров присылает content списком частей.
    """
    content = message.get("content")
    if isinstance(content, list):
        content = "".join(
            part.get("text", "")
            for part in content
            if isinstance(part, dict) and part.get("type") in (None, "text")
        )
    if not content:
        content = message.get("reasoning_content") or ""
    text = content.strip() if isinstance(content, str) else ""
    if not text:
        raise InvalidCompletion("Провайдер вернул пустой ответ")
    return text

def parse_json(text):
    """Accept the JSON a chat model returns: fenced blocks and stray prose around it."""
    value = text.strip()
    if value.startswith("```"):
        if '\n' not in value:
            raise InvalidCompletion('Незавершённый JSON-блок')
        value = value.split("\n", 1)[1].rsplit("```", 1)[0]
    try:
        return json.loads(value)
    except ValueError:
        start, end = value.find("{"), value.rfind("}")
        if start < 0 or end <= start:
            raise InvalidCompletion("Ответ не содержит JSON-объекта") from None
        try:
            return json.loads(value[start : end + 1])
        except ValueError as exc:
            raise InvalidCompletion(f"JSON не разобран: {exc}") from None


def _usage(value, depth=0):
    """Retain numeric token usage, including provider detail counters."""
    if not isinstance(value, dict) or depth > 3:
        return None
    result = {}
    for key, item in list(value.items())[:40]:
        if isinstance(item, (int, float)) and not isinstance(item, bool) and math.isfinite(item):
            result[str(key)[:100]] = item
        elif isinstance(item, dict):
            nested = _usage(item, depth + 1)
            if nested:
                result[str(key)[:100]] = nested
    return result

async def ask(messages):
    settings = require_llm()
    fallback = fallback_settings() if settings.profile == "vk" else None
    try:
        answer = await _ask_primary(messages, settings)
        if settings.json_mode and fallback is not None:
            parse_json(answer)
        record_inference(settings, settings)
        return answer
    except httpx.HTTPStatusError as exc:
        if fallback is None or (exc.response.status_code not in {408, 429} and exc.response.status_code < 500):
            raise
    except (httpx.TransportError, InvalidCompletion):
        if fallback is None:
            raise
    LOGGER.warning("VK text inference failed; using configured GenAPI fallback")
    from .text_genapi import generate, GenApiTextError
    trace = current_trace()
    started = time.monotonic()
    call = None
    if trace is not None:
        call = dict(attempt=len(trace['calls']) + 1, provider=fallback.profile,
                    model=fallback.model, status_code=None, duration_seconds=0.0,
                    validation='not_run', error_code=None, response_id=None, usage=None)
        trace['calls'].append(call)
        trace.update(provider=fallback.profile, model=fallback.model,
                     attempts=len(trace['calls']), status='running')
        publish()
    try:
        value = await generate(messages, fallback)
        if call is not None:
            call.update(status_code=200, usage=_usage(value.get('usage')))
        answer = _chat_text(value)
        parse_json(answer)
        if call is not None:
            call['response_sha256'] = hashlib.sha256(answer.encode()).hexdigest()
    except GenApiTextError as exc:
        if call is not None:
            call.update(error_code='provider_error', validation='failed')
            trace.update(error_code='provider_error', validation='failed', status='failed')
        # A timed-out paid task may still run. Do not let the agent retry loop
        # submit a second paid task when transport completion is unknown.
        raise HTTPException(503, str(exc)) from None
    finally:
        if call is not None:
            call['duration_seconds'] = round(time.monotonic() - started, 3)
            trace['duration_seconds'] = round(sum(item['duration_seconds'] for item in trace['calls']), 3)
            publish()
    record_inference(fallback, settings)
    return answer


def _chat_text(value):
    try:
        if value["choices"][0].get("finish_reason") == "length":
            raise InvalidCompletion("Ответ модели обрезан по лимиту токенов")
        return message_text(value["choices"][0]["message"])
    except (ValueError, KeyError, IndexError, AttributeError, TypeError):
        raise InvalidCompletion("Ответ провайдера без содержимого") from None


async def _ask_primary(messages, settings):
    payload = {
        "model": settings.model,
        "temperature": 0.2,
        "max_tokens": settings.max_tokens,
        "messages": messages,
    }
    if settings.json_mode:
        payload["response_format"] = {"type": "json_object"}
    trace = current_trace()
    call = None
    started = time.monotonic()
    if trace is not None:
        call = dict(attempt=len(trace['calls']) + 1, status_code=None,
                    duration_seconds=0.0, validation='not_run', error_code=None,
                    response_id=None, usage=None)
        trace['calls'].append(call)
        trace.update(requested=True, attempted=True, status='running',
                     provider=settings.profile, model=settings.model, attempts=len(trace['calls']))
        publish()
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(settings.timeout, connect=15)) as client:
            response = await client.post(
                settings.url + "/chat/completions",
                headers={"Authorization": "Bearer " + settings.key, **({"Project-ID": settings.project_id} if settings.profile == "vk" else {})},
                json=payload,
            )
            if call is not None:
                call['status_code'] = response.status_code
            response.raise_for_status()
            try:
                body = response.json()
                if call is not None:
                    call['response_id'] = str(body['id'])[:200] if body.get('id') else None
                    call['usage'] = _usage(body.get('usage'))
                if body['choices'][0].get('finish_reason') == 'length':
                    raise InvalidCompletion('Ответ модели обрезан по лимиту токенов')
                answer = message_text(body['choices'][0]['message'])
                if call is not None:
                    call['response_sha256'] = hashlib.sha256(answer.encode()).hexdigest()
                return answer
            except (ValueError, KeyError, IndexError, AttributeError, TypeError) as exc:
                raise InvalidCompletion('Ответ провайдера не соответствует формату chat completion') from exc
    except (httpx.HTTPError, InvalidCompletion) as exc:
        if call is not None:
            code = inference_error_code(exc)
            call.update(error_code=code, validation='failed')
            trace.update(error_code=code, validation='failed')
        raise
    except asyncio.CancelledError:
        if call is not None:
            call.update(error_code='interrupted', validation='failed')
            trace.update(error_code='interrupted', validation='failed', status='failed')
        raise
    finally:
        if call is not None:
            call['duration_seconds'] = round(time.monotonic() - started, 3)
            trace['duration_seconds'] = round(sum(item['duration_seconds'] for item in trace['calls']), 3)
            publish()


def inference_error_code(exc):
    if isinstance(exc, httpx.HTTPStatusError):
        return {401: 'authorization', 403: 'authorization', 429: 'rate_limit'}.get(exc.response.status_code, 'provider_error')
    if isinstance(exc, httpx.TimeoutException):
        return 'timeout'
    if isinstance(exc, httpx.HTTPError):
        return 'connection'
    return 'invalid_response'

def vision_provider():
    """Отдельная модель для проверки по картинке; по умолчанию — основная."""
    url = (os.getenv("DESIGNER_VLM_BASE_URL") or llm_settings().url).rstrip("/")
    model = os.getenv("DESIGNER_VLM_MODEL", "")
    if not url or not model:
        raise HTTPException(
            503,
            "Configure DESIGNER_VLM_MODEL (and DESIGNER_VLM_BASE_URL) for image-based audit",
        )
    return url, model

def vision_available():
    return bool(
        os.getenv("DESIGNER_VLM_MODEL")
        and (os.getenv("DESIGNER_VLM_BASE_URL") or llm_settings().url)
    )

async def ask_vision(prompt, payload, image_png: bytes):
    """Один слайд картинкой + его текст. Ответ — JSON, как и у текстовых агентов."""
    url, model = vision_provider()
    encoded = base64.b64encode(image_png).decode()
    async with httpx.AsyncClient(timeout=httpx.Timeout(180, connect=15)) as client:
        response = await client.post(
            url + "/chat/completions",
            headers={
                "Authorization": "Bearer "
                + (os.getenv("DESIGNER_VLM_API_KEY") or llm_settings().key)
            },
            json={
                "model": model,
                "temperature": 0.1,
                # Режим рассуждений съедает лимит: ответу нужен запас после мыслей.
                "max_tokens": 6000,
                "messages": [
                    {"role": "system", "content": prompt},
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image_url",
                                "image_url": {"url": f"data:image/png;base64,{encoded}"},
                            },
                            {
                                "type": "text",
                                "text": json.dumps(payload, ensure_ascii=False),
                            },
                        ],
                    },
                ],
                "response_format": {"type": "json_object"},
            },
        )
        response.raise_for_status()
        try:
            answer = message_text(response.json()["choices"][0]["message"])
        except (ValueError, KeyError, IndexError, AttributeError) as exc:
            raise InvalidCompletion(f"Ответ VLM без содержимого: {exc}") from exc
    return parse_json(answer)

def image_provider():
    """Провайдер генерации изображений; по умолчанию — адрес основной модели.

    Контракт — OpenAI-совместимый `/images/generations`, поэтому подключается
    любой сервис с таким эндпоинтом: хватает адреса, модели и ключа в окружении.
    """
    profile = os.getenv("DESIGNER_IMAGE_PROVIDER", "openai").strip().lower()
    if profile not in {"openai", "genapi"}:
        raise HTTPException(503, "DESIGNER_IMAGE_PROVIDER must be openai or genapi")
    if profile == "genapi":
        from .image_genapi import BASE_URL
        if os.getenv("DESIGNER_IMAGE_MODEL") != "z-image" or not os.getenv("DESIGNER_IMAGE_API_KEY", "").strip():
            raise HTTPException(503, "Configure GenAPI image model z-image and its separate API key")
        return BASE_URL, "z-image"
    url = (
        os.getenv("DESIGNER_IMAGE_BASE_URL") or os.getenv("DESIGNER_LLM_BASE_URL", "")
    ).rstrip("/")
    model = os.getenv("DESIGNER_IMAGE_MODEL", "")
    if not url or not model:
        raise HTTPException(
            503,
            "Configure DESIGNER_IMAGE_MODEL (and DESIGNER_IMAGE_BASE_URL) for image generation",
        )
    return url, model

def image_available():
    profile = os.getenv("DESIGNER_IMAGE_PROVIDER", "openai").strip().lower()
    if profile not in {"openai", "genapi"}:
        return False
    if profile == "genapi":
        return bool(os.getenv("DESIGNER_IMAGE_MODEL") == "z-image" and os.getenv("DESIGNER_IMAGE_API_KEY", "").strip())
    return bool(
        os.getenv("DESIGNER_IMAGE_MODEL")
        and (os.getenv("DESIGNER_IMAGE_BASE_URL") or os.getenv("DESIGNER_LLM_BASE_URL"))
    )

async def draw_image(prompt, size=None) -> bytes:
    """Одна картинка по текстовому описанию. Возвращает байты PNG.

    Провайдеры отвечают по-разному: кто-то кладёт base64 в ответ, кто-то отдаёт
    ссылку со сроком жизни. Поддержаны оба варианта, иначе половина совместимых
    сервисов не подключилась бы.
    """
    url, model = image_provider()
    size = size or os.getenv("DESIGNER_IMAGE_SIZE", "1024x1024")
    if os.getenv("DESIGNER_IMAGE_PROVIDER", "openai").strip().lower() == "genapi":
        from .image_genapi import generate, GenApiError
        try:
            return await generate(prompt, size, os.environ["DESIGNER_IMAGE_API_KEY"])
        except GenApiError as exc:
            raise InvalidCompletion(str(exc)) from None
    key = os.getenv("DESIGNER_IMAGE_API_KEY") or os.getenv("DESIGNER_LLM_API_KEY", "local")
    async with httpx.AsyncClient(timeout=httpx.Timeout(180, connect=15)) as client:
        response = await client.post(
            url + "/images/generations",
            headers={"Authorization": "Bearer " + key},
            json={
                "model": model,
                "prompt": prompt,
                "n": 1,
                "size": size,
                "response_format": "b64_json",
            },
        )
        response.raise_for_status()
        try:
            item = response.json()["data"][0]
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise InvalidCompletion(f"Ответ генератора без картинки: {exc}") from exc
        if item.get("b64_json"):
            return base64.b64decode(item["b64_json"])
        if item.get("url"):
            loaded = await client.get(item["url"])
            loaded.raise_for_status()
            return loaded.content
    raise InvalidCompletion("Генератор не вернул ни b64_json, ни ссылки")

async def vision_completion(prompt, payload, image_png, attempts=2):
    """Проверка по картинке с повтором: пустой ответ модели не должен терять слайд."""
    last = None
    for attempt in range(1, attempts + 1):
        try:
            return await ask_vision(prompt, payload, image_png)
        except (InvalidCompletion, ValueError, httpx.HTTPError) as exc:
            last = exc
            LOGGER.warning("Vision attempt %s/%s failed: %s", attempt, attempts, exc)
            if attempt < attempts and RETRY_DELAY:
                await asyncio.sleep(RETRY_DELAY)
    raise InvalidCompletion(str(last) or "VLM не ответила")

async def completion(agent, payload, validate=None):
    """Call one agent and return a usable answer.

    `validate` turns a parsed answer into the value the caller needs and raises
    ValueError when the answer is unusable. Schema misses are retried with the
    reason attached, so a weaker model gets a second chance instead of a 502.
    """
    prompt = (PROMPTS / workflow()["agents"][agent]).read_text()
    messages = [
        {"role": "system", "content": prompt},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
    ]
    return await complete_json(messages, validate=validate, agent=agent)


async def complete_json(messages, validate=None, agent='probe', attempts=None):
    """Validated JSON over the shared transport, with a bounded retry budget."""
    attempts = min(MAX_ATTEMPTS, max(1, attempts or MAX_ATTEMPTS))
    last = "LLM provider failed or returned invalid JSON"
    last_code = 'invalid_response'
    for attempt in range(1, attempts + 1):
        answer = None
        trace = current_trace()
        call_count = len(trace['calls']) if trace is not None else 0
        try:
            answer = await ask(messages)
            value = parse_json(answer)
            result = validate(value) if validate else value
            call = trace['calls'][-1] if trace is not None and len(trace['calls']) > call_count else None
            mark_validated(call, True)
            return result
        except httpx.HTTPError as exc:
            last = f"Провайдер недоступен: {exc.__class__.__name__}"
            last_code = inference_error_code(exc)
            if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code in {400, 401, 403, 404, 422}:
                break
        except (InvalidCompletion, ValueError) as exc:
            last_code = 'invalid_response'
            if hasattr(exc, 'errors'):
                last = 'Проверка схемы: ' + '; '.join(
                    '.'.join(map(str, error['loc'])) + ': ' + error['msg']
                    for error in exc.errors(include_input=False))[:500]
            else:
                last = str(exc) or exc.__class__.__name__
            if trace is not None and len(trace['calls']) > call_count:
                call = trace['calls'][-1]
                call['error_code'] = 'invalid_response'
                trace['error_code'] = 'invalid_response'
                mark_validated(call, False)
            if answer is not None:
                # Show the model its own answer; repeating only the rule rarely helps.
                messages = messages[:2] + [
                    {"role": "assistant", "content": answer[:4000]},
                    {
                        "role": "user",
                        "content": (
                            f"Предыдущий ответ не подошёл: {last}. "
                            "Верни только JSON, строго по схеме, без пояснений и текста вокруг."
                        ),
                    },
                ]
        LOGGER.warning("Agent %s attempt %s/%s failed: %s", agent, attempt, attempts, last_code)
        if attempt < attempts and RETRY_DELAY:
            await asyncio.sleep(RETRY_DELAY * attempt)
    trace = current_trace()
    if trace is not None:
        trace.update(status='failed', error_code=last_code, message='Модель не вернула проверенный ответ')
        publish()
    safe_reason = {'authorization': 'проверьте доступ к провайдеру',
        'rate_limit': 'провайдер ограничил число запросов', 'timeout': 'истекло время ожидания',
        'provider_error': 'ошибка провайдера', 'connection': 'нет соединения с провайдером',
        'invalid_response': 'ответ не прошёл проверку формата или фактов'}[last_code]
    raise HTTPException(502, f'Модель не вернула корректный ответ: {safe_reason}. Повторите запрос.')

