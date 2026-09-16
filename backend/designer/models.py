from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Series(StrictModel):
    name: str = Field(min_length=1, max_length=100)
    values: list[float] = Field(min_length=1, max_length=20)


class Visual(StrictModel):
    """Data for a native slide object.

    Validation rejects only what cannot be rendered. Density limits from the brief
    (table size, series count, missing units) are quality findings, so they are
    raised by the audit where the user can see and decide on them.
    """

    kind: Literal["none", "table", "bar", "line", "process", "icon"] = "none"
    categories: list[str] = Field(default_factory=list, max_length=20)
    series: list[Series] = Field(default_factory=list, max_length=8)
    columns: list[str] = Field(default_factory=list, max_length=8)
    rows: list[list[str]] = Field(default_factory=list, max_length=12)
    steps: list[str] = Field(default_factory=list, max_length=6)
    unit: str = Field(default="", max_length=80)

    @model_validator(mode="after")
    def coherent(self):
        if self.kind in ("bar", "line"):
            if not self.categories or not self.series:
                raise ValueError("Charts require categories and series")
            if any(len(s.values) != len(self.categories) for s in self.series):
                raise ValueError("Each series must match categories")
            if any(not (-1e15 < v < 1e15) for s in self.series for v in s.values):
                raise ValueError("Chart values must be finite")
        if self.kind == "table" and (
            not self.columns
            or not self.rows
            or any(len(r) != len(self.columns) for r in self.rows)
        ):
            raise ValueError("Table rows must match columns")
        if self.kind in ("process", "icon") and not self.steps:
            raise ValueError("Process/icon requires steps")
        return self


class SlideContent(StrictModel):
    title: str = Field(min_length=1, max_length=240)
    bullets: list[str] = Field(default_factory=list, max_length=12)
    notes: str = Field(default="", max_length=4000)
    source_refs: list[str] = Field(default_factory=list)
    visual: Visual = Field(default_factory=Visual)


class Outline(StrictModel):
    title: str = Field(min_length=1, max_length=240)
    slides: list[SlideContent] = Field(min_length=1, max_length=30)


class Brief(StrictModel):
    brief: str = Field(min_length=3, max_length=30000)
    purpose: Literal["feature", "product", "project", "initiative"] = "project"
    language: str = Field(default="ru", min_length=2, max_length=30)
    slide_count: int = Field(default=12, ge=1, le=30)
    content_pack_ids: list[str] = Field(default_factory=list, max_length=10)


class GenerateRequest(Brief):
    contextual_audit: bool = False
    template_id: str
    outline: Outline | None = None

    @model_validator(mode="after")
    def count_matches(self):
        if self.outline and len(self.outline.slides) != self.slide_count:
            raise ValueError("outline.slides must match slide_count")
        return self


class FixRequest(StrictModel):
    revision: int = Field(ge=1)
    issue_ids: list[str] = Field(min_length=1, max_length=500)


class SlideEdit(StrictModel):
    revision: int = Field(ge=1)
    content: SlideContent
