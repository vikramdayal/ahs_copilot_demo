from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ahs_copilot.query_engine.models import JoinSpec, QualifiedColumn, TypedFilter
from ahs_copilot.survey_estimation.models import (
    ComparisonSpec,
    SurveyEstimateRequest,
    SurveyEstimateResult,
)

_IDENTIFIER_PATTERN = r"^[A-Za-z_][A-Za-z0-9_]*$"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class MeasureSpec(StrictModel):
    alias: str = Field(pattern=_IDENTIFIER_PATTERN)
    statistic: Literal["count", "percentage", "mean"]
    value: QualifiedColumn | None = None

    @model_validator(mode="after")
    def validate_measure_shape(self) -> "MeasureSpec":
        if self.statistic == "mean" and self.value is None:
            raise ValueError("A mean measure requires a value variable")
        if self.statistic != "mean" and self.value is not None:
            raise ValueError(f"A {self.statistic} measure does not accept a value variable")
        return self


class NumeratorSpec(StrictModel):
    role: Literal["eligible_units", "condition_true", "weighted_value_sum"]
    description: str = Field(min_length=1)
    filters: list[TypedFilter] = Field(default_factory=list)


class DenominatorSpec(StrictModel):
    role: Literal["eligible_units", "nonmissing_weight_sum"]
    description: str = Field(min_length=1)
    filters: list[TypedFilter] = Field(default_factory=list)


class UniverseSpec(StrictModel):
    universe_id: str = Field(pattern=_IDENTIFIER_PATTERN)
    description: str = Field(min_length=1)


class WeightSpec(StrictModel):
    mode: Literal["weighted", "unweighted"]
    column: QualifiedColumn | None = None

    @model_validator(mode="after")
    def validate_weight_shape(self) -> "WeightSpec":
        if self.mode == "weighted" and self.column is None:
            raise ValueError("Weighted plans require an explicit weight column")
        if self.mode == "unweighted" and self.column is not None:
            raise ValueError("Unweighted plans must not specify a weight column")
        return self


class DerivedRecodeSpec(StrictModel):
    recode_id: str = Field(pattern=_IDENTIFIER_PATTERN)
    output_name: str = Field(pattern=_IDENTIFIER_PATTERN)
    purpose: str = Field(min_length=1)


class ValidationChecks(StrictModel):
    schema_variables: Literal[True] = True
    puf_access: Literal[True] = True
    universe_compatibility: Literal[True] = True
    measure_compatibility: Literal[True] = True
    numerator_denominator_compatibility: Literal[True] = True
    weight_compatibility: Literal[True] = True
    required_variable_closure: Literal[True] = True
    approved_join_paths: Literal[True] = True
    missing_value_codes: Literal[True] = True
    empty_denominator_runtime_flag: Literal[True] = True


class OutputFormatSpec(StrictModel):
    format: Literal["json_records", "table"] = "json_records"
    include_analysis_plan: bool = True
    include_generated_sql: bool = True
    include_execution_metadata: bool = True
    include_formula_metadata: bool = True
    limit: int | None = Field(default=None, ge=1)


class AnalysisPlan(StrictModel):
    """Structured, non-SQL analysis contract accepted before deterministic compilation."""

    plan_version: Literal["1.0"] = "1.0"
    user_question: str = Field(min_length=3)
    dataset: str = Field(pattern=_IDENTIFIER_PATTERN)
    measure: MeasureSpec
    numerator: NumeratorSpec
    denominator: DenominatorSpec
    universe: UniverseSpec
    filters: list[TypedFilter] = Field(default_factory=list)
    grouping_dimensions: list[QualifiedColumn] = Field(default_factory=list)
    weight: WeightSpec
    required_variables: list[QualifiedColumn] = Field(min_length=1)
    derived_recodes: list[DerivedRecodeSpec] = Field(default_factory=list)
    joins: list[JoinSpec] = Field(default_factory=list)
    comparisons: ComparisonSpec = Field(default_factory=ComparisonSpec)
    validation_checks: ValidationChecks = Field(default_factory=ValidationChecks)
    output_format: OutputFormatSpec = Field(default_factory=OutputFormatSpec)

    @model_validator(mode="after")
    def validate_unique_contract_items(self) -> "AnalysisPlan":
        required = [(x.dataset.lower(), x.column.upper()) for x in self.required_variables]
        if len(required) != len(set(required)):
            raise ValueError("required_variables must be unique")
        groupings = [(x.dataset.lower(), x.column.upper()) for x in self.grouping_dimensions]
        if len(groupings) != len(set(groupings)):
            raise ValueError("grouping_dimensions must be unique")
        recode_names = [x.output_name.upper() for x in self.derived_recodes]
        if len(recode_names) != len(set(recode_names)):
            raise ValueError("Derived recode output names must be unique")
        join_names = [x.dataset.lower() for x in self.joins]
        if len(join_names) != len(set(join_names)):
            raise ValueError("A dataset may be joined at most once")
        return self


class PlanValidationIssue(StrictModel):
    code: str
    path: str
    message: str


class ValidatedAnalysisPlan(StrictModel):
    plan: AnalysisPlan
    plan_fingerprint: str
    normalized_dataset: str
    normalized_universe_id: str
    inferred_required_variables: list[QualifiedColumn]
    approved_recode_ids: list[str]
    validation_messages: list[str]
    survey_request: SurveyEstimateRequest


class AnalysisPlanExecutionResult(StrictModel):
    plan: AnalysisPlan
    plan_fingerprint: str
    validation_messages: list[str]
    output_format: OutputFormatSpec
    result: SurveyEstimateResult
