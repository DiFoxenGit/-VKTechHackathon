import asyncio
import hashlib
import json
import logging
import os
from pathlib import Path

import httpx
from fastapi import HTTPException

from .models import Brief, Outline

PROMPTS = Path(__file__).parent / "prompts"
LOGGER = logging.getLogger("designer.generation")

# Open-weight models below 35B miss the schema often enough that one shot is not a
# contract. Each retry shows the model its own answer and what was wrong with it.
MAX_ATTEMPTS = max(1, int(os.getenv("DESIGNER_LLM_ATTEMPTS", "3")))
RETRY_DELAY = max(0.0, float(os.getenv("DESIGNER_LLM_RETRY_DELAY", "0.4")))


class InvalidCompletion(Exception):
    """The provider answered, but the answer cannot be used as is."""


def workflow():
    manifest = json.loads((PROMPTS / "manifest.json").read_text())
    manifest["sha256"] = {
        p.name: hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(PROMPTS.iterdir())
        if p.is_file()
    }
    return manifest


def provider():
    url = os.getenv("DESIGNER_LLM_BASE_URL", "").rstrip("/")
    model = os.getenv("DESIGNER_LLM_MODEL", "")
    if not url or not model:
        raise HTTPException(
            503,
            "Configure DESIGNER_LLM_BASE_URL and DESIGNER_LLM_MODEL, or supply an explicit outline",
        )
    return url, model


def parse_json(text):
    """Accept the JSON a chat model returns: fenced blocks and stray prose around it."""
    value = text.strip()
    if value.startswith("```"):
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


async def ask(messages):
    url, model = provider()
    async with httpx.AsyncClient(timeout=httpx.Timeout(150, connect=15)) as client:
        response = await client.post(
            url + "/chat/completions",
            headers={
                "Authorization": "Bearer " + os.getenv("DESIGNER_LLM_API_KEY", "local")
            },
            json={
                "model": model,
                "temperature": 0.2,
                "max_tokens": 14000,
                "messages": messages,
                "response_format": {"type": "json_object"},
            },
        )
        response.raise_for_status()
        try:
            return response.json()["choices"][0]["message"]["content"].strip()
        except (ValueError, KeyError, IndexError, AttributeError) as exc:
            raise InvalidCompletion(f"Ответ провайдера без содержимого: {exc}") from exc


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
    last = "LLM provider failed or returned invalid JSON"
    for attempt in range(1, MAX_ATTEMPTS + 1):
        answer = None
        try:
            answer = await ask(messages)
            value = parse_json(answer)
            return validate(value) if validate else value
        except httpx.HTTPError as exc:
            last = f"Провайдер недоступен: {exc.__class__.__name__}"
        except (InvalidCompletion, ValueError) as exc:
            last = str(exc) or exc.__class__.__name__
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
        LOGGER.warning("Agent %s attempt %s/%s failed: %s", agent, attempt, MAX_ATTEMPTS, last)
        if attempt < MAX_ATTEMPTS and RETRY_DELAY:
            await asyncio.sleep(RETRY_DELAY * attempt)
    raise HTTPException(502, f"Модель не вернула корректный ответ: {last}")


def sources_for(store, request: Brief):
    result = [{"id": "brief", "text": request.brief}]
    for identifier in request.content_pack_ids:
        item = store.get("content_packs", identifier)
        result.append({"id": identifier, "text": item["text"]})
    if sum(len(s["text"]) for s in result) > 120000:
        raise HTTPException(422, "Combined source text exceeds 120000 characters")
    return result


async def generate_outline(request, sources):
    allowed = {s["id"] for s in sources}

    def validate(result):
        outline = Outline.model_validate(result)
        if len(outline.slides) != request.slide_count:
            raise ValueError(
                f"Нужно ровно {request.slide_count} слайдов, получено {len(outline.slides)}"
            )
        unknown = {ref for slide in outline.slides for ref in slide.source_refs} - allowed
        if unknown:
            raise ValueError(
                "Неизвестные source_refs: "
                + ", ".join(sorted(unknown))
                + ". Допустимые: "
                + ", ".join(sorted(allowed))
            )
        return outline

    return await completion(
        "outline",
        {
            **request.model_dump(exclude={"outline", "template_id"}),
            "sources": sources,
            "schema": Outline.model_json_schema(),
        },
        validate=validate,
    )
