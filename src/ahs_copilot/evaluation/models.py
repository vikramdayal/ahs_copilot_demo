from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class NumericExpectation(StrictModel):
    """Expected numeric records with explicit comparison tolerances."""

    records: list[dict[str, Any]] = Field(default_factory=list)
    key_fields: list[str] = Field(default_factory=list)
    value_fields: list[str] = Field(default_factory=list)
    absolute_tolerance: float = Field(default=1e-6, ge=0)
    relative_tolerance: float = Field(default=1e-6, ge=0)

    @model_validator(mode="after")
    def validate_numeric_contract(self) -> "NumericExpectation":
        if self.records and not self.value_fields:
            raise ValueError("Numeric expectations require at least one value field")
        return self


class CitationExpectation(StrictModel):
    required: bool = True
    required_topics: list[str] = Field(default_factory=list)
    minimum_count: int = Field(default=1, ge=0)


class EvaluationCase(StrictModel):
    id: str
    domain: str
    question_type: Literal["valid", "ambiguous", "unsupported", "misleading"]
    question: str
    expected_dataset: list[str] = Field(default_factory=list)
    expected_variables: list[str] = Field(default_factory=list)
    expected_universe: str
    expected_weight: str
    expected_grouping: list[str] = Field(default_factory=list)
    expected_filters: list[dict[str, Any]] = Field(default_factory=list)
    expected_behavior: str
    acceptance_criteria: str
    expected_numeric: NumericExpectation | None = None
    citation_expectation: CitationExpectation = Field(default_factory=CitationExpectation)


class EvaluationSet(StrictModel):
    title: str
    version: str
    baseline: str
    notes: list[str] = Field(default_factory=list)
    questions: list[EvaluationCase] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_ids(self) -> "EvaluationSet":
        ids = [case.id for case in self.questions]
        if len(ids) != len(set(ids)):
            raise ValueError("Evaluation case IDs must be unique")
        return self


class CitationRecord(StrictModel):
    topic: str | None = None
    source: str
    locator: str | None = None


class CandidateResponse(StrictModel):
    """Normalized output captured from one agent/workflow attempt."""

    case_id: str
    status: Literal["completed", "clarification", "refusal", "error"]
    plan: dict[str, Any] | None = None
    plan_schema_valid: bool | None = None
    plan_validation_succeeded: bool | None = None
    plan_validation_errors: list[str] = Field(default_factory=list)
    sql_execution_succeeded: bool | None = None
    execution_error: str | None = None
    result_records: list[dict[str, Any]] = Field(default_factory=list)
    narrative: str = ""
    citations: list[CitationRecord] = Field(default_factory=list)
    refusal_or_clarification_reason: str | None = None


class CriterionScore(StrictModel):
    name: str
    earned: float
    possible: float
    passed: bool
    applicable: bool = True
    details: list[str] = Field(default_factory=list)


class ScoreSection(StrictModel):
    earned: float
    possible: float
    normalized: float
    passed: bool
    criteria: list[CriterionScore]


class EvaluationResult(StrictModel):
    case_id: str
    deterministic: ScoreSection
    narrative: ScoreSection
    overall_status: Literal["pass", "fail", "not_applicable"]
    hard_gate_failures: list[str] = Field(default_factory=list)
    diagnostics: list[str] = Field(default_factory=list)


class EvaluationRunReport(StrictModel):
    evaluation_title: str
    evaluation_version: str
    total_cases: int
    deterministic_mean: float
    narrative_mean: float
    pass_count: int
    fail_count: int
    results: list[EvaluationResult]
