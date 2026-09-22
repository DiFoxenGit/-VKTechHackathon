#!/usr/bin/env bash
# Приёмник деплоя от CI SourceCraft. Ставится на сервер вне каталога проекта
# и привязывается к deploy-ключу через command= в authorized_keys:
# по этому ключу нельзя получить shell, можно только попросить выкатить коммит.
#
#   ssh <сервер> deploy <sha>
#
# Каталог проекта — git-клон с доступом на чтение к репозиторию. Приёмник
# забирает свежий master, принимает только коммиты из него, переключает
# рабочую копию (.env и templates в .gitignore и не трогаются) и запускает
# deploy/deploy.sh. Если сборка или /health не прошли — возвращает прошлый
# коммит и прошлые образы.
set -euo pipefail

APP="${APP_DIR:-$HOME/vk-designer}"
CI="${CI_DIR:-$HOME/vk-designer-ci}"
BRANCH="${DEPLOY_BRANCH:-master}"
COMPOSE=(docker compose -f docker-compose.yml -f deploy/compose.server.yml)

read -r cmd sha rest <<<"${SSH_ORIGINAL_COMMAND:-}"
if [ "$cmd" != deploy ] || ! [[ "$sha" =~ ^[0-9a-f]{40}$ ]] || [ -n "${rest:-}" ]; then
  echo "использование: deploy <sha из 40 hex-символов>" >&2
  exit 2
fi

mkdir -p "$CI"
exec 9>"$CI/deploy.lock"
flock -w 1800 9 || { echo "предыдущий деплой не завершился за 30 минут" >&2; exit 1; }

cd "$APP"
# Связь сервера с хостингом кода временами рвётся: три попытки с таймаутом.
for attempt in 1 2 3; do
  timeout 90 git fetch --quiet origin "$BRANCH" && break
  [ "$attempt" = 3 ] && { echo "не удалось забрать origin/$BRANCH" >&2; exit 1; }
  echo "fetch не прошёл, повтор через 10 с" >&2
  sleep 10
done
if ! git merge-base --is-ancestor "$sha" "origin/$BRANCH"; then
  echo "коммит $sha не входит в origin/$BRANCH" >&2
  exit 1
fi

prev_sha="$(git rev-parse HEAD)"
echo "деплой $sha (было: $prev_sha)"

for s in backend frontend; do
  docker image inspect "vk-designer-$s:latest" >/dev/null 2>&1 \
    && docker tag "vk-designer-$s:latest" "vk-designer-$s:prev"
done

git checkout --quiet -B "$BRANCH" "$sha"
git reset --quiet --hard "$sha"

if bash deploy/deploy.sh; then
  docker image prune -f >/dev/null
  echo "готово: $sha"
  exit 0
fi

echo "деплой не прошёл, откат на $prev_sha" >&2
git reset --quiet --hard "$prev_sha"
for s in backend frontend; do
  docker image inspect "vk-designer-$s:prev" >/dev/null 2>&1 \
    && docker tag "vk-designer-$s:prev" "vk-designer-$s:latest"
done
"${COMPOSE[@]}" up -d --no-build
exit 1
