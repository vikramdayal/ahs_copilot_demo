from __future__ import annotations

import json
from decimal import Decimal

from ahs_copilot.ui.support import (
    BlockedRequest,
    SUGGESTED_QUESTIONS,
    format_estimate,
    insecurity_descriptive_plan,
    quality_by_tenure_structure_plan,
    records_to_csv,
    resolve_demo_question,
    result_records,
)


def test_three_frozen_questions_are_exposed() -> None:
    assert [item.question for item in SUGGESTED_QUESTIONS] == [
        "Compare renter cost burden in New York and Miami.",
        "Compare housing-quality problems by tenure and structure type.",
        "Explain which factors are associated with housing insecurity.",
    ]


def test_geography_question_fails_closed_without_mapping() -> None:
    resolved = resolve_demo_question("Compare renter cost burden in New York and Miami.")
    assert isinstance(resolved, BlockedRequest)
    assert resolved.code == "UNRESOLVED_GEOGRAPHY_MAPPING"
    assert "blocked" in resolved.message.lower()


def test_quality_plan_uses_raw_approved_fields() -> None:
    plan = quality_by_tenure_structure_plan(
        "Compare housing-quality problems by tenure and structure type."
    )
    assert plan["dataset"] == "household"
    assert plan["measure"]["statistic"] == "count"
    assert [item["column"] for item in plan["grouping_dimensions"]] == [
        "TENURE",
        "BLD",
        "ADEQUACY",
    ]
    assert plan["universe"]["universe_id"] == "occupied_housing_units"
    assert plan["weight"]["column"]["column"] == "WEIGHT"
    assert "sql" not in plan
    assert "query" not in plan


def test_insecurity_request_is_descriptive_not_inferential() -> None:
    plan = insecurity_descriptive_plan(
        "Explain which factors are associated with housing insecurity."
    )
    assert plan["measure"]["statistic"] == "count"
    assert plan["comparisons"]["mode"] == "none"
    assert [item["column"] for item in plan["grouping_dimensions"]] == [
        "TENURE",
        "HIWORRY",
    ]


def test_result_exports_flatten_estimate_rows() -> None:
    payload = {
        "estimates": [
            {
                "group": {"TENURE": 2},
                "estimate_alias": "high_cost_burden_pct",
                "statistic": "weighted_percentage",
                "estimate": Decimal("57.5"),
                "weighted_numerator": Decimal("23"),
                "weighted_denominator": Decimal("40"),
                "unweighted_numerator": 2,
                "unweighted_denominator": 3,
                "missing_value_rows_excluded": 0,
                "suppression": {"suppressed": False, "reasons": []},
            }
        ]
    }
    records = result_records(payload)
    assert records[0]["TENURE"] == 2
    assert records[0]["estimate"] == "57.5"
    csv_bytes = records_to_csv(records)
    assert b"TENURE" in csv_bytes
    assert b"57.5" in csv_bytes


def test_metric_formatting() -> None:
    assert format_estimate("12.34", "weighted_percentage") == "12.3%"
    assert format_estimate("1234.4", "weighted_count") == "1,234"
    assert format_estimate(None, "weighted_count") == "Suppressed / unavailable"
