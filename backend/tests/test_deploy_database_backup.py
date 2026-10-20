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
