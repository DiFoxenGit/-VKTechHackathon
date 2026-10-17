"""Model-assisted checks, called separately from deterministic audit()."""
import asyncio
import logging
import httpx
from fastapi import HTTPException
from .ai import InvalidCompletion, vision_completion, completion
from .workflow import PROMPTS, workflow
from .algorithms.context import select_context
from .language import visual_labels
from .audit import issue, VISUAL_CODES, validate_contextual_issues, validate_model_issues
LOGGER = logging.getLogger("designer.ai_audit")

async def visual_audit(deck, sources, images):
    """Контекстные проверки Приложения 1 по изображению каждого слайда.

    Детерминированные правила уже проверили геометрию по координатам; здесь модель
    смотрит на отрендеренный слайд глазами зрителя и отвечает на вопросы «да/нет».
    Слайды проверяются параллельно: это самая долгая часть пайплайна.
    """
    prompt = (PROMPTS / workflow()["agents"]["audit_image"]).read_text()
    if len(images) != len(deck["slides"]):
        raise HTTPException(502, "Visual audit requires an image for every slide")

    async def one(index, slide, image):
        content = slide["content"]
        query = " ".join([content["title"], *content["bullets"], *visual_labels(content["visual"])])
        selected = select_context(sources, query, budget=8000)
        complete_sources = selected == sources
        payload = {
            "slide_index": index,
            "title": slide["content"]["title"],
            "bullets": slide["content"]["bullets"],
            "visual": slide["content"]["visual"],
            "sources": selected,
            "source_context_complete": complete_sources,
            "verified_analytics": [{"analysis_id": r["analysis_id"], "profile": r["profile"], "facts": [{k:v for k,v in f.items() if k != "rows"} for f in r["facts"]]} for r in sources[0].get("_analysis_results", [])] if sources else [],
        }
        try:
            result = await vision_completion(prompt, payload, image)
            validate_model_issues(result, set(VISUAL_CODES))
        except (HTTPException, InvalidCompletion, httpx.HTTPError, ValueError) as exc:
            LOGGER.warning("Visual audit failed on slide %s: %s", index, exc)
            raise HTTPException(
                502, f"Не удалось проверить слайд {index + 1} по изображению; повторите проверку"
            ) from exc
        findings = []
        if not complete_sources:
            findings.append(issue(
                index, "slide_image", "source_context_incomplete",
                "Материалы слишком велики для проверки по изображению: использованы отобранные фрагменты. Полнота проверки фактов не подтверждена.",
                category="contextual",
            ))
        for item in result["issues"]:
            code = str(item.get("code", "content"))[:60]
            findings.append(
                issue(
                    index,
                    "slide_image",
                    code,
                    (VISUAL_CODES.get(code, "Замечание по слайду") + ": ")
                    + str(item.get("message", ""))[:600],
                    category="contextual",
                    severity="error" if code in {"facts_supported", "no_typos", "no_garbage"} else "warning",
                )
            )
        return findings

    batches = await asyncio.gather(
        *(
            one(index, slide, image)
            for index, (slide, image) in enumerate(zip(deck["slides"], images))
        )
    )
    return [finding for batch in batches for finding in batch]


async def contextual_audit(deck, sources):
    count = len(deck["slides"])

    result = await completion(
        "audit", {"slides": [s["content"] for s in deck["slides"]], "sources": select_context(sources, " ".join(s["content"]["title"] for s in deck["slides"])),
                  "verified_analytics": [{"analysis_id": r["analysis_id"], "profile": r["profile"], "facts": [{k:v for k,v in f.items() if k != "rows"} for f in r["facts"]]} for r in sources[0].get("_analysis_results", [])] if sources else []},
        validate=lambda result: validate_contextual_issues(result, count),
    )
    issues = []
    for j, item in enumerate(result["issues"][:200]):
        index = item.get("slide_index")
        if isinstance(index, int) and 0 <= index < len(deck["slides"]):
            issues.append(
                issue(
                    index,
                    f"context_{j}",
                    str(item.get("code", "content"))[:100],
                    str(item.get("message", ""))[:2000],
                    category="contextual",
                    severity="error" if item["code"] in {"unsupported_fact", "title_mismatch", "typo", "prompt_leak"} else "warning",
                )
            )
    return issues


