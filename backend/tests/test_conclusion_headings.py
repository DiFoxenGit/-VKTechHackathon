"""Conclusion headings must follow computed signs, targets and current inputs."""
import copy

import pytest

from designer.business_editorial import editor_payload, validate_draft, EDITORIAL_VERSION, replay_editorial
from test_business_editorial import prepared, draft_for


@pytest.mark.parametrize('version', ['baseline', 'version-b'])
def test_business_model_receives_conclusions_not_questions(version):
    from test_business_period_service import inputs
    from designer.business_bridge import prepare_business
    from designer.analytics_bridge import build_outline, verify_outline
    sources = inputs(version)
    results = prepare_business(sources, sources[0]['text'])
    outline = build_outline(results, sources, 12)
    payload = editor_payload(sources, outline, '')
    assert all('?' not in title for page in payload['pages'] for title in page['approved_titles'])
    for choice in (0, 1):
        value = draft_for(payload)
        for edit, page in zip(value['pages'], payload['pages']):
            edit['title'] = page['approved_titles'][choice]
        edited, response = validate_draft(value, sources, outline)
        sources[0]['_business_editorial'] = dict(version=EDITORIAL_VERSION, response=response)
        assert verify_outline(edited, results, sources)
        assert ('Выручка выросла' if choice == 0 else 'Изменение выручки') in edited.slides[0].title
        assert edited.slides[1].visual == outline.slides[1].visual
        sources[0].pop('_business_editorial')


@pytest.mark.parametrize('exact,word', [('12', 'выросла'), ('-12', 'снизилась'),
    ('0', 'не изменилась'), (None, 'не рассчитано'), ('0.00001', 'точности')])
def test_growth_conclusion_handles_sign_zero_unavailable_and_rounding(exact, word):
    from designer.business_semantics import conclusion_titles
    sources, _, _ = prepared()
    payload = copy.deepcopy(sources[0]['_business'])
    payload['analysis']['facts']['qoq_net_growth']['exact'] = exact
    page = next(p for p in payload['story']['slides'] if p['id'] == 'trend')
    assert word in conclusion_titles(page, payload['analysis']['facts'])[0]


@pytest.mark.parametrize('exact,word', [('99', 'не выполнен'), ('100', 'выполнен'),
    ('101', 'превышен'), (None, 'не рассчитано'), ('99.999', 'около')])
def test_plan_conclusion_is_supported_by_attainment(exact, word):
    from designer.business_semantics import conclusion_titles
    sources, _, _ = prepared()
    payload = copy.deepcopy(sources[0]['_business'])
    payload['analysis']['facts']['q3_net_plan_attainment']['exact'] = exact
    page = next(p for p in payload['story']['slides'] if p['id'] == 'plan')
    assert word in conclusion_titles(page, payload['analysis']['facts'])[0]


@pytest.mark.parametrize('title', [
    'Как менялась выручка: {{fact:qoq_net_growth}}?',
    'План выручки выполнен: {{fact:q3_net_plan_attainment}}',
])
def test_model_cannot_replace_verified_conclusion_with_question_or_false_plan_claim(title):
    sources, _, outline = prepared()
    payload = editor_payload(sources, outline, '')
    value = draft_for(payload)
    index = 2 if '?' in title else 3
    value['pages'][index]['title'] = title
    with pytest.raises(ValueError):
        validate_draft(value, sources, outline)


def test_v3_question_titles_replay_without_migrating_saved_decks():
    from designer.business_semantics import approved_titles
    from test_business_editorial import response_for
    sources, _, outline = prepared()
    payload = editor_payload(sources, outline, '')
    response = response_for(payload)
    for edit, page in zip(response['pages'], sources[0]['_business']['story']['slides']):
        edit['title'] = approved_titles(page)[0]
    sources[0]['_business_editorial'] = dict(version='business-editorial-3', response=response)
    assert '?' in replay_editorial(sources, outline).slides[1].title
