import hashlib
import json
import os
from pathlib import Path

import httpx
from fastapi import HTTPException

from .models import Brief, Outline

PROMPTS = Path(__file__).parent / "prompts"


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


async def completion(agent, payload):
    url, model = provider()
    prompt = (PROMPTS / workflow()["agents"][agent]).read_text()
    async with httpx.AsyncClient(timeout=httpx.Timeout(150, connect=15)) as client:
        try:
            response = await client.post(
                url + "/chat/completions",
                headers={
                    "Authorization": "Bearer "
                    + os.getenv("DESIGNER_LLM_API_KEY", "local")
                },
                json={
                    "model": model,
                    "temperature": 0.2,
                    "max_tokens": 14000,
                    "messages": [
                        {"role": "system", "content": prompt},
                        {
                            "role": "user",
                            "content": json.dumps(payload, ensure_ascii=False),
                        },
                    ],
                    "response_format": {"type": "json_object"},
                },
            )
            response.raise_for_status()
            value = response.json()["choices"][0]["message"]["content"].strip()
            if value.startswith("```"):
                value = value.split("\n", 1)[1].rsplit("```", 1)[0]
            return json.loads(value)
        except (httpx.HTTPError, ValueError, KeyError, IndexError) as exc:
            raise HTTPException(
                502, "LLM provider failed or returned invalid JSON"
            ) from exc


def sources_for(store, request: Brief):
    result = [{"id": "brief", "text": request.brief}]
    for identifier in request.content_pack_ids:
        item = store.get("content_packs", identifier)
        result.append({"id": identifier, "text": item["text"]})
    if sum(len(s["text"]) for s in result) > 120000:
        raise HTTPException(422, "Combined source text exceeds 120000 characters")
    return result


async def generate_outline(request, sources):
    result = await completion(
        "outline",
        {
            **request.model_dump(exclude={"outline", "template_id"}),
            "sources": sources,
            "schema": Outline.model_json_schema(),
        },
    )
    try:
        outline = Outline.model_validate(result)
    except ValueError as exc:
        raise HTTPException(
            502, "LLM outline does not match the required schema"
        ) from exc
    if len(outline.slides) != request.slide_count:
        raise HTTPException(502, "LLM returned an incorrect slide count")
    allowed = {s["id"] for s in sources}
    if any(set(slide.source_refs) - allowed for slide in outline.slides):
        raise HTTPException(502, "LLM returned unknown source references")
    return outline
