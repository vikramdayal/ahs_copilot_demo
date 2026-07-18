from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from ahs_copilot.query_engine import (
    AHSQueryEngine,
    AggregateProjection,
    ChildAggregate,
    ChildAggregation,
    ColumnProjection,
    JoinSpec,
    OrderBy,
    QualifiedColumn,
    QuerySpec,
    TypedFilter,
)
from ahs_copilot.query_engine.errors import JoinPolicyError, QueryValidationError


def col(dataset: str, column: str, alias: str | None = None) -> ColumnProjection:
    return ColumnProjection(column=QualifiedColumn(dataset=dataset, column=column), alias=alias)


def test_inspects_all_configured_schemas_and_uses_fixture(engine: AHSQueryEngine) -> None:
    schemas = engine.inspect_schemas()
    assert set(schemas) == {"household", "mortgage", "projects"}
    assert schemas["household"].synthetic_fixture is True
    assert schemas["household"].join_keys == ["CONTROL"]
    assert {x.name for x in schemas["mortgage"].columns} >= {"CONTROL", "MORTLINE", "MORTAMT"}
    assert {x.name for x in schemas["projects"].columns} >= {"CONTROL", "PROJECTNO", "PROJECTCOST"}


def test_typed_filters_are_coerced_and_parameterized(engine: AHSQueryEngine) -> None:
    request = QuerySpec(
        base_dataset="household",
        select=[col("household", "CONTROL"), col("household", "TENURE")],
        filters=[
            TypedFilter(
                column=QualifiedColumn(dataset="household", column="TENURE"),
                operator="eq",
                value="2",
            )
        ],
        order_by=[OrderBy(output_alias="CONTROL")],
    )
    compiled = engine.compile(request)
    assert "TENURE\" = ?" in compiled.sql
    assert compiled.parameters == [2]
    assert "= 2" in compiled.display_sql
    result = engine.execute(request)
    assert [row["CONTROL"] for row in result.rows] == [1002, 1005, 1006]
    assert result.metadata.datasets[0].synthetic_fixture is True
    assert result.metadata.variance_estimation == "NOT_IMPLEMENTED"


def test_household_to_mortgage_requires_control_preaggregation(engine: AHSQueryEngine) -> None:
    request = QuerySpec(
        base_dataset="household",
        select=[
            col("household", "CONTROL"),
            col("mortgage", "mortgage_count"),
            col("mortgage", "mortgage_total"),
        ],
        joins=[
            JoinSpec(
                dataset="mortgage",
                aggregation=ChildAggregation(
                    group_by=["CONTROL"],
                    aggregates=[
                        ChildAggregate(function="count", alias="mortgage_count"),
                        ChildAggregate(function="sum", column="MORTAMT", alias="mortgage_total"),
                    ],
                ),
            )
        ],
        order_by=[OrderBy(output_alias="CONTROL")],
    )
    result = engine.execute(request)
    by_control = {row["CONTROL"]: row for row in result.rows}
    assert by_control[1001]["mortgage_count"] == 2
    assert float(by_control[1001]["mortgage_total"]) == 205000.0
    assert by_control[1002]["mortgage_count"] is None
    assert result.metadata.join_contract_ids == ["rel_household_mortgage_control"]
    assert "GROUP BY \"CONTROL\"" in result.parameterized_sql


def test_direct_household_to_child_join_is_rejected(engine: AHSQueryEngine) -> None:
    request = QuerySpec(
        base_dataset="household",
        select=[col("household", "CONTROL")],
        joins=[JoinSpec(dataset="mortgage")],
    )
    with pytest.raises(JoinPolicyError, match="requires preaggregation"):
        engine.compile(request)


def test_wrong_child_aggregation_grain_is_rejected(engine: AHSQueryEngine) -> None:
    request = QuerySpec(
        base_dataset="household",
        select=[col("household", "CONTROL")],
        joins=[
            JoinSpec(
                dataset="mortgage",
                aggregation=ChildAggregation(
                    group_by=["CONTROL", "MORTLINE"],
                    aggregates=[ChildAggregate(function="count", alias="n")],
                ),
            )
        ],
    )
    with pytest.raises(JoinPolicyError, match="aggregated exactly"):
        engine.compile(request)


def test_mortgage_to_projects_join_is_rejected(engine: AHSQueryEngine) -> None:
    request = QuerySpec(
        base_dataset="mortgage",
        select=[col("mortgage", "CONTROL")],
        joins=[JoinSpec(dataset="projects")],
    )
    with pytest.raises(JoinPolicyError, match="No approved relationship"):
        engine.compile(request)


def test_child_to_parent_join_is_approved(engine: AHSQueryEngine) -> None:
    request = QuerySpec(
        base_dataset="mortgage",
        select=[
            col("mortgage", "CONTROL"),
            col("mortgage", "MORTLINE"),
            col("household", "TENURE"),
        ],
        joins=[JoinSpec(dataset="household", how="inner")],
        order_by=[OrderBy(output_alias="CONTROL"), OrderBy(output_alias="MORTLINE")],
    )
    result = engine.execute(request)
    assert len(result.rows) == 3
    assert result.rows[0] == {"CONTROL": 1001, "MORTLINE": 1, "TENURE": 1}


def test_unknown_column_is_rejected(engine: AHSQueryEngine) -> None:
    request = QuerySpec(
        base_dataset="household",
        select=[col("household", "NOT_A_COLUMN")],
    )
    with pytest.raises(QueryValidationError, match="Unknown column"):
        engine.compile(request)


def test_arbitrary_sql_field_is_rejected() -> None:
    payload = {
        "base_dataset": "household",
        "select": [
            {"kind": "column", "column": {"dataset": "household", "column": "CONTROL"}}
        ],
        "sql": "DROP TABLE household",
    }
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        QuerySpec.model_validate(payload)


def test_grouped_aggregate_is_deterministic(engine: AHSQueryEngine) -> None:
    request = QuerySpec(
        base_dataset="household",
        select=[
            col("household", "TENURE"),
            AggregateProjection(
                function="sum",
                column=QualifiedColumn(dataset="household", column="WEIGHT"),
                alias="weighted_total",
            ),
            AggregateProjection(function="count", alias="unweighted_n"),
        ],
        filters=[
            TypedFilter(
                column=QualifiedColumn(dataset="household", column="INTSTATUS"),
                operator="eq",
                value=1,
            )
        ],
        group_by=[QualifiedColumn(dataset="household", column="TENURE")],
        order_by=[OrderBy(output_alias="TENURE")],
    )
    result = engine.execute(request)
    assert result.rows == [
        {"TENURE": 1, "weighted_total": 21.0, "unweighted_n": 2},
        {"TENURE": 2, "weighted_total": 47.0, "unweighted_n": 3},
        {"TENURE": 3, "weighted_total": 7.0, "unweighted_n": 1},
    ]


def test_result_limit_is_hard_capped(engine: AHSQueryEngine) -> None:
    request = QuerySpec(
        base_dataset="household",
        select=[col("household", "CONTROL")],
        limit=1000,
    )
    compiled = engine.compile(request)
    assert compiled.effective_limit == 100
    assert compiled.sql.endswith("LIMIT 101")


def test_json_example_round_trip(engine: AHSQueryEngine) -> None:
    root = Path(__file__).resolve().parents[1]
    payload = json.loads((root / "examples/household_filter.json").read_text(encoding="utf-8"))
    result = engine.execute(payload)
    assert result.metadata.rows_returned == 4


def test_non_numeric_sum_is_rejected_before_execution(engine: AHSQueryEngine) -> None:
    request = QuerySpec(
        base_dataset="projects",
        select=[
            AggregateProjection(
                function="sum",
                column=QualifiedColumn(dataset="projects", column="PROJECTTYPE"),
                alias="bad_sum",
            )
        ],
    )
    with pytest.raises(QueryValidationError, match="requires a numeric column"):
        engine.compile(request)
