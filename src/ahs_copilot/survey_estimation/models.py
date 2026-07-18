from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ahs_copilot.query_engine.models import JoinSpec, QualifiedColumn, TypedFilter

_IDENTIFIER_PATTERN = r"^[A-Za-z_][A-Za-z0-9_]*$"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class GroupDimension(StrictModel):
    column: QualifiedColumn
    alias: str | None = Field(default=None, pattern=_IDENTIFIER_PATTERN)


EstimateStatistic = Literal["weighted_count", "weighted_percentage", "weighted_mean"]

class MissingValueRule(StrictModel):
    column: QualifiedColumn
    codes: list[Any] = Field(default_factory=list)


class EstimateDefinition(StrictModel):
    alias: str = Field(pattern=_IDENTIFIER_PATTERN)
    statistic: EstimateStatistic
    numerator_filters: list[TypedFilter] = Field(default_factory=list)
    denominator_filters: list[TypedFilter] = Field(default_factory=list)
    value: QualifiedColumn | None = None
    missing_value_rules: list[MissingValueRule] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_statistic_shape(self) -> "EstimateDefinition":
        if self.statistic == "weighted_percentage" and not self.numerator_filters:
            raise ValueError("weighted_percentage requires at least one numerator filter")
        if self.statistic == "weighted_mean":
            if self.value is None:
                raise ValueError("weighted_mean requires a value column")
            if self.numerator_filters:
                raise ValueError("weighted_mean does not accept numerator filters")
        elif self.value is not None:
            raise ValueError(f"{self.statistic} does not accept a value column")
        return self


class SuppressionPolicy(StrictModel):
    policy_id: str = "configured_unweighted_cell_thresholds_v1"
    minimum_unweighted_denominator: int = Field(default=1, ge=0)
    minimum_unweighted_numerator: int = Field(default=0, ge=0)
    minimum_unweighted_complement: int = Field(default=0, ge=0)
    action: Literal["flag", "null_estimate"] = "null_estimate"


class ComparisonSpec(StrictModel):
    mode: Literal["none", "reference", "all_pairs"] = "none"
    reference_group: dict[str, Any] | None = None
    include_ratio: bool = True

    @model_validator(mode="after")
    def validate_reference(self) -> "ComparisonSpec":
        if self.mode == "reference" and not self.reference_group:
            raise ValueError("reference comparisons require reference_group")
        if self.mode != "reference" and self.reference_group is not None:
            raise ValueError("reference_group is allowed only when mode='reference'")
        return self


class SurveyEstimateRequest(StrictModel):
    """Governed descriptive-estimation input. Raw SQL is intentionally impossible."""

    base_dataset: str = Field(pattern=_IDENTIFIER_PATTERN)
    weighting_mode: Literal["weighted", "unweighted"] = "weighted"
    weight: QualifiedColumn | None = None
    universe_filters: list[TypedFilter] = Field(default_factory=list)
    joins: list[JoinSpec] = Field(default_factory=list)
    group_by: list[GroupDimension] = Field(default_factory=list)
    estimates: list[EstimateDefinition] = Field(min_length=1)
    suppression: SuppressionPolicy | None = None
    comparisons: ComparisonSpec = Field(default_factory=ComparisonSpec)
    limit: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def validate_unique_names(self) -> "SurveyEstimateRequest":
        joins = [item.dataset.lower() for item in self.joins]
        if len(joins) != len(set(joins)):
            raise ValueError("A dataset may be joined at most once")
        estimate_aliases = [item.alias.upper() for item in self.estimates]
        if len(estimate_aliases) != len(set(estimate_aliases)):
            raise ValueError("Estimate aliases must be unique")
        group_aliases = [(item.alias or item.column.column).upper() for item in self.group_by]
        if len(group_aliases) != len(set(group_aliases)):
            raise ValueError("Group aliases must be unique")
        if self.comparisons.mode != "none" and not self.group_by:
            raise ValueError("Grouped comparisons require at least one group_by dimension")
        if self.weighting_mode == "weighted" and self.weight is None:
            pass  # the configured default weight may be resolved by the estimator
        if self.weighting_mode == "unweighted" and self.weight is not None:
            raise ValueError("Unweighted requests must not specify a weight column")
        return self


class FormulaDescriptor(StrictModel):
    estimate_alias: str
    statistic: EstimateStatistic
    numerator_formula: str
    denominator_formula: str
    estimate_formula: str
    missing_value_rule: str
    weight_rule: str


class CompiledSurveyEstimate(StrictModel):
    sql: str
    display_sql: str
    parameters: list[Any]
    effective_limit: int
    canonical_request: dict[str, Any]
    request_fingerprint: str
    datasets_used: list[str]
    join_contract_ids: list[str]
    group_aliases: list[str]
    normalized_reference_group: dict[str, Any] | None
    formulas: list[FormulaDescriptor]


class SuppressionDecision(StrictModel):
    suppressed: bool
    action: Literal["flag", "null_estimate"]
    reasons: list[str]
    policy_id: str


class SurveyEstimate(StrictModel):
    group: dict[str, Any]
    weighting_mode: Literal["weighted", "unweighted"]
    estimate_alias: str
    statistic: EstimateStatistic
    estimate: Decimal | None
    weighted_numerator: Decimal | None
    weighted_denominator: Decimal
    unweighted_numerator: int
    unweighted_denominator: int
    unweighted_complement: int | None
    invalid_weight_rows_excluded: int
    missing_value_rows_excluded: int
    suppression: SuppressionDecision
    formula: str
    standard_error: None = None
    confidence_interval: None = None


class GroupComparison(StrictModel):
    estimate_alias: str
    statistic: EstimateStatistic
    left_group: dict[str, Any]
    right_group: dict[str, Any]
    difference: Decimal | None
    ratio: Decimal | None
    suppressed: bool
    reasons: list[str]
    warnings: list[str] = Field(default_factory=list)
    inferential_test: Literal["NOT_PERFORMED"] = "NOT_PERFORMED"
    standard_error: None = None
    p_value: None = None


class VarianceMetadata(StrictModel):
    status: Literal["NOT_ESTIMATED"] = "NOT_ESTIMATED"
    replicate_weights_used: Literal[False] = False
    approved_method: None = None
    standard_errors_valid: Literal[False] = False
    message: str = (
        "Descriptive weighted estimates only. Standard errors, confidence intervals, "
        "and significance tests are unavailable until replicate weights and an approved "
        "variance method are implemented."
    )


class DatasetEstimateMetadata(StrictModel):
    logical_name: str
    source_file_id: str
    physical_path: str
    synthetic_fixture: bool
    size_bytes: int | None
    modified_ns: int | None


class SurveyExecutionMetadata(StrictModel):
    run_id: str
    request_fingerprint: str
    sql_fingerprint: str
    started_at: datetime
    finished_at: datetime
    elapsed_ms: float
    duckdb_version: str
    database: str
    memory_limit: str
    temp_directory: str
    threads: int
    datasets: list[DatasetEstimateMetadata]
    join_contract_ids: list[str]
    group_rows: int
    comparisons_returned: int
    estimation_scope: Literal["DESCRIPTIVE_WEIGHTED_ESTIMATES", "DESCRIPTIVE_UNWEIGHTED_ESTIMATES"]
    weight_column: QualifiedColumn | None
    weight_eligibility_rule: str
    arithmetic_rule: str
    suppression_policy: SuppressionPolicy
    variance: VarianceMetadata = Field(default_factory=VarianceMetadata)


class SurveyEstimateResult(StrictModel):
    estimates: list[SurveyEstimate]
    comparisons: list[GroupComparison]
    generated_sql: str
    parameterized_sql: str
    parameters: list[Any]
    formulas: list[FormulaDescriptor]
    metadata: SurveyExecutionMetadata
