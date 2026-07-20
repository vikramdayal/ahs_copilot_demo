from __future__ import annotations

from decimal import Decimal

import pytest

from ahs_copilot.analysis_plan import (
    AnalysisPlan,
    AnalysisPlanService,
    AnalysisPlanValidationError,
    DenominatorSpec,
    MeasureSpec,
    NumeratorSpec,
    UniverseSpec,
    WeightSpec,
)
from ahs_copilot.query_engine import ChildAggregate, ChildAggregation, JoinSpec, QualifiedColumn, TypedFilter


def qcol(dataset: str, column: str) -> QualifiedColumn:
    return QualifiedColumn(dataset=dataset, column=column)


def filt(dataset: str, column: str, operator: str, value=None) -> TypedFilter:
    return TypedFilter(column=qcol(dataset, column), operator=operator, value=value)


def count_plan(
    universe_id: str,
    *,
    mode: str = "weighted",
    required: list[QualifiedColumn] | None = None,
) -> AnalysisPlan:
    default_required = []
    if universe_id != "all_housing_units":
        default_required.append(qcol("household", "INTSTATUS"))
    if universe_id in {"owner_occupied_housing_units", "renter_occupied_housing_units"}:
        default_required.append(qcol("household", "TENURE"))
    if mode == "weighted":
        default_required.append(qcol("household", "WEIGHT"))
    question = (
        f"Count units in {universe_id}"
        if mode == "weighted"
        else f"Return the unweighted sample count of units in {universe_id}"
    )
    return AnalysisPlan(
        user_question=question,
        dataset="household",
        measure=MeasureSpec(alias="units", statistic="count"),
        numerator=NumeratorSpec(
            role="eligible_units", description="All units in the approved universe"
        ),
        denominator=DenominatorSpec(
            role="eligible_units", description="All units in the approved universe"
        ),
        universe=UniverseSpec(universe_id=universe_id, description=universe_id),
        weight=WeightSpec(
            mode=mode,
            column=qcol("household", "WEIGHT") if mode == "weighted" else None,
        ),
        required_variables=required or default_required,
    )


def issue_codes(exc: AnalysisPlanValidationError) -> set[str]:
    return {item.code for item in exc.issues}


def test_occupied_versus_all_housing_units(engine) -> None:
    service = AnalysisPlanService(engine)
    all_result = service.execute(count_plan("all_housing_units")).result
    occupied_result = service.execute(count_plan("occupied_housing_units")).result

    assert all_result.estimates[0].estimate == Decimal("84.000000")
    assert occupied_result.estimates[0].estimate == Decimal("75.000000")
    assert "INTSTATUS" in occupied_result.generated_sql
    assert all_result.metadata.variance.standard_errors_valid is False


def test_owner_versus_renter_universes(engine) -> None:
    service = AnalysisPlanService(engine)
    owner = service.execute(count_plan("owner_occupied_housing_units")).result.estimates[0]
    renter = service.execute(count_plan("renter_occupied_housing_units")).result.estimates[0]

    assert owner.estimate == Decimal("21.000000")
    assert owner.unweighted_denominator == 2
    assert renter.estimate == Decimal("47.000000")
    assert renter.unweighted_denominator == 3


def test_declared_missing_value_codes_are_excluded_deterministically(engine) -> None:
    plan = AnalysisPlan(
        user_question="What is mean household income across all housing units?",
        dataset="household",
        measure=MeasureSpec(
            alias="mean_income", statistic="mean", value=qcol("household", "HINCP")
        ),
        numerator=NumeratorSpec(
            role="weighted_value_sum",
            description="Weighted sum of nonmissing household income",
        ),
        denominator=DenominatorSpec(
            role="nonmissing_weight_sum",
            description="Weight sum for nonmissing household income",
        ),
        universe=UniverseSpec(
            universe_id="all_housing_units", description="All sampled housing units"
        ),
        weight=WeightSpec(mode="weighted", column=qcol("household", "WEIGHT")),
        required_variables=[qcol("household", "HINCP"), qcol("household", "WEIGHT")],
    )
    result = AnalysisPlanService(engine).execute(plan).result.estimates[0]

    assert result.estimate == Decimal("54560.000000")
    assert result.weighted_denominator == Decimal("75.000000")
    assert result.unweighted_denominator == 6
    assert result.missing_value_rows_excluded == 2


def test_weighted_versus_unweighted_output(engine) -> None:
    service = AnalysisPlanService(engine)
    weighted = service.execute(count_plan("occupied_housing_units", mode="weighted")).result
    unweighted = service.execute(count_plan("occupied_housing_units", mode="unweighted")).result

    assert weighted.estimates[0].estimate == Decimal("75.000000")
    assert weighted.estimates[0].weighting_mode == "weighted"
    assert weighted.metadata.estimation_scope == "DESCRIPTIVE_WEIGHTED_ESTIMATES"
    assert weighted.metadata.weight_column == qcol("household", "WEIGHT")

    assert unweighted.estimates[0].estimate == Decimal("6.000000")
    assert unweighted.estimates[0].weighting_mode == "unweighted"
    assert unweighted.metadata.estimation_scope == "DESCRIPTIVE_UNWEIGHTED_ESTIMATES"
    assert unweighted.metadata.weight_column is None
    assert unweighted.metadata.weight_eligibility_rule == "unit weight = 1 for every eligible row"


def test_illegal_mortgage_project_join_rejected_before_sql_generation(engine, monkeypatch) -> None:
    plan = AnalysisPlan(
        user_question="Count mortgage rows after joining projects",
        dataset="mortgage",
        measure=MeasureSpec(alias="rows", statistic="count"),
        numerator=NumeratorSpec(role="eligible_units", description="Mortgage rows"),
        denominator=DenominatorSpec(role="eligible_units", description="Mortgage rows"),
        universe=UniverseSpec(
            universe_id="occupied_housing_units", description="Deliberately incompatible universe"
        ),
        weight=WeightSpec(mode="unweighted"),
        required_variables=[qcol("mortgage", "CONTROL")],
        joins=[
            JoinSpec(
                dataset="projects",
                aggregation=ChildAggregation(
                    group_by=["CONTROL"],
                    aggregates=[ChildAggregate(function="count", alias="project_count")],
                ),
            )
        ],
    )
    service = AnalysisPlanService(engine)
    called = False

    def fail_compile(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("SQL compiler must not be called")

    monkeypatch.setattr(service.estimator, "compile", fail_compile)
    with pytest.raises(AnalysisPlanValidationError) as caught:
        service.compile(plan)
    assert "ILLEGAL_JOIN_PATH" in issue_codes(caught.value)
    assert called is False


def test_empty_denominator_returns_flagged_undefined_estimate(engine) -> None:
    plan = AnalysisPlan(
        user_question="What share has impossible housing costs?",
        dataset="household",
        measure=MeasureSpec(alias="impossible_pct", statistic="percentage"),
        numerator=NumeratorSpec(
            role="condition_true",
            description="Cost burden at least 50 percent",
            filters=[
                filt("household", "TOTHCPCT", "gt", 999),
                filt("household", "TOTHCPCT", "ge", 50),
            ],
        ),
        denominator=DenominatorSpec(
            role="eligible_units",
            description="Deliberately empty eligible denominator",
            filters=[filt("household", "TOTHCPCT", "gt", 999)],
        ),
        universe=UniverseSpec(
            universe_id="occupied_housing_units", description="Occupied housing units"
        ),
        weight=WeightSpec(mode="weighted", column=qcol("household", "WEIGHT")),
        required_variables=[
            qcol("household", "INTSTATUS"),
            qcol("household", "TOTHCPCT"),
            qcol("household", "WEIGHT"),
        ],
    )
    estimate = AnalysisPlanService(engine).execute(plan).result.estimates[0]
    assert estimate.estimate is None
    assert estimate.weighted_denominator == Decimal("0.000000")
    assert estimate.suppression.suppressed is True
    assert "ZERO_OR_NONPOSITIVE_WEIGHTED_DENOMINATOR" in estimate.suppression.reasons


def test_unknown_variable_rejected(engine) -> None:
    plan = AnalysisPlan(
        user_question="Mean of an unknown field",
        dataset="household",
        measure=MeasureSpec(
            alias="bad_mean", statistic="mean", value=qcol("household", "NOT_A_VARIABLE")
        ),
        numerator=NumeratorSpec(role="weighted_value_sum", description="Bad numerator"),
        denominator=DenominatorSpec(
            role="nonmissing_weight_sum", description="Bad denominator"
        ),
        universe=UniverseSpec(
            universe_id="occupied_housing_units", description="Occupied housing units"
        ),
        weight=WeightSpec(mode="weighted", column=qcol("household", "WEIGHT")),
        required_variables=[
            qcol("household", "INTSTATUS"),
            qcol("household", "WEIGHT"),
            qcol("household", "NOT_A_VARIABLE"),
        ],
    )
    with pytest.raises(AnalysisPlanValidationError) as caught:
        AnalysisPlanService(engine).validate(plan)
    assert "UNKNOWN_VARIABLE" in issue_codes(caught.value)


def test_puf_inaccessible_field_rejected(engine) -> None:
    plan = count_plan(
        "occupied_housing_units",
        required=[
            qcol("household", "INTSTATUS"),
            qcol("household", "WEIGHT"),
            qcol("household", "IUF_ONLY_STATE_CODE"),
        ],
    ).model_copy(
        update={"grouping_dimensions": [qcol("household", "IUF_ONLY_STATE_CODE")]}
    )
    with pytest.raises(AnalysisPlanValidationError) as caught:
        AnalysisPlanService(engine).validate(plan)
    assert "PUF_INACCESSIBLE_FIELD" in issue_codes(caught.value)


def test_missing_required_variable_declaration_rejected(engine) -> None:
    plan = count_plan(
        "occupied_housing_units",
        required=[qcol("household", "WEIGHT")],
    )
    with pytest.raises(AnalysisPlanValidationError) as caught:
        AnalysisPlanService(engine).validate(plan)
    assert "MISSING_REQUIRED_VARIABLE_DECLARATION" in issue_codes(caught.value)


def test_approved_derived_recode_is_recorded_in_validated_plan(engine) -> None:
    from ahs_copilot.analysis_plan import DerivedRecodeSpec

    plan = AnalysisPlan(
        user_question="What share of occupied units has severe cost burden?",
        dataset="household",
        measure=MeasureSpec(alias="high_burden_pct", statistic="percentage"),
        numerator=NumeratorSpec(
            role="condition_true",
            description="Cost burden at or above 50 percent",
            filters=[filt("household", "TOTHCPCT", "ge", 50)],
        ),
        denominator=DenominatorSpec(
            role="eligible_units", description="Occupied units with valid cost burden"
        ),
        universe=UniverseSpec(
            universe_id="occupied_housing_units", description="Occupied housing units"
        ),
        weight=WeightSpec(mode="weighted", column=qcol("household", "WEIGHT")),
        required_variables=[
            qcol("household", "INTSTATUS"),
            qcol("household", "TOTHCPCT"),
            qcol("household", "WEIGHT"),
        ],
        derived_recodes=[
            DerivedRecodeSpec(
                recode_id="cost_burden_50_v1",
                output_name="HIGH_BURDEN",
                purpose="Document the approved deterministic threshold used by the numerator",
            )
        ],
    )
    validated = AnalysisPlanService(engine).validate(plan)
    assert validated.approved_recode_ids == ["cost_burden_50_v1"]


def test_analysis_plan_rejects_raw_sql_property() -> None:
    from pydantic import ValidationError

    payload = count_plan("occupied_housing_units").model_dump(mode="json")
    payload["sql"] = "SELECT * FROM ahs_household"
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        AnalysisPlan.model_validate(payload)
