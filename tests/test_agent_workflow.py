from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError

from ahs_copilot.agent_workflow import (
    AHSAgentWorkflow,
    AgentWorkflowRequest,
    AgentWorkflowResult,
    AnalysisResultCritic,
    AnalysisResultChecker,
    ExpectedResultGroup,
    LangChainStructuredPlanModel,
    MockAnalysisPlanModel,
    MutuallyExclusiveGroupSet,
    PlanProposalRequest,
    ReferenceEstimate,
    ResultCriticConfig,
    WorkflowPause,
)
from ahs_copilot.analysis_plan import (
    AnalysisPlan,
    AnalysisPlanService,
    DenominatorSpec,
    MeasureSpec,
    NumeratorSpec,
    UniverseSpec,
    WeightSpec,
)
from ahs_copilot.query_engine import QualifiedColumn, TypedFilter


def qcol(column: str) -> QualifiedColumn:
    return QualifiedColumn(dataset="household", column=column)


def occupied_count_plan(*, extra_required: list[QualifiedColumn] | None = None) -> AnalysisPlan:
    required = [qcol("INTSTATUS"), qcol("WEIGHT")]
    if extra_required:
        required.extend(extra_required)
    return AnalysisPlan(
        user_question="Count occupied housing units",
        dataset="household",
        measure=MeasureSpec(alias="units", statistic="count"),
        numerator=NumeratorSpec(
            role="eligible_units", description="All units in the approved universe"
        ),
        denominator=DenominatorSpec(
            role="eligible_units", description="All units in the approved universe"
        ),
        universe=UniverseSpec(
            universe_id="occupied_housing_units", description="Occupied housing units"
        ),
        weight=WeightSpec(mode="weighted", column=qcol("WEIGHT")),
        required_variables=required,
    )


def high_burden_percentage_plan(*, grouped: bool = False) -> AnalysisPlan:
    grouping = [qcol("TENURE")] if grouped else []
    required = [qcol("INTSTATUS"), qcol("TOTHCPCT"), qcol("WEIGHT")]
    if grouped:
        required.append(qcol("TENURE"))
    return AnalysisPlan(
        user_question="What share of occupied housing units has high cost burden?",
        dataset="household",
        measure=MeasureSpec(alias="high_burden_pct", statistic="percentage"),
        numerator=NumeratorSpec(
            role="condition_true",
            description="Housing cost burden at or above 50 percent",
            filters=[
                TypedFilter(column=qcol("TOTHCPCT"), operator="ge", value=50)
            ],
        ),
        denominator=DenominatorSpec(
            role="eligible_units",
            description="Occupied units with nonmissing housing cost burden",
        ),
        universe=UniverseSpec(
            universe_id="occupied_housing_units", description="Occupied housing units"
        ),
        weight=WeightSpec(mode="weighted", column=qcol("WEIGHT")),
        required_variables=required,
        grouping_dimensions=grouping,
    )


def test_auto_approved_workflow_completes_with_deterministic_outputs(engine) -> None:
    model = MockAnalysisPlanModel([occupied_count_plan()])
    workflow = AHSAgentWorkflow(model, AnalysisPlanService(engine))

    output = workflow.invoke(
        AgentWorkflowRequest(
            question="How many occupied housing units are represented?",
            approval_mode="auto_approve",
        )
    )

    assert isinstance(output, AgentWorkflowResult)
    assert output.status == "completed"
    assert output.attempts == 1
    assert output.execution is not None
    assert output.execution.result.estimates[0].estimate == Decimal("75.000000")
    assert output.compiled is not None
    assert output.result_checks is not None and output.result_checks.passed is True
    assert output.compiled.sql == output.execution.result.parameterized_sql
    assert [event.event for event in output.audit_log][-1] == "WORKFLOW_COMPLETED"
    assert len(model.calls) == 1


def test_validation_feedback_drives_bounded_plan_repair(engine) -> None:
    invalid = occupied_count_plan(extra_required=[qcol("NOT_A_VARIABLE")])
    valid = occupied_count_plan()
    model = MockAnalysisPlanModel([invalid, valid])
    workflow = AHSAgentWorkflow(model, AnalysisPlanService(engine))

    output = workflow.invoke(
        {
            "question": "Count occupied housing units",
            "approval_mode": "auto_approve",
            "max_plan_attempts": 2,
        }
    )

    assert isinstance(output, AgentWorkflowResult)
    assert output.status == "completed"
    assert output.attempts == 2
    assert len(model.calls) == 2
    assert {item.code for item in model.calls[1].validation_issues} == {"UNKNOWN_VARIABLE"}
    events = [event.event for event in output.audit_log]
    assert "PLAN_VALIDATION_FAILED" in events
    assert "PLAN_VALIDATED" in events


def test_retry_limit_stops_invalid_structured_model_output(engine) -> None:
    invalid_payload = occupied_count_plan().model_dump(mode="json")
    invalid_payload["sql"] = "SELECT * FROM household"
    model = MockAnalysisPlanModel([invalid_payload], repeat_last=True)
    workflow = AHSAgentWorkflow(model, AnalysisPlanService(engine))

    output = workflow.invoke(
        {
            "question": "Count occupied housing units",
            "approval_mode": "auto_approve",
            "max_plan_attempts": 2,
        }
    )

    assert isinstance(output, AgentWorkflowResult)
    assert output.status == "failed"
    assert output.attempts == 2
    assert output.error is not None
    assert output.error.code == "MODEL_PLAN_PROPOSAL_FAILED"
    assert output.compiled is None
    assert output.execution is None
    assert len(model.calls) == 2


def test_interrupt_approval_resumes_same_thread(engine) -> None:
    model = MockAnalysisPlanModel([occupied_count_plan()])
    workflow = AHSAgentWorkflow(model, AnalysisPlanService(engine))

    paused = workflow.invoke(
        {
            "question": "Count occupied housing units",
            "approval_mode": "interrupt",
        },
        thread_id="approval-thread",
    )

    assert isinstance(paused, WorkflowPause)
    assert paused.approval_request.plan.measure.alias == "units"
    assert paused.approval_request.allowed_decisions == ["approved", "rejected", "revise"]

    output = workflow.resume("approval-thread", {"decision": "approved"})
    assert isinstance(output, AgentWorkflowResult)
    assert output.status == "completed"
    assert output.approval is not None and output.approval.decision == "approved"
    assert len(model.calls) == 1


def test_human_rejection_prevents_compile_and_execution(engine) -> None:
    workflow = AHSAgentWorkflow(
        MockAnalysisPlanModel([occupied_count_plan()]),
        AnalysisPlanService(engine),
    )
    paused = workflow.invoke(
        {"question": "Count occupied housing units", "approval_mode": "interrupt"},
        thread_id="reject-thread",
    )
    assert isinstance(paused, WorkflowPause)

    output = workflow.resume(
        "reject-thread",
        {"decision": "rejected", "feedback": "Use a different universe."},
    )
    assert isinstance(output, AgentWorkflowResult)
    assert output.status == "rejected"
    assert output.compiled is None
    assert output.execution is None
    assert output.error is None


def test_human_revision_loops_to_model_with_feedback(engine) -> None:
    model = MockAnalysisPlanModel([occupied_count_plan(), occupied_count_plan()])
    workflow = AHSAgentWorkflow(model, AnalysisPlanService(engine))

    first_pause = workflow.invoke(
        {"question": "Count occupied housing units", "approval_mode": "interrupt"},
        thread_id="revise-thread",
    )
    assert isinstance(first_pause, WorkflowPause)

    second_pause = workflow.resume(
        "revise-thread",
        {"decision": "revise", "feedback": "Recheck the required-variable closure."},
    )
    assert isinstance(second_pause, WorkflowPause)
    assert len(model.calls) == 2
    assert model.calls[1].human_feedback == "Recheck the required-variable closure."

    output = workflow.resume("revise-thread", {"decision": "approved"})
    assert isinstance(output, AgentWorkflowResult)
    assert output.status == "completed"
    assert output.attempts == 2


def test_semantic_context_preserves_projects_control_invariant(engine) -> None:
    workflow = AHSAgentWorkflow(
        MockAnalysisPlanModel([occupied_count_plan()]),
        AnalysisPlanService(engine),
    )

    project_relationships = [
        item
        for item in workflow.semantic_context["relationships"]
        if item["child_relation"] == "projects"
    ]
    assert len(project_relationships) == 1
    assert project_relationships[0]["keys"] == ["CONTROL"]
    constraints = " ".join(workflow.semantic_context["hard_constraints"])
    assert "CONTROL is the only required PUF projects relationship key" in constraints
    assert "preaggregated to one row per CONTROL" in constraints
    assert "PROJECTNO" not in {item["name"] for item in workflow.semantic_context["variables"]["projects"]}


def test_result_checker_detects_compiler_execution_mismatch(engine) -> None:
    service = AnalysisPlanService(engine)
    validated = service.validate(occupied_count_plan())
    compiled = service.compile_validated(validated)
    execution = service.execute_validated(validated)
    tampered = compiled.model_copy(update={"sql": compiled.sql + " -- tampered"})

    report = AnalysisResultChecker().check(validated, tampered, execution)

    assert report.passed is False
    failed = {item.check_id for item in report.checks if not item.passed}
    assert "PARAMETERIZED_SQL_MATCH" in failed


def test_workflow_input_rejects_arbitrary_sql() -> None:
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        AgentWorkflowRequest.model_validate(
            {
                "question": "Count occupied housing units",
                "approval_mode": "auto_approve",
                "sql": "SELECT * FROM household",
            }
        )


def test_langchain_adapter_binds_analysis_plan_structured_output() -> None:
    plan = occupied_count_plan()

    class FakeChatModel:
        def __init__(self) -> None:
            self.schema = None
            self.messages = None

        def with_structured_output(self, schema):
            self.schema = schema
            return self

        def invoke(self, messages):
            self.messages = messages
            return plan.model_dump(mode="json")

    fake = FakeChatModel()
    adapter = LangChainStructuredPlanModel(fake)
    output = adapter.propose(
        PlanProposalRequest(
            question="Count occupied housing units",
            attempt=1,
            max_attempts=3,
            semantic_context={"datasets": ["household"]},
        )
    )

    assert fake.schema is AnalysisPlan
    assert output == plan
    assert "Never produce SQL" in fake.messages[0].content
    assert "Return only the structured object" in fake.messages[1].content


def _critic_artifacts(engine, plan: AnalysisPlan):
    service = AnalysisPlanService(engine)
    validated = service.validate(plan)
    compiled = service.compile_validated(validated)
    execution = service.execute_validated(validated)
    return validated, compiled, execution


def _replace_estimate(execution, index: int, **changes):
    estimates = list(execution.result.estimates)
    estimates[index] = estimates[index].model_copy(update=changes)
    result = execution.result.model_copy(update={"estimates": estimates})
    return execution.model_copy(update={"result": result})


def test_result_critic_checks_denominator_consistency_and_percentage_range(engine) -> None:
    validated, compiled, execution = _critic_artifacts(
        engine, high_burden_percentage_plan()
    )
    original = execution.model_dump(mode="json")
    tampered = _replace_estimate(
        execution,
        0,
        estimate=Decimal("125.000000"),
        weighted_denominator=Decimal("1.000000"),
    )

    report = AnalysisResultCritic().critique(
        validated,
        compiled,
        tampered,
        ResultCriticConfig(max_reexecutions=1),
    )

    assert report.decision == "request_reexecution"
    assert "PERCENTAGE_RANGE[0]" in report.failed_check_ids
    assert "PERCENTAGE_WEIGHTED_NUMERATOR_WITHIN_DENOMINATOR[0]" in report.failed_check_ids
    assert "DENOMINATOR_FORMULA_CONSISTENT[0]" in report.failed_check_ids
    assert execution.model_dump(mode="json") == original
    assert report.numeric_results_unchanged is True


def test_result_critic_detects_missing_groups_and_unexpected_nulls(engine) -> None:
    validated, compiled, execution = _critic_artifacts(
        engine, high_burden_percentage_plan(grouped=True)
    )
    tampered = _replace_estimate(execution, 0, estimate=None)
    config = ResultCriticConfig(
        max_reexecutions=1,
        expected_groups=[
            ExpectedResultGroup(
                estimate_alias="high_burden_pct", group={"TENURE": 99}
            )
        ],
    )

    report = AnalysisResultCritic().critique(
        validated, compiled, tampered, config
    )

    assert report.decision == "request_reexecution"
    assert "EXPECTED_GROUPS_PRESENT" in report.failed_check_ids
    assert "NO_UNEXPECTED_NULL_NUMERIC_RESULTS" in report.failed_check_ids


def test_result_critic_rejects_nonexclusive_category_configuration(engine) -> None:
    validated, compiled, execution = _critic_artifacts(
        engine, high_burden_percentage_plan(grouped=True)
    )
    config = ResultCriticConfig(
        mutually_exclusive_group_sets=[
            MutuallyExclusiveGroupSet(
                set_id="tenure_partition",
                estimate_alias="high_burden_pct",
                categories=[{"TENURE": 1}, {"TENURE": 1, "BLD": 2}],
            )
        ]
    )

    report = AnalysisResultCritic().critique(
        validated, compiled, execution, config
    )

    assert report.decision == "reject"
    assert (
        "CATEGORY_SELECTORS_MUTUALLY_EXCLUSIVE[tenure_partition]"
        in report.failed_check_ids
    )


def test_result_critic_detects_reference_estimate_discrepancy(engine) -> None:
    validated, compiled, execution = _critic_artifacts(
        engine, high_burden_percentage_plan()
    )
    observed = execution.result.estimates[0].estimate
    assert observed is not None
    config = ResultCriticConfig(
        max_reexecutions=1,
        reference_estimates=[
            ReferenceEstimate(
                estimate_alias="high_burden_pct",
                expected=observed + Decimal("10"),
                absolute_tolerance=Decimal("0.1"),
                source_id="approved_table_spec_reference",
            )
        ],
    )

    report = AnalysisResultCritic().critique(
        validated, compiled, execution, config
    )

    assert report.decision == "request_reexecution"
    assert "REFERENCE_ESTIMATE_MATCH[0]" in report.failed_check_ids
    details = next(
        item.details
        for item in report.checks
        if item.check_id == "REFERENCE_ESTIMATE_MATCH[0]"
    )
    assert details["observed"] == str(observed)
    assert details["expected"] == str(observed + Decimal("10"))


def test_graph_reexecutes_same_validated_plan_when_critic_requests(engine) -> None:
    class OneBadExecutionService(AnalysisPlanService):
        def __init__(self, source_engine) -> None:
            super().__init__(source_engine)
            self.execute_calls = 0

        def execute_validated(self, validated):
            self.execute_calls += 1
            execution = super().execute_validated(validated)
            if self.execute_calls == 1:
                return _replace_estimate(execution, 0, estimate=None)
            return execution

    service = OneBadExecutionService(engine)
    workflow = AHSAgentWorkflow(
        MockAnalysisPlanModel([occupied_count_plan()]),
        service,
    )

    output = workflow.invoke(
        AgentWorkflowRequest(
            question="Count occupied housing units",
            approval_mode="auto_approve",
            result_critic=ResultCriticConfig(max_reexecutions=1),
        )
    )

    assert isinstance(output, AgentWorkflowResult)
    assert output.status == "completed"
    assert service.execute_calls == 2
    assert output.result_critique is not None
    assert output.result_critique.decision == "approve"
    events = [event.event for event in output.audit_log]
    assert "RESULT_CRITIC_REQUEST_REEXECUTION" in events
    assert events.count("PLAN_EXECUTED") == 2


def test_graph_rejects_result_when_critic_retry_budget_is_exhausted(engine) -> None:
    service = AnalysisPlanService(engine)
    validated = service.validate(occupied_count_plan())
    baseline = service.execute_validated(validated).result.estimates[0].estimate
    assert baseline is not None
    workflow = AHSAgentWorkflow(
        MockAnalysisPlanModel([occupied_count_plan()]),
        service,
    )

    output = workflow.invoke(
        AgentWorkflowRequest(
            question="Count occupied housing units",
            approval_mode="auto_approve",
            result_critic=ResultCriticConfig(
                max_reexecutions=0,
                reference_estimates=[
                    ReferenceEstimate(
                        estimate_alias="units",
                        expected=baseline + Decimal("1"),
                        absolute_tolerance=Decimal("0"),
                        source_id="approved_reference",
                    )
                ],
            ),
        )
    )

    assert isinstance(output, AgentWorkflowResult)
    assert output.status == "failed"
    assert output.error is not None
    assert output.error.code == "RESULT_CRITIC_REJECTED"
    assert output.result_critique is not None
    assert output.result_critique.decision == "reject"
    assert output.execution is not None
    assert output.execution.result.estimates[0].estimate == baseline
