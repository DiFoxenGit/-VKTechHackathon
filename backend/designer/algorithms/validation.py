import logging
from ..models import Outline, Visual
from ..language import CYRILLIC, LATIN, foreign_labels, visual_labels
from ..workflow import narrative_beats
from .content import (fit_schema_limits, known_numbers, topic_title, strip_beat,
                      fabricated_chart, repeated_items, drop_repeats, unsupported_numbers,
                      tidy_line, tidy_visual)
LOGGER = logging.getLogger("designer.algorithms.validation")


def validate_outline(result, request, sources, *, last_chance=False, warnings=None):
    if sources and sources[0].get("_analysis_results"):
        from ..analytics_bridge import verify_outline
        verified = Outline.model_validate(result)
        verify_outline(verified, sources[0]["_analysis_results"], sources)
        return verified
    allowed = {source["id"] for source in sources}
    known = known_numbers(sources)
    if last_chance:
        # Последняя попытка: лишний шаг схемы или строка таблицы не повод
        # остаться без колоды — обрезаем до пределов схемы.
        result = fit_schema_limits(result)
    outline = Outline.model_validate(result)
    # Замечания собираются за один проход и уходят модели одним сообщением:
    # по одному за попытку три попытки кончаются раньше, чем модель исправит
    # всё, и на последней приходится соглашаться на меньший объём.
    reasons = []
    count = len(outline.slides)
    # ТЗ задаёт целевой объём, и пользователь задаёт его явно. Перебор не
    # принимаем никогда: это верхняя граница. Недобор возвращаем модели с
    # понятной просьбой — разбить насыщенные слайды или добавить страницу с
    # таблицей либо схемой по материалам, — и соглашаемся на меньшее только
    # когда попытки кончились.
    if count > request.slide_count:
        if not last_chance:
            reasons.append(
                f"Слайдов {count}, а просили не больше {request.slide_count}. "
                "Объедини близкие мысли, не выбрасывая факты."
            )
        else:
            outline.slides = outline.slides[: request.slide_count]
            count = len(outline.slides)
    if count < request.slide_count:
        if not last_chance:
            reasons.append(
                f"Слайдов {count}, а нужно {request.slide_count}. "
                "Разбей самые насыщенные слайды на два по смыслу или добавь "
                "слайды с таблицей либо схемой по материалам: сравнение "
                "показателей, этапы, сроки. Новые слайды несут факты из "
                "источников, а не воду. Если новых фактов нет, сохрани меньший "
                "объём. Не добавляй пилот, сроки, бюджет или ресурсы ради каркаса."
            )
        else:
            LOGGER.warning(
                "Model insisted on %s slides instead of %s", count, request.slide_count
            )
            if warnings is not None:
                warnings.append(
                    f"Модель собрала {count} слайдов вместо {request.slide_count}: "
                    "в материалах не нашлось содержания на остальные. Добавьте "
                    "материалы или уменьшите запрошенный объём."
                )
    unknown = {ref for slide in outline.slides for ref in slide.source_refs} - allowed
    if unknown:
        reasons.append(
            "Неизвестные source_refs: "
            + ", ".join(sorted(unknown))
            + ". Допустимые: "
            + ", ".join(sorted(allowed))
        )
    deck_text = " ".join(
        slide.title + " " + " ".join(slide.bullets) for slide in outline.slides
    )
    cyrillic = len(CYRILLIC.findall(deck_text)) > len(LATIN.findall(deck_text))
    strangers = sorted(
        {
            label
            for slide in outline.slides
            for label in foreign_labels(
                visual_labels(slide.visual.model_dump()), cyrillic
            )
        }
    )
    if strangers and not last_chance:
        reasons.append(
            "Подписи в визуализациях на другом языке: "
            + ", ".join(strangers[:8])
            + ". Переведи все подписи, названия серий и единицы на язык колоды."
        )
    elif strangers:
        # Последняя попытка: колода без одной диаграммы лучше, чем ошибка
        # вместо колоды. Снимаем визуализации с чужими подписями и говорим
        # об этом в логе — аудит потом отметит слайд без визуализации.
        LOGGER.warning("Dropped visuals with foreign labels: %s", strangers[:8])
        for slide in outline.slides:
            if foreign_labels(visual_labels(slide.visual.model_dump()), cyrillic):
                slide.visual = Visual()
    beats = narrative_beats()
    labelled = [
        (index, slide.title)
        for index, slide in enumerate(outline.slides)
        if index > 0 and topic_title(slide.title, beats)
    ]
    if labelled and not last_chance:
        # Приложение 1, вопрос 1: заголовок содержит вывод, а не называет тему.
        reasons.append(
            "Заголовки называют раздел или тему, а не вывод: "
            + "; ".join(f"слайд {index + 1} «{title}»" for index, title in labelled[:8])
            + ". Шаги каркаса — это порядок мыслей, а не текст заголовка. Каждый "
            "заголовок — законченная мысль слайда, по возможности с числом из "
            "материалов: не «Риски», а «Главный риск — нагрузка выше 20 задач»."
        )
    elif labelled:
        # Последняя попытка: «Ожидаемый эффект: скорость сборки» читается как
        # пункт плана, а не как слайд. Название раздела снимаем, остаток
        # оставляем; вывод за модель не придумываем, а говорим об этом.
        stripped = 0
        for index, _ in labelled:
            rest = strip_beat(outline.slides[index].title, beats)
            if rest:
                outline.slides[index].title = rest
                stripped += 1
        if stripped and warnings is not None:
            warnings.append(
                f"У {stripped} заголовков модель оставила название раздела вместо вывода: "
                "префикс снят, но формулировку вывода стоит проверить."
            )
    titles = [slide.title.strip().lower() for slide in outline.slides]
    repeated = {title for title in titles if titles.count(title) > 1}
    if repeated:
        # Повтор заголовка — это два слайда об одном и том же: аудит потом
        # отметит дубль, но лучше не доводить до готовой колоды.
        reasons.append(
            "Заголовки повторяются: "
            + ", ".join(sorted(repeated)[:4])
            + ". Каждый слайд несёт свою мысль."
        )
    unitless = [
        index + 1
        for index, slide in enumerate(outline.slides)
        if slide.visual.kind in ("bar", "line") and not (slide.visual.unit or "").strip()
    ]
    if unitless and not last_chance:
        # Приложение 1: «у диаграммы нет подписей осей, единиц или легенды».
        # Единица становится подписью оси значений, без неё ось немая.
        reasons.append(
            "У диаграмм на слайдах "
            + ", ".join(map(str, unitless))
            + " не указана единица измерения (unit). Напиши, что измеряют значения: "
            "«мин», «%», «команд», «млн руб.»."
        )
    charts = [
        (index, fabricated_chart(slide.visual, known)[0])
        for index, slide in enumerate(outline.slides)
    ]
    charts = [(index, reason) for index, reason in charts if reason]
    if charts and not last_chance:
        reasons.append(
            "; ".join(f"слайд {index + 1}: диаграмма без данных, {reason}" for index, reason in charts)
            + ". Значения диаграммы — только числа из материалов дословно. "
            "Нет данных — нет диаграммы: возьми схему, таблицу или список."
        )
    elif charts:
        for index, reason in charts:
            # Последняя попытка: слайд без диаграммы лучше выдуманного графика.
            LOGGER.warning("Dropped chart without data on slide %s: %s", index + 1, reason)
            outline.slides[index].visual = Visual()
    repeats = repeated_items([slide.model_dump() for slide in outline.slides])
    if repeats and not last_chance:
        reasons.append(
            "; ".join(
                f"слайд {index + 1}: «{item}» уже есть в заголовке или на другом слайде"
                for index, item in repeats[:6]
            )
            + ". Каждый факт звучит в колоде один раз, а тезис не повторяет "
            "заголовок. Если материала мало, лучше меньше слайдов."
        )
    elif repeats:
        before = len(outline.slides)
        LOGGER.warning("Dropping repeated items on the last attempt: %s", repeats[:6])
        drop_repeats(outline)
        if warnings is not None and len(outline.slides) < before:
            warnings.append(
                f"Модель повторяла одни и те же тезисы: {before - len(outline.slides)} "
                "слайд(ов) без собственного содержания убраны."
            )
    invented = unsupported_numbers(
        "\n".join(
            slide.title
            + "\n"
            + "\n".join(slide.bullets)
            # Таблицы и подписи схем — тоже цифры на слайде (Приложение 1,
            # вопрос 4). Значения диаграмм сверяет fabricated_chart.
            + "\n"
            + "\n".join(visual_labels(slide.visual.model_dump()))
            for slide in outline.slides
        ),
        known,
    )
    if invented and not last_chance:
        # Ask again instead of shipping the figure: the audit would flag it and
        # the user would have to rewrite the slide by hand.
        reasons.append(
            "Числа отсутствуют в источниках: "
            + ", ".join(invented[:8])
            + ". Используй только те цифры, что есть в материалах дословно, "
            "и не вычисляй проценты, кратности и суммы."
        )
    elif invented:
        # Последняя попытка: колода с помеченным числом полезнее, чем ошибка
        # вместо колоды. Детерминированный аудит покажет это число
        # пользователю как неподтверждённое — там его и видно.
        LOGGER.warning("Shipping outline with unverified numbers: %s", invented[:8])
    # Неизвестный источник и повтор заголовка не чинятся сами: на последней
    # попытке они по-прежнему роняют план, как и раньше.
    fatal = [reason for reason in reasons if reason.startswith(("Неизвестные source_refs", "Заголовки повторяются"))]
    if reasons and (not last_chance or fatal):
        # При повторе сохраняем подтверждённое содержание; недостающий
        # объём нельзя заполнять выдуманными фактами.
        reminder = (
            f"Сохрани подтверждённые факты, не превышай {request.slide_count} слайдов. "
            "Если источников не хватает, оставь меньше слайдов вместо выдуманных утверждений."
        )
        raise ValueError(
            "\n".join(f"{number}. {reason}" for number, reason in enumerate(reasons, 1))
            + "\n"
            + reminder
        )
    outline.title = tidy_line(outline.title)
    for slide in outline.slides:
        slide.title = tidy_line(slide.title)
        slide.bullets = [tidy_line(b) for b in slide.bullets if b.strip()]
        tidy_visual(slide.visual)
    return outline
