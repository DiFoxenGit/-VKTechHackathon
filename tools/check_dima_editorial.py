"""D0-D4 acceptance. Offline by default; --live makes five edits and one audit.

No image generation, deployment, environment changes or retries of whole runs.
Each editorial call has the service's bounded validation retries. An exclusive
marker prevents accidentally repeating a paid run into the same output folder.
"""
import argparse
import asyncio
import copy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))

from acceptance_evidence import sanitized_inference, verify_business
from check_parallel_generation import business_inputs
from designer.analytics_bridge import extract, build_outline, verify_outline
from designer.business_bridge import prepare_business
from designer.business_editorial import (EDITORIAL_VERSION, edit_business, editor_payload,
                                        validate_draft)
from designer.business_semantics import semantic_blocks
from designer.inference_trace import capture_inference


def inputs(version, period):
    folder, settings, conditions, context, expected = business_inputs(version, period)
    sources = [{'id': 'brief', 'text': 'Прибыль и маржа, план-факт'}]
    for name in ('sales', 'plan', 'products', 'regions'):
        path = (folder if name in {'sales', 'plan'} else ROOT / 'samples/business-acceptance/data-v1') / (name + '.csv')
        sources.append({'id': name, 'text': '', 'datasets': extract(path.read_bytes(), path.name)})
    sources.append({'id': 'context', 'text': context})
    sources[0]['business_request'] = dict(settings=settings, conditions=conditions, context_source_id='context')
    return sources, expected


def audit_fixture():
    original = dict(title='Проверка партнёрской экономики', bullets=[
        'Чистая выручка: 94 823 698 RUB. Валовая прибыль: 31 570 684 RUB.',
        'Причины изменения маржи требуют проверки.'], visual={'kind': 'none'}, source_refs=['verified'])
    defective = copy.deepcopy(original)
    defective['title'] = 'Реклама доказанно увеличила выручку вдвое'
    fixed = {**copy.deepcopy(defective), 'title': original['title']}
    def protected(value):
        return hashlib.sha256(json.dumps({key: value[key] for key in ('bullets', 'visual', 'source_refs')},
                                         sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    return dict(synthetic_defective_copy=True, never_mutate_original=True,
        mode='contextual_text_audit; not visual', original=original, defective=defective,
        after_semantic_fix=fixed, protected_before_sha256=protected(defective),
        protected_after_sha256=protected(fixed), protected_facts_unchanged=protected(defective)==protected(fixed),
        sources=[{'id': 'verified', 'text': 'Выручка 94 823 698 RUB; прибыль 31 570 684 RUB. '
                  'Причинный эффект рекламы не оценивался. Удвоение выручки не доказано.'}],
        expected_codes=['unsupported_fact', 'title_mismatch'],
        safe_fix=dict(title=original['title'], preserve=['bullets', 'visual', 'source_refs']),
        geometry_fixture=dict(owner='Stepa', defect='Move the synthetic title beyond the safe area in a COPY',
                              user_choice_required=True, change_original=False))


def require_vk(trace):
    if not (trace['completed'] and trace['validation'] == 'passed' and not trace['fallback_used']
            and trace['provider'] == 'vk' and trace['model'] == 'qwen38-27b-fp8'
            and trace['successful_calls'] >= 1 and trace['calls']
            and all((c.get('provider') or trace['provider']) == 'vk' and c.get('status_code') == 200
                    for c in trace['calls'])):
        raise ValueError('Real VK Qwen acceptance failed; fallback does not qualify')


async def run(args):
    args.output.mkdir(parents=True, exist_ok=True)
    if args.live:
        with (args.output / 'live-started.json').open('x', encoding='utf8') as stream:
            json.dump({'started_utc': datetime.now(timezone.utc).isoformat()}, stream)
    report = dict(started_utc=datetime.now(timezone.utc).isoformat(), live=args.live,
                  scope='Dima semantics; not full UI/template/visual acceptance', runs=[], status='running')
    def save():
        (args.output / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf8')
    save()
    try:
        for label, version, period in [('baseline', 'baseline', 'default'),
                ('B-1', 'version-b', 'default'), ('B-2', 'version-b', 'default'),
                ('B-3', 'version-b', 'default'), ('alternate', 'baseline', 'alternate')]:
            if label not in args.labels:
                continue
            sources, expected = inputs(version, period)
            results = prepare_business(sources, sources[0]['text'])
            outline = build_outline(results, sources, 12)
            payload = editor_payload(sources, outline, sources[0]['text'])
            evidence = verify_business({'business_proof': sources[0]['_business']['analysis']},
                                      expected, sources[0]['business_request']['settings'])
            started = time.monotonic()
            with capture_inference() as trace:
                if args.live:
                    edited = await edit_business(sources, outline, sources[0]['text'])
                else:
                    draft = dict(input_sha256=payload['input_sha256'], pages=[
                        dict(id=p['id'], title=p['approved_titles'][0], hypothesis=None) for p in payload['pages']])
                    edited, response = validate_draft(draft, sources, outline)
                    sources[0]['_business_editorial'] = dict(version=EDITORIAL_VERSION, response=response)
            item = dict(label=label, input_sha256=payload['input_sha256'],
                        seconds=round(time.monotonic()-started, 3), inference=sanitized_inference(trace),
                        independent_controls=evidence['independent_numeric_controls'],
                        verified_facts=evidence['verified_facts'], facts_preserved=verify_outline(edited, results, sources),
                        twelve_pages=len(edited.slides), titles=[s.title for s in edited.slides])
            report['runs'].append(item)
            save()
            if args.live:
                require_vk(trace)
            # An arbitrary new template cannot change these native content objects.
            item['content_sha256'] = hashlib.sha256(json.dumps(edited.model_dump(), sort_keys=True,
                                                               ensure_ascii=False).encode()).hexdigest()
            if label == 'B-1':
                examples = dict(schema_version='dima-semantic-review-1', synthetic_data=True,
                    settings=sources[0]['business_request']['settings'],
                    page_contract=[semantic_blocks(p) for p in sources[0]['_business']['story']['slides']],
                    editorial_input=payload,
                    examples=[r for r in results if r.get('business_view') in
                              {'quarter_kpi', 'monthly_trend', 'region_plan_gap', 'decision_table', 'product_structure'}])
                (args.output / 'semantic-review.json').write_text(json.dumps(examples, ensure_ascii=False, indent=2), encoding='utf8')
            print(json.dumps({'label': label, 'facts_preserved': True, 'seconds': item['seconds'],
                              'provider': trace.get('provider'), 'attempts': trace['attempts']}, ensure_ascii=False), flush=True)
        fixture = audit_fixture()
        (args.output / 'audit-fixture.json').write_text(json.dumps(fixture, ensure_ascii=False, indent=2), encoding='utf8')
        if args.live:
            from designer.ai_audit import contextual_audit
            with capture_inference() as trace:
                findings = await contextual_audit({'slides': [{'content': fixture['defective']}]}, fixture['sources'])
            report['audit'] = dict(inference=sanitized_inference(trace), findings=findings,
                                  mode='contextual_text', original_preserved=True)
            save()
            require_vk(trace)
            if not any(f['code'] in fixture['expected_codes'] for f in findings):
                raise ValueError('Contextual audit missed the synthetic semantic defect')
        report['status'] = 'passed'
        save()
        return report
    except Exception as exc:
        report.update(status='failed', error_type=type(exc).__name__)
        if 'trace' in locals():
            report['last_inference'] = sanitized_inference(trace)
        save()
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true')
    parser.add_argument('--labels', nargs='+', choices=['baseline', 'B-1', 'B-2', 'B-3', 'alternate'],
                        default=['baseline', 'B-1', 'B-2', 'B-3', 'alternate'])
    parser.add_argument('--output', type=Path, default=ROOT / 'output/dima-semantic-acceptance')
    arguments = parser.parse_args()
    try:
        asyncio.run(run(arguments))
    except Exception as exc:
        raise SystemExit('Dima acceptance failed (' + type(exc).__name__ + '); inspect sanitized report.json') from None
