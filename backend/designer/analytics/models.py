"""Versioned integration contract; independent of the slide/export schemas."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, FiniteFloat, model_validator

MAX_SAFE_INTEGER = 2**53-1

class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


Scalar = str | int | FiniteFloat | bool | None
ChartKind = Literal["table", "line", "bar", "histogram", "pie", "scatter",
                    "grouped_bar", "stacked_bar", "kpi"]
Task = Literal["dynamics", "comparison", "shares", "distribution", "relationship", "reference", "summary"]


class Notice(Contract):
    code: str
    params: dict[str, Scalar] = Field(default_factory=dict)


class DatasetRef(Contract):
    dataset_id: str
    source_sha256: str
    filename: str
    archive_path: str | None = None
    table: str


class Column(Contract):
    id: str
    name: str
    unit: str = ""
    normalization: Literal["identity", "excel_percentage_points", "excel_day_fraction"] = "identity"


class Dataset(Contract):
    """Store this object in full. rows are never slide-sized samples."""
    schema_version: Literal["1.0"] = "1.0"
    ref: DatasetRef
    columns: list[Column]
    rows: list[list[Scalar]]
    row_ids: list[int]
    context: str = ""
    warnings: list[Notice] = Field(default_factory=list)

    @model_validator(mode="after")
    def rectangular(self):
        if not self.columns or len({c.id for c in self.columns}) != len(self.columns):
            raise ValueError("columns must have unique nonempty identifiers")
        if len(self.rows) != len(self.row_ids) or len(set(self.row_ids)) != len(self.row_ids):
            raise ValueError("rows require unique source row identifiers")
        if any(r < 1 for r in self.row_ids):
            raise ValueError("source row identifiers must be positive")
        if any(len(r) != len(self.columns) for r in self.rows):
            raise ValueError("rows must match columns")
        return self


class ImportResult(Contract):
    datasets: list[Dataset] = Field(default_factory=list)
    rejected: list[Notice] = Field(default_factory=list)


class ColumnProfile(Contract):
    id: str
    name: str
    kind: Literal["number", "date", "category", "text", "empty", "ambiguous"]
    role: Literal["metric", "dimension", "time", "identifier", "unknown"]
    unit: str = ""
    missing: int = 0
    distinct: int = 0
    outlier_row_ids: list[int] = Field(default_factory=list)
    period: list[str] = Field(default_factory=list)
    periodicity: str | None = None
    missing_periods: list[str] = Field(default_factory=list)


class Profile(Contract):
    row_count: int
    column_count: int
    columns: list[ColumnProfile]
    hierarchies: list[list[str]] = Field(default_factory=list)
    dimension_count: int
    metric_count: int
    warnings: list[Notice] = Field(default_factory=list)


class AnalysisRequest(Contract):
    goal: str = ""
    task: Task | None = None
    dimension: str | None = None
    series_dimension: str | None = None
    series_additive: bool = False
    metrics: list[str] = Field(default_factory=list)
    aggregation: Literal["sum", "mean", "median", "count"] = "sum"
    unit: str = ""
    locale: Literal["ru", "en"] = "ru"
    bins: int | None = Field(default=None, ge=1, le=100)
    page_size: int = Field(default=10, ge=1, le=20)
    slide_budget: int = Field(default=30, ge=1, le=30)
    # Explicit column types resolve ambiguous dates/identifiers; never inferred from a template.
    column_types: dict[str, Literal["number", "date", "category", "text"]] = Field(default_factory=dict)
    number_locale: Literal["decimal_comma", "decimal_point"] | None = None
    filters: dict[str, list[Scalar]] = Field(default_factory=dict)


class Analysis(Contract):
    goal: str
    task: Task
    dimension: str | None = None
    series_dimension: str | None = None
    metrics: list[str] = Field(default_factory=list)
    aggregation: str
    missing_policy: Literal["preserve_gaps_exclude_from_aggregate"] = "preserve_gaps_exclude_from_aggregate"
    transformations: list[str] = Field(default_factory=list)


class Candidate(Contract):
    kind: ChartKind
    rank: int = Field(ge=1, le=3)
    reason: Notice


class Visualization(Contract):
    selected: ChartKind
    candidates: list[Candidate] = Field(min_length=1, max_length=3)


class Evidence(Contract):
    """Source coordinates, not a global whitelist of numbers."""
    source_sha256: str
    row_ids: list[int]
    column_ids: list[str]
    operation: str
    parameters: dict[str, Scalar] = Field(default_factory=dict)


class Fact(Contract):
    id: str
    value: FiniteFloat
    exact: str
    unit: str
    period: list[str] = Field(default_factory=list)
    evidence: Evidence
    # exact is decimal; value is a finite plotting number, without forced truncation.
    rounding_digits: int | None = None


class Series(Contract):
    name: str
    unit: str = ""
    values: list[FiniteFloat | None]
    fact_ids: list[str]


class Point(Contract):
    x: FiniteFloat
    y: FiniteFloat
    row_id: int


class VisualData(Contract):
    categories: list[str] = Field(default_factory=list)
    series: list[Series] = Field(default_factory=list)
    points: list[Point] = Field(default_factory=list)
    columns: list[str] = Field(default_factory=list)
    rows: list[list[Scalar]] = Field(default_factory=list)
    row_ids: list[int] = Field(default_factory=list)
    pages: list[list[int]] = Field(default_factory=list)
    series_pages: list[list[int]] = Field(default_factory=list)
    bins: list[list[FiniteFloat]] = Field(default_factory=list)
    kpi_fact_ids: list[str] = Field(default_factory=list)


class Presentation(Contract):
    title: str
    x_label: str = ""
    y_label: str = ""
    x_unit: str = ""
    y_unit: str = ""
    unit: str = ""
    period: list[str] = Field(default_factory=list)
    source_label: str
    conclusion_fact_ids: list[str] = Field(default_factory=list)


class AnalysisResult(Contract):
    schema_version: Literal["1.0"] = "1.0"
    dataset_ref: DatasetRef
    profile: Profile
    analysis: Analysis
    visualization: Visualization | None = None
    data: VisualData = Field(default_factory=VisualData)
    facts: list[Fact] = Field(default_factory=list)
    presentation: Presentation | None = None
    status: Literal["ok", "warning", "refused"]
    warnings: list[Notice] = Field(default_factory=list)
    refusal: Notice | None = None

    @model_validator(mode="after")
    def coherent(self):
        if self.status == "refused":
            if self.refusal is None or self.visualization is not None:
                raise ValueError("refused results require a reason and no visualization")
        elif self.visualization is None or self.presentation is None:
            raise ValueError("successful results require visualization and presentation")
        if self.visualization and self.visualization.candidates[0].kind != self.visualization.selected:
            raise ValueError("selected visualization must be the first candidate")
        if self.visualization:
            candidates = self.visualization.candidates
            if [c.rank for c in candidates] != list(range(1, len(candidates)+1)) or len({c.kind for c in candidates}) != len(candidates):
                raise ValueError("candidates require unique kinds and sequential ranks")
        facts = {f.id: f for f in self.facts}
        if len(facts) != len(self.facts):
            raise ValueError("fact identifiers must be unique")
        for series in self.data.series:
            if len(series.values) != len(self.data.categories) or len(series.fact_ids) != len(series.values):
                raise ValueError("series values and evidence must match categories")
            for value, fact_id in zip(series.values, series.fact_ids):
                if value is not None and (fact_id not in facts or value != facts[fact_id].value):
                    raise ValueError("series values must match referenced facts")
                if value is None and fact_id:
                    raise ValueError("a missing value cannot reference a numeric fact")
        if any(i not in facts for i in self.data.kpi_fact_ids):
            raise ValueError("KPI references require existing facts")
        if self.presentation and any(i not in facts for i in self.presentation.conclusion_fact_ids):
            raise ValueError("conclusions require existing facts")
        if self.data.series_pages:
            if [i for page in self.data.series_pages for i in page] != list(range(len(self.data.series))):
                raise ValueError("series pages must include every series exactly once")
        if self.data.pages:
            size = len(self.data.rows) if self.data.columns else len(self.data.categories)
            if [i for page in self.data.pages for i in page] != list(range(size)):
                raise ValueError("pages must include every row or category exactly once")
        return self
