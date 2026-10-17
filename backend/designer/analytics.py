"""Structured source adapter and reproducible analytics, independent of style/LLM.

This is the integration fallback. A richer analyst may replace analyse(), keeping
the versioned result contract. Cells are data, never executable instructions.
"""
import csv
import hashlib
import io
import json
import math
import re
import statistics
import zipfile
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path, PurePosixPath

VERSION = 1
FORMATS = {".csv", ".xlsx", ".json", ".md", ".txt"}
CHARTS = {"bar", "line", "pie", "scatter", "histogram", "grouped_bar", "stacked_bar", "kpi"}


def number(value):
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value) if math.isfinite(value) else None
    text = re.sub(r"[\s\u00a0\u202f]", "", str(value)).replace(",", ".").replace("−", "-")
    if not re.fullmatch(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?", text):
        return None
    result = float(text)
    return result if math.isfinite(result) else None


def missing(value):
    return value is None or isinstance(value, str) and value.strip().lower() in {"", "null", "na", "n/a", "nan"}


def time_value(value):
    if isinstance(value, (date, datetime)):
        return value.isoformat()[:10]
    text = str(value)
    if re.fullmatch(r"\d{4}-\d{2}", text):
        text += "-01"
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}(?:T.*)?", text):
        try:
            return date.fromisoformat(text[:10]).isoformat()
        except ValueError:
            pass
    return None


def dataset(matrix, name, sheet, source_hash, row_numbers=None):
    nonempty = [(i, list(row)) for i, row in enumerate(matrix, 1) if any(not missing(v) for v in row)]
    if len(nonempty) < 2:
        raise ValueError("Таблица должна содержать заголовки и хотя бы одну строку")
    _, header = nonempty[0]
    columns = [str(v).strip() if not missing(v) else f"Колонка {i + 1}" for i, v in enumerate(header)]
    if len(set(columns)) != len(columns):
        raise ValueError("Повторяющиеся заголовки: уточните названия колонок")
    rows, provenance = [], []
    for index, values in nonempty[1:]:
        if len(values) > len(columns) and any(not missing(v) for v in values[len(columns):]):
            raise ValueError(f"Строка {index}: больше ячеек, чем заголовков")
        values = (values + [None] * len(columns))[:len(columns)]
        if any(isinstance(v, (dict, list)) for v in values):
            raise ValueError(f"Строка {index}: вложенные объекты не являются табличными ячейками")
        if any(isinstance(v, float) and not math.isfinite(v) for v in values):
            raise ValueError(f"Строка {index}: NaN/Infinity замените явным пропуском null")
        rows.append([v.isoformat() if isinstance(v, (date, datetime)) else v for v in values])
        provenance.append(row_numbers[index - 1] if row_numbers else index)
    if len(rows) > 100000 or len(columns) > 100:
        raise ValueError("Максимум 100000 строк и 100 колонок на таблицу")
    identity = hashlib.sha256(f"{name}:{sheet}:{source_hash}".encode()).hexdigest()[:20]
    return dict(dataset_id=identity, source_file=name, sheet=sheet, source_hash=source_hash,
                columns=columns, rows=rows, source_rows=provenance)


def extract(data, name):
    """All tables, including all XLSX sheets. Never silently drop a sheet."""
    suffix = Path(name).suffix.lower()
    digest = hashlib.sha256(data).hexdigest()
    if suffix == ".xlsx":
        from openpyxl import load_workbook
        from .parsing import check_zip
        check_zip(data)
        formulas = load_workbook(io.BytesIO(data), data_only=False, read_only=True)
        values = load_workbook(io.BytesIO(data), data_only=True, read_only=True)
        results = []
        try:
            for sheet in values:
                matrix = list(sheet.values)
                if not any(any(not missing(v) for v in row) for row in matrix):
                    continue
                for row in formulas[sheet.title]:
                    for cell in row:
                        if cell.data_type == "f" and sheet[cell.coordinate].value is None:
                            raise ValueError(f"{sheet.title}!{cell.coordinate}: формула без сохранённого результата. Пересчитайте и сохраните XLSX в Excel")
                results.append(dataset(matrix, name, sheet.title, digest))
        finally:
            formulas.close()
            values.close()
        if not results:
            raise ValueError("В XLSX нет заполненных таблиц")
        return results
    text = data.decode("utf-8-sig")
    if suffix == ".csv":
        try:
            dialect = csv.Sniffer().sniff(text[:8192], delimiters=",;\t|")
        except csv.Error:
            dialect = csv.excel
        return [dataset(list(csv.reader(io.StringIO(text), dialect)), name, "1", digest)]
    if suffix == ".json":
        obj = json.loads(text)
        if isinstance(obj, dict) and set(obj) >= {"columns", "rows"}:
            return [dataset([obj["columns"], *obj["rows"]], name, "1", digest)]
        if isinstance(obj, list) and obj and all(isinstance(v, dict) for v in obj):
            keys = list(obj[0])
            if any(set(v) != set(keys) for v in obj):
                raise ValueError("JSON: строки имеют разные колонки. Приведите таблицу к единой структуре")
            return [dataset([keys, *[[v[k] for k in keys] for v in obj]], name, "1", digest)]
        raise ValueError("JSON: ожидается массив объектов либо объект columns/rows")
    if suffix in {".txt", ".md"}:
        tables, block, lines = [], [], []
        def flush():
            if len(block) >= 2:
                tables.append(dataset(block, name, str(len(tables) + 1), digest, lines))
            block.clear()
            lines.clear()
        for index, line in enumerate(text.splitlines(), 1):
            delimiter = "|" if "|" in line else "\t" if "\t" in line else None
            if not delimiter:
                flush()
                continue
            cells = [cell.strip() for cell in line.strip().strip("|").split(delimiter)]
            if all(re.fullmatch(r":?-{3,}:?", v) for v in cells):
                continue
            block.append(cells)
            lines.append(index)
        flush()
        return tables
    return []


def extract_pack(data, name):
    """Report accepted/rejected ZIP members explicitly; retain each full dataset."""
    if Path(name).suffix.lower() != ".zip":
        tables = extract(data, name) if Path(name).suffix.lower() in FORMATS else []
        return tables, [{"name": name, "status": "accepted", "tables": len(tables)}]
    from .parsing import check_zip
    check_zip(data)
    tables, report = [], []
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        if len(archive.infolist()) > 400:
            raise ValueError("Content pack holds more than 400 files")
        for entry in archive.infolist():
            if entry.is_dir() or entry.filename.startswith("__MACOSX/"):
                continue
            if PurePosixPath(entry.filename).name == "manifest.json":
                continue
            suffix = PurePosixPath(entry.filename).suffix.lower()
            if suffix not in FORMATS:
                status = "accepted" if suffix in {".pdf", ".pptx", ".docx", ".svg", ".png", ".jpg", ".jpeg"} else "rejected"
                report.append(dict(name=entry.filename, status=status, reason="" if status == "accepted" else "Неподдерживаемый формат"))
                continue
            try:
                found = extract(archive.read(entry), entry.filename)
                tables.extend(found)
                report.append(dict(name=entry.filename, status="accepted", tables=len(found)))
            except (ValueError, UnicodeError) as exc:
                report.append(dict(name=entry.filename, status="rejected", reason=str(exc)))
    return tables, report


def profile(table):
    columns = []
    for index, label in enumerate(table["columns"]):
        values = [r[index] for r in table["rows"]]
        present = [v for v in values if not missing(v)]
        numeric = [number(v) for v in present]
        kind = "number" if present and all(v is not None for v in numeric) else "date" if present and all(time_value(v) for v in present) else "category"
        identifier = bool(re.search(r"(^id$|_id$|идентификатор|артикул|код|номер)", label.lower()))
        outliers = []
        if kind == "number" and len(present) >= 4:
            ordered = sorted(numeric)
            q1, _, q3 = statistics.quantiles(ordered, n=4, method="inclusive")
            low, high = q1 - 1.5 * (q3 - q1), q3 + 1.5 * (q3 - q1)
            outliers = [table["source_rows"][i] for i, v in enumerate(values) if number(v) is not None and (number(v) < low or number(v) > high)]
        columns.append(dict(name=label, type=kind, role="identifier" if identifier else "metric" if kind == "number" else "time" if kind == "date" else "dimension",
                            missing=sum(missing(v) for v in values), unique=len({str(v) for v in present}), outlier_rows=outliers))
    return dict(row_count=len(table["rows"]), columns=columns, outlier_criterion="1.5 IQR, inclusive quartiles; values retained")


def fmt(value):
    return f"{value:,.2f}".rstrip("0").rstrip(".").replace(",", " ") if isinstance(value, (float, int)) else "—" if missing(value) else str(value)


def analyse(table, goal=""):
    """Versioned AnalysisResult. Every output series is calculated in Python."""
    p = profile(table)
    metrics = [i for i, c in enumerate(p["columns"]) if c["role"] == "metric"]
    dimensions = [i for i, c in enumerate(p["columns"]) if c["role"] == "dimension"]
    times = [i for i, c in enumerate(p["columns"]) if c["role"] == "time"]
    lower = goal.lower()
    warnings = []
    for column in p["columns"]:
        if column["missing"]:
            warnings.append(f"{column['name']}: пропусков {column['missing']}, нулями не заменены")
        if column["outlier_rows"]:
            warnings.append(f"{column['name']}: выбросы по правилу 1.5 IQR сохранены")
    task = "comparison"
    if any(w in lower for w in ("справоч", "каталог", "таблиц")) or not metrics:
        task = "table"
    elif any(w in lower for w in ("связ", "scatter", "корреля")):
        task = "relationship"
    elif any(w in lower for w in ("распредел", "гистограмм")):
        task = "distribution"
    elif any(w in lower for w in ("дол", "состав", "канал")):
        task = "share"
    elif any(w in lower for w in ("kpi", "ключев", "итоговый показатель")):
        task = "kpi"
    elif times and not any(w in lower for w in ("сравн", "итоги регион")):
        task = "trend"
    metric = next((i for i in metrics if table["columns"][i].lower() in lower), metrics[0] if metrics else None)
    dimension = times[0] if task == "trend" and times else next((i for i in dimensions if table["columns"][i].lower() in lower), dimensions[0] if dimensions else times[0] if times else None)
    source = f"{table['source_file']} / {table['sheet']}"
    unit_match = re.search(r"\(([^)]+)\)|\[([^]]+)\]", table["columns"][metric] if metric is not None else "")
    unit = next((v for v in unit_match.groups() if v), "") if unit_match else "ед."
    base = dict(version=VERSION, analysis_id=hashlib.sha256((table["dataset_id"] + goal).encode()).hexdigest()[:24],
                dataset_id=table["dataset_id"], source_file=table["source_file"], sheet=table["sheet"], source_hash=table["source_hash"],
                goal=goal, profile=p, task=task, warnings=warnings, facts=[], provenance=[], candidates=[],
                transformations={"missing_policy": "preserve gaps; exclude missing observations from aggregates", "all_rows": True}, status="success")
    visual = dict(kind="table", columns=table["columns"][:8], rows=[[fmt(v) for v in row[:8]] for row in table["rows"][:10]], source=source)
    title = f"В таблице {len(table['rows'])} строк"
    if len(metrics) > 1 and metric is not None:
        warnings.append(f"Выбрана метрика «{table['columns'][metric]}»; остальные показатели не суммируются с ней")
    def candidate(kind, reason):
        base["candidates"].append(dict(kind=kind, reason=reason))
    def refuse(reason):
        base.update(status="refused", reason=reason)
        warnings.append(reason)
    # Percentages and rates need explicit weights/denominators, never implicit sums.
    rate = metric is not None and bool(re.search(r"%|процент|конверси|рентабель|доля", table["columns"][metric].lower()))
    if task == "relationship":
        if len(metrics) < 2:
            refuse("Для scatter нужны две числовые метрики")
        else:
            x, y = metrics[:2]
            pairs = [(number(row[x]), number(row[y]), rid) for row, rid in zip(table["rows"], table["source_rows"]) if number(row[x]) is not None and number(row[y]) is not None]
            if len(pairs) < 2:
                refuse("Недостаточно полных пар X/Y")
            elif len(pairs) > 2000:
                refuse("Более 2000 точек: требуется явная агрегация, точки не обрезаны")
            else:
                visual = dict(kind="scatter", x_values=[v[0] for v in pairs], categories=[str(v[2]) for v in pairs], series=[dict(name=table["columns"][y], values=[v[1] for v in pairs])], x_label=table["columns"][x], y_label=table["columns"][y], unit=unit, source=source)
                base["provenance"] = [dict(row=v[2], columns=[table["columns"][x], table["columns"][y]]) for v in pairs]
                title = f"Сопоставлены {len(pairs)} пар наблюдений"
                warnings.append("Взаимосвязь не доказывает причинность")
                candidate("scatter", "Две числовые переменные и пары наблюдений")
                candidate("table", "Точные пары для проверки наблюдений")
    elif task == "distribution" and metric is not None:
        observations = [(number(row[metric]), rid) for row, rid in zip(table["rows"], table["source_rows"]) if number(row[metric]) is not None]
        vals = [v for v, _ in observations]
        if not vals:
            refuse("Нет числовых наблюдений")
        else:
            lo, hi = min(vals), max(vals)
            count = min(10, max(1, math.ceil(math.sqrt(len(vals))))) if lo != hi else 1
            width = (hi - lo) / count if hi != lo else 1
            bins = [[] for _ in range(count)]
            for value, rid in observations:
                bins[min(count - 1, int((value - lo) / width))].append(rid)
            visual = dict(kind="histogram", categories=[f"{fmt(lo + i * width)} – {fmt(lo + (i + 1) * width)}" for i in range(count)], series=[dict(name="Наблюдения", values=[len(v) for v in bins])], unit="наблюдений", x_label=table["columns"][metric], source=source)
            base["provenance"] = [dict(category=label, rows=rows, column=table["columns"][metric]) for label, rows in zip(visual["categories"], bins)]
            base["facts"] = [dict(operation="median", value=statistics.median(vals), rows=[rid for _, rid in observations], column=table["columns"][metric], unit=unit, rounding=2)]
            title = f"Медиана {table['columns'][metric]}: {fmt(statistics.median(vals))}"
            base["transformations"].update(bin_width=width, bin_policy="left-inclusive; last bin includes right edge")
            candidate("histogram", "Распределение числовых наблюдений по рассчитанным интервалам")
            candidate("table", "Частоты и границы интервалов")
    elif task != "table" and metric is not None:
        groups = defaultdict(list)
        for row, rid in zip(table["rows"], table["source_rows"]):
            if dimension is not None and missing(row[dimension]):
                key = "Без категории"
            else:
                key = time_value(row[dimension]) if task == "trend" and dimension is not None else str(row[dimension]) if dimension is not None else "Итого"
            groups[key].append((number(row[metric]), rid))
        if rate and (any(len(v) > 1 for v in groups.values()) or task in {"share", "kpi"} and len(groups) > 1):
            refuse("Проценты нельзя суммировать или усреднять без весов. Выберите исходные числитель и знаменатель")
        else:
            entries = [(key, sum(v for v, _ in items if v is not None) if any(v is not None for v, _ in items) else None, [rid for _, rid in items]) for key, items in groups.items()]
            entries.sort(key=(lambda v: v[0]) if task == "trend" else (lambda v: (v[1] is None, -(v[1] or 0), v[0])))
            if task == "trend" and len(entries) > 20:
                refuse("Более 20 временных точек: задайте более крупный период. Данные сохранены целиком")
            elif len(entries) > 20:
                rest = entries[19:]
                entries = entries[:19] + [("Прочее", sum(v for _, v, _ in rest if v is not None), [rid for _, _, ids in rest for rid in ids])]
                warnings.append("Показаны 19 крупнейших категорий и сумма остальных «Прочее»")
                base["transformations"]["selection"] = "top 19 + other (sum); all rows included"
            if base["status"] == "success":
                kind = "line" if task == "trend" else "kpi" if task == "kpi" or dimension is None else "bar"
                vals = [v for _, v, _ in entries if v is not None]
                total = sum(vals)
                if task == "share":
                    if rate or not vals or any(v < 0 for v in vals) or total <= 0 or any(v is None for _, v, _ in entries):
                        refuse("Доли требуют полного состава целого, неотрицательных значений и положительного итога")
                    elif len(entries) <= 6:
                        kind = "pie"
                if task == "kpi":
                    entries = [("Итого", total, [rid for _, _, ids in entries for rid in ids])]
                visual = dict(kind=kind, categories=[v[0] for v in entries], series=[dict(name=table["columns"][metric], values=[v[1] for v in entries])], unit=unit, x_label=table["columns"][dimension] if dimension is not None else "", y_label=table["columns"][metric], source=source)
                base["provenance"] = [dict(category=k, value=v, rows=ids, column=table["columns"][metric], operation="sum_nonmissing") for k, v, ids in entries]
                base["facts"] = [dict(operation="identity" if rate else "sum_nonmissing", value=entries[-1][1] if rate else total, rows=table["source_rows"], column=table["columns"][metric], unit=unit, rounding=2)]
                title = f"{table['columns'][metric]}: последнее значение {fmt(entries[-1][1])} {unit}" if rate else f"{table['columns'][metric]}: итог {fmt(total)} {unit}"
                if task == "trend" and len(entries) > 1 and entries[0][1] is not None and entries[-1][1] is not None:
                    first, last = entries[0][1], entries[-1][1]
                    if rate:
                        growth = last - first
                        label = "п.п."
                    elif first > 0:
                        growth = (last / first - 1) * 100
                        label = "%"
                    else:
                        growth, label = None, "%"
                        warnings.append("Рост не рассчитан: начальная база неположительная")
                    if growth is not None:
                        base["facts"].append(dict(operation="difference" if rate else "(last/first-1)*100", value=growth, inputs=[first, last], period=[entries[0][0], entries[-1][0]], unit=label, rounding=2))
                        title = f"{table['columns'][metric]}: изменение {fmt(growth)} {label}"
                candidate(kind, "Время и динамика" if kind == "line" else "Компактный состав целого" if kind == "pie" else "Сравнение рассчитанных значений")
                if kind == "line":
                    candidate("grouped_bar", "Дискретное сравнение периодов")
                elif kind == "pie":
                    candidate("bar", "Удобнее сравнивать близкие доли")
                candidate("table", "Точные значения и проверка исходных показателей")
    else:
        candidate("table", "Справочные данные или отсутствие однозначной числовой метрики")
        if not metrics:
            warnings.append("Числовые метрики не определены. Показана исходная таблица без выдуманного графика")
    # Multiple series preserve the same metric/unit; unrelated metrics never share
    # a sum or axis. Group/stack is driven by the stated analytical goal.
    if base["status"] == "success" and metric is not None and not rate and (task == "trend" and dimensions or any(w in lower for w in ("группирован", "накопитель"))):
        primary = times[0] if times else dimension
        secondary = next((i for i in dimensions if i != primary), None)
        if primary is not None and secondary is not None:
            buckets = defaultdict(list)
            for row, rid in zip(table["rows"], table["source_rows"]):
                a = time_value(row[primary]) if primary in times else str(row[primary])
                b = str(row[secondary]) if not missing(row[secondary]) else "Без категории"
                buckets[(a or "Без периода", b)].append((number(row[metric]), rid))
            categories = sorted({a for a, _ in buckets})
            names = sorted({b for _, b in buckets})
            if len(categories) > 20 or len(names) > 8:
                refuse("Для нескольких серий нужны не более 20 категорий и 8 серий. Уточните агрегацию; исходные данные сохранены")
            else:
                kind = "stacked_bar" if "накопитель" in lower else "grouped_bar" if "группирован" in lower else "line" if task == "trend" else "grouped_bar"
                visual.update(kind=kind, categories=categories, x_label=table["columns"][primary], series=[])
                provenance = []
                for name in names:
                    values = []
                    for label in categories:
                        items = buckets.get((label, name), [])
                        value = sum(v for v, _ in items if v is not None) if any(v is not None for v, _ in items) else None
                        values.append(value)
                        provenance.append(dict(category=label, series=name, value=value, rows=[rid for _, rid in items], column=table["columns"][metric], operation="sum_nonmissing"))
                    visual["series"].append(dict(name=name, values=values))
                base["provenance"] = provenance
                base["candidates"] = [dict(kind=kind, reason="Сравнение одной метрики по периодам и категориям"), dict(kind="grouped_bar" if kind != "grouped_bar" else "line" if times else "stacked_bar", reason="Альтернативное сравнение тех же серий"), dict(kind="table", reason="Точные значения каждой серии")]
    base.update(visual=visual, title=title, selected=visual["kind"])
    return base


def analyse_sources(sources, goal):
    return [analyse(table, source.get("analysis_goal") or goal) for source in sources for table in source.get("datasets", [])]


def build_outline(results, sources, limit):
    from .models import Outline
    slides = []
    for result in results:
        if result["status"] == "refused":
            raise ValueError(result["reason"])
        table = next(t for s in sources for t in s.get("datasets", []) if t["dataset_id"] == result["dataset_id"])
        ref = next(s["id"] for s in sources if table in s.get("datasets", []))
        visuals = [result["visual"]]
        if result["selected"] == "table":
            visuals = []
            for start in range(0, len(table["columns"]), 7):
                indices = list(range(start, min(start + 7, len(table["columns"]))))
                if start:
                    indices.insert(0, 0)
                for row_start in range(0, len(table["rows"]), 10):
                    visuals.append(dict(kind="table", columns=[table["columns"][i] for i in indices], rows=[[fmt(row[i]) for i in indices] for row in table["rows"][row_start:row_start + 10]], source=result["visual"]["source"]))
        for page, visual in enumerate(visuals):
            slides.append(dict(title=result["title"] + (f" · часть {page + 1}/{len(visuals)}" if len(visuals) > 1 else ""),
                               bullets=result["warnings"][:2], notes=json.dumps(dict(analysis_id=result["analysis_id"], facts=result["facts"], source_hash=result["source_hash"]), ensure_ascii=False)[:4000],
                               source_refs=[ref], visual=visual, analysis_id=result["analysis_id"]))
    if len(slides) > limit:
        raise ValueError(f"Для полного результата нужно {len(slides)} слайдов, выбран лимит {limit}. Увеличьте число слайдов (максимум 30) или уточните цель агрегации; данные не обрезаны")
    return Outline.model_validate(dict(title="Аналитика по исходным данным", slides=slides))


def verify_outline(outline, results, sources, limit=30):
    expected = build_outline(results, sources, limit)
    actual = outline.model_dump() if hasattr(outline, "model_dump") else outline
    if len(actual["slides"]) != len(expected.slides):
        raise ValueError("Проверка аналитики: потеряны слайды или страницы таблицы")
    for slide, reference in zip(actual["slides"], expected.slides):
        if slide.get("analysis_id") != reference.analysis_id or slide.get("visual") != reference.visual.model_dump() or slide.get("title") != reference.title:
            raise ValueError("Проверка аналитики: изменены категория, значение, источник или проверенный вывод")
    return True
