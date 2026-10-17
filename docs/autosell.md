# Рабочая версия на auto-sell.site

Адрес приложения: **https://auto-sell.site/presentations/**.

Основной проект теперь собирает интерфейс H10MS из своей папки `frontend/`, а не прежнюю версию. Его исходники перенесены из `H10ms/hackaton-frontend` вместе с проверками пайплайна, API, хранилища и браузерными сценариями. Для локального запуска и CI используются одинаковые исходники.

## Сборка

- `VITE_APP_BASE_PATH=/presentations/` задаёт адрес ассетов и приложения.
- `VITE_API_URL=/presentations/api/v1` задаёт публичный API.
- Docker Compose без префикса продолжает поддерживать `/` и `/api/v1`.
- `npm test` запускает TypeScript и проверки реальных алгоритмов и API-адаптера. `npm run build` собирает приложение.

Модельные URL, ключ и имя модели задаются **только на backend** в `.env.autosell`, файл имеет права `600` и исключён из Git. В `VITE_*` ключ модели не передаётся. Настроенный сервер сообщает `llm_configured: true`; интерфейс отправляет ему бриф без заранее составленного плана.

## Развёртывание

Рабочая копия: `/root/vk-presentations-main`. Отдельный Compose-проект `vk-presentations-main` описан в `deploy/compose.autosell.yml`:

| Компонент | Адрес на хосте |
| --- | --- |
| Backend | `127.0.0.1:8078` |
| Frontend | `127.0.0.1:8079` |
| Публичный nginx | `/presentations/` → frontend, `/presentations/api/` → backend |

Данные хранятся в отдельном именованном томе. Исходные шаблоны монтируются из существующей папки `/root/vk-presentations/Датасет` только для чтения. Прежний backend на `8077` и его данные сохраняются для отката.

`deploy/autosell-deploy.sh <SHA>` принимает только коммит из GitHub `origin/main`, последовательно собирает backend и frontend, ожидает healthcheck и затем переключает nginx. Перед переключением сохраняются конфигурация nginx, предыдущий SHA и теги образов. При ошибке скрипт восстанавливает их. Сборки выполняются последовательно; Node ограничен 512 МБ heap для сервера с 2 ГБ RAM.

Для GitHub Actions используется отдельный SSH-ключ, ограниченный командой из `deploy/autosell-receive.sh`. Приёмник устанавливается вне репозитория в `/root/vk-presentations-main-ci/receive.sh`, а публичный ключ — в `authorized_keys` с `restrict,command=...`. Переменные `DEPLOY_HOST` и `DEPLOY_USER` указывают на этот сервер; `DEPLOY_KNOWN_HOSTS` содержит его проверенный ключ. Ключ доступа root с рабочей машины в GitHub не передаётся.

## Проверка

```bash
curl -fsS https://auto-sell.site/presentations/health
curl -fsS https://auto-sell.site/presentations/api/v1/templates
```

В браузере: открыть приложение, загрузить материалы, задать количество слайдов, создать презентацию, скачать PPTX/PDF/HTML и проверить открытие файлов. В Network генерация должна содержать `content_pack_ids` и не должна содержать `outline`, когда используется серверный ИИ. Ключ модели не должен находиться в запросах браузера или JavaScript-сборке.
