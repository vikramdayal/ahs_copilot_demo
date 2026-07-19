from __future__ import annotations

from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Condition(StrictModel):
    variable: str
    operator: Literal["eq", "ne", "gt", "ge", "lt", "le", "in", "not_in", "between", "is_null", "not_null"]
    value: Any | None = None
    values: list[Any] | None = None
    lower: Any | None = None
    upper: Any | None = None


class SurveyEstimateRequest(StrictModel):
    dataset: str = "household"
    measure: Literal["count", "percentage", "mean"]
    universe_id: str
    numerator_conditions: list[Condition] = Field(default_factory=list)
    denominator_conditions: list[Condition] = Field(default_factory=list)
    grouping_dimensions: list[str] = Field(default_factory=list)
    weight_id: str = "final_household_weight"
    value_variable: str | None = None
    minimum_unweighted_n: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def validate_measure(self) -> "SurveyEstimateRequest":
        if self.measure == "percentage" and not self.numerator_conditions:
            raise ValueError("percentage requires numerator_conditions")
        if self.measure == "mean" and not self.value_variable:
            raise ValueError("mean requires value_variable")
        return self


class CompiledSurveyEstimate(StrictModel):
    sql: str
    display_sql: str
    parameters: list[Any]
    request_fingerprint: str
    dataset: str
    universe_id: str
    weight_id: str


class SurveyEstimateResult(StrictModel):
    request: SurveyEstimateRequest
    estimates: list[dict[str, Any]]
    compiled: CompiledSurveyEstimate
    execution_metadata: dict[str, Any]
    variance: dict[str, Any]
