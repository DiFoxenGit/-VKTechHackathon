"""Machine-readable sidecar boundary for Dima's multi-source evidence."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, FiniteFloat
from . import Dataset, AnalysisRequest, AnalysisResult


class Strict(BaseModel):
    model_config=ConfigDict(extra='forbid',allow_inf_nan=False)


class SourceEvidence(Strict):
    table: Literal['sales','plan']
    row_ids: list[int]=Field(min_length=1)
    fields: list[str]=Field(min_length=1)
    role: Literal['numerator','baseline','denominator']
    fingerprint: str=Field(pattern=r'^[0-9a-f]{64}$')


class BusinessFact(Strict):
    id: str
    exact: str | None
    value: FiniteFloat | None
    unit: Literal['RUB','%','pp']
    period: list[str]=Field(min_length=2,max_length=2)
    formula: str
    evidence: list[SourceEvidence]=Field(min_length=1)
    rounding: str
    category: str | None=None


class ReadyView(Strict):
    dataset: Dataset
    request: AnalysisRequest
    result: AnalysisResult


class DerivedRow(Strict):
    derived_row: int=Field(ge=2)
    evidence: list[SourceEvidence]=Field(min_length=1)


class BusinessResult(Strict):
    schema_version: Literal['business-draft-1']
    status: Literal['draft_for_contract_review']
    fingerprints: dict[str,str]
    facts: dict[str,BusinessFact]
    views: dict[str,ReadyView]
    lineage: dict[str,list[DerivedRow]]
    warnings: list[dict]
    entities: dict[str,dict[str,str]]
    unsupported: list[str]
    explanations: dict[str,dict[str,str]]
