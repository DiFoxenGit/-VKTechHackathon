#!/usr/bin/env bash
set -euo pipefail

APP="${APP_DIR:-/root/vk-presentations-main}"
NGINX_SNIPPET="${NGINX_SNIPPET:-/etc/nginx/snippets/vk-presentations.conf}"
SHA="${1:-}"
[[ "$SHA" =~ ^[0-9a-f]{40}$ ]] || { echo 'Expected a full commit SHA' >&2; exit 2; }
cd "$APP"
git fetch --quiet origin main
git merge-base --is-ancestor "$SHA" origin/main || { echo 'Commit is not in GitHub main' >&2; exit 1; }
test -z "$(git status --porcelain --untracked-files=no)" || { echo 'Tracked server files have local changes' >&2; exit 1; }
PREVIOUS_SHA="$(git rev-parse HEAD)"
BACKUP="$APP/tmp/deploy-backups/$(date -u +%Y%m%d-%H%M%S)"
install -m 700 -d "$BACKUP"
install -m 600 .env.autosell "$BACKUP/server.env"
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
    install -m 600 "$BACKUP/server.env" .env.autosell
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
python3 deploy/runtime_profile.py .env.autosell
"${COMPOSE[@]}" build backend
"${COMPOSE[@]}" build frontend
"${COMPOSE[@]}" up -d --no-build --wait --wait-timeout 240
curl -fsS http://127.0.0.1:8078/health >/dev/null
curl -fsS http://127.0.0.1:8079/presentations/ >/dev/null
cp deploy/autosell-nginx.conf "$NGINX_SNIPPET"
nginx -t
nginx -s reload
curl -fsS --resolve auto-sell.site:443:127.0.0.1 https://auto-sell.site/presentations/health >/dev/null
"${COMPOSE[@]}" exec -T backend python -c 'import json,os; keys=("DESIGNER_LLM_PROVIDER","DESIGNER_VK_MODEL","DESIGNER_VK_SKIP","DESIGNER_FALLBACK_PROVIDER","DESIGNER_FALLBACK_MODEL","DESIGNER_FALLBACK_TIMEOUT","DESIGNER_MAX_JOBS","DESIGNER_IMAGE_PROVIDER","DESIGNER_IMAGE_MODEL","DESIGNER_IMAGE_LIMIT"); print("Runtime profile:",json.dumps({k:os.getenv(k) for k in keys}))'
echo "Deployed $SHA to https://auto-sell.site/presentations/"
