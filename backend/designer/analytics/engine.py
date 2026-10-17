"""Data selects the visual; arithmetic and source coordinates prove every value."""
import math
from collections import defaultdict
from decimal import Decimal, localcontext
from statistics import median

from .models import (Analysis, AnalysisRequest, AnalysisResult, Candidate, Evidence, Fact,
                     Notice, Point, Presentation, Series, VisualData, Visualization)
from .profiling import normalized_values, profile_dataset
from .messages import message

CALCULATION_PRECISION = 350

def _aggregate(values, operation):
    values = [v for v in values if v is not None]
    if operation == "count":
        return Decimal(len(values))
    if not values:
        return None
    with localcontext() as context:
        context.prec = CALCULATION_PRECISION
        if operation == "sum":
            return sum(values, Decimal(0))
        if operation == "mean":
            return sum(values, Decimal(0))/len(values)
        return median(values)


def _float(value):
    return float(value)


def _task(request, profile):
    if request.task:
        return request.task
    goal = request.goal.lower()
    for task, words in [
        ("reference", ("справоч", "таблиц", "reference", "table")),
        ("shares", ("дол", "структур", "share", "composition")),
        ("distribution", ("распредел", "гистограмм", "distribution", "histogram")),
        ("relationship", ("взаимосвяз", "корреляц", "relationship", "scatter")),
        ("comparison", ("сравн", "регион", "compare", "comparison")),
        ("dynamics", ("рост", "динамик", "тренд", "growth", "trend", "dynamics")),
        ("summary", ("итог", "kpi", "summary")),
    ]:
        if any(w in goal for w in words):
            return task
    return "dynamics" if any(c.role == "time" for c in profile.columns) else "comparison"


class _Calculation:
    def __init__(self, dataset, request):
        self.dataset, self.request = dataset, request
        self.profile = profile_dataset(dataset, request.column_types)
        self.task = _task(request, self.profile)
        self.warnings = list(self.profile.warnings)
        self.facts = []
        self.columns = {c.id: c for c in self.profile.columns}
        self.values = {c.id: normalized_values(dataset, c.id, c.kind) for c in self.profile.columns}
        self.indices = list(range(len(dataset.rows)))
        for col, accepted in request.filters.items():
            if col not in self.columns:
                raise ValueError("unknown filter column")
            idx = next(i for i, c in enumerate(dataset.columns) if c.id == col)
            self.indices = [i for i in self.indices if dataset.rows[i][idx] in accepted]
        self.metrics = request.metrics or [c.id for c in self.profile.columns if c.role == "metric"]
        dimensions = [c.id for c in self.profile.columns if c.role == ("time" if self.task == "dynamics" else "dimension")]
        self.dimension = request.dimension or (dimensions[0] if len(dimensions) == 1 else None)
        self.unit = request.unit
        self.analysis = Analysis(goal=request.goal, task=self.task, dimension=self.dimension,
                                 series_dimension=request.series_dimension,
                                 metrics=self.metrics, aggregation=request.aggregation,
                                 transformations=["filters"] if request.filters else [])

    def refuse(self, code, **params):
        return AnalysisResult(dataset_ref=self.dataset.ref, profile=self.profile, analysis=self.analysis,
                              status="refused", warnings=self.warnings, refusal=Notice(code=code, params=params))

    def period(self, rows):
        times = [c.id for c in self.profile.columns if c.role == "time"]
        if len(times) != 1:
            return []
        values = sorted(self.values[times[0]][i] for i in rows if self.values[times[0]][i] is not None)
        return [values[0], values[-1]] if values else []

    def fact(self, value, rows, columns, operation, unit=None, period=None, **parameters):
        if value is None:
            return ""
        identifier = f"f{len(self.facts)+1}"
        self.facts.append(Fact(id=identifier, value=_float(value), exact=str(value),
                               unit=self.unit if unit is None else unit, period=period if period is not None else self.period(rows),
                               evidence=Evidence(source_sha256=self.dataset.ref.source_sha256,
                                                 row_ids=[self.dataset.row_ids[i] for i in rows],
                                                 column_ids=columns, operation=operation, parameters=parameters)))
        return identifier

    def candidates(self, kinds):
        return Visualization(selected=kinds[0], candidates=[Candidate(kind=k, rank=i+1,
                             reason=Notice(code="candidate."+k, params={"task": self.task,
                                 "source_rows": len(self.indices), "metric_count": len(self.metrics),
                                 "dimension": self.dimension})) for i, k in enumerate(kinds)])

    def finish(self, data, kinds, title_key, title_params, conclusion_ids=(), period=()):
        if len(kinds) < 2:
            self.warnings.append(Notice(code="analysis.only_one_candidate"))
        if not self.unit and self.task != "reference":
            self.warnings.append(Notice(code="analysis.unit_unknown"))
        x_label = self.columns[self.dimension].name if self.dimension else ""
        y_label = ", ".join(self.columns[m].name for m in self.metrics)
        x_unit, y_unit = "", self.unit
        if self.task == "distribution":
            x_label, y_label = y_label, message("label.frequency", self.request.locale)
            x_unit, y_unit = self.unit, message("label.observations", self.request.locale)
        elif self.task == "relationship":
            x_label, y_label = (self.columns[m].name for m in self.metrics)
            x_unit, y_unit = (self.columns[m].unit for m in self.metrics)
        return AnalysisResult(dataset_ref=self.dataset.ref, profile=self.profile, analysis=self.analysis,
                              visualization=self.candidates(kinds), data=data, facts=self.facts,
                              presentation=Presentation(title=message(title_key, self.request.locale, **title_params),
                                  x_label=x_label, y_label=y_label, x_unit=x_unit, y_unit=y_unit, unit=self.unit,
                                  period=list(period) or self.period(self.indices), source_label=" / ".join(filter(None, [self.dataset.ref.filename,
                                        self.dataset.ref.archive_path, self.dataset.ref.table])),
                                  conclusion_fact_ids=list(conclusion_ids)),
                              status="warning" if self.warnings else "ok", warnings=self.warnings)

    def validate(self):
        if not self.indices:
            return self.refuse("analysis.no_observations")
        if self.dimension is not None and self.dimension not in self.columns:
            return self.refuse("analysis.unknown_column")
        if any(m not in self.columns for m in self.metrics):
            return self.refuse("analysis.unknown_column")
        if len(set(self.metrics)) != len(self.metrics):
            return self.refuse("analysis.duplicate_metrics")
        if self.task != "reference" and not self.metrics:
            return self.refuse("analysis.no_metric")
        if self.task != "reference" and any(self.columns[m].kind != "number" for m in self.metrics):
            return self.refuse("analysis.metric_not_numeric")
        units = {self.columns[m].unit for m in self.metrics if self.columns[m].unit}
        if self.request.aggregation != "count" and self.request.unit and units and self.task != "relationship" and units != {self.request.unit}:
            return self.refuse("analysis.incompatible_units")
        if self.task != "relationship" and len(units) > 1:
            return self.refuse("analysis.incompatible_units")
        if units and not self.unit:
            self.unit = next(iter(units)) if len(units) == 1 else ""
        if self.request.aggregation == "count" and self.task in {"summary", "dynamics", "comparison"}:
            self.unit = "observations"
        if self.task in {"dynamics", "comparison", "shares"} and self.dimension is None:
            return self.refuse("analysis.choose_dimension")
        if self.task in {"dynamics", "comparison", "shares"} and self.columns[self.dimension].kind not in {"category", "date", "number"}:
            return self.refuse("analysis.dimension_not_typed")
        if self.task == "dynamics" and self.columns[self.dimension].kind != "date":
            return self.refuse("analysis.time_not_typed")
        if self.task in {"shares", "distribution"} and len(self.metrics) != 1:
            return self.refuse("analysis.choose_one_metric")
        if self.task == "relationship" and len(self.metrics) != 2:
            return self.refuse("analysis.choose_two_metrics")
        sd = self.request.series_dimension
        if sd and (sd not in self.columns or sd == self.dimension
                   or self.columns[sd].kind not in {"category", "date"}
                   or self.task not in {"dynamics", "comparison"}):
            return self.refuse("analysis.invalid_series_dimension")
        if self.request.aggregation != "count" and self.task in {"dynamics", "comparison", "shares", "summary"} and ("%" in units or self.unit == "%"):
            groups = defaultdict(int)
            if self.dimension:
                for i in self.indices:
                    groups[self.values[self.dimension][i]] += 1
            if (self.task in {"shares", "summary"} or not groups or max(groups.values()) > 1):
                return self.refuse("analysis.percent_aggregation_requires_policy")
        if any(self.columns[m].missing for m in self.metrics):
            self.warnings.append(Notice(code="analysis.missing_preserved"))
        return None

    def reference(self):
        self.analysis.aggregation = "identity"
        size = self.request.page_size
        pages = [self.indices[i:i+size] for i in range(0, len(self.indices), size)]
        if len(pages) > self.request.slide_budget:
            return self.refuse("analysis.slide_limit", pages=len(pages))
        self.analysis.transformations.append("paginate_without_truncation")
        return self.finish(VisualData(columns=[c.name for c in self.dataset.columns],
                          rows=[self.dataset.rows[i] for i in self.indices],
                          row_ids=[self.dataset.row_ids[i] for i in self.indices],
                          pages=[list(range(i, min(i+size, len(self.indices)))) for i in range(0, len(self.indices), size)]),
                           ["table"], "title.reference", {"count": len(self.indices)})

    def summary(self):
        ids = []
        for metric in self.metrics:
            value = _aggregate([self.values[metric][i] for i in self.indices], self.request.aggregation)
            if value is None:
                return self.refuse("analysis.no_observations")
            ids.append(self.fact(value, self.indices, [metric], self.request.aggregation))
        self.analysis.transformations.append(self.request.aggregation)
        return self.finish(VisualData(kpi_fact_ids=ids), ["kpi", "table"], "title.summary", {"count": len(ids)}, ids)

    def relationship(self):
        self.analysis.aggregation = "identity"
        a, b = self.metrics
        complete = [i for i in self.indices if self.values[a][i] is not None and self.values[b][i] is not None]
        if len(complete) < 2:
            return self.refuse("analysis.insufficient_pairs")
        points = [Point(x=_float(self.values[a][i]), y=_float(self.values[b][i]), row_id=self.dataset.row_ids[i]) for i in complete]
        self.warnings.append(Notice(code="analysis.no_causality"))
        self.analysis.transformations.append("complete_pairs_only")
        count = self.fact(Decimal(len(points)), complete, self.metrics, "count_complete_pairs", unit="observations")
        return self.finish(VisualData(points=points), ["scatter", "table"], "title.relationship", {"count": len(points)}, [count])

    def distribution(self):
        self.analysis.aggregation = "histogram"
        metric = self.metrics[0]
        indices = [i for i in self.indices if self.values[metric][i] is not None]
        if not indices:
            return self.refuse("analysis.no_observations")
        values = [self.values[metric][i] for i in indices]
        low, high = min(values), max(values)
        count = self.request.bins or min(20, max(1, math.ceil(math.sqrt(len(values)))))
        if high == low:
            count = 1
        with localcontext() as ctx:
            ctx.prec = CALCULATION_PRECISION
            step = (high-low)/count if high != low else Decimal(1)
            edges = [low+step*i for i in range(count+1)]
        buckets = [[] for _ in range(count)]
        for i in indices:
            with localcontext() as ctx:
                ctx.prec = CALCULATION_PRECISION
                ordinal = min(count-1, int((self.values[metric][i]-low)/step))
            buckets[ordinal].append(i)
        counts = [len(b) for b in buckets]
        ids = [self.fact(Decimal(len(b)), b, [metric], "histogram_count", unit="observations",
                         lower=str(edges[i]), upper=str(edges[i+1]), upper_inclusive=i == count-1)
               for i, b in enumerate(buckets)]
        midpoint = self.fact(median(values), indices, [metric], "median")
        categories = [f"[{edges[i]}, {edges[i+1]}{' ]' if i == count-1 else ')'}" for i in range(count)]
        self.analysis.transformations.append("histogram_equal_width_last_inclusive")
        return self.finish(VisualData(categories=categories, series=[Series(name="frequency", unit="observations", values=counts, fact_ids=ids)],
                                     bins=[[_float(edges[i]), _float(edges[i+1])] for i in range(count)]),
                           ["histogram", "table"], "title.distribution", {"count": len(indices), "median": str(median(values))}, [midpoint])

    def grouped(self):
        groups = defaultdict(list)
        for i in self.indices:
            key = self.values[self.dimension][i]
            if key is None:
                continue
            groups[str(key)].append(i)
        if sum(map(len, groups.values())) != len(self.indices):
            self.warnings.append(Notice(code="analysis.missing_dimension_excluded"))
        if not groups:
            return self.refuse("analysis.no_observations")
        categories = sorted(groups)
        series = []
        sd = self.request.series_dimension
        levels = sorted({str(self.values[sd][i]) for i in self.indices if self.values[sd][i] is not None}) if sd else [None]
        if len(levels) * len(categories) * len(self.metrics) > 100_000:
            return self.refuse("analysis.result_limit")
        if sd and any(self.values[sd][i] is None for i in self.indices):
            self.warnings.append(Notice(code="analysis.missing_dimension_excluded"))
        for metric in self.metrics:
            for level in levels:
                values, ids = [], []
                for category in categories:
                    rows = groups[category] if sd is None else [i for i in groups[category] if str(self.values[sd][i]) == level]
                    value = _aggregate([self.values[metric][i] for i in rows], self.request.aggregation)
                    values.append(_float(value) if value is not None else None)
                    ids.append(self.fact(value, rows, [self.dimension, metric]+([sd] if sd else []), self.request.aggregation,
                                         category=category, series=level))
                series.append(Series(name=self.columns[metric].name+(f" / {level}" if sd else ""), unit=self.unit, values=values, fact_ids=ids))
        if not any(v is not None for s in series for v in s.values):
            return self.refuse("analysis.no_observations")
        self.analysis.transformations.extend(["group_by_dimension", self.request.aggregation, "sort_dimension"])
        data = VisualData(categories=categories, series=series,
                          pages=[list(range(i, min(i+20, len(categories)))) for i in range(0, len(categories), 20)])
        if len(data.pages) > self.request.slide_budget:
            return self.refuse("analysis.slide_limit", pages=len(data.pages))
        if len(categories) > 20:
            self.warnings.append(Notice(code="analysis.paginated", params={"pages": len(data.pages)}))
        if self.task != "shares" and len(categories) == 1 and len(series) == 1:
            identifier = series[0].fact_ids[0]
            data.kpi_fact_ids = [identifier]
            return self.finish(data, ["kpi", "table"], "title.comparison",
                               {"category": categories[0], "value": series[0].values[0], "metric": series[0].name}, [identifier])
        if self.task == "shares":
            return self.shares(data, groups)
        if self.task == "dynamics":
            return self.dynamics(data, groups)
        return self.comparison(data)

    def shares(self, data, groups):
        categories, series = data.categories, data.series
        if any(self.values[self.metrics[0]][i] is not None and self.values[self.metrics[0]][i] < 0 for i in self.indices):
            return self.refuse("analysis.invalid_whole")
        if any(v is None or v < 0 for v in series[0].values):
            return self.refuse("analysis.invalid_whole")
        metric = self.metrics[0]
        if self.request.aggregation != "sum":
            return self.refuse("analysis.shares_require_sum")
        exact_values = [_aggregate([self.values[metric][i] for i in groups[c]], "sum") for c in categories]
        total = _aggregate(exact_values, "sum")
        if not total or total <= 0:
            return self.refuse("analysis.invalid_whole")
        if any(self.values[metric][i] is None for i in self.indices) or sum(map(len, groups.values())) != len(self.indices):
            return self.refuse("analysis.incomplete_whole")
        total_id = self.fact(total, self.indices, [metric], "sum", scope="whole")
        shares = []
        for position, (c, value) in enumerate(zip(categories, exact_values)):
            with localcontext() as ctx:
                ctx.prec = CALCULATION_PRECISION
                share = value/total*100
            shares.append(self.fact(share, groups[c], [self.dimension, metric], "share_percent",
                                    unit="%", category=c, numerator=str(value), denominator=str(total),
                                    numerator_fact_id=series[0].fact_ids[position], denominator_fact_id=total_id))
        winner = max(range(len(categories)), key=lambda i: exact_values[i])
        fact = next(f for f in self.facts if f.id == shares[winner])
        kinds = ["pie", "bar", "table"] if 2 <= len(categories) <= 6 else ["bar", "table"]
        return self.finish(data, kinds, "title.shares", {"category": categories[winner], "value": fact.value}, [shares[winner], total_id])

    def dynamics(self, data, groups):
        categories, series = data.categories, data.series
        period = [categories[0], categories[-1]]
        first, last = series[0].values[0], series[0].values[-1]
        if len(series) == 1 and len(categories) >= 2 and first is not None and last is not None:
            # Aggregate exact values again rather than deriving from rounded plot values.
            metric = self.metrics[0]
            start = _aggregate([self.values[metric][i] for i in groups[categories[0]]], self.request.aggregation)
            end = _aggregate([self.values[metric][i] for i in groups[categories[-1]]], self.request.aggregation)
            if self.unit == "%":
                delta = end-start
                fact = self.fact(delta, groups[categories[0]]+groups[categories[-1]], [self.dimension, metric],
                                 "percentage_points", unit="pp", period=period, base=str(start), end=str(end))
                return self.finish(data, ["line", "bar", "table"], "title.percentage_points",
                                   {"metric": series[0].name, "value": _float(delta)}, [fact], period)
            if start > 0 and self.columns[self.dimension].periodicity in {"daily", "monthly", "yearly"}:
                with localcontext() as ctx:
                    ctx.prec = CALCULATION_PRECISION
                    growth = (end-start)/start*100
                fact = self.fact(growth, groups[categories[0]]+groups[categories[-1]], [self.dimension, metric],
                                 "growth_percent", unit="%", period=period, base=str(start), end=str(end))
                return self.finish(data, ["line", "bar", "table"], "title.growth",
                                   {"metric": series[0].name, "value": _float(growth)}, [fact], period)
            self.warnings.append(Notice(code="analysis.growth_not_comparable"))
        available = [(i, j, v) for i, s in enumerate(series) for j, v in enumerate(s.values) if v is not None]
        latest = max(j for _, j, _ in available)
        winner, position, value = max((p for p in available if p[1] == latest), key=lambda p: p[2])
        return self.finish(data, ["line", "grouped_bar", "table"] if len(series) > 1 else ["line", "bar", "table"],
                           "title.last_observation", {"metric": series[winner].name, "period": categories[position], "value": value},
                           [series[winner].fact_ids[position]], period=period)

    def comparison(self, data):
        categories, series = data.categories, data.series
        # Sort categories and every series together; never sort labels independently of values.
        order = sorted(range(len(categories)), key=lambda i: (series[0].values[i] is None,
                       -(series[0].values[i] or 0), categories[i]))
        data.categories = [categories[i] for i in order]
        for s in series:
            s.values = [s.values[i] for i in order]
            s.fact_ids = [s.fact_ids[i] for i in order]
        kinds = ["grouped_bar", "table"] if len(series) > 1 else ["bar", "table"]
        if (self.unit != "%" and len(series) > 1 and (self.request.series_dimension or self.request.series_additive)
                and all(v is not None and v >= 0 for s in series for v in s.values)):
            kinds.insert(1, "stacked_bar")
        return self.finish(data, kinds, "title.comparison", {"category": data.categories[0],
                           "value": series[0].values[0], "metric": series[0].name}, [series[0].fact_ids[0]])


def analyze(dataset, request=None):
    request = request or AnalysisRequest()
    try:
        calculation = _Calculation(dataset, request)
    except ValueError:
        return AnalysisResult(dataset_ref=dataset.ref, profile=profile_dataset(dataset),
                              analysis=Analysis(goal=request.goal, task=request.task or "reference",
                                                metrics=request.metrics, aggregation=request.aggregation),
                              status="refused", refusal=Notice(code="analysis.invalid_request"))
    invalid = calculation.validate()
    if invalid is not None:
        return invalid
    handler = {"reference": calculation.reference, "summary": calculation.summary,
               "relationship": calculation.relationship, "distribution": calculation.distribution}
    return handler.get(calculation.task, calculation.grouped)()


def verify_result(dataset, request, result):
    """Call with the trusted persisted source and request after any model/edit stage.

    Full deterministic recomputation catches category/value swaps, altered titles,
    fabricated facts and modified evidence. Do not accept sources from the model.
    """
    expected = analyze(dataset, request)
    return expected.model_dump(mode="json") == result.model_dump(mode="json")
