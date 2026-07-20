from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ahs_copilot.analysis_plan.models import (
    AnalysisPlan,
    AnalysisPlanExecutionResult,
    PlanValidationIssue,
    ValidatedAnalysisPlan,
)
from ahs_copilot.survey_estimation.models import CompiledSurveyEstimate


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


ApprovalMode = Literal["interrupt", "auto_approve"]
ApprovalAction = Literal["approved", "rejected", "revise"]
ResultCriticDecision = Literal["approve", "reject", "request_reexecution"]
CriticCheckStatus = Literal["passed", "failed", "not_applicable"]
RequestGuardAction = Literal["allow", "clarify", "refuse"]
WorkflowStatus = Literal[
    "planning",
    "awaiting_approval",
    "completed",
    "failed",
    "rejected",
]


class RequestGuardFinding(StrictModel):
    code: str
    category: str
    message: str


class RequestGuardDecision(StrictModel):
    action: RequestGuardAction
    code: str
    message: str
    findings: list[RequestGuardFinding] = Field(default_factory=list)
    narrative_constraints: list[str] = Field(default_factory=list)


class ExpectedResultGroup(StrictModel):
    estimate_alias: str
    group: dict[str, Any]


class ReferenceEstimate(StrictModel):
    estimate_alias: str
    group: dict[str, Any] = Field(default_factory=dict)
    expected: Decimal
    source_id: str = Field(min_length=1)
    absolute_tolerance: Decimal | None = Field(default=None, ge=0)
    relative_tolerance: Decimal | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def require_tolerance(self) -> "ReferenceEstimate":
        if self.absolute_tolerance is None and self.relative_tolerance is None:
            raise ValueError(
                "Reference estimates require an explicit absolute_tolerance or relative_tolerance"
            )
        return self


class MutuallyExclusiveGroupSet(StrictModel):
    set_id: str = Field(min_length=1)
    estimate_alias: str
    categories: list[dict[str, Any]] = Field(min_length=2)
    require_all_categories: bool = True


class ResultCriticConfig(StrictModel):
    max_reexecutions: int = Field(default=1, ge=0, le=3)
    numeric_tolerance: Decimal = Field(default=Decimal("0.000001"), ge=0)
    expected_groups: list[ExpectedResultGroup] = Field(default_factory=list)
    mutually_exclusive_group_sets: list[MutuallyExclusiveGroupSet] = Field(
        default_factory=list
    )
    reference_estimates: list[ReferenceEstimate] = Field(default_factory=list)
    reject_null_group_values: bool = True


class AgentWorkflowRequest(StrictModel):
    """Public graph input. Arbitrary SQL is intentionally not representable."""

    question: str = Field(min_length=3)
    context: dict[str, Any] = Field(default_factory=dict)
    approval_mode: ApprovalMode = "interrupt"
    max_plan_attempts: int = Field(default=3, ge=1, le=10)
    result_critic: ResultCriticConfig = Field(default_factory=ResultCriticConfig)


class PlanProposalRequest(StrictModel):
    question: str
    attempt: int = Field(ge=1)
    max_attempts: int = Field(ge=1)
    semantic_context: dict[str, Any]
    user_context: dict[str, Any] = Field(default_factory=dict)
    previous_plan: dict[str, Any] | None = None
    validation_issues: list[PlanValidationIssue] = Field(default_factory=list)
    human_feedback: str | None = None


class ApprovalDecision(StrictModel):
    decision: ApprovalAction
    feedback: str | None = None

    @model_validator(mode="after")
    def require_revision_feedback(self) -> "ApprovalDecision":
        if self.decision == "revise" and not (self.feedback or "").strip():
            raise ValueError("A revise decision requires feedback")
        return self


class ApprovalRequest(StrictModel):
    request_type: Literal["analysis_plan_approval"] = "analysis_plan_approval"
    question: str
    attempt: int
    plan: AnalysisPlan
    plan_fingerprint: str
    validation_messages: list[str]
    allowed_decisions: list[ApprovalAction] = Field(
        default_factory=lambda: ["approved", "rejected", "revise"]
    )


class WorkflowPause(StrictModel):
    status: Literal["awaiting_approval"] = "awaiting_approval"
    thread_id: str
    approval_request: ApprovalRequest


class WorkflowError(StrictModel):
    code: str
    node: str
    message: str
    retryable: bool = False


class WorkflowEvent(StrictModel):
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    level: Literal["INFO", "WARNING", "ERROR"] = "INFO"
    node: str
    event: str
    message: str
    attempt: int = 0
    details: dict[str, Any] = Field(default_factory=dict)


class ResultCheck(StrictModel):
    check_id: str
    passed: bool
    message: str


class ResultCheckReport(StrictModel):
    passed: bool
    checks: list[ResultCheck]


class ResultCriticCheck(StrictModel):
    check_id: str
    status: CriticCheckStatus
    message: str
    retryable: bool = False
    details: dict[str, Any] = Field(default_factory=dict)


class ResultCriticReport(StrictModel):
    decision: ResultCriticDecision
    checks: list[ResultCriticCheck]
    failed_check_ids: list[str] = Field(default_factory=list)
    reexecution_count: int = Field(ge=0)
    max_reexecutions: int = Field(ge=0)
    numeric_results_unchanged: Literal[True] = True


class AgentWorkflowResult(StrictModel):
    status: Literal["completed", "failed", "rejected"]
    question: str
    attempts: int
    plan: AnalysisPlan | None = None
    validated_plan: ValidatedAnalysisPlan | None = None
    approval: ApprovalDecision | None = None
    compiled: CompiledSurveyEstimate | None = None
    execution: AnalysisPlanExecutionResult | None = None
    result_checks: ResultCheckReport | None = None
    result_critique: ResultCriticReport | None = None
    request_guard: RequestGuardDecision | None = None
    error: WorkflowError | None = None
    audit_log: list[WorkflowEvent] = Field(default_factory=list)
