#!/usr/bin/env bash
# Развёртывание на сервере: собрать образы и поднять сервис за Caddy.
# Запускать из корня проекта на сервере: bash deploy/deploy.sh
set -euo pipefail

cd "$(dirname "$0")/.."

[ -f .env ] || { echo "Нет .env — скопируйте .env.example и заполните"; exit 1; }

# 2 ГБ RAM: сборка фронтенда без ограничения памяти Node падает по OOM.
export NODE_OPTIONS="${NODE_OPTIONS:---max-old-space-size=1024}"

# Первый старт после смены версии разбора шаблонов долгий: бэкенд заново
# разбирает каждый шаблон и рендерит его страницы, чтобы измерить фон. На двух
# ядрах это несколько минут, и минуты ожидания не хватает — деплой откатывался
# на исправном коде. Предел можно поднять через HEALTH_TIMEOUT.
HEALTH_TIMEOUT="${HEALTH_TIMEOUT:-420}"
COMPOSE=(docker compose -f docker-compose.yml -f deploy/compose.server.yml)

"${COMPOSE[@]}" build
"${COMPOSE[@]}" up -d

echo "--- статус ---"
"${COMPOSE[@]}" ps
echo "--- проверка API (до ${HEALTH_TIMEOUT} с) ---"
started=$SECONDS
until curl -fsS http://localhost/health >/dev/null 2>&1; do
  waited=$((SECONDS - started))
  if [ "$waited" -ge "$HEALTH_TIMEOUT" ]; then
    echo "сервис не ответил за ${HEALTH_TIMEOUT} с" >&2
    # Причина почти всегда в логе бэкенда: незапустившийся импорт, нехватка
    # памяти, ошибка в .env. Печатаем её здесь, чтобы не ходить на сервер.
    "${COMPOSE[@]}" logs --tail=40 backend >&2 || true
    exit 1
  fi
  if [ $((waited % 30)) -lt 3 ] && [ "$waited" -gt 0 ]; then
    echo "ждём: ${waited} с"
  fi
  sleep 3
done
echo "сервис отвечает через $((SECONDS - started)) с"
