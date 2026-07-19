from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
from typing import Any

from ahs_copilot.query_engine.contracts import FilterSpec
from ahs_copilot.query_engine.engine import AHSQueryEngine, quote_identifier, quote_literal
from ahs_copilot.query_engine.errors import QueryValidationError
from .contracts import CompiledSurveyEstimate, Condition, SurveyEstimateRequest, SurveyEstimateResult


class SurveyEstimator:
    def __init__(self, engine: AHSQueryEngine):
        self.engine = engine

    def _variable(self, dataset: str, name: str):
        record = self.engine.catalog.variable_by_key.get((dataset.casefold(), name.casefold()))
        if not record:
            raise QueryValidationError(f"Unknown approved variable '{dataset}.{name}'")
        if record.availability != "PUF":
            raise QueryValidationError(f"Variable '{dataset}.{name}' is not PUF-accessible")
        self.engine.dataset(dataset).actual_column(name)
        return record

    def _condition_sql(self, dataset_name: str, condition: Condition, alias: str, params: list[Any]) -> str:
        self._variable(dataset_name, condition.variable)
        return self.engine._compile_filter(
            self.engine.dataset(dataset_name),
            alias,
            FilterSpec(
                column=condition.variable,
                operator=condition.operator,
                value=condition.value,
                values=condition.values,
                lower=condition.lower,
                upper=condition.upper,
            ),
            params,
        )

    def compile(self, request: SurveyEstimateRequest) -> CompiledSurveyEstimate:
        dataset = self.engine.dataset(request.dataset)
        universe = self.engine.catalog.universe_by_id.get(request.universe_id)
        if not universe:
            raise QueryValidationError(f"Unknown universe_id: {request.universe_id}")
        if universe.dataset != request.dataset:
            raise QueryValidationError(
                f"Universe '{request.universe_id}' does not belong to dataset '{request.dataset}'"
            )
        weight = self.engine.catalog.weight_by_id.get(request.weight_id)
        if not weight:
            raise QueryValidationError(f"Unknown weight_id: {request.weight_id}")
        if weight.dataset != request.dataset or weight.availability != "PUF":
            raise QueryValidationError(f"Weight '{request.weight_id}' is not approved for this PUF dataset")

        params: list[Any] = []
        alias = "b"
        universe_conditions = [Condition.model_validate(x.model_dump()) for x in universe.conditions]
        denominator_conditions = [*universe_conditions, *request.denominator_conditions]
        denominator_parts = [self._condition_sql(request.dataset, x, alias, params) for x in denominator_conditions]
        denominator_sql = " AND ".join(denominator_parts) if denominator_parts else "TRUE"

        # Parameter order must follow SQL appearance. Build numerator with a separate list, then append.
        numerator_params: list[Any] = []
        numerator_parts = [
            self._condition_sql(request.dataset, x, alias, numerator_params)
            for x in [*denominator_conditions, *request.numerator_conditions]
        ]
        numerator_sql = " AND ".join(numerator_parts) if numerator_parts else denominator_sql

        if weight.variable is None:
            weight_sql = "CAST(1 AS DECIMAL(38, 6))"
        else:
            weight_record = self._variable(request.dataset, weight.variable)
            actual_weight = dataset.actual_column(weight.variable)
            weight_sql = f"CAST({quote_identifier(alias)}.{quote_identifier(actual_weight)} AS DECIMAL(38, 6))"

        group_selects: list[str] = []
        group_exprs: list[str] = []
        for name in request.grouping_dimensions:
            self._variable(request.dataset, name)
            actual = dataset.actual_column(name)
            expr = f"{quote_identifier(alias)}.{quote_identifier(actual)}"
            group_exprs.append(expr)
            group_selects.append(f"{expr} AS {quote_identifier(name)}")

        if request.measure == "mean":
            value_record = self._variable(request.dataset, request.value_variable or "")
            actual_value = dataset.actual_column(request.value_variable or "")
            value_ref = f"{quote_identifier(alias)}.{quote_identifier(actual_value)}"
            valid_value = f"{value_ref} IS NOT NULL"
            if value_record.missing_codes:
                valid_value += " AND " + value_ref + " NOT IN (" + ",".join(
                    quote_literal(str(x)) if isinstance(x, str) else str(x) for x in value_record.missing_codes
                ) + ")"
            denominator_sql = f"({denominator_sql}) AND ({valid_value})"

        select_prefix = (", ".join(group_selects) + ", ") if group_selects else ""
        if request.measure == "count":
            metric_sql = (
                f"SUM(CASE WHEN {denominator_sql} THEN {weight_sql} ELSE 0 END) AS weighted_numerator, "
                f"SUM(CASE WHEN {denominator_sql} THEN {weight_sql} ELSE 0 END) AS weighted_denominator, "
                f"COUNT(*) FILTER (WHERE {denominator_sql}) AS unweighted_denominator"
            )
            final_params = params + params + params
        elif request.measure == "percentage":
            metric_sql = (
                f"SUM(CASE WHEN {numerator_sql} THEN {weight_sql} ELSE 0 END) AS weighted_numerator, "
                f"SUM(CASE WHEN {denominator_sql} THEN {weight_sql} ELSE 0 END) AS weighted_denominator, "
                f"COUNT(*) FILTER (WHERE {denominator_sql}) AS unweighted_denominator"
            )
            final_params = numerator_params + params + params
        else:
            actual_value = dataset.actual_column(request.value_variable or "")
            value_ref = f"CAST({quote_identifier(alias)}.{quote_identifier(actual_value)} AS DECIMAL(38, 6))"
            metric_sql = (
                f"SUM(CASE WHEN {denominator_sql} THEN {weight_sql} * {value_ref} ELSE 0 END) AS weighted_numerator, "
                f"SUM(CASE WHEN {denominator_sql} THEN {weight_sql} ELSE 0 END) AS weighted_denominator, "
                f"COUNT(*) FILTER (WHERE {denominator_sql}) AS unweighted_denominator"
            )
            final_params = params + params + params

        sql = (
            f"SELECT {select_prefix}{metric_sql} "
            f"FROM {quote_identifier(dataset.view_name)} AS {quote_identifier(alias)}"
        )
        if group_exprs:
            sql += " GROUP BY " + ", ".join(group_exprs)
            sql += " ORDER BY " + ", ".join(group_exprs)

        display = sql
        for value in final_params:
            replacement = quote_literal(str(value)) if isinstance(value, str) else str(value)
            display = display.replace("?", replacement, 1)
        payload = json.dumps({"sql":sql,"parameters":final_params}, sort_keys=True, default=str).encode()
        return CompiledSurveyEstimate(
            sql=sql,
            display_sql=display,
            parameters=final_params,
            request_fingerprint=sha256(payload).hexdigest(),
            dataset=request.dataset,
            universe_id=request.universe_id,
            weight_id=request.weight_id,
        )

    def execute(self, request: SurveyEstimateRequest) -> SurveyEstimateResult:
        compiled = self.compile(request)
        columns, rows, elapsed = self.engine._execute_sql(compiled.sql, compiled.parameters)
        threshold = (
            request.minimum_unweighted_n
            if request.minimum_unweighted_n is not None
            else self.engine.config.minimum_unweighted_n
        )
        estimates: list[dict[str, Any]] = []
        for row in rows:
            numerator = float(row["weighted_numerator"] or 0)
            denominator = float(row["weighted_denominator"] or 0)
            unweighted = int(row["unweighted_denominator"] or 0)
            flags: list[str] = []
            status = "OK"
            estimate = None
            if denominator == 0:
                flags.append("EMPTY_DENOMINATOR")
                status = "UNDEFINED"
            else:
                if request.measure == "count":
                    estimate = numerator
                elif request.measure == "percentage":
                    estimate = numerator / denominator * 100.0
                else:
                    estimate = numerator / denominator
            if unweighted < threshold:
                flags.append("SMALL_UNWEIGHTED_CELL")
                status = "SUPPRESSED"
                if self.engine.config.null_suppressed_estimates:
                    estimate = None
            groups = {k:v for k,v in row.items() if k not in {"weighted_numerator","weighted_denominator","unweighted_denominator"}}
            estimates.append({
                "groups": groups,
                "estimate": estimate,
                "measure": request.measure,
                "weighted_numerator": numerator,
                "weighted_denominator": denominator,
                "unweighted_denominator": unweighted,
                "status": status,
                "flags": flags,
            })
        return SurveyEstimateResult(
            request=request,
            estimates=estimates,
            compiled=compiled,
            execution_metadata={
                "elapsed_ms": round(elapsed, 3),
                "executed_at": datetime.now(timezone.utc).isoformat(),
                "source_file_id": self.engine.dataset(request.dataset).schema.source_file_id,
                "physical_path": self.engine.dataset(request.dataset).schema.physical_path,
                "universe_id": request.universe_id,
                "weight_id": request.weight_id,
                "denominator_is_explicit": True,
            },
            variance={
                "status": "NOT_ESTIMATED",
                "replicate_weights_used": False,
                "approved_method": None,
                "standard_errors_valid": False,
                "standard_error": None,
                "confidence_interval": None,
                "p_value": None,
            },
        )
