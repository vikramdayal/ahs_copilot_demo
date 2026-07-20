from __future__ import annotations

from ahs_copilot.evaluation import CandidateResponse, CitationRecord, EvaluationCase, NumericExpectation, score_case


def _valid_plan() -> dict:
    return {
        "plan_version": "1.0",
        "user_question": "What share of renter households are severely cost burdened?",
        "dataset": "household",
        "measure": {"alias": "severe_burden_share", "statistic": "percentage"},
        "numerator": {
            "role": "condition_true",
            "description": "Renters with housing costs above 50 percent of income",
            "filters": [
                {
                    "column": {"dataset": "household", "column": "TOTHCPCT"},
                    "operator": "gt",
                    "value": 50,
                }
            ],
        },
        "denominator": {
            "role": "eligible_units",
            "description": "Renter-occupied homes with valid burden values",
            "filters": [],
        },
        "universe": {
            "universe_id": "renter_occupied_housing_units",
            "description": "Renter-occupied housing units",
        },
        "filters": [],
        "grouping_dimensions": [],
        "weight": {
            "mode": "weighted",
            "column": {"dataset": "household", "column": "WEIGHT"},
        },
        "required_variables": [
            {"dataset": "household", "column": "INTSTATUS"},
            {"dataset": "household", "column": "TENURE"},
            {"dataset": "household", "column": "TOTHCPCT"},
            {"dataset": "household", "column": "WEIGHT"},
        ],
        "derived_recodes": [
            {
                "recode_id": "cost_burden_50_v1",
                "output_name": "severe_burden",
                "purpose": "Identify severe cost burden",
            }
        ],
        "joins": [],
        "comparisons": {},
        "validation_checks": {},
        "output_format": {},
    }


def test_completed_case_separates_deterministic_and_narrative_scores() -> None:
    case = EvaluationCase(
        id="AHS-EVAL-T01",
        domain="affordability",
        question_type="valid",
        question="What share of renter households are severely cost burdened?",
        expected_dataset=["household"],
        expected_variables=["INTSTATUS", "TENURE", "TOTHCPCT", "WEIGHT"],
        expected_universe="renter_occupied_housing_units",
        expected_weight="final_household_weight",
        expected_grouping=[],
        expected_filters=[],
        expected_behavior="execute",
        acceptance_criteria="Execute a weighted percentage.",
        expected_numeric=NumericExpectation(
            records=[{"estimate": 25.0}],
            value_fields=["estimate"],
            absolute_tolerance=0.01,
        ),
    )
    candidate = CandidateResponse(
        case_id=case.id,
        status="completed",
        plan=_valid_plan(),
        plan_schema_valid=True,
        plan_validation_succeeded=True,
        sql_execution_succeeded=True,
        result_records=[{"estimate": 25.005}],
        narrative="The descriptive weighted estimate is 25.005 percent; no causal inference is made.",
        citations=[],
    )

    result = score_case(case, candidate)

    assert result.deterministic.passed is True
    assert result.narrative.passed is False
    assert result.overall_status == "pass"
    assert result.hard_gate_failures == []


def test_numeric_mismatch_is_a_hard_gate() -> None:
    case = EvaluationCase(
        id="AHS-EVAL-T02",
        domain="affordability",
        question_type="valid",
        question="What is the estimate?",
        expected_dataset=["household"],
        expected_variables=["TOTHCPCT", "WEIGHT"],
        expected_universe="renter_occupied_housing_units",
        expected_weight="final_household_weight",
        expected_grouping=[],
        expected_behavior="execute",
        acceptance_criteria="Match oracle.",
        expected_numeric=NumericExpectation(records=[{"estimate": 25.0}], value_fields=["estimate"]),
    )
    candidate = CandidateResponse(
        case_id=case.id,
        status="completed",
        plan=_valid_plan(),
        plan_schema_valid=True,
        plan_validation_succeeded=True,
        sql_execution_succeeded=True,
        result_records=[{"estimate": 40.0}],
        narrative="Descriptive result.",
        citations=[CitationRecord(source="AHS metadata")],
    )

    result = score_case(case, candidate)

    assert result.overall_status == "fail"
    assert "numeric_agreement" in result.hard_gate_failures


def test_correct_refusal_does_not_require_a_plan_or_sql() -> None:
    case = EvaluationCase(
        id="AHS-EVAL-T03",
        domain="migration",
        question_type="unsupported",
        question="Give state migration estimates.",
        expected_dataset=["household"],
        expected_variables=["IUF_ONLY_STATE_CODE"],
        expected_universe="occupied_housing_units",
        expected_weight="STATEWGT",
        expected_grouping=["state"],
        expected_behavior="refuse_puf_iuf",
        acceptance_criteria="Reject the IUF-only request.",
    )
    candidate = CandidateResponse(
        case_id=case.id,
        status="refusal",
        narrative="The PUF workflow does not certify state-level migration variables.",
        refusal_or_clarification_reason="State detail is IUF-only and unavailable in the governed PUF catalog.",
        citations=[CitationRecord(topic="PUF access", source="AHS executable catalog")],
    )

    result = score_case(case, candidate)

    assert result.overall_status == "pass"
    assert result.deterministic.passed is True
    assert not result.hard_gate_failures
    schema = next(x for x in result.deterministic.criteria if x.name == "plan_schema_validity")
    assert schema.applicable is False


def test_unsupported_question_wrongly_executed_fails_disposition() -> None:
    case = EvaluationCase(
        id="AHS-EVAL-T04",
        domain="demographics",
        question_type="unsupported",
        question="Compare burden by race.",
        expected_dataset=["household"],
        expected_variables=["UNKNOWN_RACE", "TOTHCPCT"],
        expected_universe="occupied_housing_units",
        expected_weight="final_household_weight",
        expected_grouping=["race"],
        expected_behavior="refuse_unsupported",
        acceptance_criteria="Do not fabricate race variables.",
    )
    candidate = CandidateResponse(
        case_id=case.id,
        status="completed",
        plan=_valid_plan(),
        plan_schema_valid=True,
        plan_validation_succeeded=True,
        sql_execution_succeeded=True,
        narrative="Completed.",
        citations=[CitationRecord(source="AHS")],
    )

    result = score_case(case, candidate)

    assert result.overall_status == "fail"
    assert "appropriate_refusal_or_clarification" in result.hard_gate_failures
