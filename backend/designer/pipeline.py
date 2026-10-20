"""Orchestrates deterministic algorithms, model calls and presentation assembly."""
import logging
import asyncio
import os
import re
import time
import httpx
from fastapi import HTTPException
from starlette.concurrency import run_in_threadpool
from . import ai
from .inference_trace import new_trace, capture_inference, current_trace, publish, validated_content
from .models import Outline
from .workflow import narrative
from .algorithms.context import select_context
from .algorithms.validation import validate_outline
from .algorithms.balance import balance_plan, apply_condensation, finish_balance
from .comparisons import add_comparison_charts
from .analytics_bridge import analyse_sources, build_outline, verify_outline, validate_business_scope
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
        trace = current_trace()
        if trace is not None:
            trace.update(status='fallback', fallback_used=True,
                         error_code=trace['error_code'] or 'not_configured',
                         message='Текст сокращён алгоритмически; исходные формулировки сохранены')
        LOGGER.warning('Condense agent unavailable')
        if warnings is not None:
            warnings.append("ИИ не сократил текст: применена алгоритмическая подгонка с сохранением исходника.")
    return finish_balance(outline, candidate, payload, warnings)


async def run_generation(request, template, sources, *, outline_factory, balance,
                         render_variant, variants, on_stage, on_outline,
                         on_variant, warnings, label_assets=None,
                         draw_illustrations=None, contextual_check=None, on_inference=None,
                         shared_editorial=None, job_id=None):
    if not sources:
        sources = [{'id': 'brief', 'text': request.brief}]
    trace = new_trace()
    sources[0]['_inference'] = trace
    with capture_inference(trace, on_inference):
        try:
            return await _run_generation(request, template, sources, outline_factory=outline_factory,
                balance=balance, render_variant=render_variant, variants=variants, on_stage=on_stage,
                on_outline=on_outline, on_variant=on_variant, warnings=warnings, label_assets=label_assets,
                draw_illustrations=draw_illustrations, contextual_check=contextual_check,
                shared_editorial=shared_editorial, job_id=job_id, on_inference=on_inference)
        finally:
            publish()


async def _run_generation(request, template, sources, *, outline_factory, balance,
                         render_variant, variants, on_stage, on_outline,
                         on_variant, warnings, label_assets=None,
                         draw_illustrations=None, contextual_check=None,
                         shared_editorial=None, job_id=None, on_inference=None):
    """Run the same content through algorithms, optional AI and each renderer.

    The HTTP layer owns jobs/storage. Callbacks make this pipeline runnable and
    testable without FastAPI, a real model, filesystem exports or a job queue.
    """
    on_stage("outline", 5)
    from .business_bridge import prepare_business
    analysis_results = await run_in_threadpool(prepare_business, sources, request.brief)
    if analysis_results is None:
        validate_business_scope(sources, request.brief)
        analysis_results = await run_in_threadpool(analyse_sources,sources,getattr(request, "analysis_goal", "") or request.brief)
    if analysis_results:
        on_stage("analytics", 8)
        sources[0]["_analysis_results"] = analysis_results
        if getattr(request, "narrative", False):
            sources[0]["_story"] = {"goal": request.brief}
        if sources[0].get('_business'):
            sources[0].pop('_business_editorial', None)
        outline = build_outline(analysis_results, sources, request.slide_count)
        for result in analysis_results:
            warnings.extend(result["warnings"])
        if sources[0].get('_business'):
            trace = current_trace()
            requested = getattr(request, 'model_content_generation', None) is not False
            trace['requested'] = requested
            if requested:
                started = time.monotonic()
                on_stage('model_content', 10)
                try:
                    settings = ai.llm_settings()
                    trace.update(provider=settings.profile, model=settings.model or None)
                    if not settings.configured:
                        raise HTTPException(503, 'Текстовая модель не настроена')
                    from .business_editorial import edit_business
                    sources[0].pop('_business_editorial', None)
                    async with asyncio.timeout(240):
                        if shared_editorial is None:
                            outline = await edit_business(sources, outline, request.brief)
                        else:
                            outline = await shared_editorial.edit(sources, outline, request.brief,
                                                                 job_id, trace, on_inference)
                    trace['content_reused_for_variants'] = len(variants)
                except (HTTPException, TimeoutError) as exc:
                    if isinstance(exc, TimeoutError):
                        trace.update(error_code='timeout', validation='failed')
                        if trace['calls']:
                            trace['calls'][-1].update(error_code='timeout', validation='failed')
                    trace.update(status='unavailable' if not trace['attempted'] else 'fallback',
                        fallback_used=True, completed=False,
                        error_code=trace['error_code'] or 'not_configured',
                        message='Модель не подготовила проверенный текст. Сохранён расчётный текст; повторите генерацию.')
                    reason = {'authorization': 'Проверьте доступ к провайдеру.',
                        'rate_limit': 'Провайдер ограничил число запросов; повторите позже.',
                        'timeout': 'Провайдер не ответил вовремя.',
                        'not_configured': 'Настройте текстовую модель.',
                        'invalid_response': 'Ответ модели не прошёл проверку фактов или формата.'}.get(trace['error_code'], 'Провайдер временно недоступен.')
                    trace['message'] = reason + ' ' + trace['message']
                    warnings.append(trace['message'])
                    LOGGER.warning('Business editorial unavailable: %s', trace['error_code'])
                finally:
                    trace['duration_seconds'] = round(time.monotonic() - started, 3)
                    publish()
    else:
        trace = current_trace()
        trace['requested'] = request.outline is None
        outline = (request.outline.model_copy(deep=True) if request.outline
               else await outline_factory(request, sources, warnings))
    on_stage("balance", 12)
    if analysis_results:
        verify_outline(outline, analysis_results, sources)
    else:
        content_trace = current_trace()
        with capture_inference(new_trace()) as condense_trace:
            try:
                outline = Outline.model_validate(await balance(outline.model_dump(), template, warnings=warnings))
            finally:
                content_trace['condense'] = condense_trace
        publish()
    if validated_content(current_trace()):
        current_trace()['content_reused_for_variants'] = len(variants)
        publish()
    on_outline(outline.model_dump())
    if label_assets is not None:
        on_stage("assets", 14)
        content_trace = current_trace()
        with capture_inference(new_trace()) as asset_trace:
            try:
                await label_assets(template, request.content_pack_ids)
            except (HTTPException, ai.InvalidCompletion, httpx.HTTPError, ValueError, TimeoutError):
                asset_trace.update(status='fallback', fallback_used=True,
                    error_code=asset_trace['error_code'] or 'asset_tagging_failed')
                warnings.append('Модель не подписала изображения; использована существующая библиотека.')
                LOGGER.warning('Asset tagging unavailable')
            finally:
                content_trace['asset_tagging'] = asset_trace
        publish()
    illustrations = None
    if draw_illustrations is not None:
        on_stage("illustrations", 15)
        requested = getattr(request, 'generate_images', None)
        if requested is None:
            requested = bool(re.search(r'(?:сгенерир\w*|созда\w* нов\w*)[^.\n]{0,100}(?:иллюстрац|картин|изображ)|generate[^.\n]{0,100}(?:image|illustration)', request.brief, re.I))
        drawn = await draw_illustrations(
            {"slides": [{"content": slide.model_dump()} for slide in outline.slides], 'image_requested': requested}, template)
        owner, metas = drawn[:2]
        status = drawn[2] if len(drawn) > 2 else {'status': 'ready' if metas else 'failed', 'message': 'Иллюстрации готовы' if metas else 'Изображение не создано'}
        illustrations = (owner, metas, status)
        if status['status'] in {'unavailable', 'failed'}:
            warnings.append(status['message'])
    findings = None
    if request.contextual_audit and contextual_check is not None:
        on_stage("contextual_audit", 15)
        content_trace = current_trace()
        # A successful optional audit is not proof of model-authored content.
        with capture_inference() as audit_trace:
            try:
                findings = await contextual_check(
                    {"slides": [{"content": slide.model_dump()} for slide in outline.slides]}, sources)
            finally:
                content_trace['contextual_audit'] = audit_trace
        publish()
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

