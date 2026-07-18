from __future__ import annotations

import itertools
import time
import uuid
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_EVEN
from typing import Any

from ahs_copilot.query_engine.engine import (
    AHSQueryEngine,
    Namespace,
    QueryContext,
    _NUMERIC_TYPES,
    _canonical_json,
    _quote_identifier,
    _render_display_sql,
    _sha256_text,
)
from ahs_copilot.query_engine.errors import QueryValidationError, ResultLimitError
from ahs_copilot.query_engine.models import QualifiedColumn, TypedFilter

from .models import (
    CompiledSurveyEstimate,
    DatasetEstimateMetadata,
    EstimateDefinition,
    FormulaDescriptor,
    GroupComparison,
    MissingValueRule,
    SuppressionDecision,
    SuppressionPolicy,
    SurveyEstimate,
    SurveyEstimateRequest,
    SurveyEstimateResult,
    SurveyExecutionMetadata,
)


class SurveyEstimator:
    """Deterministic descriptive survey estimates over a governed AHS rowset."""

    def __init__(self, engine: AHSQueryEngine) -> None:
        self.engine = engine

    def _policy(self, request: SurveyEstimateRequest) -> SuppressionPolicy:
        if request.suppression is not None:
            return request.suppression
        configured = self.engine.config.survey.suppression
        return SuppressionPolicy.model_validate(configured.model_dump())

    def _resolve_weight(
        self, request: SurveyEstimateRequest, context: QueryContext
    ) -> tuple[QualifiedColumn | None, Namespace, str]:
        if context.base.schema.grain != "HOUSING_UNIT":
            raise QueryValidationError(
                "This descriptive estimator currently requires a HOUSING_UNIT base dataset; "
                "child-grain weights are not certified"
            )
        namespace = context.namespaces[context.base.logical_name]
        if request.weighting_mode == "unweighted":
            return None, namespace, "1"
        weight = request.weight or QualifiedColumn(
            dataset=context.base.logical_name,
            column=self.engine.config.survey.default_weight_column,
        )
        runtime = self.engine._runtime(weight.dataset)
        if runtime.logical_name != context.base.logical_name:
            raise QueryValidationError("The survey weight must belong to the base housing-unit dataset")
        duckdb_type = self.engine._column_type(namespace, weight.column)
        if not duckdb_type.upper().startswith(_NUMERIC_TYPES):
            raise QueryValidationError(f"Survey weight must be numeric; received {duckdb_type}")
        ref = f"{_quote_identifier(namespace.alias)}.{_quote_identifier(weight.column)}"
        return QualifiedColumn(dataset=context.base.logical_name, column=weight.column), namespace, ref

    def _column_ref(
        self, column: QualifiedColumn, namespaces: dict[str, Namespace]
    ) -> tuple[str, str, str]:
        runtime = self.engine._runtime(column.dataset)
        namespace = namespaces.get(runtime.logical_name)
        if namespace is None:
            raise QueryValidationError(
                f"Column references dataset {column.dataset!r}, which is not in the estimate request"
            )
        duckdb_type = self.engine._column_type(namespace, column.column)
        ref = f"{_quote_identifier(namespace.alias)}.{_quote_identifier(column.column)}"
        return runtime.logical_name, duckdb_type, ref

    def _compile_filters(
        self,
        filters: list[TypedFilter],
        namespaces: dict[str, Namespace],
        parameters: list[Any],
    ) -> str:
        if not filters:
            return "TRUE"
        return " AND ".join(
            f"({self.engine._compile_filter(item, namespaces, parameters)})" for item in filters
        )

    def _decimal_cast(self, ref: str) -> str:
        options = self.engine.config.survey
        return f"CAST({ref} AS DECIMAL({options.decimal_precision},{options.decimal_scale}))"

    def _product_decimal_cast(self, left_ref: str, right_ref: str) -> tuple[str, str]:
        """Return a widened fixed-point product and a same-typed zero literal."""

        options = self.engine.config.survey
        precision = min(38, options.decimal_precision * 2)
        scale = min(precision - 1, options.decimal_scale * 2)
        # DuckDB can overflow while multiplying two DECIMAL(18, s) operands before
        # an outer widening cast is applied. Normalize each row's numeric product
        # into the widened fixed-point type, then SUM those decimal row products.
        product = (
            f"CAST(CAST({left_ref} AS DOUBLE) * CAST({right_ref} AS DOUBLE) "
            f"AS DECIMAL({precision},{scale}))"
        )
        zero = f"CAST(0 AS DECIMAL({precision},{scale}))"
        return product, zero

    def _valid_weight_condition(self, weight_ref: str, weighting_mode: str) -> str:
        if weighting_mode == "unweighted":
            return "TRUE"
        if self.engine.config.survey.positive_weights_only:
            return f"({weight_ref} IS NOT NULL AND {weight_ref} > 0)"
        return f"({weight_ref} IS NOT NULL)"

    def _group_parts(
        self, request: SurveyEstimateRequest, context: QueryContext
    ) -> tuple[list[str], list[str], list[str], dict[str, tuple[str, str]]]:
        select_parts: list[str] = []
        group_refs: list[str] = []
        aliases: list[str] = []
        metadata: dict[str, tuple[str, str]] = {}
        for item in request.group_by:
            _, duckdb_type, ref = self._column_ref(item.column, context.namespaces)
            alias = item.alias or item.column.column
            select_parts.append(f"{ref} AS {_quote_identifier(alias)}")
            group_refs.append(ref)
            aliases.append(alias)
            metadata[alias] = (duckdb_type, item.column.column)
        return select_parts, group_refs, aliases, metadata

    def _normalize_reference_group(
        self,
        request: SurveyEstimateRequest,
        group_metadata: dict[str, tuple[str, str]],
    ) -> dict[str, Any] | None:
        if request.comparisons.mode != "reference":
            return None
        assert request.comparisons.reference_group is not None
        expected = set(group_metadata)
        actual = set(request.comparisons.reference_group)
        if actual != expected:
            raise QueryValidationError(
                f"reference_group keys must exactly match group aliases {sorted(expected)}; "
                f"received {sorted(actual)}"
            )
        normalized: dict[str, Any] = {}
        for alias, value in request.comparisons.reference_group.items():
            duckdb_type, _ = group_metadata[alias]
            normalized[alias] = self.engine._coerce_scalar(duckdb_type, value)
        return normalized

    def _formula(
        self, definition: EstimateDefinition, weighting_mode: str
    ) -> FormulaDescriptor:
        positive_only = self.engine.config.survey.positive_weights_only
        if weighting_mode == "unweighted":
            weight_rule = "Each eligible row receives deterministic unit weight 1."
            if definition.statistic == "weighted_count":
                estimate_formula = "sum(I_i)"
                numerator = "sum(I_i)"
                denominator = "sum(D_i), reported for audit but not used in the count formula"
                missing = "Rows failing the numerator condition contribute zero; declared missing values are excluded."
            elif definition.statistic == "weighted_percentage":
                estimate_formula = "100 * sum(I_i) / sum(D_i)"
                numerator = "sum(I_i)"
                denominator = "sum(D_i)"
                missing = "Numerator is evaluated within the denominator after declared missing-value exclusions."
            else:
                estimate_formula = "sum(y_i) / n over nonmissing y_i"
                numerator = "sum(y_i) over nonmissing y_i"
                denominator = "n over nonmissing y_i"
                missing = "Rows with null or declared missing y_i are excluded from both terms."
        else:
            weight_rule = (
                "Only non-null positive weights are eligible."
                if positive_only
                else "Only non-null weights are eligible; zero and negative weights are retained by configuration."
            )
            if definition.statistic == "weighted_count":
                estimate_formula = "sum(w_i * I_i)"
                numerator = "sum(w_i * I_i)"
                denominator = "sum(w_i * D_i), reported for audit but not used in the count formula"
                missing = "Rows failing the numerator condition contribute zero; declared missing values and ineligible weights are excluded."
            elif definition.statistic == "weighted_percentage":
                estimate_formula = "100 * sum(w_i * I_i) / sum(w_i * D_i)"
                numerator = "sum(w_i * I_i)"
                denominator = "sum(w_i * D_i)"
                missing = "Numerator is evaluated within the denominator after declared missing-value exclusions."
            else:
                estimate_formula = "sum(w_i * y_i) / sum(w_i) over nonmissing y_i"
                numerator = "sum(w_i * y_i) over nonmissing y_i"
                denominator = "sum(w_i) over nonmissing y_i"
                missing = "Rows with null or declared missing y_i, or ineligible weights, are excluded from both terms."
        return FormulaDescriptor(
            estimate_alias=definition.alias,
            statistic=definition.statistic,
            numerator_formula=numerator,
            denominator_formula=denominator,
            estimate_formula=estimate_formula,
            missing_value_rule=missing,
            weight_rule=weight_rule,
        )

    def compile(
        self, request: SurveyEstimateRequest | dict[str, Any]
    ) -> CompiledSurveyEstimate:
        if not isinstance(request, SurveyEstimateRequest):
            request = SurveyEstimateRequest.model_validate(request)
        context = self.engine._build_query_context(request.base_dataset, request.joins)
        weight, _, weight_ref = self._resolve_weight(request, context)
        weight_decimal = self._decimal_cast(weight_ref)
        valid_weight = self._valid_weight_condition(weight_ref, request.weighting_mode)

        group_select, group_refs, group_aliases, group_metadata = self._group_parts(request, context)
        normalized_reference = self._normalize_reference_group(request, group_metadata)
        select_parts = list(group_select)
        select_parameters: list[Any] = []
        formulas: list[FormulaDescriptor] = []

        for index, definition in enumerate(request.estimates):
            formulas.append(self._formula(definition, request.weighting_mode))

            value_ref: str | None = None
            if definition.statistic == "weighted_mean":
                assert definition.value is not None
                _, value_type, value_ref = self._column_ref(definition.value, context.namespaces)
                if not value_type.upper().startswith(_NUMERIC_TYPES):
                    raise QueryValidationError(
                        f"weighted_mean requires a numeric value column; received {value_type}"
                    )

            def compile_missing_eligibility(parameters: list[Any]) -> str:
                parts: list[str] = []
                for rule in definition.missing_value_rules:
                    _, duckdb_type, ref = self._column_ref(rule.column, context.namespaces)
                    part = f"({ref} IS NOT NULL)"
                    if rule.codes:
                        values = [
                            self.engine._coerce_scalar(duckdb_type, code) for code in rule.codes
                        ]
                        parameters.extend(values)
                        placeholders = ", ".join("?" for _ in values)
                        part += f" AND ({ref} NOT IN ({placeholders}))"
                    parts.append(f"({part})")
                if definition.statistic == "weighted_mean":
                    assert value_ref is not None
                    value_key = (definition.value.dataset.lower(), definition.value.column.upper())
                    rule_keys = {
                        (item.column.dataset.lower(), item.column.column.upper())
                        for item in definition.missing_value_rules
                    }
                    if value_key not in rule_keys:
                        parts.append(f"({value_ref} IS NOT NULL)")
                return " AND ".join(parts) if parts else "TRUE"

            # Compile every CASE expression in textual placeholder order.
            numerator_denominator = self._compile_filters(
                definition.denominator_filters, context.namespaces, select_parameters
            )
            numerator_missing = compile_missing_eligibility(select_parameters)
            if definition.statistic == "weighted_mean":
                numerator_weight_condition = (
                    f"({numerator_denominator}) AND ({numerator_missing}) AND {valid_weight}"
                )
                assert value_ref is not None
                numerator_weight_expression, numerator_zero_decimal = self._product_decimal_cast(
                    weight_ref, value_ref
                )
            else:
                numerator_filters = self._compile_filters(
                    definition.numerator_filters, context.namespaces, select_parameters
                )
                numerator_weight_condition = (
                    f"({numerator_denominator}) AND ({numerator_missing}) AND {valid_weight} "
                    f"AND ({numerator_filters})"
                )
                numerator_weight_expression = weight_decimal
                numerator_zero_decimal = self._decimal_cast("0")

            denominator_for_weight = self._compile_filters(
                definition.denominator_filters, context.namespaces, select_parameters
            )
            denominator_missing = compile_missing_eligibility(select_parameters)
            denominator_weight_condition = (
                f"({denominator_for_weight}) AND ({denominator_missing}) AND {valid_weight}"
            )

            numerator_denominator_n = self._compile_filters(
                definition.denominator_filters, context.namespaces, select_parameters
            )
            numerator_missing_n = compile_missing_eligibility(select_parameters)
            if definition.statistic == "weighted_mean":
                numerator_n_condition = (
                    f"({numerator_denominator_n}) AND ({numerator_missing_n}) AND {valid_weight}"
                )
            else:
                numerator_filters_n = self._compile_filters(
                    definition.numerator_filters, context.namespaces, select_parameters
                )
                numerator_n_condition = (
                    f"({numerator_denominator_n}) AND ({numerator_missing_n}) AND {valid_weight} "
                    f"AND ({numerator_filters_n})"
                )

            denominator_for_n = self._compile_filters(
                definition.denominator_filters, context.namespaces, select_parameters
            )
            denominator_missing_n = compile_missing_eligibility(select_parameters)
            denominator_n_condition = (
                f"({denominator_for_n}) AND ({denominator_missing_n}) AND {valid_weight}"
            )

            denominator_for_invalid = self._compile_filters(
                definition.denominator_filters, context.namespaces, select_parameters
            )
            invalid_missing = compile_missing_eligibility(select_parameters)
            invalid_weight_condition = (
                "FALSE"
                if request.weighting_mode == "unweighted"
                else f"({denominator_for_invalid}) AND ({invalid_missing}) AND NOT {valid_weight}"
            )

            denominator_for_missing = self._compile_filters(
                definition.denominator_filters, context.namespaces, select_parameters
            )
            eligible_for_missing = compile_missing_eligibility(select_parameters)
            missing_value_condition = (
                "FALSE"
                if eligible_for_missing == "TRUE"
                else f"({denominator_for_missing}) AND {valid_weight} AND NOT ({eligible_for_missing})"
            )

            zero_decimal = self._decimal_cast("0")
            select_parts.extend(
                [
                    "COALESCE(SUM(CASE WHEN "
                    f"{numerator_weight_condition} THEN {numerator_weight_expression} "
                    f"ELSE {numerator_zero_decimal} END), {numerator_zero_decimal}) AS "
                    f"{_quote_identifier(f'__e{index}_num_w')}",
                    "COALESCE(SUM(CASE WHEN "
                    f"{denominator_weight_condition} THEN {weight_decimal} "
                    f"ELSE {zero_decimal} END), {zero_decimal}) AS "
                    f"{_quote_identifier(f'__e{index}_den_w')}",
                    "SUM(CASE WHEN "
                    f"{numerator_n_condition} THEN 1 ELSE 0 END) AS "
                    f"{_quote_identifier(f'__e{index}_num_n')}",
                    "SUM(CASE WHEN "
                    f"{denominator_n_condition} THEN 1 ELSE 0 END) AS "
                    f"{_quote_identifier(f'__e{index}_den_n')}",
                    "SUM(CASE WHEN "
                    f"{invalid_weight_condition} THEN 1 ELSE 0 END) AS "
                    f"{_quote_identifier(f'__e{index}_invalid_w_n')}",
                    "SUM(CASE WHEN "
                    f"{missing_value_condition} THEN 1 ELSE 0 END) AS "
                    f"{_quote_identifier(f'__e{index}_missing_y_n')}",
                ]
            )

        universe_parameters: list[Any] = []
        universe_parts = [
            self.engine._compile_filter(item, context.namespaces, universe_parameters)
            for item in request.universe_filters
        ]
        parameters = select_parameters + context.parameters + universe_parameters
        sql = f"SELECT {', '.join(select_parts)} {context.from_sql}"
        if universe_parts:
            sql += " WHERE " + " AND ".join(f"({part})" for part in universe_parts)
        if group_refs:
            sql += " GROUP BY " + ", ".join(group_refs)
            sql += " ORDER BY " + ", ".join(
                f"{_quote_identifier(alias)} ASC NULLS LAST" for alias in group_aliases
            )
        effective_limit = min(
            request.limit or self.engine.config.engine.max_result_rows,
            self.engine.config.engine.max_result_rows,
        )
        sql += f" LIMIT {effective_limit + 1}"

        canonical = request.model_dump(mode="json")
        canonical["resolved_weight"] = weight.model_dump(mode="json") if weight is not None else None
        canonical["resolved_suppression"] = self._policy(request).model_dump(mode="json")
        fingerprint = _sha256_text(_canonical_json(canonical))
        return CompiledSurveyEstimate(
            sql=sql,
            display_sql=_render_display_sql(sql, parameters),
            parameters=parameters,
            effective_limit=effective_limit,
            canonical_request=canonical,
            request_fingerprint=fingerprint,
            datasets_used=context.datasets_used,
            join_contract_ids=context.join_contract_ids,
            group_aliases=group_aliases,
            normalized_reference_group=normalized_reference,
            formulas=formulas,
        )

    def _quantize(self, value: Decimal | None) -> Decimal | None:
        if value is None:
            return None
        places = self.engine.config.survey.output_decimal_places
        quantum = Decimal(1).scaleb(-places)
        return value.quantize(quantum, rounding=ROUND_HALF_EVEN)

    @staticmethod
    def _decimal(value: Any) -> Decimal:
        if value is None:
            return Decimal(0)
        return value if isinstance(value, Decimal) else Decimal(str(value))

    def _suppression(
        self,
        definition: EstimateDefinition,
        policy: SuppressionPolicy,
        denominator_weighted: Decimal,
        denominator_n: int,
        numerator_n: int,
        complement_n: int | None,
    ) -> SuppressionDecision:
        reasons: list[str] = []
        if denominator_weighted <= 0:
            reasons.append("ZERO_OR_NONPOSITIVE_WEIGHTED_DENOMINATOR")
        if denominator_n < policy.minimum_unweighted_denominator:
            reasons.append("UNWEIGHTED_DENOMINATOR_BELOW_CONFIGURED_MINIMUM")
        if (
            definition.statistic in {"weighted_count", "weighted_percentage"}
            and numerator_n < policy.minimum_unweighted_numerator
        ):
            reasons.append("UNWEIGHTED_NUMERATOR_BELOW_CONFIGURED_MINIMUM")
        if (
            definition.statistic == "weighted_percentage"
            and complement_n is not None
            and complement_n < policy.minimum_unweighted_complement
        ):
            reasons.append("UNWEIGHTED_COMPLEMENT_BELOW_CONFIGURED_MINIMUM")
        return SuppressionDecision(
            suppressed=bool(reasons),
            action=policy.action,
            reasons=reasons,
            policy_id=policy.policy_id,
        )

    def _comparison_pairs(
        self,
        request: SurveyEstimateRequest,
        compiled: CompiledSurveyEstimate,
        group_records: list[dict[str, Any]],
    ) -> list[tuple[dict[str, Any], dict[str, Any]]]:
        if request.comparisons.mode == "none":
            return []
        if request.comparisons.mode == "all_pairs":
            return list(itertools.combinations(group_records, 2))
        reference = compiled.normalized_reference_group
        assert reference is not None
        matches = [item for item in group_records if item == reference]
        if len(matches) != 1:
            raise QueryValidationError(
                f"Reference group {reference!r} matched {len(matches)} result groups; expected exactly one"
            )
        ref = matches[0]
        return [(item, ref) for item in group_records if item != ref]

    def execute(
        self, request: SurveyEstimateRequest | dict[str, Any]
    ) -> SurveyEstimateResult:
        if not isinstance(request, SurveyEstimateRequest):
            request = SurveyEstimateRequest.model_validate(request)
        compiled = self.compile(request)
        policy = self._policy(request)
        resolved_weight_payload = compiled.canonical_request["resolved_weight"]
        resolved_weight = (
            QualifiedColumn.model_validate(resolved_weight_payload)
            if resolved_weight_payload is not None
            else None
        )

        started = datetime.now(timezone.utc)
        start_clock = time.perf_counter()
        cursor = self.engine.connection.execute(compiled.sql, compiled.parameters)
        names = [item[0] for item in cursor.description]
        raw_rows = cursor.fetchall()
        if len(raw_rows) > compiled.effective_limit:
            raise ResultLimitError(
                "Grouped survey-estimate output exceeds the configured row limit; "
                "refine the grouping rather than returning a partial estimate table"
            )
        rows = [dict(zip(names, values)) for values in raw_rows]

        formula_by_alias = {item.estimate_alias: item for item in compiled.formulas}
        estimates: list[SurveyEstimate] = []
        raw_estimates: dict[tuple[str, tuple[tuple[str, Any], ...]], Decimal | None] = {}
        public_by_key: dict[tuple[str, tuple[tuple[str, Any], ...]], SurveyEstimate] = {}
        group_records: list[dict[str, Any]] = []

        for row in rows:
            group = {alias: row[alias] for alias in compiled.group_aliases}
            group_records.append(group)
            group_key = tuple((alias, group[alias]) for alias in compiled.group_aliases)
            for index, definition in enumerate(request.estimates):
                numerator_w = self._decimal(row[f"__e{index}_num_w"])
                denominator_w = self._decimal(row[f"__e{index}_den_w"])
                numerator_n = int(row[f"__e{index}_num_n"] or 0)
                denominator_n = int(row[f"__e{index}_den_n"] or 0)
                invalid_weight_n = int(row[f"__e{index}_invalid_w_n"] or 0)
                missing_value_n = int(row[f"__e{index}_missing_y_n"] or 0)
                complement_n = (
                    denominator_n - numerator_n
                    if definition.statistic == "weighted_percentage"
                    else None
                )
                if denominator_w <= 0:
                    raw_estimate = None
                elif definition.statistic == "weighted_count":
                    raw_estimate = numerator_w
                elif definition.statistic == "weighted_percentage":
                    raw_estimate = Decimal(100) * numerator_w / denominator_w
                else:
                    raw_estimate = numerator_w / denominator_w
                decision = self._suppression(
                    definition,
                    policy,
                    denominator_w,
                    denominator_n,
                    numerator_n,
                    complement_n,
                )
                released = raw_estimate
                if decision.suppressed and policy.action == "null_estimate":
                    released = None
                public = SurveyEstimate(
                    group=group,
                    weighting_mode=request.weighting_mode,
                    estimate_alias=definition.alias,
                    statistic=definition.statistic,
                    estimate=self._quantize(released),
                    weighted_numerator=self._quantize(numerator_w),
                    weighted_denominator=self._quantize(denominator_w) or Decimal(0),
                    unweighted_numerator=numerator_n,
                    unweighted_denominator=denominator_n,
                    unweighted_complement=complement_n,
                    invalid_weight_rows_excluded=invalid_weight_n,
                    missing_value_rows_excluded=missing_value_n,
                    suppression=decision,
                    formula=formula_by_alias[definition.alias].estimate_formula,
                )
                key = (definition.alias, group_key)
                estimates.append(public)
                raw_estimates[key] = raw_estimate
                public_by_key[key] = public

        pairs = self._comparison_pairs(request, compiled, group_records)
        total_comparisons = len(pairs) * len(request.estimates)
        if total_comparisons > self.engine.config.survey.max_comparisons:
            raise ResultLimitError(
                f"Comparison request would produce {total_comparisons} rows, exceeding "
                f"survey.max_comparisons={self.engine.config.survey.max_comparisons}"
            )
        comparisons: list[GroupComparison] = []
        for definition in request.estimates:
            for left_group, right_group in pairs:
                left_key = tuple((alias, left_group[alias]) for alias in compiled.group_aliases)
                right_key = tuple((alias, right_group[alias]) for alias in compiled.group_aliases)
                left_public = public_by_key[(definition.alias, left_key)]
                right_public = public_by_key[(definition.alias, right_key)]
                left_raw = raw_estimates[(definition.alias, left_key)]
                right_raw = raw_estimates[(definition.alias, right_key)]
                reasons: list[str] = []
                warnings: list[str] = []
                if left_public.suppression.suppressed or right_public.suppression.suppressed:
                    reasons.append("INPUT_ESTIMATE_SUPPRESSED")
                if left_raw is None or right_raw is None:
                    reasons.append("INPUT_ESTIMATE_UNDEFINED")
                difference: Decimal | None = None
                ratio: Decimal | None = None
                if not reasons and left_raw is not None and right_raw is not None:
                    difference = left_raw - right_raw
                    if request.comparisons.include_ratio:
                        if right_raw == 0:
                            warnings.append("RATIO_UNDEFINED_ZERO_REFERENCE_ESTIMATE")
                        else:
                            ratio = left_raw / right_raw
                comparisons.append(
                    GroupComparison(
                        estimate_alias=definition.alias,
                        statistic=definition.statistic,
                        left_group=left_group,
                        right_group=right_group,
                        difference=self._quantize(difference) if not reasons else None,
                        ratio=self._quantize(ratio) if not reasons else None,
                        suppressed=bool(reasons),
                        reasons=reasons,
                        warnings=warnings,
                    )
                )

        finished = datetime.now(timezone.utc)
        elapsed_ms = (time.perf_counter() - start_clock) * 1000
        dataset_metadata: list[DatasetEstimateMetadata] = []
        for logical_name in compiled.datasets_used:
            runtime = self.engine.runtime_datasets[logical_name]
            try:
                stat = runtime.physical_path.stat()
                size_bytes, modified_ns = stat.st_size, stat.st_mtime_ns
            except OSError:
                size_bytes, modified_ns = None, None
            dataset_metadata.append(
                DatasetEstimateMetadata(
                    logical_name=logical_name,
                    source_file_id=runtime.binding.source.source_file_id,
                    physical_path=str(runtime.physical_path),
                    synthetic_fixture=runtime.synthetic_fixture,
                    size_bytes=size_bytes,
                    modified_ns=modified_ns,
                )
            )
        version_row = self.engine.connection.execute("PRAGMA version").fetchone()
        duckdb_version = str(version_row[0]) if version_row else "unknown"
        survey_options = self.engine.config.survey
        metadata = SurveyExecutionMetadata(
            run_id=str(uuid.uuid4()),
            request_fingerprint=compiled.request_fingerprint,
            sql_fingerprint=_sha256_text(
                compiled.sql + "\n" + _canonical_json(compiled.parameters)
            ),
            started_at=started,
            finished_at=finished,
            elapsed_ms=elapsed_ms,
            duckdb_version=duckdb_version,
            database=self.engine.config.engine.database,
            memory_limit=self.engine.config.engine.memory_limit,
            temp_directory=str(self.engine.config.engine.temp_directory),
            threads=self.engine.config.engine.threads,
            datasets=dataset_metadata,
            join_contract_ids=compiled.join_contract_ids,
            group_rows=len(rows),
            comparisons_returned=len(comparisons),
            estimation_scope=(
                "DESCRIPTIVE_WEIGHTED_ESTIMATES"
                if request.weighting_mode == "weighted"
                else "DESCRIPTIVE_UNWEIGHTED_ESTIMATES"
            ),
            weight_column=resolved_weight,
            weight_eligibility_rule=(
                "unit weight = 1 for every eligible row"
                if request.weighting_mode == "unweighted"
                else (
                    "weight IS NOT NULL AND weight > 0"
                    if survey_options.positive_weights_only
                    else "weight IS NOT NULL"
                )
            ),
            arithmetic_rule=(
                f"DuckDB DECIMAL({survey_options.decimal_precision},{survey_options.decimal_scale}) "
                f"component sums; final ratios rounded HALF_EVEN to "
                f"{survey_options.output_decimal_places} decimal places"
            ),
            suppression_policy=policy,
        )
        return SurveyEstimateResult(
            estimates=estimates,
            comparisons=comparisons,
            generated_sql=compiled.display_sql,
            parameterized_sql=compiled.sql,
            parameters=compiled.parameters,
            formulas=compiled.formulas,
            metadata=metadata,
        )
