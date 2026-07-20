from __future__ import annotations

import copy
import csv
import hashlib
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


COMPARISON_DIMENSIONS: dict[str, dict[str, str]] = {
    "geography": {
        "column": "OMB13CBSA",
        "label": "Geography (raw OMB13CBSA code)",
    },
    "tenure": {
        "column": "TENURE",
        "label": "Tenure",
    },
    "structure_type": {
        "column": "BLD",
        "label": "Structure type (raw BLD code)",
    },
    "year_built": {
        "column": "YRBUILT",
        "label": "Year-built group",
    },
}

TENURE_LABELS: dict[int, str] = {
    1: "Owner occupied",
    2: "Renter occupied",
    3: "Occupied without payment",
}

YEAR_BUILT_PRESETS: dict[str, tuple[int | None, int | None]] = {
    "All approved years": (None, None),
    "2010 or later": (2010, None),
    "2000–2009": (2000, 2009),
    "1990–1999": (1990, 1999),
    "1980–1989": (1980, 1989),
    "1960–1979": (1960, 1979),
    "Before 1960": (None, 1959),
}


@dataclass(frozen=True)
class ComparisonPlanMutation:
    """Filter-only clone of an already approved AnalysisPlan."""

    plan: dict[str, Any]
    changed_columns: tuple[str, ...]
    selections: dict[str, Any]
    base_contract_fingerprint: str
    modified_contract_fingerprint: str

    @property
    def contract_preserved(self) -> bool:
        return self.base_contract_fingerprint == self.modified_contract_fingerprint


def _catalog_payload(catalog: Mapping[str, Any] | str | None) -> Mapping[str, Any]:
    if catalog is None:
        return {}
    if isinstance(catalog, Mapping):
        return catalog
    with open(catalog, encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, Mapping):
        raise ValueError("Semantic catalog must contain a JSON object")
    return payload


def approved_catalog_columns(
    catalog: Mapping[str, Any] | str | None,
    *,
    dataset: str = "household",
) -> set[str]:
    """Return executable PUF variable names without inferring missing metadata."""

    payload = _catalog_payload(catalog)
    approved: set[str] = set()
    for item in payload.get("variables", []) or []:
        if not isinstance(item, Mapping):
            continue
        if str(item.get("dataset", "")).lower() != dataset.lower():
            continue
        if str(item.get("access_level", "")).upper() != "PUF":
            continue
        name = str(item.get("name", "")).upper()
        if name:
            approved.add(name)
    return approved


def comparison_capabilities(
    plan: Any,
    catalog: Mapping[str, Any] | str | None,
) -> dict[str, dict[str, Any]]:
    payload = to_plain(plan)
    dataset = str(payload.get("dataset") or "household")
    approved = approved_catalog_columns(catalog, dataset=dataset)
    result: dict[str, dict[str, Any]] = {}
    for dimension_id, spec in COMPARISON_DIMENSIONS.items():
        column = spec["column"]
        result[dimension_id] = {
            **spec,
            "enabled": column.upper() in approved,
            "reason": (
                None
                if column.upper() in approved
                else f"{column} is not approved in the executable {dataset} catalog."
            ),
        }
    return result


def parse_integer_codes(value: str | Iterable[Any] | None) -> list[int]:
    if value is None:
        return []
    if isinstance(value, str):
        tokens = [item.strip() for item in value.split(",") if item.strip()]
    else:
        tokens = list(value)
    codes: list[int] = []
    for token in tokens:
        try:
            code = int(token)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Comparison codes must be integers; received {token!r}.") from exc
        if code not in codes:
            codes.append(code)
    return codes


def _comparison_contract_payload(plan: Any) -> dict[str, Any]:
    """Remove only workspace-managed filters and their required-variable closure."""

    payload = copy.deepcopy(to_plain(plan))
    managed = {item["column"] for item in COMPARISON_DIMENSIONS.values()}
    payload["filters"] = [
        item
        for item in payload.get("filters", [])
        if str((item.get("column") or {}).get("column", "")).upper() not in managed
    ]
    payload["required_variables"] = [
        item
        for item in payload.get("required_variables", [])
        if str(item.get("column", "")).upper() not in managed
    ]
    return payload


def comparison_contract_fingerprint(plan: Any) -> str:
    canonical = json.dumps(
        _comparison_contract_payload(plan),
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def comparison_cache_key(base_plan_fingerprint: str, selections: Mapping[str, Any]) -> str:
    canonical = json.dumps(
        {"base_plan_fingerprint": base_plan_fingerprint, "selections": to_plain(selections)},
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _managed_filter_signature(filters: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    managed = {item["column"] for item in COMPARISON_DIMENSIONS.values()}
    result: dict[str, Any] = {}
    for item in filters:
        column = str((item.get("column") or {}).get("column", "")).upper()
        if column in managed:
            result[column] = {
                "operator": item.get("operator"),
                "value": to_plain(item.get("value")),
            }
    return result


def build_comparison_plan(
    base_plan: Any,
    selections: Mapping[str, Any],
    *,
    approved_columns: set[str] | None = None,
) -> ComparisonPlanMutation:
    """Clone a validated plan and replace only approved top-level comparison filters.

    The user question, measure, numerator, denominator, universe, weight, joins,
    recodes, grouping dimensions, output contract, and validation checks are kept
    byte-for-byte equivalent after canonical serialization.
    """

    base = copy.deepcopy(to_plain(base_plan))
    if not isinstance(base, dict):
        raise TypeError("base_plan must serialize to a mapping")
    approved = {item.upper() for item in approved_columns} if approved_columns is not None else None
    existing_filters = list(base.get("filters", []) or [])
    managed_columns = {item["column"] for item in COMPARISON_DIMENSIONS.values()}
    preserved_filters = [
        item
        for item in existing_filters
        if str((item.get("column") or {}).get("column", "")).upper() not in managed_columns
    ]
    replacement_filters: list[dict[str, Any]] = []
    normalized: dict[str, Any] = {}

    for dimension_id in ("geography", "tenure", "structure_type"):
        column = COMPARISON_DIMENSIONS[dimension_id]["column"]
        codes = parse_integer_codes(selections.get(dimension_id))
        normalized[dimension_id] = codes
        if not codes:
            continue
        if approved is not None and column.upper() not in approved:
            raise ValueError(f"{column} is not approved in the executable catalog.")
        replacement_filters.append(typed_filter(column, "in", codes, str(base.get("dataset", "household"))))

    year_selection = selections.get("year_built") or {}
    if not isinstance(year_selection, Mapping):
        raise ValueError("year_built selection must be an object containing min and max")
    minimum = year_selection.get("min")
    maximum = year_selection.get("max")
    minimum = int(minimum) if minimum not in (None, "") else None
    maximum = int(maximum) if maximum not in (None, "") else None
    if minimum is not None and maximum is not None and minimum > maximum:
        raise ValueError("Year-built minimum cannot exceed maximum.")
    normalized["year_built"] = {"min": minimum, "max": maximum}
    if minimum is not None or maximum is not None:
        column = COMPARISON_DIMENSIONS["year_built"]["column"]
        if approved is not None and column.upper() not in approved:
            raise ValueError(f"{column} is not approved in the executable catalog.")
        if minimum is not None and maximum is not None:
            replacement_filters.append(
                typed_filter(column, "between", [minimum, maximum], str(base.get("dataset", "household")))
            )
        elif minimum is not None:
            replacement_filters.append(
                typed_filter(column, "ge", minimum, str(base.get("dataset", "household")))
            )
        else:
            replacement_filters.append(
                typed_filter(column, "le", maximum, str(base.get("dataset", "household")))
            )

    modified = copy.deepcopy(base)
    modified["filters"] = preserved_filters + replacement_filters
    required = list(modified.get("required_variables", []) or [])
    seen = {
        (str(item.get("dataset", "")).lower(), str(item.get("column", "")).upper())
        for item in required
    }
    for item in replacement_filters:
        qcolumn = item["column"]
        key = (str(qcolumn["dataset"]).lower(), str(qcolumn["column"]).upper())
        if key not in seen:
            required.append(qcolumn)
            seen.add(key)
    modified["required_variables"] = required

    before = _managed_filter_signature(existing_filters)
    after = _managed_filter_signature(modified["filters"])
    changed_columns = tuple(sorted(set(before) | set(after), key=str))
    changed_columns = tuple(column for column in changed_columns if before.get(column) != after.get(column))
    mutation = ComparisonPlanMutation(
        plan=modified,
        changed_columns=changed_columns,
        selections=normalized,
        base_contract_fingerprint=comparison_contract_fingerprint(base),
        modified_contract_fingerprint=comparison_contract_fingerprint(modified),
    )
    if not mutation.contract_preserved:
        raise AssertionError("Comparison mutation changed the approved analysis contract.")
    if modified.get("user_question") != base.get("user_question"):
        raise AssertionError("Comparison mutation changed the original research question.")
    return mutation


def comparison_selections_from_plan(plan: Any) -> dict[str, Any]:
    """Extract workspace selections from an existing plan's managed filters."""

    payload = to_plain(plan)
    by_column = {
        spec["column"]: dimension_id for dimension_id, spec in COMPARISON_DIMENSIONS.items()
    }
    selections: dict[str, Any] = {
        "geography": [],
        "tenure": [],
        "structure_type": [],
        "year_built": {"min": None, "max": None},
    }
    for item in payload.get("filters", []) or []:
        column = str((item.get("column") or {}).get("column", "")).upper()
        dimension_id = by_column.get(column)
        if dimension_id is None:
            continue
        operator = item.get("operator")
        value = item.get("value")
        if dimension_id != "year_built":
            if operator == "eq":
                selections[dimension_id] = parse_integer_codes([value])
            elif operator == "in":
                selections[dimension_id] = parse_integer_codes(value)
            continue
        if operator == "between" and isinstance(value, list) and len(value) == 2:
            selections["year_built"] = {"min": int(value[0]), "max": int(value[1])}
        elif operator == "ge":
            selections["year_built"]["min"] = int(value)
        elif operator == "le":
            selections["year_built"]["max"] = int(value)
        elif operator == "eq":
            selections["year_built"] = {"min": int(value), "max": int(value)}
    return selections
