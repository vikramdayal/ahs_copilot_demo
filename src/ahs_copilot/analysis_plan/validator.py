from __future__ import annotations

from typing import Any, Iterable

from ahs_copilot.query_engine.engine import AHSQueryEngine, _NUMERIC_TYPES, _canonical_json, _sha256_text
from ahs_copilot.query_engine.errors import DatasetResolutionError, JoinPolicyError
from ahs_copilot.query_engine.models import QualifiedColumn, TypedFilter
from ahs_copilot.survey_estimation.models import (
    EstimateDefinition,
    GroupDimension,
    MissingValueRule,
    SurveyEstimateRequest,
)

from .catalog import SemanticCatalog, SemanticUniverse, SemanticVariable
from .errors import AnalysisPlanValidationError
from .models import AnalysisPlan, PlanValidationIssue, ValidatedAnalysisPlan


class AnalysisPlanValidator:
    """Fail-closed semantic validation performed before survey SQL compilation."""

    def __init__(self, engine: AHSQueryEngine, semantic_catalog: str | None = None) -> None:
        self.engine = engine
        configured = getattr(engine.config.metadata, "semantic_catalog", None)
        path = semantic_catalog or configured
        if path is None:
            raise ValueError("A semantic catalog path is required for AnalysisPlan validation")
        self.catalog = SemanticCatalog(path)

    @staticmethod
    def _issue(code: str, path: str, message: str) -> PlanValidationIssue:
        return PlanValidationIssue(code=code, path=path, message=message)

    @staticmethod
    def _key(column: QualifiedColumn) -> tuple[str, str]:
        return column.dataset.lower(), column.column.upper()

    @staticmethod
    def _dedupe(columns: Iterable[QualifiedColumn]) -> list[QualifiedColumn]:
        values: dict[tuple[str, str], QualifiedColumn] = {}
        for column in columns:
            values[(column.dataset.lower(), column.column.upper())] = QualifiedColumn(
                dataset=column.dataset.lower(), column=column.column
            )
        return [values[key] for key in sorted(values)]

    def _resolve_dataset(self, name: str, issues: list[PlanValidationIssue], path: str) -> str | None:
        try:
            return self.engine.catalog.resolve(name).logical_name
        except DatasetResolutionError as exc:
            issues.append(self._issue("UNKNOWN_DATASET", path, str(exc)))
            return None

    def _normalize_column(
        self,
        column: QualifiedColumn,
        issues: list[PlanValidationIssue],
        path: str,
        allowed_datasets: set[str],
        aggregate_outputs: set[tuple[str, str]],
    ) -> QualifiedColumn | None:
        dataset = self._resolve_dataset(column.dataset, issues, f"{path}.dataset")
        if dataset is None:
            return None
        if dataset not in allowed_datasets:
            issues.append(
                self._issue(
                    "DATASET_NOT_IN_PLAN",
                    path,
                    f"Dataset {dataset!r} is not the base dataset or an approved joined dataset",
                )
            )
            return None
        if (dataset, column.column.upper()) in aggregate_outputs:
            return QualifiedColumn(dataset=dataset, column=column.column)
        semantic = self.catalog.variable(dataset, column.column)
        if semantic is None:
            issues.append(
                self._issue(
                    "UNKNOWN_VARIABLE",
                    path,
                    f"Variable {dataset}.{column.column} is absent from the approved semantic model",
                )
            )
            return None
        if semantic.access_level != self.catalog.document.access_mode:
            issues.append(
                self._issue(
                    "PUF_INACCESSIBLE_FIELD",
                    path,
                    f"Variable {dataset}.{column.column} requires {semantic.access_level} access",
                )
            )
            return None
        runtime = self.engine._runtime(dataset)
        physical = {item.name.upper() for item in runtime.schema.columns}
        if column.column.upper() not in physical:
            issues.append(
                self._issue(
                    "VARIABLE_NOT_IN_PHYSICAL_SCHEMA",
                    path,
                    f"Approved PUF variable {dataset}.{column.column} is not present in the inspected CSV schema",
                )
            )
            return None
        return QualifiedColumn(dataset=dataset, column=column.column)

    def _validate_joins(
        self, plan: AnalysisPlan, base_dataset: str, issues: list[PlanValidationIssue]
    ) -> tuple[set[str], set[tuple[str, str]], list[QualifiedColumn]]:
        allowed = {base_dataset}
        aggregate_outputs: set[tuple[str, str]] = set()
        raw_required: list[QualifiedColumn] = []
        base_relation = self.engine._runtime(base_dataset).binding.source.relation
        for index, join in enumerate(plan.joins):
            path = f"joins[{index}]"
            target = self._resolve_dataset(join.dataset, issues, f"{path}.dataset")
            if target is None:
                continue
            try:
                contract, direction = self.engine.catalog.relationship(
                    base_relation, self.engine._runtime(target).binding.source.relation
                )
            except JoinPolicyError as exc:
                issues.append(self._issue("ILLEGAL_JOIN_PATH", path, str(exc)))
                continue
            if direction == "parent_to_child":
                if join.aggregation is None:
                    issues.append(
                        self._issue(
                            "CHILD_PREAGGREGATION_REQUIRED",
                            path,
                            f"{target} must be aggregated to {contract.keys} before joining",
                        )
                    )
                    continue
                if [x.upper() for x in join.aggregation.group_by] != [
                    x.upper() for x in contract.keys
                ]:
                    issues.append(
                        self._issue(
                            "INVALID_CHILD_GRAIN",
                            f"{path}.aggregation.group_by",
                            f"Expected exactly {contract.keys}",
                        )
                    )
                for key in contract.keys:
                    raw_required.append(QualifiedColumn(dataset=target, column=key))
                for filter_item in join.aggregation.filters:
                    raw_required.append(
                        QualifiedColumn(dataset=target, column=filter_item.column.column)
                    )
                for aggregate in join.aggregation.aggregates:
                    aggregate_outputs.add((target, aggregate.alias.upper()))
                    if aggregate.column is not None:
                        raw_required.append(QualifiedColumn(dataset=target, column=aggregate.column))
            elif join.aggregation is not None:
                issues.append(
                    self._issue(
                        "UNEXPECTED_CHILD_AGGREGATION",
                        f"{path}.aggregation",
                        "Child-to-parent joins must not include child aggregation",
                    )
                )
            allowed.add(target)
        return allowed, aggregate_outputs, raw_required

    def _measure_shape(self, plan: AnalysisPlan, issues: list[PlanValidationIssue]) -> None:
        statistic = plan.measure.statistic
        if statistic == "count":
            if plan.numerator.role != "eligible_units" or plan.denominator.role != "eligible_units":
                issues.append(
                    self._issue(
                        "INCOMPATIBLE_NUMERATOR_DENOMINATOR",
                        "numerator/denominator",
                        "Count plans require eligible_units numerator and denominator roles",
                    )
                )
        elif statistic == "percentage":
            if plan.numerator.role != "condition_true" or plan.denominator.role != "eligible_units":
                issues.append(
                    self._issue(
                        "INCOMPATIBLE_NUMERATOR_DENOMINATOR",
                        "numerator/denominator",
                        "Percentage plans require condition_true over an eligible_units denominator",
                    )
                )
            if not plan.numerator.filters:
                issues.append(
                    self._issue(
                        "UNDERSPECIFIED_NUMERATOR",
                        "numerator.filters",
                        "A percentage numerator requires at least one typed condition",
                    )
                )
        elif statistic == "mean":
            if (
                plan.numerator.role != "weighted_value_sum"
                or plan.denominator.role != "nonmissing_weight_sum"
            ):
                issues.append(
                    self._issue(
                        "INCOMPATIBLE_NUMERATOR_DENOMINATOR",
                        "numerator/denominator",
                        "Mean plans require weighted_value_sum and nonmissing_weight_sum roles",
                    )
                )
            if plan.numerator.filters != plan.denominator.filters:
                issues.append(
                    self._issue(
                        "MEAN_FILTER_MISMATCH",
                        "numerator/denominator.filters",
                        "Mean numerator and denominator filters must be identical",
                    )
                )

    def _missing_code_filters(
        self, plan: AnalysisPlan, normalized_columns: dict[tuple[str, str], QualifiedColumn]
    ) -> list[TypedFilter]:
        targets: list[QualifiedColumn] = []
        if plan.measure.statistic == "mean" and plan.measure.value is not None:
            key = self._key(plan.measure.value)
            if key in normalized_columns:
                targets.append(normalized_columns[key])
        if plan.measure.statistic == "percentage":
            for item in plan.numerator.filters:
                key = self._key(item.column)
                if key in normalized_columns:
                    targets.append(normalized_columns[key])
        filters: list[TypedFilter] = []
        seen: set[tuple[str, str]] = set()
        for column in targets:
            key = self._key(column)
            if key in seen:
                continue
            seen.add(key)
            variable = self.catalog.variable(column.dataset, column.column)
            if variable is not None and variable.missing_codes:
                filters.append(
                    TypedFilter(column=column, operator="not_in", value=list(variable.missing_codes))
                )
        return filters

    def validate(self, plan: AnalysisPlan | dict[str, Any]) -> ValidatedAnalysisPlan:
        if not isinstance(plan, AnalysisPlan):
            plan = AnalysisPlan.model_validate(plan)
        issues: list[PlanValidationIssue] = []
        base_dataset = self._resolve_dataset(plan.dataset, issues, "dataset")
        if base_dataset is None:
            raise AnalysisPlanValidationError(issues)

        universe = self.catalog.universe(plan.universe.universe_id)
        if universe is None:
            issues.append(
                self._issue(
                    "UNKNOWN_UNIVERSE",
                    "universe.universe_id",
                    f"Universe {plan.universe.universe_id!r} is not approved",
                )
            )
        elif universe.dataset.lower() != base_dataset:
            issues.append(
                self._issue(
                    "UNIVERSE_DATASET_MISMATCH",
                    "universe.universe_id",
                    f"Universe {universe.universe_id!r} belongs to {universe.dataset!r}, not {base_dataset!r}",
                )
            )

        allowed_datasets, aggregate_outputs, join_required = self._validate_joins(
            plan, base_dataset, issues
        )
        self._measure_shape(plan, issues)

        all_references: list[tuple[str, QualifiedColumn]] = [
            (f"joins.required[{i}]", item) for i, item in enumerate(join_required)
        ]
        if plan.measure.value is not None:
            all_references.append(("measure.value", plan.measure.value))
        for prefix, filters in (
            ("numerator.filters", plan.numerator.filters),
            ("denominator.filters", plan.denominator.filters),
            ("filters", plan.filters),
        ):
            all_references.extend((f"{prefix}[{i}].column", item.column) for i, item in enumerate(filters))
        all_references.extend(
            (f"grouping_dimensions[{i}]", item) for i, item in enumerate(plan.grouping_dimensions)
        )
        if plan.weight.column is not None:
            all_references.append(("weight.column", plan.weight.column))
        all_references.extend(
            (f"required_variables[{i}]", item) for i, item in enumerate(plan.required_variables)
        )
        if universe is not None:
            all_references.extend(
                (f"universe[{i}]", item) for i, item in enumerate(universe.required_variables)
            )

        normalized_columns: dict[tuple[str, str], QualifiedColumn] = {}
        for path, column in all_references:
            normalized = self._normalize_column(
                column, issues, path, allowed_datasets, aggregate_outputs
            )
            if normalized is not None:
                normalized_columns[self._key(column)] = normalized

        # Type compatibility is validated here so incompatible plans never reach SQL generation.
        if plan.measure.value is not None:
            normalized_value = normalized_columns.get(self._key(plan.measure.value))
            if normalized_value is not None:
                runtime = self.engine._runtime(normalized_value.dataset)
                type_by_name = {x.name.upper(): x.duckdb_type for x in runtime.schema.columns}
                value_type = type_by_name.get(normalized_value.column.upper(), "")
                if plan.measure.statistic == "mean" and not value_type.upper().startswith(_NUMERIC_TYPES):
                    issues.append(
                        self._issue(
                            "NONNUMERIC_MEAN_VARIABLE",
                            "measure.value",
                            f"Mean variable has incompatible physical type {value_type!r}",
                        )
                    )

        for prefix, filters in (
            ("numerator.filters", plan.numerator.filters),
            ("denominator.filters", plan.denominator.filters),
            ("filters", plan.filters),
        ):
            for index, item in enumerate(filters):
                normalized = normalized_columns.get(self._key(item.column))
                if normalized is None or self._key(normalized) in aggregate_outputs:
                    continue
                runtime = self.engine._runtime(normalized.dataset)
                type_by_name = {x.name.upper(): x.duckdb_type for x in runtime.schema.columns}
                duckdb_type = type_by_name.get(normalized.column.upper(), "")
                if item.operator in {"lt", "le", "gt", "ge", "between"} and not (
                    duckdb_type.upper().startswith(_NUMERIC_TYPES)
                    or duckdb_type.upper() == "DATE"
                    or duckdb_type.upper().startswith("TIMESTAMP")
                ):
                    issues.append(
                        self._issue(
                            "FILTER_TYPE_MISMATCH",
                            f"{prefix}[{index}]",
                            f"Operator {item.operator!r} is incompatible with {duckdb_type!r}",
                        )
                    )
                try:
                    if item.operator not in {"is_null", "is_not_null"}:
                        values = item.value if isinstance(item.value, list) else [item.value]
                        for value in values:
                            self.engine._coerce_scalar(duckdb_type, value)
                except Exception as exc:
                    issues.append(
                        self._issue(
                            "FILTER_VALUE_TYPE_MISMATCH",
                            f"{prefix}[{index}].value",
                            str(exc),
                        )
                    )

        if self.engine._runtime(base_dataset).schema.grain != "HOUSING_UNIT":
            issues.append(
                self._issue(
                    "BASE_GRAIN_INCOMPATIBLE",
                    "dataset",
                    "Descriptive housing-unit estimation requires a HOUSING_UNIT base dataset",
                )
            )

        approved_recode_ids: list[str] = []
        recode_required: list[QualifiedColumn] = []
        for index, item in enumerate(plan.derived_recodes):
            recode = self.catalog.recode(item.recode_id)
            if recode is None:
                issues.append(
                    self._issue(
                        "UNKNOWN_DERIVED_RECODE",
                        f"derived_recodes[{index}].recode_id",
                        f"Recode {item.recode_id!r} is not approved",
                    )
                )
                continue
            if recode.access_level != self.catalog.document.access_mode:
                issues.append(
                    self._issue(
                        "PUF_INACCESSIBLE_RECODE",
                        f"derived_recodes[{index}]",
                        f"Recode {item.recode_id!r} requires {recode.access_level} access",
                    )
                )
                continue
            approved_recode_ids.append(recode.recode_id)
            recode_required.extend(recode.required_variables)

        if plan.weight.mode == "weighted" and plan.weight.column is not None:
            normalized_weight = normalized_columns.get(self._key(plan.weight.column))
            if normalized_weight is not None:
                approved = self.catalog.weight(normalized_weight.dataset, normalized_weight.column)
                if approved is None or approved.access_level != self.catalog.document.access_mode:
                    issues.append(
                        self._issue(
                            "UNAPPROVED_WEIGHT",
                            "weight.column",
                            f"{normalized_weight.dataset}.{normalized_weight.column} is not an approved PUF weight",
                        )
                    )
                elif universe is not None and universe.universe_id not in approved.approved_universes:
                    issues.append(
                        self._issue(
                            "WEIGHT_UNIVERSE_MISMATCH",
                            "weight.column",
                            f"Weight {approved.weight_id!r} is not approved for universe {universe.universe_id!r}",
                        )
                    )
                runtime = self.engine._runtime(normalized_weight.dataset)
                type_by_name = {x.name.upper(): x.duckdb_type for x in runtime.schema.columns}
                weight_type = type_by_name.get(normalized_weight.column.upper(), "")
                if not weight_type.upper().startswith(_NUMERIC_TYPES):
                    issues.append(
                        self._issue(
                            "NONNUMERIC_WEIGHT",
                            "weight.column",
                            f"Weight column has incompatible physical type {weight_type!r}",
                        )
                    )

        inferred: list[QualifiedColumn] = []
        if universe is not None:
            inferred.extend(universe.required_variables)
        inferred.extend(join_required)
        inferred.extend(item.column for item in plan.filters)
        inferred.extend(item.column for item in plan.numerator.filters)
        inferred.extend(item.column for item in plan.denominator.filters)
        inferred.extend(plan.grouping_dimensions)
        inferred.extend(recode_required)
        if plan.measure.value is not None:
            inferred.append(plan.measure.value)
        if plan.weight.column is not None:
            inferred.append(plan.weight.column)
        inferred_normalized: list[QualifiedColumn] = []
        for column in inferred:
            key = self._key(column)
            normalized = normalized_columns.get(key)
            if normalized is None and key in aggregate_outputs:
                continue
            if normalized is not None:
                inferred_normalized.append(normalized)
        inferred_normalized = self._dedupe(inferred_normalized)
        declared = {
            self._key(normalized_columns[self._key(item)])
            for item in plan.required_variables
            if self._key(item) in normalized_columns
        }
        missing_required = [item for item in inferred_normalized if self._key(item) not in declared]
        for item in missing_required:
            issues.append(
                self._issue(
                    "MISSING_REQUIRED_VARIABLE_DECLARATION",
                    "required_variables",
                    f"Plan uses {item.dataset}.{item.column} but does not declare it",
                )
            )

        if issues:
            raise AnalysisPlanValidationError(issues)
        assert universe is not None

        def normalize_filter(item: TypedFilter) -> TypedFilter:
            normalized = normalized_columns.get(self._key(item.column), item.column)
            return TypedFilter(column=normalized, operator=item.operator, value=item.value)

        universe_filters = [normalize_filter(item) for item in universe.filters]
        universe_filters.extend(normalize_filter(item) for item in plan.filters)
        numerator_filters = [normalize_filter(item) for item in plan.numerator.filters]
        denominator_filters = [normalize_filter(item) for item in plan.denominator.filters]
        missing_rules = []
        for item in self._missing_code_filters(plan, normalized_columns):
            missing_rules.append(
                MissingValueRule(column=item.column, codes=list(item.value))
            )

        statistic_map = {
            "count": "weighted_count",
            "percentage": "weighted_percentage",
            "mean": "weighted_mean",
        }
        estimate = EstimateDefinition(
            alias=plan.measure.alias,
            statistic=statistic_map[plan.measure.statistic],
            numerator_filters=numerator_filters,
            denominator_filters=denominator_filters,
            value=(
                normalized_columns[self._key(plan.measure.value)]
                if plan.measure.value is not None
                else None
            ),
            missing_value_rules=missing_rules,
        )
        survey_request = SurveyEstimateRequest(
            base_dataset=base_dataset,
            weighting_mode=plan.weight.mode,
            weight=(
                normalized_columns[self._key(plan.weight.column)]
                if plan.weight.column is not None
                else None
            ),
            universe_filters=universe_filters,
            joins=plan.joins,
            group_by=[
                GroupDimension(column=normalized_columns[self._key(item)])
                for item in plan.grouping_dimensions
            ],
            estimates=[estimate],
            comparisons=plan.comparisons,
            limit=plan.output_format.limit,
        )
        canonical = plan.model_dump(mode="json")
        fingerprint = _sha256_text(_canonical_json(canonical))
        messages = [
            "PLAN_SCHEMA_VALID",
            "DATASET_AND_UNIVERSE_RESOLVED",
            "PUF_ACCESS_CONFIRMED",
            "REQUIRED_VARIABLE_CLOSURE_CONFIRMED",
            "JOIN_PATHS_APPROVED",
            "NUMERATOR_DENOMINATOR_COMPATIBLE",
            "WEIGHT_MODE_COMPATIBLE",
            "MISSING_VALUE_CODES_BOUND_TO_DENOMINATOR",
            "READY_FOR_DETERMINISTIC_SQL_COMPILATION",
        ]
        return ValidatedAnalysisPlan(
            plan=plan,
            plan_fingerprint=fingerprint,
            normalized_dataset=base_dataset,
            normalized_universe_id=universe.universe_id,
            inferred_required_variables=inferred_normalized,
            approved_recode_ids=approved_recode_ids,
            validation_messages=messages,
            survey_request=survey_request,
        )
