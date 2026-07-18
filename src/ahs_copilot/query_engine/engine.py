from __future__ import annotations

import hashlib
import json
import re
import time
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import duckdb

from .catalog import CatalogRegistry, DatasetBinding, RelationshipContract
from .config import AppConfig, CsvReadOptions, load_config
from .errors import ConfigurationError, JoinPolicyError, QueryValidationError, SchemaValidationError
from .fixture import create_synthetic_fixture
from .models import (
    AggregateProjection,
    ChildAggregate,
    ColumnProjection,
    ColumnSchema,
    CompiledQuery,
    DatasetExecutionMetadata,
    DatasetSchema,
    ExecutionMetadata,
    QualifiedColumn,
    QueryResult,
    QuerySpec,
    JoinSpec,
    TypedFilter,
)

_NUMERIC_TYPES = (
    "TINYINT",
    "SMALLINT",
    "INTEGER",
    "BIGINT",
    "HUGEINT",
    "UTINYINT",
    "USMALLINT",
    "UINTEGER",
    "UBIGINT",
    "DECIMAL",
    "DOUBLE",
    "FLOAT",
    "REAL",
)
_INTEGER_TYPES = (
    "TINYINT",
    "SMALLINT",
    "INTEGER",
    "BIGINT",
    "HUGEINT",
    "UTINYINT",
    "USMALLINT",
    "UINTEGER",
    "UBIGINT",
)
_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


@dataclass
class RuntimeDataset:
    logical_name: str
    binding: DatasetBinding
    physical_path: Path
    synthetic_fixture: bool
    view_name: str
    schema: DatasetSchema


@dataclass
class Namespace:
    logical_name: str
    alias: str
    columns: dict[str, str]


@dataclass
class QueryContext:
    base: RuntimeDataset
    namespaces: dict[str, Namespace]
    parameters: list[Any]
    from_sql: str
    datasets_used: list[str]
    join_contract_ids: list[str]


def _quote_identifier(value: str) -> str:
    if not _IDENTIFIER_RE.fullmatch(value):
        raise QueryValidationError(f"Invalid SQL identifier: {value!r}")
    return '"' + value.replace('"', '""') + '"'


def _quote_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _render_parameter(value: Any) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, (int, float, Decimal)):
        return str(value)
    if isinstance(value, (date, datetime)):
        return _quote_literal(value.isoformat())
    return _quote_literal(str(value))


def _render_display_sql(sql: str, parameters: list[Any]) -> str:
    parts = sql.split("?")
    if len(parts) - 1 != len(parameters):
        return sql
    rendered = [parts[0]]
    for parameter, suffix in zip(parameters, parts[1:]):
        rendered.append(_render_parameter(parameter))
        rendered.append(suffix)
    return "".join(rendered)


class AHSQueryEngine:
    """Governed DuckDB engine that compiles typed plans; it never accepts raw SQL."""

    def __init__(self, config: str | Path | AppConfig) -> None:
        self.config = load_config(config) if not isinstance(config, AppConfig) else config
        self.catalog = CatalogRegistry(self.config)
        self.connection = duckdb.connect(self.config.engine.database)
        self.runtime_datasets: dict[str, RuntimeDataset] = {}
        self._configure_duckdb()
        self._prepare_datasets()

    def close(self) -> None:
        self.connection.close()

    def __enter__(self) -> "AHSQueryEngine":
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        self.close()

    def _configure_duckdb(self) -> None:
        options = self.config.engine
        options.temp_directory.mkdir(parents=True, exist_ok=True)
        self.connection.execute(f"SET memory_limit = {_quote_literal(options.memory_limit)}")
        self.connection.execute(f"SET temp_directory = {_quote_literal(str(options.temp_directory))}")
        self.connection.execute(f"SET threads = {int(options.threads)}")
        self.connection.execute(
            f"SET preserve_insertion_order = {'true' if options.preserve_insertion_order else 'false'}"
        )

    def _prepare_datasets(self) -> None:
        fixture_paths: dict[str, Path] = {}
        if self.config.fixture.mode == "required":
            fixture_paths = create_synthetic_fixture(self.config.fixture.directory)
        elif self.config.fixture.mode == "auto" and any(
            not dataset.path.exists() for dataset in self.config.datasets.values()
        ):
            fixture_paths = create_synthetic_fixture(self.config.fixture.directory)

        for logical_name, binding in self.catalog.bindings.items():
            configured = self.config.datasets[logical_name]
            path = configured.path
            synthetic = False
            if self.config.fixture.mode == "required":
                path = fixture_paths.get(binding.source.relation, path)
                synthetic = True
            elif not path.exists():
                if self.config.fixture.mode == "disabled":
                    raise ConfigurationError(f"CSV file not found for {logical_name}: {path}")
                fallback = fixture_paths.get(binding.source.relation)
                if fallback is None:
                    raise ConfigurationError(
                        f"No synthetic fixture is defined for relation {binding.source.relation!r}"
                    )
                path = fallback
                synthetic = True
            view_name = f"ahs_{logical_name}"
            scan_sql = self._csv_scan_sql(path, configured.csv)
            self.connection.execute(
                f"CREATE OR REPLACE VIEW {_quote_identifier(view_name)} AS SELECT * FROM {scan_sql}"
            )
            columns = self._inspect_view(view_name)
            column_names = {x.name.upper() for x in columns}
            missing_keys = [key for key in binding.source.join_keys if key.upper() not in column_names]
            if missing_keys:
                raise SchemaValidationError(
                    f"Dataset {logical_name!r} is missing approved key columns: {missing_keys}"
                )
            schema = DatasetSchema(
                logical_name=logical_name,
                source_file_id=binding.source.source_file_id,
                source_name=binding.source.name,
                relation=binding.source.relation,
                grain=binding.source.grain,
                join_keys=binding.source.join_keys,
                physical_path=str(path),
                synthetic_fixture=synthetic,
                columns=columns,
            )
            self.runtime_datasets[logical_name] = RuntimeDataset(
                logical_name=logical_name,
                binding=binding,
                physical_path=path,
                synthetic_fixture=synthetic,
                view_name=view_name,
                schema=schema,
            )

    @staticmethod
    def _csv_scan_sql(path: Path, options: CsvReadOptions) -> str:
        return (
            "read_csv("
            f"{_quote_literal(str(path))}, "
            f"header = {'true' if options.header else 'false'}, "
            f"delim = {_quote_literal(options.delimiter)}, "
            "auto_detect = true, "
            f"sample_size = {int(options.sample_size)}, "
            f"all_varchar = {'true' if options.all_varchar else 'false'}, "
            f"ignore_errors = {'true' if options.ignore_errors else 'false'}, "
            f"union_by_name = {'true' if options.union_by_name else 'false'}"
            ")"
        )

    def _inspect_view(self, view_name: str) -> list[ColumnSchema]:
        rows = self.connection.execute(
            f"DESCRIBE SELECT * FROM {_quote_identifier(view_name)}"
        ).fetchall()
        return [
            ColumnSchema(name=str(row[0]), duckdb_type=str(row[1]), nullable=str(row[2]).upper() != "NO")
            for row in rows
        ]

    def inspect_schemas(self) -> dict[str, DatasetSchema]:
        return {name: runtime.schema for name, runtime in sorted(self.runtime_datasets.items())}

    def _runtime(self, name: str) -> RuntimeDataset:
        binding = self.catalog.resolve(name)
        return self.runtime_datasets[binding.logical_name]

    @staticmethod
    def _column_type(namespace: Namespace, column: str) -> str:
        try:
            return namespace.columns[column.upper()]
        except KeyError as exc:
            raise QueryValidationError(
                f"Unknown column {column!r} on dataset {namespace.logical_name!r}"
            ) from exc

    @staticmethod
    def _coerce_scalar(duckdb_type: str, value: Any) -> Any:
        normalized = duckdb_type.upper()
        if value is None:
            raise QueryValidationError("Use is_null/is_not_null rather than comparing to null")
        if normalized.startswith(_INTEGER_TYPES):
            if isinstance(value, bool):
                raise QueryValidationError(f"Boolean is not valid for integer column {duckdb_type}")
            try:
                converted = int(value)
            except (TypeError, ValueError) as exc:
                raise QueryValidationError(f"Cannot coerce {value!r} to {duckdb_type}") from exc
            if isinstance(value, float) and not value.is_integer():
                raise QueryValidationError(f"Non-integral value {value!r} is invalid for {duckdb_type}")
            if isinstance(value, str) and str(converted) != value.strip().lstrip("+"):
                if not (value.strip().startswith("-") and str(converted) == value.strip()):
                    raise QueryValidationError(f"Non-integral value {value!r} is invalid for {duckdb_type}")
            return converted
        if normalized.startswith(_NUMERIC_TYPES):
            try:
                return Decimal(str(value))
            except (InvalidOperation, ValueError) as exc:
                raise QueryValidationError(f"Cannot coerce {value!r} to {duckdb_type}") from exc
        if normalized == "BOOLEAN":
            if isinstance(value, bool):
                return value
            if isinstance(value, str) and value.strip().lower() in {"true", "false", "1", "0"}:
                return value.strip().lower() in {"true", "1"}
            raise QueryValidationError(f"Cannot coerce {value!r} to BOOLEAN")
        if normalized == "DATE":
            if isinstance(value, date) and not isinstance(value, datetime):
                return value
            try:
                return date.fromisoformat(str(value))
            except ValueError as exc:
                raise QueryValidationError(f"Cannot coerce {value!r} to DATE") from exc
        if normalized.startswith("TIMESTAMP"):
            if isinstance(value, datetime):
                return value
            try:
                return datetime.fromisoformat(str(value))
            except ValueError as exc:
                raise QueryValidationError(f"Cannot coerce {value!r} to TIMESTAMP") from exc
        if normalized in {"VARCHAR", "CHAR", "TEXT", "UUID"} or normalized.startswith("VARCHAR"):
            return str(value)
        raise QueryValidationError(f"Filters are not supported for DuckDB type {duckdb_type}")

    def _compile_filter(
        self,
        item: TypedFilter,
        namespaces: dict[str, Namespace],
        parameters: list[Any],
    ) -> str:
        runtime = self._runtime(item.column.dataset)
        namespace = namespaces.get(runtime.logical_name)
        if namespace is None:
            raise QueryValidationError(
                f"Filter references dataset {item.column.dataset!r}, which is not in the query"
            )
        duckdb_type = self._column_type(namespace, item.column.column)
        ref = f"{_quote_identifier(namespace.alias)}.{_quote_identifier(item.column.column)}"
        op = item.operator
        if op == "is_null":
            return f"{ref} IS NULL"
        if op == "is_not_null":
            return f"{ref} IS NOT NULL"
        if op in {"lt", "le", "gt", "ge", "between"} and not (
            duckdb_type.upper().startswith(_NUMERIC_TYPES)
            or duckdb_type.upper() == "DATE"
            or duckdb_type.upper().startswith("TIMESTAMP")
        ):
            raise QueryValidationError(f"Operator {op} is incompatible with {duckdb_type}")
        operator_sql = {"eq": "=", "ne": "!=", "lt": "<", "le": "<=", "gt": ">", "ge": ">="}
        if op in operator_sql:
            parameters.append(self._coerce_scalar(duckdb_type, item.value))
            return f"{ref} {operator_sql[op]} ?"
        if op in {"in", "not_in"}:
            values = [self._coerce_scalar(duckdb_type, x) for x in item.value]
            parameters.extend(values)
            placeholders = ", ".join("?" for _ in values)
            return f"{ref} {'NOT IN' if op == 'not_in' else 'IN'} ({placeholders})"
        if op == "between":
            lower, upper = [self._coerce_scalar(duckdb_type, x) for x in item.value]
            parameters.extend([lower, upper])
            return f"{ref} BETWEEN ? AND ?"
        raise QueryValidationError(f"Unsupported filter operator: {op}")

    def _compile_child_filter(
        self,
        item: TypedFilter,
        child_runtime: RuntimeDataset,
        alias: str,
        parameters: list[Any],
    ) -> str:
        referenced = self._runtime(item.column.dataset)
        if referenced.logical_name != child_runtime.logical_name:
            raise QueryValidationError(
                "Child-aggregation filters may reference only the child dataset being aggregated"
            )
        namespace = Namespace(
            logical_name=child_runtime.logical_name,
            alias=alias,
            columns={x.name.upper(): x.duckdb_type for x in child_runtime.schema.columns},
        )
        return self._compile_filter(item, {child_runtime.logical_name: namespace}, parameters)

    @staticmethod
    def _validate_aggregate_type(function: str, duckdb_type: str | None) -> None:
        if function in {"sum", "avg"}:
            if duckdb_type is None or not duckdb_type.upper().startswith(_NUMERIC_TYPES):
                raise QueryValidationError(
                    f"Aggregate {function} requires a numeric column; received {duckdb_type or 'none'}"
                )

    @staticmethod
    def _aggregate_sql(function: str, ref: str | None) -> str:
        if function == "count":
            return f"COUNT({ref or '*'})"
        if function == "count_distinct":
            if ref is None:
                raise QueryValidationError("count_distinct requires a column")
            return f"COUNT(DISTINCT {ref})"
        mapping = {"sum": "SUM", "avg": "AVG", "min": "MIN", "max": "MAX"}
        if ref is None:
            raise QueryValidationError(f"{function} requires a column")
        return f"{mapping[function]}({ref})"

    def _compile_child_subquery(
        self,
        child: RuntimeDataset,
        contract: RelationshipContract,
        aggregation: Any,
        child_alias: str,
        parameters: list[Any],
    ) -> tuple[str, dict[str, str]]:
        expected_keys = [x.upper() for x in contract.keys]
        actual_keys = [x.upper() for x in aggregation.group_by]
        if actual_keys != expected_keys:
            raise JoinPolicyError(
                f"Child relation {child.logical_name!r} must be aggregated exactly by {contract.keys}; "
                f"received {aggregation.group_by}"
            )
        child_columns = {x.name.upper(): x.duckdb_type for x in child.schema.columns}
        select_parts: list[str] = []
        exposed: dict[str, str] = {}
        for key in contract.keys:
            if key.upper() not in child_columns:
                raise SchemaValidationError(f"Child dataset {child.logical_name!r} lacks join key {key!r}")
            select_parts.append(_quote_identifier(key))
            exposed[key.upper()] = child_columns[key.upper()]
        for aggregate in aggregation.aggregates:
            assert isinstance(aggregate, ChildAggregate)
            ref = None
            result_type = "BIGINT" if aggregate.function in {"count", "count_distinct"} else "DOUBLE"
            if aggregate.column is not None:
                column_type = child_columns.get(aggregate.column.upper())
                if column_type is None:
                    raise QueryValidationError(
                        f"Unknown child column {aggregate.column!r} on {child.logical_name!r}"
                    )
                ref = _quote_identifier(aggregate.column)
                self._validate_aggregate_type(aggregate.function, column_type)
                if aggregate.function in {"min", "max"}:
                    result_type = column_type
            select_parts.append(
                f"{self._aggregate_sql(aggregate.function, ref)} AS {_quote_identifier(aggregate.alias)}"
            )
            exposed[aggregate.alias.upper()] = result_type
        where_parts = [
            self._compile_child_filter(x, child, child_alias, parameters) for x in aggregation.filters
        ]
        sql = (
            f"SELECT {', '.join(select_parts)} "
            f"FROM {_quote_identifier(child.view_name)} AS {_quote_identifier(child_alias)}"
        )
        if where_parts:
            sql += " WHERE " + " AND ".join(f"({x})" for x in where_parts)
        sql += " GROUP BY " + ", ".join(_quote_identifier(x) for x in contract.keys)
        return sql, exposed

    def _build_query_context(
        self,
        base_dataset: str,
        joins: list[JoinSpec],
        *,
        parameters: list[Any] | None = None,
    ) -> QueryContext:
        """Build the governed FROM/JOIN clause shared by query and survey compilers."""

        base = self._runtime(base_dataset)
        base_alias = "b"
        namespaces: dict[str, Namespace] = {
            base.logical_name: Namespace(
                logical_name=base.logical_name,
                alias=base_alias,
                columns={x.name.upper(): x.duckdb_type for x in base.schema.columns},
            )
        }
        bound_parameters = parameters if parameters is not None else []
        from_sql = f"FROM {_quote_identifier(base.view_name)} AS {_quote_identifier(base_alias)}"
        join_contract_ids: list[str] = []
        datasets_used = [base.logical_name]

        for index, join in enumerate(joins, start=1):
            target = self._runtime(join.dataset)
            if target.logical_name == base.logical_name:
                raise JoinPolicyError("Self joins are not approved")
            contract, direction = self.catalog.relationship(
                base.binding.source.relation, target.binding.source.relation
            )
            join_contract_ids.append(contract.relationship_id)
            datasets_used.append(target.logical_name)
            alias = f"j{index}"
            join_keyword = "LEFT JOIN" if join.how == "left" else "INNER JOIN"
            if direction == "parent_to_child":
                if contract.parent_to_child_requires_preaggregation and join.aggregation is None:
                    raise JoinPolicyError(
                        f"Joining {base.logical_name!r} to child {target.logical_name!r} requires "
                        f"preaggregation to {contract.keys}; direct joins can multiply household weights"
                    )
                if join.aggregation is None:
                    raise JoinPolicyError("Missing required child aggregation")
                child_sql, exposed = self._compile_child_subquery(
                    target, contract, join.aggregation, f"c{index}", bound_parameters
                )
                namespaces[target.logical_name] = Namespace(target.logical_name, alias, exposed)
                on_parts = [
                    f"{_quote_identifier(base_alias)}.{_quote_identifier(key)} = "
                    f"{_quote_identifier(alias)}.{_quote_identifier(key)}"
                    for key in contract.keys
                ]
                from_sql += (
                    f" {join_keyword} ({child_sql}) AS {_quote_identifier(alias)} ON "
                    + " AND ".join(on_parts)
                )
            elif direction == "child_to_parent":
                if join.aggregation is not None:
                    raise JoinPolicyError("Child-to-parent joins do not accept child aggregation")
                namespaces[target.logical_name] = Namespace(
                    target.logical_name,
                    alias,
                    {x.name.upper(): x.duckdb_type for x in target.schema.columns},
                )
                on_parts = [
                    f"{_quote_identifier(base_alias)}.{_quote_identifier(key)} = "
                    f"{_quote_identifier(alias)}.{_quote_identifier(key)}"
                    for key in contract.keys
                ]
                from_sql += (
                    f" {join_keyword} {_quote_identifier(target.view_name)} AS {_quote_identifier(alias)} ON "
                    + " AND ".join(on_parts)
                )
            else:
                raise JoinPolicyError(f"Unsupported approved join direction: {direction}")

        return QueryContext(
            base=base,
            namespaces=namespaces,
            parameters=bound_parameters,
            from_sql=from_sql,
            datasets_used=datasets_used,
            join_contract_ids=join_contract_ids,
        )

    def compile(self, spec: QuerySpec | dict[str, Any]) -> CompiledQuery:
        if not isinstance(spec, QuerySpec):
            spec = QuerySpec.model_validate(spec)
        context = self._build_query_context(spec.base_dataset, spec.joins)
        namespaces = context.namespaces
        parameters = context.parameters
        from_sql = context.from_sql

        output_aliases: set[str] = set()
        selected_plain: list[tuple[str, str]] = []
        select_parts: list[str] = []
        has_aggregate = False
        for projection in spec.select:
            if isinstance(projection, ColumnProjection):
                runtime = self._runtime(projection.column.dataset)
                namespace = namespaces.get(runtime.logical_name)
                if namespace is None:
                    raise QueryValidationError(
                        f"Projection references dataset {projection.column.dataset!r}, which is not in the query"
                    )
                self._column_type(namespace, projection.column.column)
                ref = f"{_quote_identifier(namespace.alias)}.{_quote_identifier(projection.column.column)}"
                alias = projection.alias or projection.column.column
                selected_plain.append((runtime.logical_name, projection.column.column.upper()))
            else:
                assert isinstance(projection, AggregateProjection)
                has_aggregate = True
                ref = None
                if projection.column is not None:
                    runtime = self._runtime(projection.column.dataset)
                    namespace = namespaces.get(runtime.logical_name)
                    if namespace is None:
                        raise QueryValidationError(
                            f"Aggregate references dataset {projection.column.dataset!r}, which is not in the query"
                        )
                    column_type = self._column_type(namespace, projection.column.column)
                    self._validate_aggregate_type(projection.function, column_type)
                    ref = f"{_quote_identifier(namespace.alias)}.{_quote_identifier(projection.column.column)}"
                alias = projection.alias
                ref = self._aggregate_sql(projection.function, ref)
            if alias.upper() in output_aliases:
                raise QueryValidationError(f"Duplicate output alias: {alias!r}")
            output_aliases.add(alias.upper())
            select_parts.append(f"{ref} AS {_quote_identifier(alias)}")

        group_refs: list[str] = []
        group_keys: set[tuple[str, str]] = set()
        for column in spec.group_by:
            runtime = self._runtime(column.dataset)
            namespace = namespaces.get(runtime.logical_name)
            if namespace is None:
                raise QueryValidationError(
                    f"Group-by references dataset {column.dataset!r}, which is not in the query"
                )
            self._column_type(namespace, column.column)
            group_keys.add((runtime.logical_name, column.column.upper()))
            group_refs.append(
                f"{_quote_identifier(namespace.alias)}.{_quote_identifier(column.column)}"
            )
        if has_aggregate:
            missing = [item for item in selected_plain if item not in group_keys]
            if missing:
                raise QueryValidationError(
                    f"Every non-aggregate projection must be grouped when aggregates are present: {missing}"
                )
        elif spec.group_by:
            missing = [item for item in selected_plain if item not in group_keys]
            if missing:
                raise QueryValidationError(f"Selected columns are missing from GROUP BY: {missing}")

        where_parts = [self._compile_filter(x, namespaces, parameters) for x in spec.filters]
        sql = f"SELECT {', '.join(select_parts)} {from_sql}"
        if where_parts:
            sql += " WHERE " + " AND ".join(f"({x})" for x in where_parts)
        if group_refs:
            sql += " GROUP BY " + ", ".join(group_refs)
        if spec.order_by:
            order_parts = []
            for item in spec.order_by:
                if item.output_alias.upper() not in output_aliases:
                    raise QueryValidationError(
                        f"ORDER BY must reference a selected output alias: {item.output_alias!r}"
                    )
                order_parts.append(
                    f"{_quote_identifier(item.output_alias)} {item.direction.upper()}"
                )
            sql += " ORDER BY " + ", ".join(order_parts)
        requested_limit = spec.limit or self.config.engine.max_result_rows
        effective_limit = min(requested_limit, self.config.engine.max_result_rows)
        sql += f" LIMIT {effective_limit + 1}"

        canonical = spec.model_dump(mode="json")
        query_fingerprint = _sha256_text(_canonical_json(canonical))
        return CompiledQuery(
            sql=sql,
            display_sql=_render_display_sql(sql, parameters),
            parameters=parameters,
            effective_limit=effective_limit,
            canonical_spec=canonical,
            query_fingerprint=query_fingerprint,
            datasets_used=context.datasets_used,
            join_contract_ids=context.join_contract_ids,
        )

    def execute(self, spec: QuerySpec | dict[str, Any]) -> QueryResult:
        compiled = self.compile(spec)
        started = datetime.now(timezone.utc)
        start_clock = time.perf_counter()
        cursor = self.connection.execute(compiled.sql, compiled.parameters)
        names = [item[0] for item in cursor.description]
        raw_rows = cursor.fetchall()
        truncated = len(raw_rows) > compiled.effective_limit
        raw_rows = raw_rows[: compiled.effective_limit]
        rows = [dict(zip(names, values)) for values in raw_rows]
        finished = datetime.now(timezone.utc)
        elapsed_ms = (time.perf_counter() - start_clock) * 1000
        dataset_metadata = []
        for logical_name in compiled.datasets_used:
            runtime = self.runtime_datasets[logical_name]
            try:
                stat = runtime.physical_path.stat()
                size_bytes, modified_ns = stat.st_size, stat.st_mtime_ns
            except OSError:
                size_bytes, modified_ns = None, None
            dataset_metadata.append(
                DatasetExecutionMetadata(
                    logical_name=logical_name,
                    source_file_id=runtime.binding.source.source_file_id,
                    physical_path=str(runtime.physical_path),
                    synthetic_fixture=runtime.synthetic_fixture,
                    size_bytes=size_bytes,
                    modified_ns=modified_ns,
                    columns=runtime.schema.columns,
                )
            )
        version_row = self.connection.execute("PRAGMA version").fetchone()
        duckdb_version = str(version_row[0]) if version_row else "unknown"
        metadata = ExecutionMetadata(
            run_id=str(uuid.uuid4()),
            query_fingerprint=compiled.query_fingerprint,
            sql_fingerprint=_sha256_text(compiled.sql + "\n" + _canonical_json(compiled.parameters)),
            started_at=started,
            finished_at=finished,
            elapsed_ms=elapsed_ms,
            duckdb_version=duckdb_version,
            database=self.config.engine.database,
            memory_limit=self.config.engine.memory_limit,
            temp_directory=str(self.config.engine.temp_directory),
            threads=self.config.engine.threads,
            datasets=dataset_metadata,
            join_contract_ids=compiled.join_contract_ids,
            rows_returned=len(rows),
            result_truncated=truncated,
        )
        return QueryResult(
            columns=names,
            rows=rows,
            generated_sql=compiled.display_sql,
            parameterized_sql=compiled.sql,
            parameters=compiled.parameters,
            metadata=metadata,
        )
