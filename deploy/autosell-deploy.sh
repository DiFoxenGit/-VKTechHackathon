#!/usr/bin/env bash
set -euo pipefail

APP="${APP_DIR:-/root/vk-presentations-main}"
NGINX_SNIPPET=/etc/nginx/snippets/vk-presentations.conf
SHA="${1:-}"
[[ "$SHA" =~ ^[0-9a-f]{40}$ ]] || { echo 'Expected a full commit SHA' >&2; exit 2; }
cd "$APP"
git fetch --quiet origin main
git merge-base --is-ancestor "$SHA" origin/main || { echo 'Commit is not in GitHub main' >&2; exit 1; }
test -z "$(git status --porcelain --untracked-files=no)" || { echo 'Tracked server files have local changes' >&2; exit 1; }
PREVIOUS_SHA="$(git rev-parse HEAD)"
BACKUP="$APP/tmp/deploy-backups/$(date -u +%Y%m%d-%H%M%S)"
mkdir -p "$BACKUP"
cp "$NGINX_SNIPPET" "$BACKUP/nginx.conf"
COMPOSE=(docker compose -p vk-presentations-main --env-file .env.autosell -f deploy/compose.autosell.yml)
for service in backend frontend; do
    image="vk-presentations-main-$service"
    if docker image inspect "$image:latest" >/dev/null 2>&1; then
        docker tag "$image:latest" "$image:previous"
    fi
done

rollback() {
    local status=$?
    trap - ERR
    cp "$BACKUP/nginx.conf" "$NGINX_SNIPPET"
    nginx -t && nginx -s reload
    git checkout --quiet --detach "$PREVIOUS_SHA"
    for service in backend frontend; do
        image="vk-presentations-main-$service"
        if docker image inspect "$image:previous" >/dev/null 2>&1; then
            docker tag "$image:previous" "$image:latest"
        fi
    done
    "${COMPOSE[@]}" up -d --no-build || true
    echo "Deployment failed; restored $PREVIOUS_SHA and nginx configuration" >&2
    exit "$status"
}
trap rollback ERR
git checkout --quiet --detach "$SHA"
"${COMPOSE[@]}" build backend
"${COMPOSE[@]}" build frontend
"${COMPOSE[@]}" up -d --no-build --wait --wait-timeout 240
curl -fsS http://127.0.0.1:8078/health >/dev/null
curl -fsS http://127.0.0.1:8079/presentations/ >/dev/null
cp deploy/autosell-nginx.conf "$NGINX_SNIPPET"
nginx -t
nginx -s reload
curl -fsS --resolve auto-sell.site:443:127.0.0.1 https://auto-sell.site/presentations/health >/dev/null
echo "Deployed $SHA to https://auto-sell.site/presentations/"
