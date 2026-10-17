"""Orchestrates deterministic algorithms, model calls and presentation assembly."""
import logging
import os
from fastapi import HTTPException
from starlette.concurrency import run_in_threadpool
from . import ai
from .models import Outline
from .workflow import narrative
from .algorithms.context import select_context
from .algorithms.validation import validate_outline
from .algorithms.balance import balance_plan, apply_condensation, finish_balance
from .comparisons import add_comparison_charts
from .analytics_bridge import analyse_sources, build_outline, verify_outline
LOGGER = logging.getLogger("designer.pipeline")


async def generate_outline(request, sources, warnings=None):
    attempt = 0
    def validate(result):
        nonlocal attempt
        attempt += 1
        return validate_outline(result, request, sources,
                                last_chance=attempt >= ai.MAX_ATTEMPTS, warnings=warnings)
    result = await ai.completion("outline", {
        **request.model_dump(exclude={"outline", "template_id"}),
        "narrative": narrative(request.purpose),
        "sources": select_context(sources, request.brief,
                                  budget=max(2000, int(os.getenv("DESIGNER_CONTEXT_CHARS", "24000")))),
        "schema": Outline.model_json_schema(),
    }, validate=validate)
    return add_comparison_charts(result, sources, request.language)


async def balance_outline(outline, template, capacity=None, warnings=None):
    """Ask AI to shorten only what algorithms identified, then validate and fit."""
    from .layout import slide_capacity
    payload = balance_plan(outline, slide_capacity(template) if capacity is None else capacity)
    if not payload["slides"]:
        return Outline.model_validate(outline).model_dump()
    candidate = outline
    try:
        if ai.llm_settings().configured:
            candidate = await ai.completion(
                "condense", payload,
                validate=lambda result: apply_condensation(outline, result, payload))
    except HTTPException as exc:
        LOGGER.warning("Condense agent unavailable: %s", exc.detail)
        if warnings is not None:
            warnings.append("ИИ не сократил текст: применена алгоритмическая подгонка с сохранением исходника.")
    return finish_balance(outline, candidate, payload, warnings)


async def run_generation(request, template, sources, *, outline_factory, balance,
                         render_variant, variants, on_stage, on_outline,
                         on_variant, warnings, label_assets=None,
                         draw_illustrations=None, contextual_check=None):
    """Run the same content through algorithms, optional AI and each renderer.

    The HTTP layer owns jobs/storage. Callbacks make this pipeline runnable and
    testable without FastAPI, a real model, filesystem exports or a job queue.
    """
    on_stage("outline", 5)
    analysis_results = await run_in_threadpool(analyse_sources,sources,getattr(request, "analysis_goal", "") or request.brief)
    if analysis_results:
        on_stage("analytics", 8)
        sources[0]["_analysis_results"] = analysis_results
        outline = build_outline(analysis_results, sources, request.slide_count)
        for result in analysis_results:
            warnings.extend(result["warnings"])
    else:
        outline = (request.outline.model_copy(deep=True) if request.outline
               else await outline_factory(request, sources, warnings))
    on_stage("balance", 12)
    if analysis_results:
        verify_outline(outline, analysis_results, sources)
    else:
        outline = Outline.model_validate(await balance(outline.model_dump(), template, warnings=warnings))
    on_outline(outline.model_dump())
    if label_assets is not None:
        on_stage("assets", 14)
        await label_assets(template, request.content_pack_ids)
    illustrations = None
    if draw_illustrations is not None:
        on_stage("illustrations", 15)
        owner, metas = await draw_illustrations(
            {"slides": [{"content": slide.model_dump()} for slide in outline.slides]}, template)
        illustrations = (owner, metas) if metas else None
    findings = None
    if request.contextual_audit and contextual_check is not None:
        on_stage("contextual_audit", 15)
        findings = await contextual_check(
            {"slides": [{"content": slide.model_dump()} for slide in outline.slides]}, sources)
    results = []
    for index, variant in enumerate(variants):
        if analysis_results:
            verify_outline(outline, analysis_results, sources)
        on_stage("layout_and_audit", 20 + int(index * 75 / max(1, len(variants))))
        result = await render_variant(request, outline.model_dump(), template, sources,
                                      variant["id"], findings, illustrations)
        results.append(result)
        on_variant(result)
    return results

