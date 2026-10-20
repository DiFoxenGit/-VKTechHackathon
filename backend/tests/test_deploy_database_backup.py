import importlib.util
import json
from pathlib import Path
import sqlite3
import sys

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / 'deploy/backup_database.py'
spec = importlib.util.spec_from_file_location('deploy_database_backup', SCRIPT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


@pytest.mark.parametrize('status', ['completed', 'running', 'queued'])
def test_backup_preserves_all_rows_and_refuses_active_jobs(tmp_path, status):
    source = tmp_path / 'designer.sqlite3'
    with sqlite3.connect(source) as db:
        db.execute('CREATE TABLE records (kind TEXT, id TEXT, data TEXT)')
        db.execute('INSERT INTO records VALUES (?,?,?)', ('jobs', 'job', json.dumps({'status': status})))
        db.execute('INSERT INTO records VALUES (?,?,?)', ('presentations', 'deck', '{"revision":7}'))
    if status in {'running', 'queued'}:
        with pytest.raises(ValueError, match='Active generation'):
            module.backup(source, 'a' * 40)
        assert not (tmp_path / 'deploy-backups').exists()
    else:
        target = module.backup(source, 'a' * 40)
        with sqlite3.connect(source) as a, sqlite3.connect(target) as b:
            assert a.execute('SELECT * FROM records').fetchall() == b.execute('SELECT * FROM records').fetchall()
        if sys.platform != 'win32':
            assert target.stat().st_mode & 0o777 == 0o600
        assert module.backup(source, 'a' * 40) != target


def test_missing_database_is_not_created(tmp_path):
    missing = tmp_path / 'missing.sqlite3'
    with pytest.raises(sqlite3.Error):
        module.backup(missing, 'a' * 40)
    assert not missing.exists()


def test_diagnostics_report_counts_and_statuses_without_secrets(tmp_path, monkeypatch):
    source = tmp_path / 'designer.sqlite3'
    with sqlite3.connect(source) as db:
        db.execute('CREATE TABLE records (kind TEXT, id TEXT, data TEXT)')
        db.execute('INSERT INTO records VALUES (?,?,?)', ('jobs', 'job', 'private-dataset-text'))
    monkeypatch.setenv('DESIGNER_API_KEY', 'private-api-key')
    class Response:
        status = 200
        def __enter__(self): return self
        def __exit__(self, *args): pass
    calls = []
    def open_request(request, timeout):
        calls.append(request.full_url)
        assert timeout == 3 and request.get_header('Authorization') == 'Bearer private-api-key'
        if request.full_url.endswith('workflow'):
            raise TimeoutError('private-provider-details')
        return Response()
    monkeypatch.setattr(module.urllib.request, 'urlopen', open_request)
    result = module.diagnostic_snapshot(source)
    assert len(calls) == 3 and result['records'] == [{'kind': 'jobs', 'count': 1, 'bytes': 20}]
    assert result['api'][1]['error_type'] == 'TimeoutError'
    assert result['api'][0]['http'] == result['api'][2]['http'] == 200
    assert 'private' not in json.dumps(result)
