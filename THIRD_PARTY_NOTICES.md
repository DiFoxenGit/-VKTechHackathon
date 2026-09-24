# Сторонние компоненты и их лицензии

Код проекта распространяется под [MIT](LICENSE). Ниже — всё стороннее, что входит в сборку
или вызывается ею. Копилефтных лицензий (GPL, AGPL, SSPL) среди встраиваемых зависимостей нет:
до 25.09.2026 рендер PDF шёл через PyMuPDF (AGPL-3.0), он заменён на pypdfium2 и Pillow.

## Бэкенд (Python, `backend/requirements.txt` и зависимости)

| Пакет | Лицензия | Для чего |
|---|---|---|
| fastapi, pydantic, pydantic-core, annotated-types, typing-inspection | MIT | HTTP API и схемы |
| starlette, uvicorn, httpx, httpcore, idna, click | BSD-3-Clause | сервер и HTTP-клиент |
| anyio, h11 | MIT | асинхронный ввод-вывод |
| python-multipart | Apache-2.0 | загрузка файлов |
| python-pptx | MIT | чтение шаблонов и сборка PPTX |
| lxml | BSD-3-Clause | разбор XML, SVG и HTML |
| xlsxwriter | BSD-2-Clause | данные диаграмм внутри PPTX |
| pypdf | BSD-3-Clause | чтение PDF контент-пакетов |
| pypdfium2 (и встроенный PDFium) | Apache-2.0 или BSD-3-Clause | растр страниц PDF, текстовый слой HTML |
| pillow | MIT-CMU (HPND) | картинки: разбор, перекраска, контакт-листы |
| fonttools | MIT | покрытие глифов шрифтами шаблона |
| certifi | MPL-2.0 | корневые сертификаты (файл данных, без изменений) |
| packaging | Apache-2.0 или BSD-2-Clause | сравнение версий |
| typing-extensions | PSF-2.0 | совместимость типов |

## Фронтенд (`frontend/package.json`, рантайм)

| Пакет | Лицензия |
|---|---|
| react, react-dom | MIT |
| lucide-react | ISC |
| @fontsource-variable/manrope (шрифт Manrope) | OFL-1.1 |
| @fontsource/play (шрифт Play) | OFL-1.1 |

## Входит в Docker-образ, но работает отдельной программой

| Компонент | Лицензия | Для чего |
|---|---|---|
| LibreOffice Impress | MPL-2.0 | PPTX → PDF (отдельный процесс, не линкуется) |
| fonts-dejavu-core | Bitstream Vera / DejaVu (свободная) | запасной шрифт рендера |
| fonts-liberation | OFL-1.1 | запасной шрифт рендера |

## Шрифты и картинки в репозитории

| Что | Лицензия |
|---|---|
| `backend/designer/assets/fonts/Play-*.ttf` | OFL-1.1, текст в `backend/designer/assets/fonts/OFL.txt` |
| Встроенный набор иконок и иллюстраций `backend/designer/assets/pack/` | нарисован для проекта генератором `tools/make_content_pack.py`, распространяется под MIT вместе с кодом |

## Модели (вызываются по API, в репозиторий не входят)

| Модель | Лицензия весов | Роль |
|---|---|---|
| gpt-oss-20b | Apache-2.0 | план колоды, текстовый аудит |
| Qwen3.6-35B-A3B | Apache-2.0 | аудит по картинке, подпись ассетов |

## Происхождение кода

Бэкенд и фронтенд выросли из репозиториев участников команды (`kiritomp3/vk-presentations`,
`H10ms/hackaton-frontend`) и распространяются под той же MIT. В исходном репозитории бэкенд
лежал внутри обёртки Presenton (Apache-2.0); её код сюда не перенесён — пакет `designer`
написан командой.

Подробности про размер и выбор моделей — в [MODELS.md](MODELS.md). Шаблоны презентаций
организаторов в репозиторий не входят (`templates/` в `.gitignore`).
