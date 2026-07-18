from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError

from ahs_copilot.query_engine import (
    ChildAggregate,
    ChildAggregation,
    JoinSpec,
    QualifiedColumn,
    TypedFilter,
)
from ahs_copilot.query_engine.errors import QueryValidationError
from ahs_copilot.survey_estimation import (
    ComparisonSpec,
    EstimateDefinition,
    GroupDimension,
    SuppressionPolicy,
    SurveyEstimateRequest,
    SurveyEstimator,
)


def qcol(dataset: str, column: str) -> QualifiedColumn:
    return QualifiedColumn(dataset=dataset, column=column)


def filt(dataset: str, column: str, operator: str, value=None) -> TypedFilter:
    return TypedFilter(column=qcol(dataset, column), operator=operator, value=value)


def occupied_request() -> SurveyEstimateRequest:
    return SurveyEstimateRequest(
        base_dataset="household",
        universe_filters=[filt("household", "INTSTATUS", "eq", 1)],
        estimates=[
            EstimateDefinition(alias="occupied_units", statistic="weighted_count"),
            EstimateDefinition(
                alias="high_burden_pct",
                statistic="weighted_percentage",
                numerator_filters=[filt("household", "TOTHCPCT", "ge", 50)],
                denominator_filters=[filt("household", "TOTHCPCT", "is_not_null")],
            ),
            EstimateDefinition(
                alias="mean_income",
                statistic="weighted_mean",
                value=qcol("household", "HINCP"),
            ),
        ],
    )


def test_weighted_count_percentage_mean_and_denominators(engine) -> None:
    result = SurveyEstimator(engine).execute(occupied_request())
    by_alias = {item.estimate_alias: item for item in result.estimates}

    count = by_alias["occupied_units"]
    assert count.estimate == Decimal("75.000000")
    assert count.weighted_denominator == Decimal("75.000000")
    assert count.unweighted_denominator == 6

    pct = by_alias["high_burden_pct"]
    assert pct.weighted_numerator == Decimal("32.000000")
    assert pct.weighted_denominator == Decimal("75.000000")
    assert pct.estimate == Decimal("42.666667")
    assert pct.unweighted_numerator == 2
    assert pct.unweighted_denominator == 6
    assert pct.unweighted_complement == 4

    mean = by_alias["mean_income"]
    assert mean.weighted_numerator == Decimal("4092000.000000")
    assert mean.weighted_denominator == Decimal("75.000000")
    assert mean.estimate == Decimal("54560.000000")
    assert mean.missing_value_rows_excluded == 0

    assert result.metadata.estimation_scope == "DESCRIPTIVE_WEIGHTED_ESTIMATES"
    assert result.metadata.variance.status == "NOT_ESTIMATED"
    assert result.metadata.variance.standard_errors_valid is False
    assert all(item.standard_error is None for item in result.estimates)


def test_grouped_reference_comparisons_are_descriptive_only(engine) -> None:
    request = SurveyEstimateRequest(
        base_dataset="household",
        universe_filters=[filt("household", "INTSTATUS", "eq", 1)],
        group_by=[GroupDimension(column=qcol("household", "TENURE"))],
        estimates=[EstimateDefinition(alias="units", statistic="weighted_count")],
        comparisons=ComparisonSpec(mode="reference", reference_group={"TENURE": 1}),
    )
    result = SurveyEstimator(engine).execute(request)
    assert [item.group for item in result.estimates] == [
        {"TENURE": 1},
        {"TENURE": 2},
        {"TENURE": 3},
    ]
    comparison = next(item for item in result.comparisons if item.left_group == {"TENURE": 2})
    assert comparison.right_group == {"TENURE": 1}
    assert comparison.difference == Decimal("26.000000")
    assert comparison.ratio == Decimal("2.238095")
    assert comparison.inferential_test == "NOT_PERFORMED"
    assert comparison.standard_error is None
    assert comparison.p_value is None


def test_zero_reference_keeps_difference_but_not_ratio(engine) -> None:
    request = SurveyEstimateRequest(
        base_dataset="household",
        universe_filters=[filt("household", "INTSTATUS", "eq", 1)],
        group_by=[GroupDimension(column=qcol("household", "TENURE"))],
        estimates=[
            EstimateDefinition(
                alias="high_burden_pct",
                statistic="weighted_percentage",
                numerator_filters=[filt("household", "TOTHCPCT", "ge", 50)],
                denominator_filters=[filt("household", "TOTHCPCT", "is_not_null")],
            )
        ],
        comparisons=ComparisonSpec(mode="reference", reference_group={"TENURE": 1}),
    )
    result = SurveyEstimator(engine).execute(request)
    comparison = next(item for item in result.comparisons if item.left_group == {"TENURE": 2})
    assert comparison.difference == Decimal("68.085106")
    assert comparison.ratio is None
    assert comparison.suppressed is False
    assert comparison.warnings == ["RATIO_UNDEFINED_ZERO_REFERENCE_ESTIMATE"]


def test_configurable_suppression_nulls_estimate_and_exposes_reason(engine) -> None:
    request = SurveyEstimateRequest(
        base_dataset="household",
        universe_filters=[filt("household", "INTSTATUS", "eq", 1)],
        group_by=[GroupDimension(column=qcol("household", "TENURE"))],
        estimates=[
            EstimateDefinition(
                alias="high_burden_pct",
                statistic="weighted_percentage",
                numerator_filters=[filt("household", "TOTHCPCT", "ge", 50)],
                denominator_filters=[filt("household", "TOTHCPCT", "is_not_null")],
            )
        ],
        suppression=SuppressionPolicy(
            policy_id="test_minimums",
            minimum_unweighted_denominator=2,
            minimum_unweighted_numerator=1,
            minimum_unweighted_complement=1,
            action="null_estimate",
        ),
    )
    result = SurveyEstimator(engine).execute(request)
    owner = next(item for item in result.estimates if item.group == {"TENURE": 1})
    assert owner.estimate is None
    assert owner.suppression.suppressed is True
    assert "UNWEIGHTED_NUMERATOR_BELOW_CONFIGURED_MINIMUM" in owner.suppression.reasons

    other = next(item for item in result.estimates if item.group == {"TENURE": 3})
    assert other.estimate is None
    assert "UNWEIGHTED_DENOMINATOR_BELOW_CONFIGURED_MINIMUM" in other.suppression.reasons


def test_child_preaggregation_is_preserved_and_parameter_order_is_correct(engine) -> None:
    request = SurveyEstimateRequest(
        base_dataset="household",
        universe_filters=[filt("household", "INTSTATUS", "eq", 1)],
        joins=[
            JoinSpec(
                dataset="mortgage",
                aggregation=ChildAggregation(
                    group_by=["CONTROL"],
                    filters=[filt("mortgage", "MORTAMT", "ge", 100000)],
                    aggregates=[
                        ChildAggregate(function="count", alias="large_mortgage_count"),
                        ChildAggregate(
                            function="sum", column="MORTAMT", alias="large_mortgage_total"
                        ),
                    ],
                ),
            )
        ],
        estimates=[
            EstimateDefinition(
                alias="large_mortgage_households_pct",
                statistic="weighted_percentage",
                numerator_filters=[filt("mortgage", "large_mortgage_count", "ge", 1)],
            ),
            EstimateDefinition(
                alias="mean_large_mortgage_total",
                statistic="weighted_mean",
                value=qcol("mortgage", "large_mortgage_total"),
                denominator_filters=[filt("mortgage", "large_mortgage_count", "ge", 1)],
            ),
        ],
    )
    estimator = SurveyEstimator(engine)
    compiled = estimator.compile(request)
    assert compiled.parameters[:2] == [1, 1]
    assert compiled.parameters[-2:] == [100000, 1]
    assert "GROUP BY \"CONTROL\"" in compiled.sql
    result = estimator.execute(request)
    by_alias = {item.estimate_alias: item for item in result.estimates}
    estimate = by_alias["large_mortgage_households_pct"]
    assert estimate.weighted_numerator == Decimal("21.000000")
    assert estimate.weighted_denominator == Decimal("75.000000")
    assert estimate.estimate == Decimal("28.000000")
    mean = by_alias["mean_large_mortgage_total"]
    assert mean.weighted_numerator == Decimal("3120000.000000")
    assert mean.weighted_denominator == Decimal("21.000000")
    assert mean.estimate == Decimal("148571.428571")
    assert result.metadata.join_contract_ids == ["rel_household_mortgage_control"]


def test_child_grain_base_is_rejected_for_survey_estimation(engine) -> None:
    request = SurveyEstimateRequest(
        base_dataset="mortgage",
        weight=qcol("mortgage", "MORTAMT"),
        estimates=[EstimateDefinition(alias="bad", statistic="weighted_count")],
    )
    with pytest.raises(QueryValidationError, match="HOUSING_UNIT base dataset"):
        SurveyEstimator(engine).compile(request)


def test_survey_request_rejects_raw_sql() -> None:
    payload = {
        "base_dataset": "household",
        "estimates": [{"alias": "units", "statistic": "weighted_count"}],
        "sql": "SELECT * FROM ahs_household",
    }
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        SurveyEstimateRequest.model_validate(payload)
