"""Собрать встроенный визуальный контент-пакет: пиктограммы и иллюстрации в SVG.

Пакет нужен на случай, когда в загруженном шаблоне своих иконок нет или их
некому подписать (мультимодальная модель не настроена). Всё нарисовано заново
на сетке 24×24 (иконки) и 400×300 (иллюстрации), без чужих наборов.

Цвета в иллюстрациях — не значения, а роли: var(--accent), var(--soft) и т. д.
При вставке в слайд роли превращаются в цвета палитры шаблона, поэтому одна и
та же иллюстрация выглядит своей и в синем VK Tech, и в чёрном WorkSpace.

    python tools/make_content_pack.py

Пишет backend/designer/assets/pack/ (встроенный набор) и
samples/content-pack/visual-pack.zip — тот же набор как загружаемый пакет.
"""

import json
import math
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PACK = ROOT / "backend" / "designer" / "assets" / "pack"
ZIP = ROOT / "samples" / "content-pack" / "visual-pack.zip"

ICON_HEAD = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
    'stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
)
ILLUSTRATION_HEAD = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 300">'


def dot(x, y, r=1.1):
    return f'<circle cx="{x}" cy="{y}" r="{r}" fill="currentColor" stroke="none"/>'


def gear_points(cx, cy, outer, inner, teeth, phase=0.0):
    """Контур шестерни: зубья — трапеции между двумя окружностями."""
    points = []
    step = 2 * math.pi / teeth
    for i in range(teeth):
        a = phase + i * step
        for angle, radius in (
            (a - step * 0.22, inner),
            (a - step * 0.12, outer),
            (a + step * 0.12, outer),
            (a + step * 0.22, inner),
        ):
            points.append(f"{cx + radius * math.cos(angle):.2f},{cy + radius * math.sin(angle):.2f}")
    return " ".join(points)


def star_points(cx, cy, outer, inner, rays=5):
    points = []
    for i in range(rays * 2):
        radius = outer if i % 2 == 0 else inner
        angle = -math.pi / 2 + i * math.pi / rays
        points.append(f"{cx + radius * math.cos(angle):.2f},{cy + radius * math.sin(angle):.2f}")
    return " ".join(points)


# Имя, тело SVG, корни слов. Корень совпадает с началом слова подписи, поэтому
# «команд» ловит «команды» и «командам», а «рост» не ловит «простой».
ICONS = [
    ("growth", '<polyline points="3 17 9 11 13 15 21 7"/><polyline points="15 7 21 7 21 13"/>',
     ["рост", "растёт", "растет", "вырос", "увелич", "прирост", "динамик", "эффект", "выгод", "growth", "increase"]),
    ("decline", '<polyline points="3 7 9 13 13 9 21 17"/><polyline points="21 11 21 17 15 17"/>',
     ["сниж", "сниз", "паден", "упал", "сократ", "сокращ", "уменьш", "меньше", "decline", "reduce", "decrease"]),
    ("clock", '<circle cx="12" cy="12" r="9"/><polyline points="12 7 12 12 15.5 14"/>',
     ["врем", "срок", "минут", "мин", "час", "длител", "быстр", "дедлайн", "time", "hour", "minute"]),
    ("calendar", '<rect x="3" y="5" width="18" height="16" rx="2"/><line x1="16" y1="3" x2="16" y2="7"/>'
     '<line x1="8" y1="3" x2="8" y2="7"/><line x1="3" y1="11" x2="21" y2="11"/>' + dot(8, 15.5) + dot(12, 15.5),
     ["календар", "дата", "дат", "квартал", "месяц", "недел", "дней", "день", "дня", "год", "расписан", "график работ",
      "q1", "q2", "q3", "q4", "calendar", "date", "quarter", "week", "month"]),
    ("team", '<circle cx="9" cy="8" r="3.5"/><path d="M3 20v-1a5 5 0 0 1 5-5h2a5 5 0 0 1 5 5v1"/>'
     '<path d="M16 4.6a3.5 3.5 0 0 1 0 6.8"/><path d="M21 20v-1a5 5 0 0 0-3.5-4.8"/>',
     ["команд", "отдел", "сотрудник", "люд", "человек", "коллег", "участник", "дизайнер", "специалист", "сообществ",
      "team", "people", "staff"]),
    ("user", '<circle cx="12" cy="8" r="4"/><path d="M5 21v-1a6 6 0 0 1 6-6h2a6 6 0 0 1 6 6v1"/>',
     ["пользоват", "клиент", "автор", "руководител", "заказчик", "спикер", "user", "client", "customer"]),
    ("target", '<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="5"/>' + dot(12, 12, 1.4),
     ["цель", "цели", "целей", "целев", "задач", "фокус", "результат", "kpi", "ориентир", "target", "goal", "objective"]),
    ("idea", '<path d="M9 18h6"/><path d="M10 21h4"/>'
     '<path d="M12 3a6 6 0 0 0-3.9 10.6c.6.6.9 1.4.9 2.4h6c0-1 .3-1.8.9-2.4A6 6 0 0 0 12 3z"/>',
     ["идея", "идеи", "идей", "идею", "гипотез", "предлож", "инициатив", "концепц", "инновац", "творч", "idea", "innovation", "proposal"]),
    ("document", '<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/>'
     '<polyline points="14 3 14 8 19 8"/><line x1="9" y1="13" x2="15" y2="13"/><line x1="9" y1="17" x2="13" y2="17"/>',
     ["документ", "файл", "отчёт", "отчет", "материал", "регламент", "текст", "заметк", "бриф", "pdf", "docx",
      "document", "file", "report"]),
    ("presentation", '<rect x="3" y="4" width="18" height="12" rx="1.5"/><line x1="12" y1="16" x2="12" y2="20"/>'
     '<line x1="8" y1="20" x2="16" y2="20"/><polyline points="7 12 10 9 13 11 17 7"/>',
     ["презентац", "колод", "слайд", "доклад", "выступлен", "pptx", "deck", "slide", "presentation"]),
    ("layout", '<rect x="3" y="3" width="18" height="18" rx="2"/><line x1="3" y1="9" x2="21" y2="9"/>'
     '<line x1="9" y1="9" x2="9" y2="21"/>',
     ["шаблон", "макет", "вёрстк", "верстк", "сверст", "структур", "компонов", "layout", "template"]),
    ("database", '<ellipse cx="12" cy="6" rx="8" ry="3"/><path d="M4 6v6c0 1.7 3.6 3 8 3s8-1.3 8-3V6"/>'
     '<path d="M4 12v6c0 1.7 3.6 3 8 3s8-1.3 8-3v-6"/>',
     ["данн", "база", "баз", "хранилищ", "источник", "sql", "data", "database", "storage"]),
    ("cloud", '<path d="M7 18a4.5 4.5 0 0 1-.6-9a6 6 0 0 1 11.4 1.6A3.8 3.8 0 0 1 17.5 18z"/>',
     ["облак", "облач", "saas", "онлайн", "хостинг", "cloud", "online"]),
    ("server", '<rect x="3" y="4" width="18" height="7" rx="2"/><rect x="3" y="13" width="18" height="7" rx="2"/>'
     + dot(7, 7.5) + dot(7, 16.5),
     ["сервер", "машин", "vcpu", "cpu", "ram", "гб", "памят", "инфраструкт", "мощност", "ресурс", "железо",
      "server", "hardware", "infrastructure"]),
    ("shield", '<path d="M12 3l7 3v5c0 4.5-3 8.5-7 10c-4-1.5-7-5.5-7-10V6z"/><polyline points="9 12 11 14 15 10"/>',
     ["безопасн", "защит", "надёжн", "надежн", "соответств", "стил", "фирменн", "security", "protect", "compliance"]),
    ("lock", '<rect x="5" y="11" width="14" height="10" rx="2"/><path d="M8 11V7a4 4 0 0 1 8 0v4"/>',
     ["доступ", "конфиденц", "приват", "закрыт", "пароль", "шифрован", "lock", "access", "private"]),
    ("check", '<circle cx="12" cy="12" r="9"/><polyline points="8 12 11 15 16 9"/>',
     ["готов", "одобр", "решени", "согласов", "выполн", "успех", "успешн", "исправл", "утвер", "done", "approve", "success"]),
    ("gears", f'<polygon points="{gear_points(10, 10, 6.6, 4.6, 6)}"/><circle cx="10" cy="10" r="2"/>'
     f'<polygon points="{gear_points(17.5, 17.5, 4.3, 2.9, 5, 0.3)}"/>',
     ["процесс", "автомат", "настрой", "конвейер", "пайплайн", "механизм", "сборк", "генерац", "операц",
      "process", "automation", "workflow", "pipeline"]),
    ("alert", '<path d="M10.3 4.3L2.6 18a2 2 0 0 0 1.7 3h15.4a2 2 0 0 0 1.7-3L13.7 4.3a2 2 0 0 0-3.4 0z"/>'
     '<line x1="12" y1="9.5" x2="12" y2="13.5"/>' + dot(12, 17),
     ["риск", "проблем", "ошибк", "угроз", "огранич", "внимани", "опасн", "слаб", "выдум", "risk", "warning", "issue"]),
    ("star", f'<polygon points="{star_points(12, 12.5, 9.5, 4.2)}"/>',
     ["качеств", "лучш", "оценк", "рейтинг", "преимущ", "ценност", "премиум", "quality", "best", "value"]),
    ("rocket", '<path d="M14 4c3-1.6 5.4-1.1 6-1c.1.6.6 3-1 6l-7 7l-4-4z"/><path d="M8 12H5l3-4h4"/>'
     '<path d="M12 16v3l4-3v-4"/><circle cx="15.5" cy="8.5" r="1.4"/>'
     '<path d="M6.5 16.5c-1.5.5-2.5 2-2.5 3.5c1.5 0 3-1 3.5-2.5"/>',
     ["запуск", "старт", "релиз", "внедр", "масштаб", "пилот", "раскат", "launch", "release", "rollout", "startup"]),
    ("money", '<circle cx="12" cy="12" r="9"/><path d="M10 17V7h3.5a2.5 2.5 0 0 1 0 5H8"/>'
     '<line x1="8" y1="14.8" x2="14" y2="14.8"/>',
     ["деньг", "бюджет", "стоим", "стоил", "стоит", "руб", "рубл", "₽", "выручк", "затрат", "цен", "экономи", "инвест", "оплат", "финанс",
      "cost", "budget", "money", "price", "revenue"]),
    ("chart", '<line x1="4" y1="20" x2="20" y2="20"/><line x1="7" y1="20" x2="7" y2="13"/>'
     '<line x1="12" y1="20" x2="12" y2="6"/><line x1="17" y1="20" x2="17" y2="10"/>',
     ["аналит", "показател", "метрик", "статист", "отчётност", "дашборд", "измер", "замер", "analytics", "metric",
      "dashboard"]),
    ("pie", '<path d="M12 3a9 9 0 1 0 9 9h-9z"/><path d="M15 3.5a9 9 0 0 1 5.5 5.5H15z"/>',
     ["доля", "доли", "долю", "долей", "процент", "распредел", "сегмент", "share", "percent", "segment"]),
    ("search", '<circle cx="11" cy="11" r="7"/><line x1="16.2" y1="16.2" x2="21" y2="21"/>',
     ["поиск", "исследован", "анализ", "провер", "найд", "аудит", "search", "research", "audit"]),
    ("chat", '<path d="M5 5h14a1 1 0 0 1 1 1v10a1 1 0 0 1-1 1H9l-5 4V6a1 1 0 0 1 1-1z"/>'
     '<line x1="8" y1="9" x2="16" y2="9"/><line x1="8" y1="13" x2="13" y2="13"/>',
     ["коммуникац", "сообщен", "чат", "обсужд", "отзыв", "обратн", "диалог", "мнени", "chat", "feedback", "message"]),
    ("mail", '<rect x="3" y="5" width="18" height="14" rx="2"/><polyline points="3 7 12 13 21 7"/>',
     ["почт", "письм", "рассылк", "email", "mail"]),
    ("mobile", '<rect x="7" y="2" width="10" height="20" rx="2"/><line x1="11" y1="18" x2="13" y2="18"/>',
     ["мобил", "телефон", "смартфон", "приложен", "ios", "android", "app", "mobile", "phone"]),
    ("monitor", '<rect x="3" y="4" width="18" height="12" rx="2"/><line x1="8" y1="20" x2="16" y2="20"/>'
     '<line x1="12" y1="16" x2="12" y2="20"/>',
     ["компьютер", "экран", "интерфейс", "веб", "сайт", "браузер", "html", "desktop", "web", "interface"]),
    ("code", '<polyline points="8 7 3 12 8 17"/><polyline points="16 7 21 12 16 17"/><line x1="14" y1="5" x2="10" y2="19"/>',
     ["код", "разработ", "программ", "api", "open-source", "репозитор", "code", "developer", "software"]),
    ("sparkles", '<path d="M11 3c.5 4 2 5.5 6 6c-4 .5-5.5 2-6 6c-.5-4-2-5.5-6-6c4-.5 5.5-2 6-6z"/>'
     '<path d="M19 14c.2 1.5.8 2.1 2.2 2.3c-1.4.2-2 .8-2.2 2.2c-.2-1.4-.8-2-2.2-2.2c1.4-.2 2-.8 2.2-2.3z"/>',
     ["ии", "нейросет", "модел", "искусствен", "gpt", "llm", "ai", "умн", "интеллект", "машинн"]),
    ("cpu", '<rect x="6" y="6" width="12" height="12" rx="1.5"/><rect x="9.5" y="9.5" width="5" height="5"/>'
     '<line x1="9" y1="2" x2="9" y2="4"/><line x1="15" y1="2" x2="15" y2="4"/><line x1="9" y1="20" x2="9" y2="22"/>'
     '<line x1="15" y1="20" x2="15" y2="22"/><line x1="2" y1="9" x2="4" y2="9"/><line x1="2" y1="15" x2="4" y2="15"/>'
     '<line x1="20" y1="9" x2="22" y2="9"/><line x1="20" y1="15" x2="22" y2="15"/>',
     ["процессор", "вычисл", "инференс", "gpu", "видеокарт", "compute", "inference"]),
    ("plug", '<line x1="9" y1="2" x2="9" y2="7"/><line x1="15" y1="2" x2="15" y2="7"/>'
     '<path d="M6 7h12v4a6 6 0 0 1-12 0z"/><line x1="12" y1="17" x2="12" y2="22"/>',
     ["интеграц", "подключ", "коннектор", "совместим", "протокол", "плагин", "integration", "connect", "plugin"]),
    ("network", '<circle cx="6" cy="12" r="2.5"/><circle cx="18" cy="6" r="2.5"/><circle cx="18" cy="18" r="2.5"/>'
     '<line x1="8.2" y1="10.8" x2="15.8" y2="7.2"/><line x1="8.2" y1="13.2" x2="15.8" y2="16.8"/>',
     ["сеть", "сетев", "связ", "партнёр", "партнер", "экосистем", "распростран", "network", "partner", "ecosystem"]),
    ("education", '<path d="M2 9l10-5l10 5l-10 5z"/><path d="M6 11v5c0 1.5 2.7 3 6 3s6-1.5 6-3v-5"/>'
     '<line x1="22" y1="9" x2="22" y2="14"/>',
     ["обучен", "образован", "студент", "курс", "знани", "учеб", "школ", "education", "learning", "course"]),
    ("book", '<path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20V3H6.5A2.5 2.5 0 0 0 4 5.5z"/>'
     '<path d="M4 19.5A2.5 2.5 0 0 0 6.5 22H20v-5"/>',
     ["книг", "документац", "инструкц", "руководств", "гайд", "справочн", "правил", "guide", "manual", "docs"]),
    ("flag", '<line x1="5" y1="21" x2="5" y2="4"/><path d="M5 4h12l-2 4l2 4H5"/>',
     ["этап", "вех", "milestone", "достиж", "финиш", "итог", "стади", "phase", "stage"]),
    ("question", '<circle cx="12" cy="12" r="9"/><path d="M9.5 9.5a2.5 2.5 0 1 1 3.6 2.2c-.7.4-1.1 1-1.1 1.8"/>'
     + dot(12, 17),
     ["вопрос", "faq", "неизвест", "уточн", "question", "unknown"]),
    ("checklist", '<line x1="10" y1="6" x2="20" y2="6"/><line x1="10" y1="12" x2="20" y2="12"/>'
     '<line x1="10" y1="18" x2="20" y2="18"/><polyline points="3.5 6 5 7.5 7.5 5"/>'
     '<polyline points="3.5 12 5 13.5 7.5 11"/><polyline points="3.5 18 5 19.5 7.5 17"/>',
     ["список", "чек-лист", "требован", "критери", "пункт", "перечен", "checklist", "requirements", "criteria"]),
    ("next", '<circle cx="12" cy="12" r="9"/><line x1="8" y1="12" x2="16" y2="12"/><polyline points="12 8 16 12 12 16"/>',
     ["следующ", "далее", "переход", "дальнейш", "шаг", "план", "next", "step", "plan"]),
    ("refresh", '<path d="M20 11a8 8 0 0 0-14.9-3"/><polyline points="4 4 4 8 8 8"/>'
     '<path d="M4 13a8 8 0 0 0 14.9 3"/><polyline points="20 20 20 16 16 16"/>',
     ["обновл", "цикл", "итерац", "повтор", "регуляр", "ревизи", "верси", "update", "cycle", "iteration", "version"]),
    ("zap", '<polygon points="13 2 4 14 11 14 10 22 20 9 13 9"/>',
     ["скорост", "быстр", "мгновен", "ускор", "производительн", "энерг", "моментал", "fast", "speed", "instant"]),
    ("globe", '<circle cx="12" cy="12" r="9"/><line x1="3" y1="12" x2="21" y2="12"/>'
     '<path d="M12 3a14 14 0 0 1 0 18a14 14 0 0 1 0-18z"/>',
     ["домен", "https", "dns", "интернет", "мир", "глобал", "международ", "стран", "рынок", "рынк", "регион", "global", "world", "market"]),
    ("building", '<path d="M4 21V4a1 1 0 0 1 1-1h10a1 1 0 0 1 1 1v17"/><path d="M16 9h3a1 1 0 0 1 1 1v11"/>'
     '<line x1="2" y1="21" x2="22" y2="21"/><line x1="8" y1="7" x2="9" y2="7"/><line x1="11.5" y1="7" x2="12.5" y2="7"/>'
     '<line x1="8" y1="11" x2="9" y2="11"/><line x1="11.5" y1="11" x2="12.5" y2="11"/>'
     '<line x1="8" y1="15" x2="9" y2="15"/><line x1="11.5" y1="15" x2="12.5" y2="15"/>',
     ["компани", "организац", "офис", "предприят", "бизнес", "корпорат", "холдинг", "company", "business", "enterprise"]),
    ("layers", '<polygon points="12 3 21 8 12 13 3 8"/><polyline points="3 12 12 17 21 12"/><polyline points="3 16 12 21 21 16"/>',
     ["слой", "слои", "уровн", "стек", "очеред", "архитектур", "платформ", "layers", "stack", "platform", "queue"]),
    ("palette", '<path d="M12 3a9 9 0 0 0 0 18c1.1 0 1.8-.8 1.8-1.8c0-.5-.2-.9-.5-1.2c-.3-.3-.5-.8-.5-1.2'
     'c0-1 .8-1.8 1.8-1.8H16a5 5 0 0 0 5-5c0-4.4-4-8-9-8z"/>' + dot(7.5, 11.5, 1.2) + dot(10, 7.5, 1.2) + dot(14.5, 7.5, 1.2),
     ["дизайн", "цвет", "бренд", "оформлен", "визуал", "палитр", "гарнитур", "шрифт", "design", "brand", "style"]),
    ("image", '<rect x="3" y="4" width="18" height="16" rx="2"/><circle cx="8.5" cy="9.5" r="1.5"/>'
     '<polyline points="21 16 16 11 5 20"/>',
     ["изображ", "картин", "фото", "иллюстрац", "скриншот", "image", "photo", "picture"]),
    ("video", '<rect x="3" y="5" width="18" height="14" rx="2"/><polygon points="10 9 15 12 10 15"/>',
     ["видео", "ролик", "трансляц", "демо", "запис", "video", "demo", "stream"]),
    ("bell", '<path d="M6 16v-5a6 6 0 0 1 12 0v5l2 2H4z"/><path d="M10 21h4"/>',
     ["уведомл", "оповещ", "напомин", "сигнал", "notification", "alert"]),
    ("support", '<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="4"/>'
     '<line x1="5.6" y1="5.6" x2="9.2" y2="9.2"/><line x1="14.8" y1="14.8" x2="18.4" y2="18.4"/>'
     '<line x1="14.8" y1="9.2" x2="18.4" y2="5.6"/><line x1="5.6" y1="18.4" x2="9.2" y2="14.8"/>',
     ["поддерж", "помощ", "сопровожд", "сервисн", "support", "help", "service"]),
    ("download", '<line x1="12" y1="3" x2="12" y2="15"/><polyline points="7 10 12 15 17 10"/><line x1="5" y1="21" x2="19" y2="21"/>',
     ["экспорт", "выгруз", "скача", "download", "export"]),
    ("upload", '<line x1="12" y1="21" x2="12" y2="9"/><polyline points="7 14 12 9 17 14"/><line x1="5" y1="3" x2="19" y2="3"/>',
     ["импорт", "загруз", "upload", "import"]),
    ("expand", '<polyline points="15 3 21 3 21 9"/><polyline points="9 21 3 21 3 15"/>'
     '<line x1="21" y1="3" x2="14" y2="10"/><line x1="3" y1="21" x2="10" y2="14"/>',
     ["масштабир", "расшир", "тираж", "распростран", "scale", "expand"]),
    ("funnel", '<polygon points="3 4 21 4 14 12 14 19 10 21 10 12"/>',
     ["воронк", "фильтр", "отбор", "конверс", "funnel", "filter", "conversion"]),
    ("key", '<circle cx="7.5" cy="15.5" r="4.5"/><line x1="10.7" y1="12.3" x2="20" y2="3"/>'
     '<line x1="16" y1="7" x2="19" y2="10"/><line x1="14" y1="9" x2="16" y2="11"/>',
     ["ключ", "токен", "авторизац", "key", "token", "auth"]),
    ("compass", '<circle cx="12" cy="12" r="9"/><polygon points="15.5 8.5 13.5 13.5 8.5 15.5 10.5 10.5"/>',
     ["стратег", "направлен", "навигац", "видени", "курс", "strategy", "direction", "vision"]),
    ("award", '<circle cx="12" cy="9" r="6"/><polyline points="8.5 14 7 22 12 19 17 22 15.5 14"/>',
     ["наград", "достижен", "признан", "лидер", "победител", "award", "achievement", "leader"]),
    ("edit", '<path d="M4 20h4L19 9a2.1 2.1 0 0 0-3-3L5 17z"/><line x1="14" y1="8" x2="17" y2="11"/>',
     ["правк", "редакт", "изменен", "ручн", "вручную", "исправлен", "edit", "manual", "change"]),
    ("eye", '<path d="M2 12s3.5-7 10-7s10 7 10 7s-3.5 7-10 7s-10-7-10-7z"/><circle cx="12" cy="12" r="3"/>',
     ["контрол", "наблюд", "мониторинг", "прозрачн", "видим", "ревью", "просмотр", "review", "monitor", "visibility"]),
    ("cross", '<circle cx="12" cy="12" r="9"/><line x1="9" y1="9" x2="15" y2="15"/><line x1="15" y1="9" x2="9" y2="15"/>',
     ["нарушен", "отказ", "отмен", "отклон", "брак", "запрет", "fail", "reject", "violation"]),
    ("pin", '<path d="M12 21s-7-6-7-11a7 7 0 0 1 14 0c0 5-7 11-7 11z"/><circle cx="12" cy="10" r="2.5"/>',
     ["город", "адрес", "локац", "филиал", "площадк", "location", "city", "office"]),
    ("hourglass", '<path d="M7 3h10"/><path d="M7 21h10"/><path d="M8 3c0 5 8 5 8 9s-8 4-8 9"/>'
     '<path d="M16 3c0 5-8 5-8 9s8 4 8 9"/>',
     ["ожидан", "задерж", "пауза", "простой", "долго", "wait", "delay", "pending"]),
    ("dot", '<circle cx="12" cy="12" r="9"/>' + dot(12, 12, 3.2),
     []),
]

# Иконка без смысла: маркер тезиса, когда подобрать значок по словам не вышло.
NEUTRAL_ICON = "dot"


def v(role):
    return f"var(--{role})"


def person(cx, top, scale, role):
    """Человечек: голова и плечи. Плечи — полуокружность, поэтому без дыр."""
    r = 22 * scale
    body_w, body_h = 76 * scale, 54 * scale
    return (
        f'<circle cx="{cx}" cy="{top + r}" r="{r}" fill="{v(role)}"/>'
        f'<path d="M{cx - body_w / 2} {top + 2 * r + 10 * scale + body_h}'
        f"a{body_w / 2} {body_h} 0 0 1 {body_w} 0z\" fill=\"{v(role)}\"/>"
    )


ILLUSTRATIONS = [
    (
        "growth",
        f'<circle cx="200" cy="150" r="128" fill="{v("soft")}"/>'
        f'<rect x="92" y="62" width="216" height="168" rx="18" fill="{v("paper")}"/>'
        f'<rect x="122" y="168" width="30" height="40" rx="6" fill="{v("muted")}"/>'
        f'<rect x="167" y="142" width="30" height="66" rx="6" fill="{v("muted")}"/>'
        f'<rect x="212" y="118" width="30" height="90" rx="6" fill="{v("accent2")}"/>'
        f'<rect x="257" y="88" width="30" height="120" rx="6" fill="{v("accent")}"/>'
        f'<polyline points="118 150 176 118 220 128 282 70" fill="none" stroke="{v("ink")}" '
        f'stroke-width="7" stroke-linecap="round" stroke-linejoin="round"/>'
        f'<polygon points="292 60 268 66 286 84" fill="{v("ink")}"/>'
        f'<circle cx="330" cy="70" r="10" fill="{v("accent2")}"/><circle cx="70" cy="222" r="14" fill="{v("accent")}"/>',
        ["рост", "вырос", "увелич", "эффект", "результат", "выгод", "показател", "метрик", "динамик", "прирост",
         "growth", "result", "effect"],
    ),
    (
        "team",
        f'<circle cx="200" cy="160" r="124" fill="{v("soft")}"/>'
        + person(128, 92, 0.9, "muted")
        + person(272, 92, 0.9, "accent2")
        + person(200, 70, 1.15, "accent")
        + f'<rect x="96" y="232" width="208" height="12" rx="6" fill="{v("ink")}"/>'
        f'<circle cx="332" cy="84" r="12" fill="{v("accent")}"/><circle cx="66" cy="110" r="8" fill="{v("accent2")}"/>',
        ["команд", "отдел", "сотрудник", "люд", "коллег", "участник", "дизайнер", "специалист", "пользоват",
         "клиент", "team", "people"],
    ),
    (
        "security",
        f'<circle cx="200" cy="150" r="124" fill="{v("soft")}"/>'
        f'<path d="M200 40l92 36v62c0 58-38 104-92 124c-54-20-92-66-92-124V76z" fill="{v("accent")}"/>'
        f'<path d="M200 66l66 26v48c0 42-28 76-66 92z" fill="{v("accent2")}"/>'
        f'<polyline points="160 152 190 182 244 124" fill="none" stroke="{v("paper")}" stroke-width="16" '
        f'stroke-linecap="round" stroke-linejoin="round"/>'
        f'<circle cx="84" cy="80" r="10" fill="{v("accent2")}"/><circle cx="324" cy="228" r="14" fill="{v("muted")}"/>',
        ["безопасн", "защит", "надёжн", "надежн", "риск", "контрол", "аудит", "провер", "соответств", "качеств",
         "security", "risk", "compliance"],
    ),
    (
        "launch",
        f'<circle cx="200" cy="150" r="126" fill="{v("soft")}"/>'
        f'<path d="M200 36c42 30 58 82 46 138h-92c-12-56 4-108 46-138z" fill="{v("accent")}"/>'
        f'<circle cx="200" cy="112" r="24" fill="{v("paper")}"/><circle cx="200" cy="112" r="14" fill="{v("accent2")}"/>'
        f'<path d="M154 150l-34 42v24l40-18z" fill="{v("accent2")}"/>'
        f'<path d="M246 150l34 42v24l-40-18z" fill="{v("accent2")}"/>'
        f'<path d="M176 178h48l-8 30h-32z" fill="{v("muted")}"/>'
        f'<path d="M184 208h32c0 26-8 42-16 56c-8-14-16-30-16-56z" fill="{v("accent2")}"/>'
        f'<circle cx="92" cy="86" r="7" fill="{v("accent")}"/><circle cx="316" cy="70" r="10" fill="{v("accent2")}"/>'
        f'<circle cx="330" cy="200" r="6" fill="{v("accent")}"/>',
        ["запуск", "старт", "релиз", "внедр", "масштаб", "пилот", "раскат", "следующ", "план", "launch", "release",
         "rollout", "start"],
    ),
    (
        "presentation",
        f'<circle cx="200" cy="150" r="126" fill="{v("soft")}"/>'
        f'<rect x="84" y="58" width="232" height="150" rx="14" fill="{v("paper")}"/>'
        f'<rect x="84" y="58" width="232" height="30" rx="14" fill="{v("accent")}"/>'
        f'<rect x="84" y="74" width="232" height="14" fill="{v("accent")}"/>'
        f'<rect x="108" y="108" width="84" height="10" rx="5" fill="{v("ink")}"/>'
        f'<rect x="108" y="128" width="64" height="8" rx="4" fill="{v("muted")}"/>'
        f'<rect x="108" y="144" width="74" height="8" rx="4" fill="{v("muted")}"/>'
        f'<rect x="108" y="160" width="56" height="8" rx="4" fill="{v("muted")}"/>'
        f'<rect x="214" y="150" width="18" height="38" rx="4" fill="{v("muted")}"/>'
        f'<rect x="240" y="130" width="18" height="58" rx="4" fill="{v("accent2")}"/>'
        f'<rect x="266" y="110" width="18" height="78" rx="4" fill="{v("accent")}"/>'
        f'<rect x="194" y="208" width="12" height="36" fill="{v("ink")}"/>'
        f'<rect x="150" y="240" width="100" height="12" rx="6" fill="{v("ink")}"/>',
        ["презентац", "колод", "слайд", "доклад", "шаблон", "макет", "вёрстк", "верстк", "дизайн", "отчёт", "отчет",
         "presentation", "slide", "deck", "report"],
    ),
    (
        "automation",
        f'<circle cx="200" cy="150" r="126" fill="{v("soft")}"/>'
        f'<polygon points="{gear_points(158, 124, 62, 48, 10)}" fill="{v("accent")}"/>'
        f'<circle cx="158" cy="124" r="22" fill="{v("paper")}"/>'
        f'<polygon points="{gear_points(252, 174, 44, 34, 8, 0.2)}" fill="{v("accent2")}"/>'
        f'<circle cx="252" cy="174" r="15" fill="{v("paper")}"/>'
        f'<rect x="76" y="232" width="248" height="16" rx="8" fill="{v("ink")}"/>'
        f'<rect x="96" y="204" width="28" height="28" rx="5" fill="{v("muted")}"/>'
        f'<rect x="286" y="204" width="28" height="28" rx="5" fill="{v("accent")}"/>',
        ["автомат", "процесс", "конвейер", "пайплайн", "генерац", "сборк", "настрой", "механизм", "интеграц",
         "automation", "process", "pipeline", "workflow"],
    ),
    (
        "data",
        f'<circle cx="200" cy="150" r="126" fill="{v("soft")}"/>'
        f'<path d="M110 130a44 44 0 0 1 60-54a58 58 0 0 1 108 20a38 38 0 0 1 2 76H116a42 42 0 0 1-6-42z" '
        f'fill="{v("paper")}"/>'
        f'<rect x="162" y="120" width="76" height="110" fill="{v("accent")}"/>'
        f'<ellipse cx="200" cy="230" rx="38" ry="14" fill="{v("accent")}"/>'
        f'<ellipse cx="200" cy="120" rx="38" ry="14" fill="{v("accent2")}"/>'
        f'<rect x="162" y="158" width="76" height="6" fill="{v("paper")}"/>'
        f'<rect x="162" y="194" width="76" height="6" fill="{v("paper")}"/>'
        f'<circle cx="80" cy="220" r="10" fill="{v("accent2")}"/><circle cx="326" cy="92" r="8" fill="{v("accent")}"/>',
        ["данн", "база", "хранилищ", "облак", "сервер", "инфраструкт", "источник", "интеграц", "ресурс", "машин",
         "data", "cloud", "storage", "server"],
    ),
    (
        "target",
        f'<circle cx="200" cy="150" r="126" fill="{v("soft")}"/>'
        f'<circle cx="190" cy="160" r="96" fill="{v("paper")}"/>'
        f'<circle cx="190" cy="160" r="72" fill="{v("accent")}"/>'
        f'<circle cx="190" cy="160" r="48" fill="{v("paper")}"/>'
        f'<circle cx="190" cy="160" r="24" fill="{v("accent2")}"/>'
        f'<line x1="196" y1="154" x2="300" y2="50" stroke="{v("ink")}" stroke-width="8" stroke-linecap="round"/>'
        f'<polygon points="300 50 318 24 326 58" fill="{v("ink")}"/>'
        f'<polygon points="300 50 276 42 310 32" fill="{v("ink")}"/>',
        ["цель", "цели", "целей", "целев", "задач", "фокус", "результат", "kpi", "ориентир", "приоритет", "стратег", "goal", "target", "focus"],
    ),
    (
        "idea",
        f'<circle cx="200" cy="150" r="126" fill="{v("soft")}"/>'
        f'<path d="M200 50a70 70 0 0 0-44 124c10 9 14 20 14 32h60c0-12 4-23 14-32A70 70 0 0 0 200 50z" '
        f'fill="{v("accent")}"/>'
        f'<rect x="172" y="214" width="56" height="14" rx="7" fill="{v("ink")}"/>'
        f'<rect x="180" y="234" width="40" height="14" rx="7" fill="{v("ink")}"/>'
        f'<path d="M166 102a40 40 0 0 1 34-20" fill="none" stroke="{v("paper")}" stroke-width="10" '
        f'stroke-linecap="round"/>'
        f'<line x1="96" y1="96" x2="116" y2="108" stroke="{v("accent2")}" stroke-width="8" stroke-linecap="round"/>'
        f'<line x1="304" y1="96" x2="284" y2="108" stroke="{v("accent2")}" stroke-width="8" stroke-linecap="round"/>'
        f'<line x1="200" y1="18" x2="200" y2="34" stroke="{v("accent2")}" stroke-width="8" stroke-linecap="round"/>'
        f'<line x1="86" y1="160" x2="106" y2="160" stroke="{v("accent2")}" stroke-width="8" stroke-linecap="round"/>'
        f'<line x1="314" y1="160" x2="294" y2="160" stroke="{v("accent2")}" stroke-width="8" stroke-linecap="round"/>',
        ["идея", "идеи", "идей", "идею", "гипотез", "предлож", "инициатив", "концепц", "инновац", "решени", "возможн", "idea", "proposal",
         "innovation", "opportunity"],
    ),
    (
        "plan",
        f'<circle cx="200" cy="150" r="126" fill="{v("soft")}"/>'
        f'<rect x="98" y="66" width="204" height="176" rx="16" fill="{v("paper")}"/>'
        f'<rect x="98" y="66" width="204" height="40" rx="16" fill="{v("accent")}"/>'
        f'<rect x="98" y="90" width="204" height="16" fill="{v("accent")}"/>'
        f'<rect x="140" y="50" width="12" height="32" rx="6" fill="{v("ink")}"/>'
        f'<rect x="248" y="50" width="12" height="32" rx="6" fill="{v("ink")}"/>'
        + "".join(
            f'<circle cx="{134 + col * 44}" cy="{136 + row * 40}" r="11" '
            f'fill="{v("accent2") if (row, col) == (1, 2) else v("muted")}"/>'
            for row in range(3)
            for col in range(4)
        )
        + f'<circle cx="300" cy="228" r="30" fill="{v("accent2")}"/>'
        f'<polyline points="286 228 297 239 316 216" fill="none" stroke="{v("paper")}" stroke-width="8" '
        f'stroke-linecap="round" stroke-linejoin="round"/>',
        ["план", "календар", "срок", "квартал", "этап", "дорожн", "график", "расписан", "шаг", "следующ", "roadmap",
         "plan", "schedule", "timeline"],
    ),
    (
        "discussion",
        f'<circle cx="200" cy="150" r="126" fill="{v("soft")}"/>'
        f'<path d="M84 70h150a18 18 0 0 1 18 18v74a18 18 0 0 1-18 18h-96l-40 32v-32h-14a18 18 0 0 1-18-18V88'
        f'a18 18 0 0 1 18-18z" fill="{v("accent")}"/>'
        f'<circle cx="122" cy="126" r="10" fill="{v("paper")}"/><circle cx="158" cy="126" r="10" fill="{v("paper")}"/>'
        f'<circle cx="194" cy="126" r="10" fill="{v("paper")}"/>'
        f'<path d="M316 132h-86a16 16 0 0 0-16 16v58a16 16 0 0 0 16 16h70l34 26v-26h-18a0 0 0 0 0 0 0'
        f'a16 16 0 0 0 16-16v-58a16 16 0 0 0-16-16z" fill="{v("accent2")}"/>'
        f'<rect x="236" y="162" width="62" height="10" rx="5" fill="{v("paper")}"/>'
        f'<rect x="236" y="182" width="42" height="10" rx="5" fill="{v("paper")}"/>',
        ["вопрос", "обсужд", "коммуникац", "отзыв", "обратн", "диалог", "решени", "просьб", "проси", "руководств",
         "question", "discussion", "feedback", "ask"],
    ),
    (
        "money",
        f'<circle cx="200" cy="150" r="126" fill="{v("soft")}"/>'
        f'<rect x="92" y="96" width="176" height="104" rx="14" fill="{v("accent")}"/>'
        f'<circle cx="180" cy="148" r="30" fill="{v("paper")}"/>'
        f'<path d="M174 166v-34h10a8 8 0 0 1 0 16h-16" fill="none" stroke="{v("accent")}" stroke-width="6" '
        f'stroke-linecap="round" stroke-linejoin="round"/>'
        f'<line x1="168" y1="157" x2="186" y2="157" stroke="{v("accent")}" stroke-width="6" stroke-linecap="round"/>'
        + "".join(
            f'<ellipse cx="280" cy="{230 - i * 18}" rx="40" ry="12" fill="{v("accent2") if i % 2 == 0 else v("muted")}"/>'
            for i in range(5)
        )
        + f'<circle cx="96" cy="232" r="12" fill="{v("accent2")}"/>',
        ["деньг", "бюджет", "стоим", "стоил", "стоит", "руб", "рубл", "выручк", "затрат", "цен", "экономи", "инвест", "оплат", "финанс",
         "money", "budget", "cost", "price"],
    ),
    (
        "risk",
        f'<circle cx="200" cy="150" r="126" fill="{v("soft")}"/>'
        f'<path d="M184 62a18 18 0 0 1 32 0l92 164a18 18 0 0 1-16 26H108a18 18 0 0 1-16-26z" fill="{v("accent")}"/>'
        f'<rect x="190" y="112" width="20" height="74" rx="10" fill="{v("paper")}"/>'
        f'<circle cx="200" cy="214" r="12" fill="{v("paper")}"/>'
        f'<circle cx="84" cy="96" r="10" fill="{v("accent2")}"/><circle cx="322" cy="84" r="14" fill="{v("muted")}"/>',
        ["риск", "проблем", "ошибк", "угроз", "огранич", "опасн", "слаб", "сбо", "risk", "problem", "threat"],
    ),
]


def build():
    manifest = {
        "name": "Встроенный визуальный пакет",
        "version": 1,
        "neutral_icon": f"icons/{NEUTRAL_ICON}.svg",
        "assets": [],
    }
    for folder in ("icons", "illustrations"):
        (PACK / folder).mkdir(parents=True, exist_ok=True)
        for old in (PACK / folder).glob("*.svg"):
            old.unlink()
    for name, body, tags in ICONS:
        path = f"icons/{name}.svg"
        (PACK / path).write_text(ICON_HEAD + body + "</svg>\n", encoding="utf-8")
        manifest["assets"].append({"file": path, "kind": "icon", "tags": tags})
    for name, body, tags in ILLUSTRATIONS:
        path = f"illustrations/{name}.svg"
        (PACK / path).write_text(ILLUSTRATION_HEAD + body + "</svg>\n", encoding="utf-8")
        manifest["assets"].append({"file": path, "kind": "illustration", "tags": tags})
    (PACK / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )
    ZIP.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(ZIP, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.write(PACK / "manifest.json", "manifest.json")
        for item in manifest["assets"]:
            archive.write(PACK / item["file"], item["file"])
    print(f"{len(ICONS)} иконок, {len(ILLUSTRATIONS)} иллюстраций → {PACK.relative_to(ROOT)}, {ZIP.relative_to(ROOT)}")


if __name__ == "__main__":
    build()
