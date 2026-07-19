from __future__ import annotations

import logging
import operator
from typing import Annotated, Any, Literal
from uuid import uuid4

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt
from typing_extensions import TypedDict

from ahs_copilot.analysis_plan import AnalysisPlanService, AnalysisPlanValidationError
from ahs_copilot.analysis_plan.models import AnalysisPlan, ValidatedAnalysisPlan
from ahs_copilot.survey_estimation.models import CompiledSurveyEstimate

from .models import (
    AgentWorkflowRequest,
    AgentWorkflowResult,
    ApprovalDecision,
    ApprovalRequest,
    PlanProposalRequest,
    ResultCriticConfig,
    ResultCriticReport,
    ResultCheckReport,
    WorkflowError,
    WorkflowEvent,
    WorkflowPause,
)
from .planner import AnalysisPlanModel, build_semantic_planning_context
from .result_critic import AnalysisResultCritic
from .result_checks import AnalysisResultChecker

logger = logging.getLogger(__name__)


class AHSAgentState(TypedDict, total=False):
    """JSON-serializable shared graph state suitable for durable checkpointers."""

    question: str
    user_context: dict[str, Any]
    semantic_context: dict[str, Any]
    approval_mode: Literal["interrupt", "auto_approve"]
    max_plan_attempts: int
    result_critic_config: dict[str, Any]
    result_reexecution_count: int
    attempt: int
    proposed_plan: dict[str, Any] | None
    validated_plan: dict[str, Any] | None
    validation_issues: list[dict[str, Any]]
    human_feedback: str | None
    approval: dict[str, Any] | None
    compiled: dict[str, Any] | None
    execution: dict[str, Any] | None
    result_checks: dict[str, Any] | None
    result_critique: dict[str, Any] | None
    error: dict[str, Any] | None
    status: str
    audit_log: Annotated[list[dict[str, Any]], operator.add]


class _Nodes:
    def __init__(
        self,
        model: AnalysisPlanModel,
        service: AnalysisPlanService,
        result_checker: AnalysisResultChecker,
        result_critic: AnalysisResultCritic,
    ) -> None:
        self.model = model
        self.service = service
        self.result_checker = result_checker
        self.result_critic = result_critic

    @staticmethod
    def _event(
        node: str,
        event: str,
        message: str,
        *,
        attempt: int = 0,
        level: Literal["INFO", "WARNING", "ERROR"] = "INFO",
        details: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        log_fn = (
            logger.error
            if level == "ERROR"
            else logger.warning
            if level == "WARNING"
            else logger.info
        )
        log_fn("node=%s event=%s attempt=%s message=%s", node, event, attempt, message)
        return WorkflowEvent(
            node=node,
            event=event,
            message=message,
            attempt=attempt,
            level=level,
            details=details or {},
        ).model_dump(mode="json")

    @staticmethod
    def _error(
        code: str,
        node: str,
        message: str,
        *,
        retryable: bool = False,
    ) -> dict[str, Any]:
        return WorkflowError(
            code=code,
            node=node,
            message=message,
            retryable=retryable,
        ).model_dump(mode="json")

    def propose_plan(self, state: AHSAgentState) -> dict[str, Any]:
        attempt = state.get("attempt", 0) + 1
        request = PlanProposalRequest(
            question=state["question"],
            attempt=attempt,
            max_attempts=state["max_plan_attempts"],
            semantic_context=state["semantic_context"],
            user_context=state.get("user_context", {}),
            previous_plan=state.get("proposed_plan"),
            validation_issues=state.get("validation_issues", []),
            human_feedback=state.get("human_feedback"),
        )
        try:
            plan = self.model.propose(request)
            return {
                "attempt": attempt,
                "proposed_plan": plan.model_dump(mode="json"),
                "validated_plan": None,
                "validation_issues": [],
                "approval": None,
                "compiled": None,
                "execution": None,
                "result_checks": None,
                "result_critique": None,
                "error": None,
                "status": "planning",
                "audit_log": [
                    self._event(
                        "propose_plan",
                        "PLAN_PROPOSED",
                        "The model returned a typed AnalysisPlan.",
                        attempt=attempt,
                    )
                ],
            }
        except Exception as exc:
            retryable = attempt < state["max_plan_attempts"]
            return {
                "attempt": attempt,
                "proposed_plan": None,
                "validated_plan": None,
                "error": self._error(
                    "MODEL_PLAN_PROPOSAL_FAILED",
                    "propose_plan",
                    str(exc),
                    retryable=retryable,
                ),
                "status": "planning",
                "audit_log": [
                    self._event(
                        "propose_plan",
                        "PLAN_PROPOSAL_FAILED",
                        str(exc),
                        attempt=attempt,
                        level="WARNING" if retryable else "ERROR",
                    )
                ],
            }

    @staticmethod
    def route_after_proposal(state: AHSAgentState) -> str:
        if state.get("proposed_plan") is not None and state.get("error") is None:
            return "validate_plan"
        if state.get("attempt", 0) < state["max_plan_attempts"]:
            return "propose_plan"
        return "fail"

    def validate_plan(self, state: AHSAgentState) -> dict[str, Any]:
        attempt = state.get("attempt", 0)
        payload = state.get("proposed_plan")
        if payload is None:
            return {
                "error": self._error(
                    "MISSING_PROPOSED_PLAN",
                    "validate_plan",
                    "No proposed AnalysisPlan was available for validation.",
                ),
                "audit_log": [
                    self._event(
                        "validate_plan",
                        "MISSING_PLAN",
                        "No proposed plan was available.",
                        attempt=attempt,
                        level="ERROR",
                    )
                ],
            }
        try:
            validated = self.service.validate(AnalysisPlan.model_validate(payload))
            return {
                "validated_plan": validated.model_dump(mode="json"),
                "validation_issues": [],
                "error": None,
                "audit_log": [
                    self._event(
                        "validate_plan",
                        "PLAN_VALIDATED",
                        "Deterministic AnalysisPlan validation passed.",
                        attempt=attempt,
                        details={"plan_fingerprint": validated.plan_fingerprint},
                    )
                ],
            }
        except AnalysisPlanValidationError as exc:
            retryable = attempt < state["max_plan_attempts"]
            return {
                "validated_plan": None,
                "validation_issues": [item.model_dump(mode="json") for item in exc.issues],
                "error": self._error(
                    "PLAN_VALIDATION_FAILED",
                    "validate_plan",
                    str(exc),
                    retryable=retryable,
                ),
                "audit_log": [
                    self._event(
                        "validate_plan",
                        "PLAN_VALIDATION_FAILED",
                        str(exc),
                        attempt=attempt,
                        level="WARNING" if retryable else "ERROR",
                        details={"issue_codes": [item.code for item in exc.issues]},
                    )
                ],
            }

    @staticmethod
    def route_after_validation(state: AHSAgentState) -> str:
        if state.get("validated_plan") is not None:
            return "approval_gate"
        if state.get("attempt", 0) < state["max_plan_attempts"]:
            return "propose_plan"
        return "fail"

    def approval_gate(self, state: AHSAgentState) -> dict[str, Any]:
        payload = state.get("validated_plan")
        if payload is None:
            return {
                "error": self._error(
                    "MISSING_VALIDATED_PLAN",
                    "approval_gate",
                    "Approval was requested without a validated plan.",
                ),
                "audit_log": [
                    self._event(
                        "approval_gate",
                        "MISSING_VALIDATED_PLAN",
                        "Approval was requested without a validated plan.",
                        attempt=state.get("attempt", 0),
                        level="ERROR",
                    )
                ],
            }
        validated = ValidatedAnalysisPlan.model_validate(payload)
        request = ApprovalRequest(
            question=state["question"],
            attempt=state.get("attempt", 0),
            plan=validated.plan,
            plan_fingerprint=validated.plan_fingerprint,
            validation_messages=validated.validation_messages,
        )
        if state["approval_mode"] == "auto_approve":
            decision = ApprovalDecision(decision="approved")
        else:
            raw_decision = interrupt(request.model_dump(mode="json"))
            decision = ApprovalDecision.model_validate(raw_decision)
        return {
            "approval": decision.model_dump(mode="json"),
            "human_feedback": decision.feedback,
            "status": "awaiting_approval",
            "audit_log": [
                self._event(
                    "approval_gate",
                    f"PLAN_{decision.decision.upper()}",
                    f"Human approval decision: {decision.decision}.",
                    attempt=state.get("attempt", 0),
                    level="WARNING" if decision.decision != "approved" else "INFO",
                )
            ],
        }

    @staticmethod
    def route_after_approval(state: AHSAgentState) -> str:
        payload = state.get("approval")
        if payload is None:
            return "fail"
        decision = ApprovalDecision.model_validate(payload)
        if decision.decision == "approved":
            return "compile_plan"
        if decision.decision == "revise":
            if state.get("attempt", 0) < state["max_plan_attempts"]:
                return "propose_plan"
            return "fail"
        return "reject"

    def compile_plan(self, state: AHSAgentState) -> dict[str, Any]:
        payload = state.get("validated_plan")
        if payload is None:
            return {
                "error": self._error(
                    "MISSING_VALIDATED_PLAN",
                    "compile_plan",
                    "Compilation requires a validated AnalysisPlan.",
                ),
                "audit_log": [
                    self._event(
                        "compile_plan",
                        "COMPILATION_BLOCKED",
                        "Compilation requires a validated plan.",
                        attempt=state.get("attempt", 0),
                        level="ERROR",
                    )
                ],
            }
        try:
            validated = ValidatedAnalysisPlan.model_validate(payload)
            compiled = self.service.compile_validated(validated)
            return {
                "compiled": compiled.model_dump(mode="json"),
                "error": None,
                "audit_log": [
                    self._event(
                        "compile_plan",
                        "PLAN_COMPILED",
                        "Deterministic survey SQL compilation completed.",
                        attempt=state.get("attempt", 0),
                        details={"request_fingerprint": compiled.request_fingerprint},
                    )
                ],
            }
        except Exception as exc:
            return {
                "compiled": None,
                "error": self._error(
                    "DETERMINISTIC_COMPILATION_FAILED",
                    "compile_plan",
                    str(exc),
                ),
                "audit_log": [
                    self._event(
                        "compile_plan",
                        "COMPILATION_FAILED",
                        str(exc),
                        attempt=state.get("attempt", 0),
                        level="ERROR",
                    )
                ],
            }

    @staticmethod
    def route_after_compile(state: AHSAgentState) -> str:
        return "execute_plan" if state.get("compiled") is not None else "fail"

    def execute_plan(self, state: AHSAgentState) -> dict[str, Any]:
        payload = state.get("validated_plan")
        if payload is None:
            return {
                "error": self._error(
                    "MISSING_VALIDATED_PLAN",
                    "execute_plan",
                    "Execution requires a validated AnalysisPlan.",
                )
            }
        try:
            validated = ValidatedAnalysisPlan.model_validate(payload)
            execution = self.service.execute_validated(validated)
            return {
                "execution": execution.model_dump(mode="json"),
                "result_checks": None,
                "result_critique": None,
                "error": None,
                "audit_log": [
                    self._event(
                        "execute_plan",
                        "PLAN_EXECUTED",
                        "Deterministic survey execution completed.",
                        attempt=state.get("attempt", 0),
                        details={"run_id": execution.result.metadata.run_id},
                    )
                ],
            }
        except Exception as exc:
            return {
                "execution": None,
                "error": self._error(
                    "DETERMINISTIC_EXECUTION_FAILED",
                    "execute_plan",
                    str(exc),
                ),
                "audit_log": [
                    self._event(
                        "execute_plan",
                        "EXECUTION_FAILED",
                        str(exc),
                        attempt=state.get("attempt", 0),
                        level="ERROR",
                    )
                ],
            }

    @staticmethod
    def route_after_execute(state: AHSAgentState) -> str:
        return "check_result" if state.get("execution") is not None else "fail"

    def check_result(self, state: AHSAgentState) -> dict[str, Any]:
        validated_payload = state.get("validated_plan")
        compiled_payload = state.get("compiled")
        execution_payload = state.get("execution")
        if validated_payload is None or compiled_payload is None or execution_payload is None:
            return {
                "error": self._error(
                    "INCOMPLETE_DETERMINISTIC_OUTPUT",
                    "check_result",
                    "Result checks require validated, compiled, and executed artifacts.",
                )
            }
        from ahs_copilot.analysis_plan.models import AnalysisPlanExecutionResult

        validated = ValidatedAnalysisPlan.model_validate(validated_payload)
        compiled = CompiledSurveyEstimate.model_validate(compiled_payload)
        execution = AnalysisPlanExecutionResult.model_validate(execution_payload)
        report = self.result_checker.check(validated, compiled, execution)
        return {
            "result_checks": report.model_dump(mode="json"),
            "error": (
                None
                if report.passed
                else self._error(
                    "RESULT_INTEGRITY_CHECK_FAILED",
                    "check_result",
                    "One or more deterministic result checks failed.",
                )
            ),
            "audit_log": [
                self._event(
                    "check_result",
                    "RESULT_CHECKS_PASSED" if report.passed else "RESULT_CHECKS_FAILED",
                    "Deterministic result integrity checks completed.",
                    attempt=state.get("attempt", 0),
                    level="INFO" if report.passed else "ERROR",
                    details={
                        "failed_checks": [item.check_id for item in report.checks if not item.passed]
                    },
                )
            ],
        }

    @staticmethod
    def route_after_result_check(state: AHSAgentState) -> str:
        payload = state.get("result_checks")
        if payload is None:
            return "fail"
        return "critique_result" if ResultCheckReport.model_validate(payload).passed else "fail"

    def critique_result(self, state: AHSAgentState) -> dict[str, Any]:
        validated_payload = state.get("validated_plan")
        compiled_payload = state.get("compiled")
        execution_payload = state.get("execution")
        if validated_payload is None or compiled_payload is None or execution_payload is None:
            return {
                "error": self._error(
                    "INCOMPLETE_RESULT_CRITIC_INPUT",
                    "critique_result",
                    "Result criticism requires validated, compiled, and executed artifacts.",
                ),
                "audit_log": [
                    self._event(
                        "critique_result",
                        "RESULT_CRITIC_INPUT_MISSING",
                        "Result critic inputs were incomplete.",
                        attempt=state.get("attempt", 0),
                        level="ERROR",
                    )
                ],
            }

        from ahs_copilot.analysis_plan.models import AnalysisPlanExecutionResult

        validated = ValidatedAnalysisPlan.model_validate(validated_payload)
        compiled = CompiledSurveyEstimate.model_validate(compiled_payload)
        execution = AnalysisPlanExecutionResult.model_validate(execution_payload)
        config = ResultCriticConfig.model_validate(state.get("result_critic_config", {}))
        reexecution_count = int(state.get("result_reexecution_count", 0))
        report = self.result_critic.critique(
            validated,
            compiled,
            execution,
            config,
            reexecution_count=reexecution_count,
        )
        update: dict[str, Any] = {
            "result_critique": report.model_dump(mode="json"),
            "error": None,
            "audit_log": [
                self._event(
                    "critique_result",
                    f"RESULT_CRITIC_{report.decision.upper()}",
                    "Deterministic result criticism completed without altering numeric results.",
                    attempt=state.get("attempt", 0),
                    level="INFO" if report.decision == "approve" else "WARNING",
                    details={
                        "decision": report.decision,
                        "failed_checks": report.failed_check_ids,
                        "reexecution_count": reexecution_count,
                        "max_reexecutions": config.max_reexecutions,
                    },
                )
            ],
        }
        if report.decision == "request_reexecution":
            update["result_reexecution_count"] = reexecution_count + 1
        elif report.decision == "reject":
            update["error"] = self._error(
                "RESULT_CRITIC_REJECTED",
                "critique_result",
                "The deterministic result critic rejected the result after plan-consistency checks.",
            )
        return update

    @staticmethod
    def route_after_result_critic(state: AHSAgentState) -> str:
        payload = state.get("result_critique")
        if payload is None:
            return "fail"
        decision = ResultCriticReport.model_validate(payload).decision
        if decision == "approve":
            return "complete"
        if decision == "request_reexecution":
            return "execute_plan"
        return "critic_reject"

    def complete(self, state: AHSAgentState) -> dict[str, Any]:
        return {
            "status": "completed",
            "audit_log": [
                self._event(
                    "complete",
                    "WORKFLOW_COMPLETED",
                    "AHS agent workflow completed successfully.",
                    attempt=state.get("attempt", 0),
                )
            ],
        }

    def reject(self, state: AHSAgentState) -> dict[str, Any]:
        return {
            "status": "rejected",
            "error": None,
            "audit_log": [
                self._event(
                    "reject",
                    "WORKFLOW_REJECTED",
                    "The validated AnalysisPlan was rejected by the approver.",
                    attempt=state.get("attempt", 0),
                    level="WARNING",
                )
            ],
        }

    def critic_reject(self, state: AHSAgentState) -> dict[str, Any]:
        failed_checks = (
            ResultCriticReport.model_validate(state["result_critique"]).failed_check_ids
            if state.get("result_critique")
            else []
        )
        return {
            "status": "failed",
            "audit_log": [
                self._event(
                    "critic_reject",
                    "WORKFLOW_RESULT_REJECTED",
                    "The result critic rejected the deterministic result; numeric results were not altered.",
                    attempt=state.get("attempt", 0),
                    level="ERROR",
                    details={"failed_checks": failed_checks},
                )
            ],
        }

    def fail(self, state: AHSAgentState) -> dict[str, Any]:
        error = state.get("error") or self._error(
            "WORKFLOW_FAILED",
            "fail",
            "The workflow terminated without a successful deterministic result.",
        )
        parsed = WorkflowError.model_validate(error)
        return {
            "status": "failed",
            "error": error,
            "audit_log": [
                self._event(
                    "fail",
                    "WORKFLOW_FAILED",
                    parsed.message,
                    attempt=state.get("attempt", 0),
                    level="ERROR",
                    details={"code": parsed.code, "node": parsed.node},
                )
            ],
        }


def build_ahs_agent_graph(
    model: AnalysisPlanModel,
    service: AnalysisPlanService,
    *,
    result_checker: AnalysisResultChecker | None = None,
    result_critic: AnalysisResultCritic | None = None,
    checkpointer: Any | None = None,
):
    nodes = _Nodes(
        model,
        service,
        result_checker or AnalysisResultChecker(),
        result_critic or AnalysisResultCritic(),
    )
    builder = StateGraph(AHSAgentState)
    builder.add_node("propose_plan", nodes.propose_plan)
    builder.add_node("validate_plan", nodes.validate_plan)
    builder.add_node("approval_gate", nodes.approval_gate)
    builder.add_node("compile_plan", nodes.compile_plan)
    builder.add_node("execute_plan", nodes.execute_plan)
    builder.add_node("check_result", nodes.check_result)
    builder.add_node("critique_result", nodes.critique_result)
    builder.add_node("complete", nodes.complete)
    builder.add_node("reject", nodes.reject)
    builder.add_node("critic_reject", nodes.critic_reject)
    builder.add_node("fail", nodes.fail)

    builder.add_edge(START, "propose_plan")
    builder.add_conditional_edges(
        "propose_plan",
        nodes.route_after_proposal,
        {
            "propose_plan": "propose_plan",
            "validate_plan": "validate_plan",
            "fail": "fail",
        },
    )
    builder.add_conditional_edges(
        "validate_plan",
        nodes.route_after_validation,
        {
            "propose_plan": "propose_plan",
            "approval_gate": "approval_gate",
            "fail": "fail",
        },
    )
    builder.add_conditional_edges(
        "approval_gate",
        nodes.route_after_approval,
        {
            "propose_plan": "propose_plan",
            "compile_plan": "compile_plan",
            "reject": "reject",
            "fail": "fail",
        },
    )
    builder.add_conditional_edges(
        "compile_plan",
        nodes.route_after_compile,
        {"execute_plan": "execute_plan", "fail": "fail"},
    )
    builder.add_conditional_edges(
        "execute_plan",
        nodes.route_after_execute,
        {"check_result": "check_result", "fail": "fail"},
    )
    builder.add_conditional_edges(
        "check_result",
        nodes.route_after_result_check,
        {"critique_result": "critique_result", "fail": "fail"},
    )
    builder.add_conditional_edges(
        "critique_result",
        nodes.route_after_result_critic,
        {
            "complete": "complete",
            "execute_plan": "execute_plan",
            "critic_reject": "critic_reject",
            "fail": "fail",
        },
    )
    builder.add_edge("complete", END)
    builder.add_edge("reject", END)
    builder.add_edge("critic_reject", END)
    builder.add_edge("fail", END)
    return builder.compile(checkpointer=checkpointer)


class AHSAgentWorkflow:
    """Typed LangGraph facade with resumable human approval."""

    def __init__(
        self,
        model: AnalysisPlanModel,
        service: AnalysisPlanService,
        *,
        result_checker: AnalysisResultChecker | None = None,
        result_critic: AnalysisResultCritic | None = None,
        checkpointer: Any | None = None,
    ) -> None:
        self.service = service
        self.checkpointer = checkpointer or InMemorySaver()
        self.graph = build_ahs_agent_graph(
            model,
            service,
            result_checker=result_checker,
            result_critic=result_critic,
            checkpointer=self.checkpointer,
        )
        self.semantic_context = build_semantic_planning_context(service)

    @staticmethod
    def _config(
        thread_id: str,
        max_attempts: int,
        max_result_reexecutions: int = 1,
    ) -> dict[str, Any]:
        return {
            "configurable": {"thread_id": thread_id},
            "recursion_limit": max(
                30,
                max_attempts * 8 + max_result_reexecutions * 4 + 10,
            ),
        }

    @staticmethod
    def _final_result(state: dict[str, Any]) -> AgentWorkflowResult:
        status = state.get("status")
        if status not in {"completed", "failed", "rejected"}:
            raise ValueError(f"Workflow is not final: status={status!r}")
        return AgentWorkflowResult.model_validate(
            {
                "status": status,
                "question": state["question"],
                "attempts": state.get("attempt", 0),
                "plan": state.get("proposed_plan"),
                "validated_plan": state.get("validated_plan"),
                "approval": state.get("approval"),
                "compiled": state.get("compiled"),
                "execution": state.get("execution"),
                "result_checks": state.get("result_checks"),
                "result_critique": state.get("result_critique"),
                "error": state.get("error"),
                "audit_log": state.get("audit_log", []),
            }
        )

    @staticmethod
    def _pause(state: dict[str, Any], thread_id: str) -> WorkflowPause:
        interrupts = state.get("__interrupt__", [])
        if not interrupts:
            raise ValueError("No interrupt payload was returned")
        value = getattr(interrupts[0], "value", interrupts[0])
        return WorkflowPause(
            thread_id=thread_id,
            approval_request=ApprovalRequest.model_validate(value),
        )

    def invoke(
        self,
        request: AgentWorkflowRequest | dict[str, Any],
        *,
        thread_id: str | None = None,
    ) -> AgentWorkflowResult | WorkflowPause:
        parsed = (
            request
            if isinstance(request, AgentWorkflowRequest)
            else AgentWorkflowRequest.model_validate(request)
        )
        resolved_thread_id = thread_id or str(uuid4())
        initial: AHSAgentState = {
            "question": parsed.question,
            "user_context": parsed.context,
            "semantic_context": self.semantic_context,
            "approval_mode": parsed.approval_mode,
            "max_plan_attempts": parsed.max_plan_attempts,
            "result_critic_config": parsed.result_critic.model_dump(mode="json"),
            "result_reexecution_count": 0,
            "attempt": 0,
            "proposed_plan": None,
            "validated_plan": None,
            "validation_issues": [],
            "human_feedback": None,
            "approval": None,
            "compiled": None,
            "execution": None,
            "result_checks": None,
            "result_critique": None,
            "error": None,
            "status": "planning",
            "audit_log": [],
        }
        state = self.graph.invoke(
            initial,
            config=self._config(
                resolved_thread_id,
                parsed.max_plan_attempts,
                parsed.result_critic.max_reexecutions,
            ),
        )
        if state.get("__interrupt__"):
            return self._pause(state, resolved_thread_id)
        return self._final_result(state)

    def resume(
        self,
        thread_id: str,
        decision: ApprovalDecision | dict[str, Any],
    ) -> AgentWorkflowResult | WorkflowPause:
        parsed = (
            decision
            if isinstance(decision, ApprovalDecision)
            else ApprovalDecision.model_validate(decision)
        )
        base_config = {"configurable": {"thread_id": thread_id}}
        snapshot = self.graph.get_state(base_config)
        max_attempts = int(snapshot.values.get("max_plan_attempts", 3))
        critic_config = ResultCriticConfig.model_validate(
            snapshot.values.get("result_critic_config", {})
        )
        state = self.graph.invoke(
            Command(resume=parsed.model_dump(mode="json")),
            config=self._config(
                thread_id,
                max_attempts,
                critic_config.max_reexecutions,
            ),
        )
        if state.get("__interrupt__"):
            return self._pause(state, thread_id)
        return self._final_result(state)
