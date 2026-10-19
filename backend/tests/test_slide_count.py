import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from designer.slide_count import explicit_slide_count
from designer.models import Brief, GenerateRequest

CASES=json.loads((Path(__file__).parent/'fixtures/slide_count_cases.json').read_text(encoding='utf-8'))


@pytest.mark.parametrize('case',CASES,ids=lambda case:case['text'])
def test_count_language_contract(case):
    if case.get('error'):
        with pytest.raises(ValueError): explicit_slide_count(case['text'])
    else:
        assert explicit_slide_count(case['text'])==case['count']


def test_conflicting_request_cannot_start_a_paid_generation(tmp_path,monkeypatch):
    from fastapi.testclient import TestClient
    from designer.app import create_app
    monkeypatch.delenv('DESIGNER_TEMPLATE_DIR',raising=False)
    with TestClient(create_app(tmp_path)) as client:
        response=client.post('/api/v1/generations',json={
            'brief':'Создай презентацию из пяти слайдов.',
            'slide_count':10,'template_id':'not-loaded'})
        assert response.status_code==422
        assert '5' in response.text and '10' in response.text


def test_matching_count_and_outline_remain_valid():
    request=GenerateRequest(brief='Создай презентацию из пяти слайдов.',slide_count=5,template_id='test')
    assert request.slide_count==5
    assert Brief(brief='Проект про 5 команд и 10 регионов.',slide_count=10).slide_count==10
    with pytest.raises(ValidationError):
        Brief(brief='Создай презентацию из пяти слайдов.',slide_count=10)
