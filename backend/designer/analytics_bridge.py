"""Service adapter for Dima's contract. Numeric values come from analytics only."""
import hashlib
import io
import json
import zipfile
from pathlib import PurePosixPath
from .analytics import AnalysisRequest, AnalysisResult, Dataset, analyze, import_datasets, verify_result
from .analytics.messages import explain
from .analytics.profiling import missing, number, profile_dataset

FORMATS = {".csv", ".xlsx", ".json", ".md", ".txt"}
CHARTS = {"bar", "line", "pie", "scatter", "histogram", "grouped_bar", "stacked_bar", "kpi"}


def fmt(value):
    return "—" if missing(value) else str(value)


def _table(dataset):
    return dict(dataset_id=dataset.ref.dataset_id, source_file=dataset.ref.filename,
                sheet=dataset.ref.table, source_hash=dataset.ref.source_sha256,
                columns=[c.name for c in dataset.columns], rows=dataset.rows,
                source_rows=dataset.row_ids, contract=dataset.model_dump(mode="json"))


def _dataset(table):
    if "contract" in table:
        return Dataset.model_validate(table["contract"])
    # Previously saved content packs preserve their full cells and coordinates.
    return Dataset.model_validate(dict(ref=dict(dataset_id=table["dataset_id"], filename=table["source_file"],
        source_sha256=table["source_hash"], table=table["sheet"]),
        columns=[dict(id=f"c{i+1}", name=name) for i, name in enumerate(table["columns"])],
        rows=table["rows"], row_ids=table["source_rows"]))


def extract(data, name):
    imported = import_datasets(data, name)
    if imported.rejected and (not imported.datasets or any(not n.params.get("sheet") for n in imported.rejected)):
        # Plain text is still valid material for the ordinary text pipeline.
        if PurePosixPath(name).suffix.lower() in {".txt", ".md"} and all(n.code == "import.no_table" for n in imported.rejected):
            return []
        raise ValueError("; ".join(explain(n) for n in imported.rejected))
    return [_table(d) for d in imported.datasets]


def extract_pack(data, name):
    suffix = PurePosixPath(name).suffix.lower()
    if suffix != ".zip":
        if suffix == ".xlsx":
            imported = import_datasets(data,name)
            if imported.rejected and any(not n.params.get("sheet") for n in imported.rejected):
                raise ValueError("; ".join(explain(n) for n in imported.rejected))
            report = [dict(name=name,status="accepted",tables=len(imported.datasets))] if imported.datasets else []
            report.extend(dict(name=name+" / "+str(n.params.get("sheet","")),status="rejected",reason=explain(n)) for n in imported.rejected)
            return [_table(d) for d in imported.datasets],report
        tables = extract(data, name) if suffix in FORMATS else []
        return tables, [dict(name=name, status="accepted", tables=len(tables))]
    from .analytics.importing import safe_archive, ImportFailure
    try:
        with safe_archive(data):
            pass
    except ImportFailure as exc:
        raise ValueError(explain(exc.notice)) from exc
    imported = import_datasets(data, name)
    rejected = {n.params.get("file", ""): n for n in imported.rejected if not n.params.get("sheet")}
    if "" in rejected:
        raise ValueError(explain(rejected[""]))
    report = []
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        for entry in archive.infolist():
            if entry.is_dir() or PurePosixPath(entry.filename).name == "manifest.json":
                continue
            suffix = PurePosixPath(entry.filename).suffix.lower()
            notice = rejected.get(entry.filename)
            asset = suffix in {".pdf", ".pptx", ".docx", ".svg", ".png", ".jpg", ".jpeg"}
            text = suffix in {".txt", ".md"} and notice and notice.code == "import.no_table"
            accepted = not notice or asset or text
            report.append(dict(name=entry.filename, status="accepted" if accepted else "rejected",
                tables=sum(d.ref.archive_path == entry.filename for d in imported.datasets),
                reason="" if accepted else explain(notice)))
    report.extend(dict(name=str(n.params.get("file",name))+" / "+str(n.params["sheet"]),status="rejected",reason=explain(n)) for n in imported.rejected if n.params.get("sheet"))
    return [_table(d) for d in imported.datasets], report


def request_for(table, goal="", settings=None):
    if settings is not None:
        return AnalysisRequest.model_validate({**settings, "goal": goal})
    profile = profile_dataset(_dataset(table))
    # An exact column name in the goal resolves a metric choice; never guess.
    chosen = [c.id for c in profile.columns if c.role == "metric" and c.name.casefold() in goal.casefold()]
    return AnalysisRequest(goal=goal, metrics=chosen)


def _visuals(result):
    """Paginate ready values without altering the canonical contract."""
    data, presentation = result.data, result.presentation
    kind = result.visualization.selected
    def axis(label, unit):
        return f"{label} ({unit})" if unit and unit.casefold() not in label.casefold() else label
    common = dict(kind=kind, source=presentation.source_label, unit=presentation.unit,
                  x_label=axis(presentation.x_label,presentation.x_unit), y_label=axis(presentation.y_label,presentation.y_unit))
    if kind == "table":
        visuals = []
        for start in range(0, len(data.columns), 7):
            cols = list(range(start, min(start+7, len(data.columns))))
            if start:
                cols.insert(0, 0)
            for page in data.pages or [list(range(len(data.rows)))]:
                for offset in range(0, len(page), 10):
                    visuals.append(dict(**common, columns=[data.columns[i] for i in cols],
                        rows=[[fmt(data.rows[r][c]) for c in cols] for r in page[offset:offset+10]]))
        return visuals
    if kind == "scatter":
        if len(data.points)>2000:
            raise ValueError("Для экспорта более 2000 точек уточните выборку; данные сохранены целиком")
        return [dict(**common, categories=[str(p.row_id) for p in data.points], x_values=[p.x for p in data.points],
                     series=[dict(name=presentation.y_label, values=[p.y for p in data.points])])]
    if kind == "kpi":
        facts = {f.id:f for f in result.facts}
        return [dict(**{**common, "unit":facts[f].unit}, categories=[f],
                     series=[dict(name=presentation.y_label or f, values=[facts[f].value])]) for f in data.kpi_fact_ids]
    categories = data.categories
    if kind == "histogram":
        categories = [f"{a:.6g} – {b:.6g}" for a,b in data.bins]
    pages = data.pages or [list(range(i,min(i+20,len(categories)))) for i in range(0,len(categories),20)]
    series_pages = data.series_pages or [list(range(i,min(i+5,len(data.series)))) for i in range(0,len(data.series),5)]
    return [dict(**common,categories=[categories[i] for i in page],
        series=[dict(name=data.series[s].name,values=[data.series[s].values[i] for i in page]) for s in series_page])
        for page in pages for series_page in series_pages]


def _view(result, request, source_id=None):
    payload = result.model_dump(mode="json")
    ref = result.dataset_ref
    identifier = hashlib.sha256(json.dumps([source_id,ref.model_dump(),request.model_dump()],sort_keys=True,ensure_ascii=False).encode()).hexdigest()[:24]
    base = dict(version=1, source_id=source_id, contract=payload, analysis_request=request.model_dump(mode="json"),
        analysis_id=identifier, dataset_id=ref.dataset_id, source_file=ref.filename,
        sheet=ref.table, source_hash=ref.source_sha256, profile=payload["profile"],
        goal=request.goal, task=result.analysis.task, status=result.status,
        warnings=[explain(n, request.locale) for n in result.warnings], facts=payload["facts"],
        provenance=[f["evidence"] for f in payload["facts"]], transformations=payload["analysis"]["transformations"],
        candidates=[], selected="", title="")
    if result.status == "refused":
        base["reason"] = explain(result.refusal, request.locale)
        return base
    base.update(candidates=[dict(kind=c.kind, rank=c.rank, reason=explain(c.reason,request.locale)) for c in result.visualization.candidates],
                selected=result.visualization.selected, title=result.presentation.title)
    base["visual"] = _visuals(result)[0]
    return base


def analyse(table, goal="", settings=None):
    request = request_for(table, goal, settings)
    return _view(analyze(_dataset(table),request),request)


def analyse_sources(sources, goal):
    results = []
    for source in sources:
        resolved = source.setdefault("resolved_analysis_requests",{})
        for table in source.get("datasets",[]):
            request = request_for(table, source.get("analysis_goal") or goal, source.get("analysis_requests",{}).get(table["dataset_id"]))
            resolved[table["dataset_id"]] = request.model_dump(mode="json")
            results.append(_view(analyze(_dataset(table),request),request,source.get("id")))
    return results


def _verify_results(results, sources):
    for result in results:
        if "contract" not in result:
            raise ValueError("Презентация создана временной аналитикой. Пересоздайте её из сохранённых исходных файлов для проверки AnalysisResult 1.0")
        matched = next(((s,t) for s in sources for t in s.get("datasets",[]) if t["dataset_id"]==result["dataset_id"] and (result.get("source_id") is None or s.get("id")==result["source_id"])),None)
        if matched is None:
            raise ValueError("Проверка аналитики: исходная таблица не найдена")
        source,table = matched
        settings = source.get("resolved_analysis_requests",{}).get(result["dataset_id"],source.get("analysis_requests",{}).get(result["dataset_id"]))
        if settings is None:
            raise ValueError("Проверка аналитики: отсутствует сохранённый запрос анализа")
        request = AnalysisRequest.model_validate(settings)
        contract = AnalysisResult.model_validate(result["contract"])
        if not verify_result(_dataset(table),request,contract) or _view(contract,request,result.get("source_id"))!=result:
            raise ValueError("Проверка аналитики: изменены данные, доказательства или проверенный вывод")


def build_outline(results, sources, limit):
    from .models import Outline
    slides = []
    for result in results:
        if result["status"] == "refused":
            raise ValueError(result["reason"])
        ref = next(s["id"] for s in sources for t in s.get("datasets",[]) if t["dataset_id"]==result["dataset_id"] and (result.get("source_id") is None or s.get("id")==result["source_id"]))
        visuals = _visuals(AnalysisResult.model_validate(result["contract"]))
        for page, visual in enumerate(visuals):
            slides.append(dict(title=result["title"] + (f" · часть {page + 1}/{len(visuals)}" if len(visuals) > 1 else ""),
                               bullets=result["warnings"][:2], notes=json.dumps(dict(analysis_id=result["analysis_id"], facts=result["facts"], source_hash=result["source_hash"]), ensure_ascii=False)[:4000],
                               source_refs=[ref], visual=visual, analysis_id=result["analysis_id"]))
    if len(slides) > limit:
        raise ValueError(f"Для полного результата нужно {len(slides)} слайдов, выбран лимит {limit}. Увеличьте число слайдов (максимум 30) или уточните цель агрегации; данные не обрезаны")
    return Outline.model_validate(dict(title="Аналитика по исходным данным", slides=slides))


def verify_outline(outline, results, sources, limit=30):
    _verify_results(results,sources)
    expected = build_outline(results, sources, limit)
    actual = outline.model_dump() if hasattr(outline, "model_dump") else outline
    if len(actual["slides"]) != len(expected.slides):
        raise ValueError("Проверка аналитики: потеряны слайды или страницы таблицы")
    for slide, reference in zip(actual["slides"], expected.slides):
        if slide.get("analysis_id") != reference.analysis_id or slide.get("visual") != reference.visual.model_dump() or slide.get("title") != reference.title:
            raise ValueError("Проверка аналитики: изменены категория, значение, источник или проверенный вывод")
    return True
