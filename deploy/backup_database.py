"""Consistent pre-deploy snapshot, refusing to interrupt an active generation."""
import json
import os
from pathlib import Path
import re
import sqlite3
import sys
import tempfile


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
    try:
        backup(Path('/data/designer.sqlite3'), sys.argv[1])
    except (ValueError, sqlite3.Error, OSError, IndexError):
        raise SystemExit('Database backup deferred or failed; existing containers preserved') from None
    print('Private database backup completed')
