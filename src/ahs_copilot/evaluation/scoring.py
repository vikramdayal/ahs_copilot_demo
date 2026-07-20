from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence
from typing import Any

from pydantic import ValidationError

from ahs_copilot.analysis_plan.models import AnalysisPlan

from .models import (
    CandidateResponse,
    CriterionScore,
    EvaluationCase,
    EvaluationResult,
    ScoreSection,
)

DETERMINISTIC_WEIGHTS: dict[str, float] = {
    "dataset_selection": 10.0,
    "variable_selection": 10.0,
    "universe_correctness": 10.0,
    "weight_correctness": 10.0,
    "filter_correctness": 10.0,
    "plan_schema_validity": 15.0,
    "sql_execution_success": 10.0,
    "numeric_agreement": 15.0,
    "appropriate_refusal_or_clarification": 10.0,
}

NARRATIVE_WEIGHTS: dict[str, float] = {
    "citation_completeness": 60.0,
    "response_quality": 40.0,
}

NON_EXECUTION_BEHAVIORS = {
    "clarify",
    "clarify_then_block",
    "clarify_then_block_if_needed",
    "clarify_or_execute_defined_summary",
    "clarify_or_map_certified_labels",
    "clarify_multi_mortgage_semantics",
    "clarify_multi_project_semantics",
    "refuse_unsupported",
    "refuse_puf_iuf",
    "refuse_variance",
    "refuse_stereotyping_and_unsupported",
    "refuse_false_premise",
    "refuse_illegal_join",
    "refuse_raw_sql_and_prediction",
}

REFUSAL_BEHAVIORS = {x for x in NON_EXECUTION_BEHAVIORS if x.startswith("refuse")}
CLARIFICATION_BEHAVIORS = {x for x in NON_EXECUTION_BEHAVIORS if x.startswith("clarify")}


def _criterion(name: str, possible: float, earned: float, details: list[str], *, applicable: bool = True) -> CriterionScore:
    if not applicable:
        return CriterionScore(name=name, earned=0.0, possible=0.0, passed=True, applicable=False, details=details)
    bounded = min(max(float(earned), 0.0), possible)
    return CriterionScore(
        name=name,
        earned=bounded,
        possible=possible,
        passed=math.isclose(bounded, possible),
        details=details,
    )


def _normalize_name(value: Any) -> str:
    return str(value or "").strip().upper()


def _qualified_name(value: Any) -> str:
    if isinstance(value, Mapping):
        dataset = value.get("dataset")
        column = value.get("column")
        if dataset and column:
            return f"{str(dataset).lower()}.{_normalize_name(column)}"
        if column:
            return _normalize_name(column)
    return _normalize_name(value)


def _plan_datasets(plan: Mapping[str, Any]) -> set[str]:
    datasets = {str(plan.get("dataset", "")).lower()}
    for join in plan.get("joins", []) or []:
        if isinstance(join, Mapping) and join.get("dataset"):
            datasets.add(str(join["dataset"]).lower())
    return {x for x in datasets if x}


def _plan_variables(plan: Mapping[str, Any]) -> set[str]:
    variables: set[str] = set()
    for value in plan.get("required_variables", []) or []:
        variables.add(_qualified_name(value))
        if isinstance(value, Mapping) and value.get("column"):
            variables.add(_normalize_name(value["column"]))
    measure = plan.get("measure") or {}
    if isinstance(measure, Mapping) and measure.get("value"):
        variables.add(_qualified_name(measure["value"]))
        if isinstance(measure["value"], Mapping):
            variables.add(_normalize_name(measure["value"].get("column")))
    weight = plan.get("weight") or {}
    if isinstance(weight, Mapping) and weight.get("column"):
        variables.add(_qualified_name(weight["column"]))
        if isinstance(weight["column"], Mapping):
            variables.add(_normalize_name(weight["column"].get("column")))
    for bucket in ("filters",):
        for item in plan.get(bucket, []) or []:
            if isinstance(item, Mapping) and item.get("column"):
                variables.add(_qualified_name(item["column"]))
                if isinstance(item["column"], Mapping):
                    variables.add(_normalize_name(item["column"].get("column")))
    for section in ("numerator", "denominator"):
        spec = plan.get(section) or {}
        for item in spec.get("filters", []) if isinstance(spec, Mapping) else []:
            if isinstance(item, Mapping) and item.get("column"):
                variables.add(_qualified_name(item["column"]))
                if isinstance(item["column"], Mapping):
                    variables.add(_normalize_name(item["column"].get("column")))
    for value in plan.get("grouping_dimensions", []) or []:
        variables.add(_qualified_name(value))
        if isinstance(value, Mapping):
            variables.add(_normalize_name(value.get("column")))
    return {x for x in variables if x}


def _expected_variable_is_executable(name: str) -> bool:
    upper = _normalize_name(name)
    return not (
        upper.startswith("UNKNOWN_")
        or upper.startswith("IUF_ONLY_")
        or upper in {"RAW_SQL", "REPLICATE_WEIGHTS", "STATEWGT", "INCORRECT_WEIGHT", "NONE"}
    )


def _score_set_match(expected: Sequence[str], actual: set[str], possible: float, label: str) -> CriterionScore:
    expected_norm = {_normalize_name(x) for x in expected if _expected_variable_is_executable(x)}
    if not expected_norm:
        return _criterion(label, possible, possible, ["No executable expected items; criterion satisfied by non-execution path."])
    found = {x for x in expected_norm if x in actual or any(v.endswith(f".{x}") for v in actual)}
    ratio = len(found) / len(expected_norm)
    missing = sorted(expected_norm - found)
    details = [f"Matched {len(found)} of {len(expected_norm)} expected items."]
    if missing:
        details.append(f"Missing: {', '.join(missing)}")
    return _criterion(label, possible, possible * ratio, details)


def _canonical_filter(item: Mapping[str, Any]) -> tuple[str, str, str]:
    column = _qualified_name(item.get("column"))
    operator = str(item.get("operator", "")).lower()
    value = repr(item.get("value"))
    return column, operator, value


def _all_plan_filters(plan: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    filters: list[Mapping[str, Any]] = []
    for item in plan.get("filters", []) or []:
        if isinstance(item, Mapping):
            filters.append(item)
    for section in ("numerator", "denominator"):
        spec = plan.get(section) or {}
        if isinstance(spec, Mapping):
            for item in spec.get("filters", []) or []:
                if isinstance(item, Mapping):
                    filters.append(item)
    return filters


def _score_filters(case: EvaluationCase, plan: Mapping[str, Any], possible: float, *, semantic_validation_succeeded: bool | None) -> CriterionScore:
    actual = {_canonical_filter(x) for x in _all_plan_filters(plan)}
    if case.expected_filters:
        expected = {_canonical_filter(x) for x in case.expected_filters}
        missing = expected - actual
        unexpected = actual - expected
        exact = not missing and not unexpected
        details = [f"Expected {len(expected)} filters; observed {len(actual)}."]
        if missing:
            details.append(f"Missing filters: {sorted(missing)!r}")
        if unexpected:
            details.append(f"Unexpected filters: {sorted(unexpected)!r}")
        return _criterion("filter_correctness", possible, possible if exact else 0.0, details)

    # The initial evaluation set describes filters through universe and behavior.
    # In that mode, require a successful governed semantic validation rather than
    # guessing AHS code values in the scorer.
    return _criterion(
        "filter_correctness",
        possible,
        possible if semantic_validation_succeeded is True else 0.0,
        [
            "No literal filter oracle supplied; filter correctness requires successful governed plan validation."
            if semantic_validation_succeeded is True
            else "No literal filter oracle supplied and governed plan validation did not succeed."
        ],
    )


def _score_plan_schema(candidate: CandidateResponse, possible: float) -> CriterionScore:
    if candidate.plan is None:
        return _criterion("plan_schema_validity", possible, 0.0, ["No plan supplied."])
    try:
        AnalysisPlan.model_validate(candidate.plan)
    except ValidationError as exc:
        return _criterion("plan_schema_validity", possible, 0.0, [str(exc)])
    if candidate.plan_schema_valid is False:
        return _criterion("plan_schema_validity", possible, 0.0, ["Candidate marked plan as schema-invalid."])
    return _criterion("plan_schema_validity", possible, possible, ["AnalysisPlan Pydantic schema validation passed."])


def _score_universe(case: EvaluationCase, plan: Mapping[str, Any], possible: float) -> CriterionScore:
    expected = _normalize_name(case.expected_universe)
    actual = _normalize_name((plan.get("universe") or {}).get("universe_id") if isinstance(plan.get("universe"), Mapping) else None)
    if expected in {"UNSPECIFIED", "UNSUPPORTED_JOIN", "NONE"}:
        return _criterion("universe_correctness", possible, possible, ["Universe is intentionally unresolved for this case."])
    return _criterion(
        "universe_correctness",
        possible,
        possible if actual == expected else 0.0,
        [f"Expected {expected}; observed {actual or 'missing'}."],
    )


def _score_weight(case: EvaluationCase, plan: Mapping[str, Any], possible: float) -> CriterionScore:
    expected = _normalize_name(case.expected_weight)
    weight = plan.get("weight") or {}
    actual = ""
    if isinstance(weight, Mapping):
        column = weight.get("column")
        actual = _qualified_name(column)
        if isinstance(column, Mapping):
            actual = _normalize_name(column.get("column"))
        if not actual:
            actual = _normalize_name(weight.get("mode"))
    if expected in {"UNSPECIFIED", "NONE", "INCORRECT_WEIGHT"}:
        return _criterion("weight_correctness", possible, possible, ["Weight is intentionally unresolved or invalid for this case."])
    aliases = {
        "FINAL_HOUSEHOLD_WEIGHT": {"WEIGHT", "HOUSEHOLD.WEIGHT"},
        "SP1WEIGHT": {"SP1WEIGHT", "HOUSEHOLD.SP1WEIGHT"},
    }
    allowed = aliases.get(expected, {expected})
    return _criterion(
        "weight_correctness",
        possible,
        possible if actual in allowed else 0.0,
        [f"Expected one of {sorted(allowed)}; observed {actual or 'missing'}."],
    )


def _score_grouping(case: EvaluationCase, plan: Mapping[str, Any]) -> list[str]:
    expected = {_normalize_name(x) for x in case.expected_grouping}
    actual = {_normalize_name((x or {}).get("column") if isinstance(x, Mapping) else x) for x in plan.get("grouping_dimensions", []) or []}
    missing = expected - actual
    return [] if not missing else [f"Missing grouping dimensions: {', '.join(sorted(missing))}"]


def _numeric_equal(expected: Any, actual: Any, abs_tol: float, rel_tol: float) -> bool:
    if isinstance(expected, bool) or isinstance(actual, bool):
        return expected == actual
    if isinstance(expected, (int, float)) and isinstance(actual, (int, float)):
        return math.isclose(float(expected), float(actual), abs_tol=abs_tol, rel_tol=rel_tol)
    return expected == actual


def _score_numeric(case: EvaluationCase, candidate: CandidateResponse, possible: float) -> CriterionScore:
    oracle = case.expected_numeric
    if oracle is None or not oracle.records:
        return _criterion("numeric_agreement", possible, 0.0, ["No numeric oracle supplied."], applicable=False)
    actual_by_key: dict[tuple[Any, ...], Mapping[str, Any]] = {}
    for row in candidate.result_records:
        key = tuple(row.get(field) for field in oracle.key_fields)
        actual_by_key[key] = row
    comparisons = 0
    passed = 0
    failures: list[str] = []
    for expected_row in oracle.records:
        key = tuple(expected_row.get(field) for field in oracle.key_fields)
        actual_row = actual_by_key.get(key)
        if actual_row is None:
            failures.append(f"Missing expected result row for key {key!r}.")
            comparisons += len(oracle.value_fields)
            continue
        for field in oracle.value_fields:
            comparisons += 1
            if _numeric_equal(expected_row.get(field), actual_row.get(field), oracle.absolute_tolerance, oracle.relative_tolerance):
                passed += 1
            else:
                failures.append(
                    f"{key!r}.{field}: expected {expected_row.get(field)!r}, observed {actual_row.get(field)!r}."
                )
    ratio = passed / comparisons if comparisons else 1.0
    details = [f"Matched {passed} of {comparisons} numeric values.", *failures[:20]]
    return _criterion("numeric_agreement", possible, possible * ratio, details)


def _expected_response_status(case: EvaluationCase) -> set[str]:
    behavior = case.expected_behavior
    if behavior in REFUSAL_BEHAVIORS:
        return {"refusal"}
    if behavior in CLARIFICATION_BEHAVIORS:
        return {"clarification"}
    if behavior in {"correct_causal_claim", "correct_and_execute_or_refuse", "correct_denominator_and_weight"}:
        return {"completed", "refusal", "clarification"}
    if behavior in {"execute_or_block_geography", "execute_if_code_mapping_certified", "execute_if_special_weight_certified"}:
        return {"completed", "refusal"}
    return {"completed"}


def _score_response_disposition(case: EvaluationCase, candidate: CandidateResponse, possible: float) -> CriterionScore:
    expected = _expected_response_status(case)
    passed = candidate.status in expected
    details = [f"Expected status in {sorted(expected)}; observed {candidate.status}."]
    if candidate.status in {"refusal", "clarification"} and not candidate.refusal_or_clarification_reason:
        passed = False
        details.append("Refusal/clarification lacks an explicit reason.")
    return _criterion("appropriate_refusal_or_clarification", possible, possible if passed else 0.0, details)


def _score_citations(case: EvaluationCase, candidate: CandidateResponse, possible: float) -> CriterionScore:
    expectation = case.citation_expectation
    if not expectation.required:
        return _criterion("citation_completeness", possible, possible, ["Citations are not required for this case."])
    count_ok = len(candidate.citations) >= expectation.minimum_count
    topics = {_normalize_name(x.topic) for x in candidate.citations if x.topic}
    missing_topics = {_normalize_name(x) for x in expectation.required_topics} - topics
    passed = count_ok and not missing_topics
    details = [f"Observed {len(candidate.citations)} citations; minimum is {expectation.minimum_count}."]
    if missing_topics:
        details.append(f"Missing citation topics: {', '.join(sorted(missing_topics))}")
    return _criterion("citation_completeness", possible, possible if passed else 0.0, details)


def _score_response_quality(case: EvaluationCase, candidate: CandidateResponse, possible: float) -> CriterionScore:
    text = candidate.narrative.strip()
    checks = {
        "nonempty": bool(text),
        "descriptive_boundary": not bool(re.search(r"\b(proves?|causes?|statistically significant)\b", text, re.I)),
        "no_raw_sql_claim": not bool(re.search(r"\bSELECT\s+\*\s+FROM\b", text, re.I)),
        "explains_nonexecution": candidate.status == "completed" or bool(candidate.refusal_or_clarification_reason),
    }
    if case.question_type == "misleading":
        checks["does_not_adopt_false_premise"] = not bool(re.search(r"\b(confirm(ed)?|as you said|clearly shows)\b", text, re.I))
    passed_count = sum(checks.values())
    ratio = passed_count / len(checks)
    details = [f"{name}: {'passed' if ok else 'failed'}" for name, ok in checks.items()]
    return _criterion("response_quality", possible, possible * ratio, details)


def _section(criteria: list[CriterionScore], *, pass_threshold: float) -> ScoreSection:
    earned = sum(x.earned for x in criteria if x.applicable)
    possible = sum(x.possible for x in criteria if x.applicable)
    normalized = earned / possible if possible else 1.0
    return ScoreSection(
        earned=earned,
        possible=possible,
        normalized=normalized,
        passed=normalized >= pass_threshold,
        criteria=criteria,
    )


def score_case(case: EvaluationCase, candidate: CandidateResponse) -> EvaluationResult:
    if candidate.case_id != case.id:
        raise ValueError(f"Candidate case_id {candidate.case_id!r} does not match {case.id!r}")

    expected_statuses = _expected_response_status(case)
    expects_execution = expected_statuses == {"completed"}
    plan = candidate.plan or {}

    deterministic: list[CriterionScore] = []
    nonexecution_correct = candidate.status in {"refusal", "clarification"} and candidate.status in expected_statuses

    if nonexecution_correct:
        for name in ("dataset_selection", "variable_selection", "universe_correctness", "weight_correctness", "filter_correctness", "plan_schema_validity", "sql_execution_success", "numeric_agreement"):
            deterministic.append(_criterion(name, DETERMINISTIC_WEIGHTS[name], 0.0, ["Not applicable after correct non-execution disposition."], applicable=False))
    else:
        actual_datasets = _plan_datasets(plan)
        expected_datasets = {x.lower() for x in case.expected_dataset if x.lower() not in {"unsupported_join", "none"}}
        dataset_union = expected_datasets | actual_datasets
        dataset_ratio = len(expected_datasets & actual_datasets) / len(dataset_union) if dataset_union else 1.0
        deterministic.append(_criterion(
            "dataset_selection", DETERMINISTIC_WEIGHTS["dataset_selection"],
            DETERMINISTIC_WEIGHTS["dataset_selection"] * dataset_ratio,
            [f"Expected {sorted(expected_datasets)}; observed {sorted(actual_datasets)}."],
        ))
        variable_score = _score_set_match(case.expected_variables, _plan_variables(plan), DETERMINISTIC_WEIGHTS["variable_selection"], "variable_selection")
        grouping_errors = _score_grouping(case, plan)
        if grouping_errors and variable_score.passed:
            variable_score = variable_score.model_copy(update={"earned": variable_score.earned * 0.8, "passed": False, "details": variable_score.details + grouping_errors})
        deterministic.append(variable_score)
        deterministic.append(_score_universe(case, plan, DETERMINISTIC_WEIGHTS["universe_correctness"]))
        deterministic.append(_score_weight(case, plan, DETERMINISTIC_WEIGHTS["weight_correctness"]))
        deterministic.append(_score_filters(case, plan, DETERMINISTIC_WEIGHTS["filter_correctness"], semantic_validation_succeeded=candidate.plan_validation_succeeded))
        deterministic.append(_score_plan_schema(candidate, DETERMINISTIC_WEIGHTS["plan_schema_validity"]))
        execution_earned = DETERMINISTIC_WEIGHTS["sql_execution_success"] if candidate.sql_execution_succeeded is True else 0.0
        execution_details = ["SQL execution succeeded." if execution_earned else f"SQL execution did not succeed: {candidate.execution_error or 'no success signal' }."]
        deterministic.append(_criterion("sql_execution_success", DETERMINISTIC_WEIGHTS["sql_execution_success"], execution_earned, execution_details, applicable=expects_execution or candidate.status == "completed"))
        deterministic.append(_score_numeric(case, candidate, DETERMINISTIC_WEIGHTS["numeric_agreement"]))

    deterministic.append(_score_response_disposition(case, candidate, DETERMINISTIC_WEIGHTS["appropriate_refusal_or_clarification"]))

    narrative = [
        _score_citations(case, candidate, NARRATIVE_WEIGHTS["citation_completeness"]),
        _score_response_quality(case, candidate, NARRATIVE_WEIGHTS["response_quality"]),
    ]

    deterministic_section = _section(deterministic, pass_threshold=0.90)
    narrative_section = _section(narrative, pass_threshold=0.70)

    hard_gate_failures: list[str] = []
    by_name = {item.name: item for item in deterministic}
    disposition = by_name["appropriate_refusal_or_clarification"]
    if not disposition.passed:
        hard_gate_failures.append("appropriate_refusal_or_clarification")
    if candidate.status == "completed":
        for gate in ("plan_schema_validity", "sql_execution_success"):
            item = by_name.get(gate)
            if item and item.applicable and not item.passed:
                hard_gate_failures.append(gate)
        numeric = by_name.get("numeric_agreement")
        if numeric and numeric.applicable and not numeric.passed:
            hard_gate_failures.append("numeric_agreement")

    overall = "pass" if deterministic_section.passed and not hard_gate_failures else "fail"
    diagnostics = [detail for item in deterministic + narrative for detail in item.details if not item.passed]
    return EvaluationResult(
        case_id=case.id,
        deterministic=deterministic_section,
        narrative=narrative_section,
        overall_status=overall,
        hard_gate_failures=hard_gate_failures,
        diagnostics=diagnostics,
    )
