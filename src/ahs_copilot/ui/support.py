from __future__ import annotations

import csv
import io
import json
from dataclasses import asdict, dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Iterable, Mapping


@dataclass(frozen=True)
class SuggestedQuestion:
    question_id: str
    eyebrow: str
    title: str
    question: str
    governance_note: str


@dataclass(frozen=True)
class BlockedRequest:
    code: str
    title: str
    message: str
    details: tuple[str, ...] = ()


SUGGESTED_QUESTIONS: tuple[SuggestedQuestion, ...] = (
    SuggestedQuestion(
        question_id="cost-burden-geography",
        eyebrow="AFFORDABILITY",
        title="Renter cost burden",
        question="Compare renter cost burden in New York and Miami.",
        governance_note=(
            "Requires approved geography code-to-label mappings. The app fails closed "
            "when those mappings are absent."
        ),
    ),
    SuggestedQuestion(
        question_id="quality-tenure-structure",
        eyebrow="HOUSING QUALITY",
        title="Quality by tenure and structure",
        question="Compare housing-quality problems by tenure and structure type.",
        governance_note=(
            "The no-network lane returns a weighted raw-code distribution and does not "
            "invent category labels."
        ),
    ),
    SuggestedQuestion(
        question_id="insecurity-descriptive",
        eyebrow="HOUSING SECURITY",
        title="Housing insecurity indicators",
        question="Explain which factors are associated with housing insecurity.",
        governance_note=(
            "Reframed as descriptive distributions only; no causal or inferential claim."
        ),
    ),
)


def qcol(column: str, dataset: str = "household") -> dict[str, str]:
    return {"dataset": dataset, "column": column}


def typed_filter(column: str, operator: str, value: Any, dataset: str = "household") -> dict[str, Any]:
    return {"column": qcol(column, dataset), "operator": operator, "value": value}


def _base_plan(
    *,
    question: str,
    alias: str,
    statistic: str,
    group_columns: Iterable[str],
    required_columns: Iterable[str],
    numerator_filters: list[dict[str, Any]] | None = None,
    universe_id: str = "occupied_housing_units",
    universe_description: str = "Occupied interviewed housing units",
) -> dict[str, Any]:
    numerator_filters = list(numerator_filters or [])
    numerator_role = "condition_true" if statistic == "percentage" else "eligible_units"
    plan: dict[str, Any] = {
        "plan_version": "1.0",
        "user_question": question,
        "dataset": "household",
        "measure": {"alias": alias, "statistic": statistic},
        "numerator": {
            "role": numerator_role,
            "description": (
                "Housing units satisfying the approved numerator condition"
                if numerator_filters
                else "All housing units in the approved universe"
            ),
            "filters": numerator_filters,
        },
        "denominator": {
            "role": "eligible_units",
            "description": "All housing units in the approved universe",
            "filters": [],
        },
        "universe": {
            "universe_id": universe_id,
            "description": universe_description,
        },
        "filters": [],
        "grouping_dimensions": [qcol(column) for column in group_columns],
        "weight": {"mode": "weighted", "column": qcol("WEIGHT")},
        "required_variables": [qcol(column) for column in required_columns],
        "derived_recodes": [],
        "joins": [],
        "comparisons": {"mode": "none", "include_ratio": True},
        "output_format": {
            "format": "json_records",
            "include_analysis_plan": True,
            "include_generated_sql": True,
            "include_execution_metadata": True,
            "include_formula_metadata": True,
        },
    }
    return plan


def quality_by_tenure_structure_plan(question: str) -> dict[str, Any]:
    """Safe fallback: weighted counts by raw certified fields, without label invention."""

    return _base_plan(
        question=question,
        alias="housing_quality_units",
        statistic="count",
        group_columns=("TENURE", "BLD", "ADEQUACY"),
        required_columns=("INTSTATUS", "TENURE", "BLD", "ADEQUACY", "WEIGHT"),
    )


def insecurity_descriptive_plan(question: str) -> dict[str, Any]:
    """Descriptive reframe of an otherwise inferential/causal wording."""

    return _base_plan(
        question=question,
        alias="housing_insecurity_units",
        statistic="count",
        group_columns=("TENURE", "HIWORRY"),
        required_columns=("INTSTATUS", "TENURE", "HIWORRY", "WEIGHT"),
    )


def occupied_count_plan(question: str) -> dict[str, Any]:
    return _base_plan(
        question=question,
        alias="occupied_units",
        statistic="count",
        group_columns=(),
        required_columns=("INTSTATUS", "WEIGHT"),
    )


def high_burden_by_tenure_plan(question: str) -> dict[str, Any]:
    return _base_plan(
        question=question,
        alias="high_cost_burden_pct",
        statistic="percentage",
        group_columns=("TENURE",),
        required_columns=("INTSTATUS", "TENURE", "TOTHCPCT", "WEIGHT"),
        numerator_filters=[typed_filter("TOTHCPCT", "ge", 50)],
    )


def resolve_demo_question(question: str) -> dict[str, Any] | BlockedRequest:
    normalized = " ".join(question.lower().split())

    if ("new york" in normalized and "miami" in normalized) or (
        "cost burden" in normalized and "geograph" in normalized
    ):
        return BlockedRequest(
            code="UNRESOLVED_GEOGRAPHY_MAPPING",
            title="Geography mapping is not certified",
            message=(
                "The approved executable catalog exposes OMB13CBSA, but it does not "
                "currently certify the requested New York and Miami code-to-label mappings. "
                "This request is blocked rather than guessed."
            ),
            details=(
                "Add approved code-label mappings to the semantic metadata.",
                "Do not equate a CBSA with a city unless the metadata explicitly authorizes that wording.",
                "After the mapping is certified, rerun the request and approve the generated plan.",
            ),
        )

    if "housing-quality" in normalized or "housing quality" in normalized or "adequacy" in normalized:
        return quality_by_tenure_structure_plan(question)

    if "housing insecurity" in normalized or "associated with" in normalized:
        return insecurity_descriptive_plan(question)

    if "high" in normalized and "burden" in normalized and "tenure" in normalized:
        return high_burden_by_tenure_plan(question)

    if "occupied" in normalized and ("count" in normalized or "how many" in normalized):
        return occupied_count_plan(question)

    return BlockedRequest(
        code="NO_OFFLINE_TEMPLATE",
        title="No certified no-network template matched",
        message=(
            "The deterministic demo lane supports the three governed journeys plus a small "
            "set of basic counts. Configure a model provider for broader typed-plan generation, "
            "or revise the question to a supported descriptive request."
        ),
        details=(
            "The model may propose only an AnalysisPlan object.",
            "The deterministic validator still decides whether the plan can execute.",
        ),
    )


def to_plain(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return to_plain(value.model_dump(mode="json"))
    if isinstance(value, Mapping):
        return {str(key): to_plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [to_plain(item) for item in value]
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if hasattr(value, "__dataclass_fields__"):
        return to_plain(asdict(value))
    return value


def result_records(result: Any) -> list[dict[str, Any]]:
    payload = to_plain(result)
    if isinstance(payload, Mapping) and "result" in payload and isinstance(payload["result"], Mapping):
        payload = payload["result"]
    estimates = payload.get("estimates", []) if isinstance(payload, Mapping) else []
    records: list[dict[str, Any]] = []
    for item in estimates:
        group = item.get("group") or {}
        suppression = item.get("suppression") or {}
        record: dict[str, Any] = {
            **{str(key): value for key, value in group.items()},
            "estimate_alias": item.get("estimate_alias"),
            "statistic": item.get("statistic"),
            "estimate": item.get("estimate"),
            "weighted_numerator": item.get("weighted_numerator"),
            "weighted_denominator": item.get("weighted_denominator"),
            "unweighted_numerator": item.get("unweighted_numerator"),
            "unweighted_denominator": item.get("unweighted_denominator"),
            "missing_value_rows_excluded": item.get("missing_value_rows_excluded"),
            "suppressed": suppression.get("suppressed", False),
            "suppression_reasons": "; ".join(suppression.get("reasons") or []),
        }
        records.append(record)
    return records


def _csv_scalar(value: Any) -> Any:
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(to_plain(value), sort_keys=True)
    return value


def records_to_csv(records: list[dict[str, Any]]) -> bytes:
    if not records:
        return b""
    fieldnames: list[str] = []
    seen: set[str] = set()
    for record in records:
        for key in record:
            if key not in seen:
                fieldnames.append(key)
                seen.add(key)
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()
    for record in records:
        writer.writerow({key: _csv_scalar(value) for key, value in record.items()})
    return buffer.getvalue().encode("utf-8")


def object_to_json_bytes(value: Any) -> bytes:
    return json.dumps(to_plain(value), indent=2, sort_keys=True).encode("utf-8")


def group_label(group: Mapping[str, Any] | None) -> str:
    if not group:
        return "All eligible units"
    return " · ".join(f"{key}={value}" for key, value in group.items())


def format_estimate(value: Any, statistic: str | None) -> str:
    if value is None:
        return "Suppressed / unavailable"
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return str(value)
    if statistic == "weighted_percentage":
        return f"{numeric:,.1f}%"
    if statistic == "weighted_mean":
        return f"{numeric:,.2f}"
    return f"{numeric:,.0f}"


def plan_summary(plan: Any) -> dict[str, Any]:
    payload = to_plain(plan)
    return {
        "dataset": payload.get("dataset"),
        "measure": payload.get("measure"),
        "universe": payload.get("universe"),
        "weight": payload.get("weight"),
        "grouping_dimensions": payload.get("grouping_dimensions", []),
        "filters": payload.get("filters", []),
        "numerator_filters": (payload.get("numerator") or {}).get("filters", []),
        "required_variables": payload.get("required_variables", []),
        "joins": payload.get("joins", []),
    }
