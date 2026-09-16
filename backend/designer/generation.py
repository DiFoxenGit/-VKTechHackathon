import asyncio
import hashlib
import json
import logging
import os
import re
from pathlib import Path

import httpx
from fastapi import HTTPException

from .language import CYRILLIC, LATIN, foreign_labels, visual_labels
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


# A 32k-token window holds roughly this much Russian text next to the schema and
# the instructions. Long content packs are selected down to fit instead of failing.
CONTEXT_BUDGET = max(2000, int(os.getenv("DESIGNER_CONTEXT_CHARS", "24000")))
CHUNK_SIZE = 1200

WORD = re.compile(r"\w{4,}", re.UNICODE)


def chunk_text(text, size=CHUNK_SIZE):
    """Split on blank lines, then pack paragraphs into chunks of about `size`."""
    chunks, current = [], ""
    for paragraph in re.split(r"\n\s*\n", text.strip()):
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        while len(paragraph) > size:
            # A single huge paragraph still has to be cut somewhere.
            cut = paragraph.rfind(" ", 0, size) or size
            chunks.append(paragraph[:cut].strip())
            paragraph = paragraph[cut:].strip()
        if len(current) + len(paragraph) + 2 > size and current:
            chunks.append(current.strip())
            current = ""
        current += paragraph + "\n\n"
    if current.strip():
        chunks.append(current.strip())
    return chunks


def relevance(chunk, terms):
    """Share of the query vocabulary present in this chunk."""
    if not terms:
        return 0.0
    words = set(WORD.findall(chunk.lower()))
    return len(words & terms) / len(terms)


def select_context(sources, query, budget=CONTEXT_BUDGET):
    """Fit the sources into the model's window, keeping what the brief asks about.

    Order inside a document is preserved, so the planner still sees a narrative,
    and every source keeps its id: dropped text never breaks source_refs.
    """
    total = sum(len(s["text"]) for s in sources)
    if total <= budget:
        return sources
    terms = set(WORD.findall(query.lower()))
    scored = []
    for source in sources:
        chunks = chunk_text(source["text"])
        for position, chunk in enumerate(chunks):
            # The opening of a document carries context a keyword match misses.
            head_bonus = 0.25 if position == 0 else 0.0
            scored.append(
                {
                    "source": source["id"],
                    "position": position,
                    "text": chunk,
                    "score": relevance(chunk, terms) + head_bonus,
                }
            )
    scored.sort(key=lambda item: (-item["score"], item["source"], item["position"]))
    kept, used = [], 0
    for item in scored:
        if used + len(item["text"]) > budget:
            continue
        kept.append(item)
        used += len(item["text"])
    result = []
    for source in sources:
        parts = sorted(
            (item for item in kept if item["source"] == source["id"]),
            key=lambda item: item["position"],
        )
        text = "\n\n[...]\n\n".join(item["text"] for item in parts)
        # A source that lost every chunk still appears, so its id stays valid.
        result.append({**source, "text": text or source["text"][:1000]})
    return result


NUMBER = re.compile(r"\d+(?:[.,]\d+)?")


def numbers_in(text):
    """Numbers as written, with the decimal separator normalised."""
    return {value.replace(",", ".") for value in NUMBER.findall(text)}


def known_numbers(sources):
    return numbers_in("\n".join(source["text"] for source in sources))


def unsupported_numbers(text, known):
    """Numbers on a slide that no source states literally.

    The brief demands that every figure on a slide exists in the materials, so a
    derived percentage is as wrong as an invented one.
    """
    return sorted(numbers_in(text) - known)


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

    known = known_numbers(sources)

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
        deck_text = " ".join(
            slide.title + " " + " ".join(slide.bullets) for slide in outline.slides
        )
        cyrillic = len(CYRILLIC.findall(deck_text)) > len(LATIN.findall(deck_text))
        strangers = sorted(
            {
                label
                for slide in outline.slides
                for label in foreign_labels(
                    visual_labels(slide.visual.model_dump()), cyrillic
                )
            }
        )
        if strangers:
            raise ValueError(
                "Подписи в визуализациях на другом языке: "
                + ", ".join(strangers[:8])
                + ". Переведи все подписи, названия серий и единицы на язык колоды."
            )
        invented = unsupported_numbers(
            "\n".join(
                slide.title + "\n" + "\n".join(slide.bullets)
                for slide in outline.slides
            ),
            known,
        )
        if invented:
            # Ask again instead of shipping the figure: the audit would flag it and
            # the user would have to rewrite the slide by hand.
            raise ValueError(
                "Числа отсутствуют в источниках: "
                + ", ".join(invented[:8])
                + ". Используй только те цифры, что есть в материалах дословно, "
                "и не вычисляй проценты, кратности и суммы."
            )
        return outline

    return await completion(
        "outline",
        {
            **request.model_dump(exclude={"outline", "template_id"}),
            "sources": select_context(sources, request.brief),
            "schema": Outline.model_json_schema(),
        },
        validate=validate,
    )
