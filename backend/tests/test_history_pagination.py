"""History pages must not parse every stored business dataset."""
from fastapi.testclient import TestClient

from designer.app import create_app
from designer.storage import Store


def test_history_projects_and_pages_in_sql_without_decoding_unselected_records(tmp_path):
    app = create_app(tmp_path)
    store = app.state.store
    with store.connection() as c:
        c.execute('INSERT INTO records VALUES (?,?,?)', ('presentations', 'old', 'invalid unselected JSON'))
    for index in range(4):
        store.put('presentations', dict(id=str(index), title='Отчёт', revision=1,
            deck={'bulky': 'x' * 50000}, sources=['private material'], audit={},
            analysis=[{'bulky': 'x' * 50000}], analysis_results=[], business_proof={},
            generation={'mode': 'llm'}))
    with TestClient(app) as client:
        response = client.get('/api/v1/presentations?offset=1&limit=2')
    assert response.status_code == 200
    value = response.json()
    assert value['total'] == 5 and [p['id'] for p in value['items']] == ['2', '1']
    assert all(p['generation']['mode'] == 'llm' for p in value['items'])
    assert all(not ({'deck', 'sources', 'audit', 'analysis', 'analysis_results', 'business_proof'} & p.keys()) for p in value['items'])
    assert store.get('presentations', '1')['sources'] == ['private material']


def test_empty_page_has_total_and_no_records(tmp_path):
    store = Store(tmp_path)
    store.put('presentations', {'id': 'one'})
    assert store.page('presentations', offset=10, limit=2) == {'total': 1, 'items': []}
