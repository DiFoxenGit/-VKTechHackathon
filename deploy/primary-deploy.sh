#!/usr/bin/env bash
# Primary stand. Private runtime override and existing data volumes are preserved.
set -euo pipefail
umask 022
SHA="${1:-}"
[[ "$SHA" =~ ^[0-9a-f]{40}$ ]] || { echo 'Expected a full commit SHA' >&2; exit 2; }
APP="${APP_DIR:-/home/administrator/vk-designer}"
RUNTIME="${RUNTIME_DIR:-/home/administrator/vk-designer-runtime}"
cd "$APP"
test -f "$RUNTIME/genapi.compose.json"
test -z "$(git status --porcelain --untracked-files=no)" || { echo 'Tracked server files have local changes' >&2; exit 1; }
timeout 90 git fetch --quiet https://github.com/DiFoxenGit/-VKTechHackathon.git \
    main:refs/remotes/github/main
git merge-base --is-ancestor "$SHA" refs/remotes/github/main || { echo 'Commit is not in GitHub main' >&2; exit 1; }
PREVIOUS_SHA="$(git rev-parse HEAD)"
if [ "$SHA" != "$PREVIOUS_SHA" ] && git merge-base --is-ancestor "$SHA" "$PREVIOUS_SHA"; then
    echo "Skipped superseded deployment $SHA"
    exit 0
fi
COMPOSE=(docker compose -p vk-designer -f docker-compose.yml -f deploy/compose.server.yml -f "$RUNTIME/genapi.compose.json")
BACKUP="$RUNTIME/deploy-backups/$(date -u +%Y%m%d-%H%M%S)"
install -m 700 -d "$BACKUP"
install -m 600 "$RUNTIME/genapi.compose.json" "$BACKUP/genapi.compose.json"
if [ -f .env ]; then install -m 600 .env "$BACKUP/server.env"; fi
sha256sum "$RUNTIME/genapi.compose.json" > "$BACKUP/runtime.sha256"
for service in backend frontend; do
    running_id="$("${COMPOSE[@]}" ps -q "$service")"
    test -n "$running_id"
    docker tag "$(docker inspect --format '{{.Image}}' "$running_id")" "vk-designer-$service:before-$SHA"
done
switched=0
rollback() {
    local status=$?
    trap - ERR
    git checkout --quiet --detach "$PREVIOUS_SHA"
    for service in backend frontend; do
        docker tag "vk-designer-$service:before-$SHA" "vk-designer-$service:latest"
    done
    if [ "$switched" = 1 ]; then
        "${COMPOSE[@]}" up -d --no-build --wait --wait-timeout 240 || true
    fi
    echo "Deployment failed; restored $PREVIOUS_SHA. Backup: $BACKUP" >&2
    exit "$status"
}
trap rollback ERR
git checkout --quiet --detach "$SHA"
"${COMPOSE[@]}" build backend
"${COMPOSE[@]}" build frontend
# Do not interrupt active generation. Back up SQLite consistently before restart.
"${COMPOSE[@]}" exec -T backend python - "$SHA" <<'PY'
import json
import os
import sqlite3
import sys
import tempfile
from pathlib import Path

with sqlite3.connect('/data/designer.sqlite3') as source:
    jobs = (json.loads(row[0]) for row in source.execute('SELECT data FROM records WHERE kind=?', ('jobs',)))
    if any(job.get('status') in {'queued', 'running'} for job in jobs):
        raise SystemExit('Active generation; deployment deferred. Retry CI after completion.')
    folder = Path('/data/deploy-backups')
    folder.mkdir(mode=0o700, exist_ok=True)
    descriptor, target = tempfile.mkstemp(prefix=sys.argv[1] + '-', suffix='.sqlite3', dir=folder)
    os.close(descriptor)
    with sqlite3.connect(target) as destination:
        source.backup(destination)
PY
sha256sum --status -c "$BACKUP/runtime.sha256"
switched=1
"${COMPOSE[@]}" up -d --no-build --wait --wait-timeout 240
curl -fsS --retry 5 --retry-delay 3 --retry-all-errors http://127.0.0.1/health >/dev/null
sha256sum --status -c "$BACKUP/runtime.sha256"
printf '%s\n' "$SHA" > "$RUNTIME/deployed-main.sha"
install -m 700 deploy/primary-deploy.sh "$RUNTIME/primary-deploy.sh.pending"
mv "$RUNTIME/primary-deploy.sh.pending" "$RUNTIME/primary-deploy.sh"
echo "Deployed $SHA to primary http://158.160.225.35/"
