from __future__ import annotations

import json
from decimal import Decimal

from ahs_copilot.ui.support import (
    BlockedRequest,
    approved_catalog_columns,
    build_comparison_plan,
    build_trust_disclosure,
    comparison_cache_key,
    comparison_capabilities,
    comparison_selections_from_plan,
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



def test_comparison_plan_changes_only_managed_filters() -> None:
    base = quality_by_tenure_structure_plan(
        "Compare housing-quality problems by tenure and structure type."
    )
    base["filters"] = [
        {"column": {"dataset": "household", "column": "ADEQUACY"}, "operator": "in", "value": [1, 2]}
    ]
    mutation = build_comparison_plan(
        base,
        {
            "geography": [35620, 33100],
            "tenure": [2],
            "structure_type": [2, 3],
            "year_built": {"min": None, "max": None},
        },
        approved_columns={"ADEQUACY", "OMB13CBSA", "TENURE", "BLD"},
    )
    assert mutation.contract_preserved
    assert mutation.plan["user_question"] == base["user_question"]
    assert mutation.plan["measure"] == base["measure"]
    assert mutation.plan["universe"] == base["universe"]
    assert mutation.plan["weight"] == base["weight"]
    assert set(mutation.changed_columns) == {"BLD", "OMB13CBSA", "TENURE"}
    filters = {
        item["column"]["column"]: item for item in mutation.plan["filters"]
    }
    assert filters["ADEQUACY"]["value"] == [1, 2]
    assert filters["OMB13CBSA"]["operator"] == "in"
    assert filters["OMB13CBSA"]["value"] == [35620, 33100]
    assert filters["TENURE"]["value"] == [2]
    assert filters["BLD"]["value"] == [2, 3]
    assert "sql" not in mutation.plan


def test_comparison_plan_rejects_unapproved_year_built() -> None:
    base = quality_by_tenure_structure_plan("Housing quality comparison")
    try:
        build_comparison_plan(
            base,
            {
                "geography": [],
                "tenure": [],
                "structure_type": [],
                "year_built": {"min": 2000, "max": 2009},
            },
            approved_columns={"TENURE", "BLD"},
        )
    except ValueError as exc:
        assert "YRBUILT" in str(exc)
    else:
        raise AssertionError("Unapproved YRBUILT filter should fail closed")


def test_comparison_capabilities_are_catalog_driven() -> None:
    base = quality_by_tenure_structure_plan("Housing quality comparison")
    catalog = {
        "variables": [
            {"dataset": "household", "name": "TENURE", "access_level": "PUF"},
            {"dataset": "household", "name": "BLD", "access_level": "PUF"},
            {"dataset": "household", "name": "OMB13CBSA", "access_level": "PUF"},
            {"dataset": "household", "name": "YRBUILT", "access_level": "IUF"},
        ]
    }
    assert approved_catalog_columns(catalog) == {"TENURE", "BLD", "OMB13CBSA"}
    capabilities = comparison_capabilities(base, catalog)
    assert capabilities["geography"]["enabled"] is True
    assert capabilities["tenure"]["enabled"] is True
    assert capabilities["structure_type"]["enabled"] is True
    assert capabilities["year_built"]["enabled"] is False


def test_comparison_selections_round_trip_and_cache_key_is_stable() -> None:
    base = quality_by_tenure_structure_plan("Housing quality comparison")
    mutation = build_comparison_plan(
        base,
        {
            "geography": "35620, 33100, 35620",
            "tenure": [2],
            "structure_type": [],
            "year_built": {"min": None, "max": None},
        },
        approved_columns={"OMB13CBSA", "TENURE", "BLD"},
    )
    extracted = comparison_selections_from_plan(mutation.plan)
    assert extracted["geography"] == [35620, 33100]
    assert extracted["tenure"] == [2]
    key1 = comparison_cache_key("base-fingerprint", mutation.selections)
    key2 = comparison_cache_key("base-fingerprint", dict(reversed(list(mutation.selections.items()))))
    assert key1 == key2


def test_trust_disclosure_exposes_required_governance_fields() -> None:
    from types import SimpleNamespace

    plan = quality_by_tenure_structure_plan(
        "Compare housing-quality problems by tenure and structure type."
    )
    result = SimpleNamespace(
        validated_plan={
            "plan": plan,
            "plan_fingerprint": "plan-fingerprint",
            "normalized_universe_id": "occupied_housing_units",
            "validation_messages": ["PLAN_SCHEMA_VALID", "WEIGHT_MODE_COMPATIBLE"],
            "survey_request": {
                "universe_filters": [
                    {
                        "column": {"dataset": "household", "column": "INTSTATUS"},
                        "operator": "eq",
                        "value": 1,
                    }
                ]
            },
        },
        plan=plan,
        compiled={
            "formulas": [
                {
                    "estimate_alias": "housing_quality_units",
                    "numerator_formula": "sum(w_i * I_i)",
                    "denominator_formula": "sum(w_i * D_i)",
                    "estimate_formula": "sum(w_i * I_i)",
                }
            ]
        },
        result_checks={
            "passed": True,
            "checks": [
                {
                    "check_id": "PLAN_FINGERPRINT_MATCH",
                    "passed": True,
                    "message": "Execution plan fingerprint matches.",
                }
            ],
        },
        result_critique={
            "decision": "approve",
            "checks": [
                {
                    "check_id": "REFERENCE_ESTIMATE_CONSISTENCY",
                    "status": "not_applicable",
                    "message": "No approved reference estimates were supplied.",
                    "details": {},
                }
            ],
        },
    )
    payload = {
        "estimates": [
            {
                "estimate_alias": "housing_quality_units",
                "unweighted_denominator": 3,
                "weighted_denominator": "47.0",
                "missing_value_rows_excluded": 0,
            }
        ],
        "metadata": {
            "weight_column": "household.WEIGHT",
            "weight_eligibility_rule": "weight IS NOT NULL AND weight > 0",
            "arithmetic_rule": "Decimal component sums",
            "request_fingerprint": "request-fingerprint",
            "sql_fingerprint": "sql-fingerprint",
        },
    }

    disclosure = build_trust_disclosure(result, payload)

    assert disclosure["universe"]["universe_id"] == "occupied_housing_units"
    assert disclosure["universe"]["resolved_filters"][0]["column"]["column"] == "INTSTATUS"
    assert disclosure["denominator"]["role"] == "eligible_units"
    assert disclosure["denominator"]["formula"] == "sum(w_i * D_i)"
    assert disclosure["denominator"]["observed_values"]["weighted"] == ["47.0"]
    assert disclosure["survey_weight"]["selected_column"] == "household.WEIGHT"
    assert disclosure["survey_weight"]["eligibility_rule"] == "weight IS NOT NULL AND weight > 0"
    assert any(item["type"] == "deterministic_formula" for item in disclosure["transformations"])
    assert disclosure["validation"]["overall_status"] == "passed"
    assert disclosure["reference_comparison"]["status"] == "not_performed"
    assert disclosure["assumptions"]["recorded"] is False
    assert disclosure["assumptions"]["status"] == "NO_RECORDED_ASSUMPTIONS"


def test_trust_disclosure_reports_explicit_assumptions_and_reference_failure() -> None:
    from types import SimpleNamespace

    plan = quality_by_tenure_structure_plan("Housing quality comparison")
    plan["assumptions"] = ["Approved test-only assumption"]
    result = SimpleNamespace(
        validated_plan={"plan": plan, "validation_messages": []},
        plan=plan,
        compiled={"formulas": []},
        result_checks={"checks": []},
        result_critique={
            "decision": "reject",
            "checks": [
                {
                    "check_id": "REFERENCE_ESTIMATE_MATCH[0]",
                    "status": "failed",
                    "message": "Reference estimate did not match.",
                    "details": {"source_id": "approved-reference"},
                }
            ],
        },
    )

    disclosure = build_trust_disclosure(result, {"estimates": [], "metadata": {}})

    assert disclosure["reference_comparison"]["status"] == "failed"
    assert disclosure["assumptions"]["recorded"] is True
    assert disclosure["assumptions"]["records"][0]["value"] == ["Approved test-only assumption"]
