from __future__ import annotations

from typing import Literal
from pydantic import BaseModel, ConfigDict, Field
from ahs_copilot.survey_estimation.contracts import Condition, SurveyEstimateRequest


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AnalysisPlan(StrictModel):
    user_question: str
    dataset: str
    measure: Literal["count", "percentage", "mean"]
    numerator: list[Condition] = Field(default_factory=list)
    denominator: list[Condition] = Field(default_factory=list)
    universe: str
    filters: list[Condition] = Field(default_factory=list)
    grouping_dimensions: list[str] = Field(default_factory=list)
    weight: str
    required_variables: list[str]
    derived_recodes: list[str] = Field(default_factory=list)
    validation_checks: list[str] = Field(default_factory=list)
    output_format: Literal["json", "table"] = "json"
    value_variable: str | None = None


class ValidationIssue(StrictModel):
    code: str
    path: str
    message: str


class ValidatedAnalysisPlan(StrictModel):
    plan: AnalysisPlan
    normalized_request: SurveyEstimateRequest
    required_variable_closure: list[str]
    validation_checks: list[str]
