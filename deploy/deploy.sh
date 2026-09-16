#!/usr/bin/env bash
# Развёртывание на сервере: собрать образы и поднять сервис за Caddy.
# Запускать из корня проекта на сервере: bash deploy/deploy.sh
set -euo pipefail

cd "$(dirname "$0")/.."

[ -f .env ] || { echo "Нет .env — скопируйте .env.example и заполните"; exit 1; }

# 2 ГБ RAM: сборка фронтенда без ограничения памяти Node падает по OOM.
export NODE_OPTIONS="${NODE_OPTIONS:---max-old-space-size=1024}"

docker compose -f docker-compose.yml -f deploy/compose.server.yml build
docker compose -f docker-compose.yml -f deploy/compose.server.yml up -d

echo "--- статус ---"
docker compose -f docker-compose.yml -f deploy/compose.server.yml ps
echo "--- проверка API ---"
for i in $(seq 1 30); do
  if curl -fsS http://localhost/health >/dev/null 2>&1; then echo "сервис отвечает"; exit 0; fi
  sleep 2
done
echo "сервис не ответил за 60 секунд, смотрите docker compose logs" >&2
exit 1
