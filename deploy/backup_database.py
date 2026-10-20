"""Consistent pre-deploy snapshot, refusing to interrupt an active generation."""
import json
import os
from pathlib import Path
import re
import sqlite3
import sys
import tempfile
import time
import urllib.request


def diagnostic_snapshot(database):
    """Bounded pre-restart evidence; never print data, headers or credentials."""
    result = {'api': []}
    try:
        with sqlite3.connect(database.resolve().as_uri() + '?mode=ro', uri=True, timeout=3) as conn:
            result['records'] = [dict(kind=kind, count=count, bytes=size) for kind, count, size in
                conn.execute('SELECT kind,count(*),sum(length(CAST(data AS BLOB))) FROM records GROUP BY kind')]
    except (sqlite3.Error, OSError):
        result['database_status'] = 'unavailable'
    key = os.getenv('DESIGNER_API_KEY', '')
    headers = {'Authorization': 'Bearer ' + key} if key else {}
    for path in ('/health', '/api/v1/workflow', '/api/v1/templates'):
        started = time.monotonic()
        item = {'path': path}
        try:
            request = urllib.request.Request('http://127.0.0.1:8000' + path, headers=headers)
            with urllib.request.urlopen(request, timeout=3) as response:
                item['http'] = response.status
        except Exception as exc:
            item['error_type'] = type(exc).__name__
        item['seconds'] = round(time.monotonic() - started, 3)
        result['api'].append(item)
    return result


def backup(database, sha):
    if not re.fullmatch('[a-f0-9]{40}', sha):
        raise ValueError('Invalid deployment SHA')
    with sqlite3.connect(database.resolve().as_uri() + '?mode=ro', uri=True) as source:
        jobs = (json.loads(row[0]) for row in source.execute('SELECT data FROM records WHERE kind=?', ('jobs',)))
        if any(job.get('status') in {'queued', 'running'} for job in jobs):
            raise ValueError('Active generation; deployment deferred. Retry CI after completion.')
        folder = database.parent / 'deploy-backups'
        folder.mkdir(mode=0o700, exist_ok=True)
        descriptor, target = tempfile.mkstemp(prefix=sha + '-', suffix='.sqlite3', dir=folder)
        os.close(descriptor)
        with sqlite3.connect(target) as destination:
            source.backup(destination)
    return Path(target)


if __name__ == '__main__':
    print('Pre-deploy diagnostics: ' + json.dumps(diagnostic_snapshot(Path('/data/designer.sqlite3'))), flush=True)
    try:
        backup(Path('/data/designer.sqlite3'), sys.argv[1])
    except (ValueError, sqlite3.Error, OSError, IndexError):
        raise SystemExit('Database backup deferred or failed; existing containers preserved') from None
    print('Private database backup completed')
