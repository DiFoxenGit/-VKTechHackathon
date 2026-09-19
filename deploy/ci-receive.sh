#!/usr/bin/env bash
# Приёмник релизов от GitHub Actions. Ставится на сервер вне каталога проекта
# и привязывается к deploy-ключу через command= в authorized_keys:
# по этому ключу нельзя получить shell, можно только передать релиз.
#
#   ssh <сервер> deploy <sha>  < release.tar.gz
#
# Шаги: распаковать релиз, синхронизировать код (.env, templates и рабочие
# файлы сервера не трогаются), запустить deploy/deploy.sh. Если сборка или
# проверка /health не прошли — вернуть прошлые образы и код.
set -euo pipefail

APP="${APP_DIR:-$HOME/vk-designer}"
CI="${CI_DIR:-$HOME/vk-designer-ci}"
KEEP_RELEASES=3

read -r cmd sha rest <<<"${SSH_ORIGINAL_COMMAND:-}"
if [ "$cmd" != deploy ] || ! [[ "$sha" =~ ^[0-9a-f]{40}$ ]] || [ -n "${rest:-}" ]; then
  echo "использование: deploy <sha из 40 hex-символов>" >&2
  exit 2
fi

mkdir -p "$CI/releases"
exec 9>"$CI/deploy.lock"
flock -w 1800 9 || { echo "предыдущий деплой не завершился за 30 минут" >&2; exit 1; }

rel="$CI/releases/$sha"
rm -rf "$rel" && mkdir -p "$rel"
tar -xzf - -C "$rel"
[ -f "$rel/deploy/deploy.sh" ] || { echo "в релизе нет deploy/deploy.sh" >&2; exit 1; }

prev_sha="$(cat "$APP/.deployed-sha" 2>/dev/null || true)"
echo "деплой $sha (было: ${prev_sha:-неизвестно})"

sync_code() {
  rsync -a --delete \
    --exclude=/.env --exclude=/templates/ --exclude=/out/ --exclude=/tmp_upload/ \
    --exclude=/bench.py --exclude=/.deployed-sha \
    "$1/" "$APP/"
}

for s in backend frontend; do
  docker image inspect "vk-designer-$s:latest" >/dev/null 2>&1 \
    && docker tag "vk-designer-$s:latest" "vk-designer-$s:prev"
done

sync_code "$rel"
cd "$APP"

if bash deploy/deploy.sh; then
  echo "$sha" > .deployed-sha
  ls -1dt "$CI"/releases/*/ | tail -n +$((KEEP_RELEASES + 1)) | xargs -r rm -rf
  docker image prune -f >/dev/null
  echo "готово: $sha"
  exit 0
fi

echo "деплой не прошёл, откат на ${prev_sha:-прошлые образы}" >&2
for s in backend frontend; do
  docker image inspect "vk-designer-$s:prev" >/dev/null 2>&1 \
    && docker tag "vk-designer-$s:prev" "vk-designer-$s:latest"
done
if [ -n "$prev_sha" ] && [ -d "$CI/releases/$prev_sha" ]; then
  sync_code "$CI/releases/$prev_sha"
fi
docker compose -f docker-compose.yml -f deploy/compose.server.yml up -d --no-build
exit 1
