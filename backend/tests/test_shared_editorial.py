"""Batch sharing preserves actual HTTP evidence and never reuses another run."""
import asyncio
import copy
import io
import json
import time

import httpx
import pytest
from fastapi.testclient import TestClient
from pptx import Presentation

from designer.app import create_app
from designer.business_editorial import editor_payload, validate_editorial, validate_draft, PROMPT
from designer.inference_trace import capture_inference, new_trace, validated_content
from designer.shared_editorial import SharedEditorial
from test_business_editorial import prepared, response_for, draft_for, install_transport, model_env
from test_business_period_service import upload
from acceptance_evidence import verify_shared_jobs


@pytest.mark.parametrize('word', ['Первоочередной', 'Первоначальный', 'Первопричина', 'Третейский'])
def test_qualitative_words_are_not_number_literals(word):
    sources, _, outline = prepared()
    response = response_for(editor_payload(sources, outline, 'Отчёт'))
    response['pages'][1]['title'] = word + ' ориентир: {{fact:q3_net}}'
    # Historical v3 prose still accepts qualitative words; v4 uses fact menus.
    validate_editorial(response, sources, outline, conclusions=False)


@pytest.mark.parametrize('word', ['первый', 'первая', 'первую', 'первых', 'первым', 'третья', 'третьих', 'третий', 'треть', 'трети', 'третей', 'третям', 'третями', 'третях'])
def test_actual_ordinals_remain_forbidden(word):
    sources, _, outline = prepared()
    response = response_for(editor_payload(sources, outline, 'Отчёт'))
    response['pages'][1]['title'] = 'Ориентир ' + word + ': {{fact:q3_net}}'
    with pytest.raises(ValueError, match='Числа и даты'):
        validate_editorial(response, sources, outline)


def test_compact_payload_retains_page_bindings_tokens_and_unique_context():
    sources, _, outline = prepared()
    payload = editor_payload(sources, outline, 'Отчёт')
    assert len(PROMPT) < 1600
    assert 'facts' not in payload
    assert all('context_excerpt' not in page and 'statements' not in page for page in payload['pages'])
    assert all(ref in payload['context'] for page in payload['pages'] for ref in page['context_refs'])
    validate_editorial(response_for(payload), sources, outline)


@pytest.mark.parametrize('tamper', ['order', 'number', 'stale', 'foreign_fact', 'binding'])
def test_small_model_response_cannot_bypass_full_editorial_validation(tamper):
    sources, _, outline = prepared()
    value = draft_for(editor_payload(sources, outline, 'Отчёт'))
    if tamper == 'order': value['pages'].reverse()
    if tamper == 'number': value['pages'][0]['title'] += ' 999'
    if tamper == 'stale': value['input_sha256'] = '0' * 64
    if tamper == 'foreign_fact': value['pages'][0]['title'] += ' {{fact:invented}}'
    if tamper == 'binding': value['pages'][0]['fact_ids'] = ['invented']
    with pytest.raises(ValueError):
        validate_draft(value, sources, outline)


def test_shared_http_batch_has_one_model_call_and_fresh_next_batch(tmp_path, monkeypatch, model_env):
    calls = []
    async def handler(request):
        calls.append(request)
        await asyncio.sleep(.04)  # Ensure the second job joins while the owner is running.
        payload = json.loads(json.loads(request.content)['messages'][1]['content'])
        return httpx.Response(200, json={'id': 'batch-response-' + str(len(calls)),
            'choices': [{'message': {'content': json.dumps(draft_for(payload), ensure_ascii=False)}}]})
    install_transport(monkeypatch, handler)
    with TestClient(create_app(tmp_path)) as client:
        template_ids = []
        for index in range(3):
            native = Presentation(); slide = native.slides.add_slide(native.slide_layouts[1])
            slide.shapes.title.text = 'Шаблон ' + str(index)
            slide.placeholders[1].text = 'Образец оформления'
            stream = io.BytesIO(); native.save(stream)
            template_ids.append(client.post('/api/v1/templates', files={
                'file': (f'template-{index}.pptx', stream.getvalue())}).json()['id'])
        request = upload(client)
        request.update(generate_images=False, model_content_generation=True)
        requests = [{**request, 'template_id': template_id} for template_id in template_ids]
        # A mismatched batch is rejected before any job or paid call exists.
        bad = copy.deepcopy(requests); bad[1]['brief'] += ' Другой вопрос.'
        assert client.post('/api/v1/generation-batches', json={'requests': bad}).status_code == 422
        assert not calls
        batches = []
        for count in (1, 2):
            submitted = client.post('/api/v1/generation-batches', json={'requests': requests})
            assert submitted.status_code == 202, submitted.text
            jobs = submitted.json()['jobs']; deadline = time.monotonic() + 100
            while any(job['status'] not in {'completed', 'failed'} for job in jobs) and time.monotonic() < deadline:
                time.sleep(.03)
                jobs = [client.get('/api/v1/jobs/' + job['id']).json() for job in jobs]
            assert all(job['status'] == 'completed' for job in jobs), jobs
            evidence = [{'job_id': job['id'], 'inference': job['inference']} for job in jobs]
            summary = verify_shared_jobs(evidence, 3)
            assert summary['validated_model_calls'] == 1 and summary['templates_reusing_content'] == 2
            assert len(calls) == count
            for job in jobs:
                assert validated_content(job['inference']) and len(job['presentation_ids']) == 3
                for identifier in job['presentation_ids']:
                    record = client.get('/api/v1/presentations/' + identifier).json()
                    assert record['generation']['mode'] == 'llm'
            batches.append(evidence)
        assert batches[0][0]['inference']['response_id'] != batches[1][0]['inference']['response_id']
        reused = next(job for job in batches[0] if job['inference'].get('shared_inference'))
        reused['inference']['content_input_sha256'] = 'f' * 64
        assert not validated_content(reused['inference'])
        with pytest.raises(ValueError):
            verify_shared_jobs(batches[0], 3)


def test_cancelled_owner_releases_waiter_without_extra_call(monkeypatch):
    async def run():
        entered = asyncio.Event()
        async def blocked(*args):
            entered.set()
            await asyncio.Event().wait()
        monkeypatch.setattr('designer.shared_editorial.edit_business', blocked)
        group = SharedEditorial('test-batch')
        async def edit(identifier):
            sources, _, outline = prepared()
            trace = new_trace(True)
            with capture_inference(trace):
                return await group.edit(sources, outline, 'Отчёт', identifier, trace, None)
        owner = asyncio.create_task(edit('owner'))
        await entered.wait()
        waiter = asyncio.create_task(edit('waiter'))
        await asyncio.sleep(0)
        owner.cancel()
        with pytest.raises(asyncio.CancelledError):
            await owner
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(waiter, 1)
    asyncio.run(run())
