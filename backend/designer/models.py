from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator, field_validator
from .analytics.models import AnalysisRequest
from .analytics.business_periods import BusinessPeriods
from .analytics.business_conditions import ContextConditions

STEP_VISUAL_KINDS = ('process', 'icon', 'cycle', 'pyramid', 'timeline')


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Series(StrictModel):
    name: str = Field(min_length=1, max_length=100)
    values: list[float | None] = Field(min_length=1, max_length=2000)


class Visual(StrictModel):
    """Data for a native slide object.

    Validation rejects only what cannot be rendered. Density limits from the brief
    (table size, series count, missing units) are quality findings, so they are
    raised by the audit where the user can see and decide on them.
    """

    # Pydantic's after-validator is invisible in the schema sent to the model.
    # Publish its conditional requirement, rather than silently inventing steps.
    model_config = ConfigDict(extra='forbid', json_schema_extra={'allOf': [{
        'if': {'required': ['kind'], 'properties': {'kind': {'enum': list(STEP_VISUAL_KINDS)}}},
        'then': {'required': ['steps'], 'properties': {'steps': {'minItems': 1}}},
    }]})

    kind: Literal[
        "none",
        "table",
        "bar",
        "line",
        "pie",
        "scatter",
        "histogram",
        "grouped_bar",
        "stacked_bar",
        "kpi",
        "process",
        "icon",
        "cycle",
        "pyramid",
        "timeline",
        "comparison",
    ] = "none"
    categories: list[str] = Field(default_factory=list, max_length=2000)
    series: list[Series] = Field(default_factory=list, max_length=8)
    columns: list[str] = Field(default_factory=list, max_length=8)
    rows: list[list[str]] = Field(default_factory=list, max_length=12)
    steps: list[str] = Field(default_factory=list, max_length=6)
    unit: str = Field(default="", max_length=80)
    source: str = Field(default="", max_length=500)
    x_label: str = Field(default="", max_length=120)
    y_label: str = Field(default="", max_length=120)
    x_values: list[float] = Field(default_factory=list, max_length=2000)

    @model_validator(mode="after")
    def coherent(self):
        if self.kind in ("bar", "line", "pie", "scatter", "histogram", "grouped_bar", "stacked_bar", "kpi"):
            if not self.categories or not self.series:
                raise ValueError("Charts require categories and series")
            if any(len(s.values) != len(self.categories) for s in self.series):
                raise ValueError("Each series must match categories")
            if any(v is not None and not (-1e15 < v < 1e15) for s in self.series for v in s.values):
                raise ValueError("Chart values must be finite")
            if self.kind != "scatter" and len(self.categories) > 20:
                raise ValueError("More than 20 categories require explicit aggregation or pagination")
            if self.kind == "scatter" and (len(self.x_values) != len(self.categories) or any(not (-1e15 < v < 1e15) for v in self.x_values)):
                raise ValueError("Scatter requires finite X values matching Y values")
            if self.kind == "pie" and (len(self.series) != 1 or any(v is None or v < 0 for v in self.series[0].values) or sum(self.series[0].values) <= 0):
                raise ValueError("Pie requires one nonnegative complete series with positive total")
        if self.kind == "table" and (
            not self.columns
            or not self.rows
            or any(len(r) != len(self.columns) for r in self.rows)
        ):
            raise ValueError("Table rows must match columns")
        if self.kind in STEP_VISUAL_KINDS and not self.steps:
            raise ValueError('Step diagrams require steps: supply a nonempty steps array from source material, or use kind=none')
        if self.kind == "comparison" and (
            len(self.columns) != 2 or not self.rows or any(len(r) != 2 for r in self.rows)
        ):
            raise ValueError("Comparison requires two columns and rows of two cells")
        return self


class SlideContent(StrictModel):
    role: Literal['auto', 'cover', 'content', 'closing'] = 'auto'
    block_roles: list[Literal['lead', 'evidence', 'action', 'caveat', 'source', 'subtitle']] = Field(default_factory=list, max_length=12)
    title: str = Field(min_length=1, max_length=240)
    bullets: list[str] = Field(default_factory=list, max_length=12)
    notes: str = Field(default="", max_length=4000)
    source_refs: list[str] = Field(default_factory=list)
    visual: Visual = Field(default_factory=Visual)
    analysis_id: str = ""

    @model_validator(mode='after')
    def cover_is_a_title_page(self):
        if self.block_roles and len(self.block_roles) != len(self.bullets):
            raise ValueError('У каждого текстового блока должна быть одна семантическая роль.')
        if self.role == 'cover' and (self.visual.kind != 'none' or len(self.bullets) > 1):
            raise ValueError('Обложка содержит название и один блок периода/адресата; доказательства и списки перенесите на содержательные страницы.')
        return self


class Outline(StrictModel):
    title: str = Field(min_length=1, max_length=240)
    slides: list[SlideContent] = Field(min_length=1, max_length=30)


class Brief(StrictModel):
    brief: str = Field(min_length=3, max_length=30000)
    purpose: Literal["feature", "product", "project", "initiative"] = "project"
    language: str = Field(default="ru", min_length=2, max_length=30)
    slide_count: int = Field(default=12, ge=1, le=30)
    content_pack_ids: list[str] = Field(default_factory=list, max_length=10)
    business_settings: BusinessPeriods | None = None
    business_conditions: ContextConditions | None = None
    business_context_id: str | None = Field(default=None, max_length=100)

    @field_validator('business_settings', mode='before')
    @classmethod
    def periods_are_comparable(cls, value):
        if value is None:return None
        try:return BusinessPeriods.model_validate(value)
        except ValueError as exc:
            raise ValueError('Проверьте периоды: закрытые месяцы ГГГГ-ММ; сравнения одинаковой длины, прошлогодние месяцы сдвинуты на год. История заканчивается отчётным месяцем и покрывает все сравнения; план покрывает отчётный и сравнительный периоды.') from exc

    @model_validator(mode="after")
    def business_context(self):
        if (self.business_conditions is None) != (self.business_context_id is None):
            raise ValueError('Укажите файл делового контекста и подтверждённые условия вместе.')
        if self.business_context_id is not None and self.business_context_id not in self.content_pack_ids:
            raise ValueError('Файл делового контекста должен входить в выбранные материалы.')
        return self

    @model_validator(mode="after")
    def slide_count_matches_text(self):
        from .slide_count import explicit_slide_count
        specified = explicit_slide_count(self.brief)
        if specified is not None and specified != self.slide_count:
            raise ValueError(f'В тексте указано {specified} слайдов, в настройках {self.slide_count}. Согласуйте количество до генерации / Brief and settings must specify the same slide count')
        return self


class PackAnalysisRequest(StrictModel):
    goal: str = Field(default="", max_length=1000)
    requests: dict[str, AnalysisRequest] = Field(default_factory=dict, max_length=256)


class GenerateRequest(Brief):
    model_content_generation: bool | None = None
    generate_images: bool | None = None
    narrative: bool = False
    contextual_audit: bool = False
    template_id: str
    outline: Outline | None = None
    analysis_goal: str = Field(default="", max_length=1000)
    analysis_goals: dict[str, str] = Field(default_factory=dict, max_length=10)
    analysis_requests: dict[str, AnalysisRequest] = Field(default_factory=dict, max_length=256)
    brandbook_id: str | None = None
    style_overrides: dict = Field(default_factory=dict)

    @model_validator(mode="after")
    def count_matches(self):
        if self.outline and len(self.outline.slides) != self.slide_count:
            raise ValueError("outline.slides must match slide_count")
        return self


class GenerateBatchRequest(StrictModel):
    requests: list[GenerateRequest] = Field(min_length=1, max_length=3)

    @model_validator(mode='after')
    def shared_content(self):
        ignored = {'template_id', 'brandbook_id', 'style_overrides'}
        content = self.requests[0].model_dump(exclude=ignored)
        if any(item.model_dump(exclude=ignored) != content for item in self.requests[1:]):
            raise ValueError('Задания общей генерации должны иметь одинаковые исходники, бриф, периоды и условия')
        if len({item.template_id for item in self.requests}) != len(self.requests):
            raise ValueError('Выберите разные шаблоны для общей генерации')
        return self


class FixRequest(StrictModel):
    revision: int = Field(ge=1)
    issue_ids: list[str] = Field(min_length=1, max_length=500)


class SlideEdit(StrictModel):
    revision: int = Field(ge=1)
    content: SlideContent


class PresentationEdit(StrictModel):
    revision: int = Field(ge=1)
    title: str = Field(min_length=1, max_length=240)
    variant: Literal["classic", "split", "focus"]
    slides: list[SlideContent] = Field(min_length=1, max_length=30)
