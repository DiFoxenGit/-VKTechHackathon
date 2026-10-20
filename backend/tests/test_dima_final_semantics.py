"""Final Dima regressions: role-aware headings and honest pixel checks."""
import asyncio
import json

import pytest

from designer import ai, ai_assets
from designer.business_editorial import EDITORIAL_VERSION, editor_payload, validate_draft
from test_business_editorial import prepared, draft_for


@pytest.mark.parametrize('choice', [0, 1])
def test_role_titles_do_not_require_decorative_numbers_and_keep_all_facts(choice):
    sources, results, outline = prepared()
    payload = editor_payload(sources, outline, sources[0]['text'])
    draft = draft_for(payload)
    for page, edit in zip(payload['pages'], draft['pages']):
        edit['title'] = page['approved_titles'][choice]
    edited, _ = validate_draft(draft, sources, outline)
    from designer.analytics_bridge import verify_outline
    sources[0]['_business_editorial'] = {'version': EDITORIAL_VERSION,
        'response': validate_draft(draft, sources, outline)[1]}
    assert verify_outline(edited, results, sources)
    assert not any(char.isdigit() for char in edited.slides[-2].title)
    assert edited.slides[-1].bullets == outline.slides[-1].bullets
    assert all(old.visual == new.visual for old, new in zip(outline.slides, edited.slides))
    roles = json.loads(edited.slides[-1].notes)['semantic_blocks']
    assert roles['role'] == 'action'
    assert roles['action_ref'] == 'implementation'


@pytest.mark.parametrize('title', [
    'Риски: {{fact:partners_margin_change}}',
    'Ресурсы ограничивают рост: {{fact:partners_margin_change}}',
])
def test_risk_title_cannot_hide_missing_meaning_behind_a_metric(title):
    sources, _, outline = prepared()
    payload = editor_payload(sources, outline, '')
    draft = draft_for(payload)
    draft['pages'][-2]['title'] = title
    with pytest.raises(ValueError, match='смысловой заголовок'):
        validate_draft(draft, sources, outline)


@pytest.mark.parametrize('availability,answer,expected', [
    (False, {}, 'unavailable'), (True, {}, 'failed'),
    (True, {'has_text': 'false'}, 'failed'), (True, {'has_text': False}, 'passed'),
])
def test_image_check_never_claims_unchecked_pixels_are_clean(tmp_path, monkeypatch, availability, answer, expected):
    monkeypatch.setattr(ai, 'vision_available', lambda: availability)
    monkeypatch.setenv('DESIGNER_VLM_MODEL', 'fixture-vision')
    monkeypatch.setenv('DESIGNER_VLM_BASE_URL', 'https://fixture.invalid/v1')
    async def vision(*args, **kwargs):
        return answer
    monkeypatch.setattr(ai, 'vision_completion', vision)
    (tmp_path / 'test.png').write_bytes(b'fixture')
    metas = [{'id': 'test', 'file': 'test.png'}]
    kept = asyncio.run(ai_assets.drop_lettered(metas, tmp_path))
    assert kept[0]['quality_check']['status'] == expected
    assert kept[0]['quality_check']['scope'] == 'visible_text_only'
    assert kept[0]['quality_check']['image_sha256']


def test_legacy_saved_titles_replay_without_rewriting_historical_facts():
    from designer.business_editorial import replay_editorial
    from test_business_editorial import response_for
    sources, _, outline = prepared()
    response = response_for(editor_payload(sources, outline, ''))
    for edit in response['pages']:
        edit['title'] = 'Ориентир ' + edit['id'] + ': {{fact:' + edit['fact_ids'][0] + '}}'
    response['pages'][-2]['title'] = 'Риски: {{fact:partners_margin_change}}'
    response['pages'][-1]['title'] = 'Действия: {{fact:q3_margin}}'
    sources[0]['_business_editorial'] = dict(version='business-editorial-2', response=response)
    assert replay_editorial(sources, outline).slides[-2].title.startswith('Риски:')
    with pytest.raises(ValueError, match='заголовок-вывод'):
        from designer.business_editorial import validate_editorial
        validate_editorial(response, sources, outline)


def test_duplicate_title_feedback_identifies_both_pages():
    from designer.business_editorial import validate_editorial
    from test_business_editorial import response_for
    sources, _, outline = prepared()
    response = response_for(editor_payload(sources, outline, ''))
    response['pages'][0]['title'] = response['pages'][2]['title']
    with pytest.raises(ValueError, match=r'страница trend, поле title; повтор decision.title'):
        validate_editorial(response, sources, outline, conclusions=False)


def test_failed_pixel_check_does_not_log_provider_body(tmp_path, monkeypatch, caplog):
    monkeypatch.setattr(ai, 'vision_available', lambda: True)
    monkeypatch.setenv('DESIGNER_VLM_MODEL', 'fixture-vision')
    monkeypatch.setenv('DESIGNER_VLM_BASE_URL', 'https://fixture.invalid/v1')
    async def fail(*args, **kwargs):
        raise ValueError('secret-provider-body')
    monkeypatch.setattr(ai, 'vision_completion', fail)
    (tmp_path / 'a.png').write_bytes(b'fixture')
    kept = asyncio.run(ai_assets.drop_lettered([{'id': 'a', 'file': 'a.png'}], tmp_path))
    assert kept[0]['quality_check']['status'] == 'failed'
    assert 'secret-provider-body' not in caplog.text
