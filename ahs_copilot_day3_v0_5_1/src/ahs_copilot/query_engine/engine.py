from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
import json
import math
import os
import re
import time
from typing import Any

import duckdb

from ahs_copilot import __version__
from ahs_copilot.metadata.models import RelationshipRecord, SourceFileRecord
from .catalog import CatalogBundle
from .config import EngineConfig, load_config
from .contracts import (
    AggregateSpec,
    ColumnSchema,
    CompiledQuery,
    DatasetSchema,
    FilterSpec,
    QueryResult,
    QuerySpec,
    SchemaInspection,
    SelectColumn,
)
from .errors import ConfigurationError, ExecutionError, QueryValidationError, SchemaValidationError


_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def quote_identifier(value: str) -> str:
    if not _IDENTIFIER.fullmatch(value):
        raise QueryValidationError(f"Unsafe identifier: {value!r}")
    return '"' + value.replace('"', '""') + '"'


def quote_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def json_safe(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (datetime,)):
        return value.isoformat()
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    return value


@dataclass
class ResolvedDataset:
    schema: DatasetSchema
    view_name: str
    source: SourceFileRecord
    actual_by_casefold: dict[str, str]

    def actual_column(self, requested: str) -> str:
        actual = self.actual_by_casefold.get(requested.casefold())
        if not actual:
            raise QueryValidationError(
                f"Unknown column '{requested}' for dataset '{self.schema.logical_dataset}'"
            )
        return actual


class AHSQueryEngine:
    def __init__(self, config_path: str | Path):
        self.config: EngineConfig = load_config(config_path)
        self.catalog = CatalogBundle(
            self.config.source_files_path,
            self.config.execution_catalog_path,
            self.config.semantic_catalog_path,
        )
        self.config.temp_directory.mkdir(parents=True, exist_ok=True)
        self.connection = duckdb.connect(database=":memory:")
        self.connection.execute(f"SET memory_limit={quote_literal(self.config.memory_limit)}")
        self.connection.execute(f"SET threads={self.config.threads}")
        self.connection.execute(
            f"SET preserve_insertion_order={'true' if self.config.preserve_insertion_order else 'false'}"
        )
        self.connection.execute(f"SET temp_directory={quote_literal(str(self.config.temp_directory))}")
        self.datasets: dict[str, ResolvedDataset] = {}
        self._register_datasets()

    def __enter__(self) -> "AHSQueryEngine":
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()

    def close(self) -> None:
        if self.connection is not None:
            self.connection.close()
            self.connection = None

    def _resolve_path(self, logical: str) -> tuple[Path, bool]:
        ds = self.config.datasets[logical]
        fixture_path = self.config.fixture_directory / ds.fixture_file
        if self.config.fixture_mode == "required":
            if not fixture_path.exists():
                raise ConfigurationError(f"Required fixture does not exist: {fixture_path}")
            return fixture_path, True
        if ds.path.exists():
            return ds.path, False
        if self.config.fixture_mode == "auto" and fixture_path.exists():
            return fixture_path, True
        raise ConfigurationError(
            f"Configured dataset '{logical}' does not exist at {ds.path}; "
            f"fixture mode is {self.config.fixture_mode!r}"
        )

    def _register_datasets(self) -> None:
        for index, (logical, ds_cfg) in enumerate(self.config.datasets.items()):
            source = self.catalog.source_by_id.get(ds_cfg.source_file_id)
            if not source:
                raise ConfigurationError(
                    f"Dataset '{logical}' references unknown source_file_id '{ds_cfg.source_file_id}'"
                )
            if source.logical_dataset != logical:
                raise ConfigurationError(
                    f"Dataset '{logical}' does not match source contract logical_dataset "
                    f"'{source.logical_dataset}'"
                )
            path, fixture_used = self._resolve_path(logical)
            view_name = f"dataset_{index}_{logical}"
            sample_size = self.config.csv_sample_size
            sql = (
                f"CREATE VIEW {quote_identifier(view_name)} AS "
                f"SELECT * FROM read_csv_auto({quote_literal(str(path))}, "
                f"header=true, sample_size={sample_size}, union_by_name=true)"
            )
            try:
                self.connection.execute(sql)
                described = self.connection.execute(
                    f"DESCRIBE SELECT * FROM {quote_identifier(view_name)}"
                ).fetchall()
            except Exception as exc:
                raise SchemaValidationError(
                    f"Cannot inspect dataset '{logical}' from {path}: {exc}"
                ) from exc
            columns = [ColumnSchema(name=row[0], duckdb_type=row[1]) for row in described]
            actual = {c.name.casefold(): c.name for c in columns}

            missing_relationship = [k for k in source.relationship_keys if k.casefold() not in actual]
            if missing_relationship:
                raise SchemaValidationError(
                    f"Dataset '{logical}' is missing approved relationship key columns: "
                    f"{missing_relationship}"
                )
            missing_identity = [k for k in source.row_identity_columns if k.casefold() not in actual]
            if missing_identity:
                raise SchemaValidationError(
                    f"Dataset '{logical}' is missing declared row-identity columns: {missing_identity}"
                )
            missing_pk = [
                k for k in (source.declared_primary_key or []) if k.casefold() not in actual
            ]
            if missing_pk:
                raise SchemaValidationError(
                    f"Dataset '{logical}' is missing declared primary-key columns: {missing_pk}"
                )

            schema = DatasetSchema(
                logical_dataset=logical,
                physical_path=str(path),
                source_file_id=source.source_file_id,
                grain=source.grain,
                relationship_keys=source.relationship_keys,
                row_identity_columns=source.row_identity_columns,
                declared_primary_key=source.declared_primary_key,
                fixture_used=fixture_used,
                columns=columns,
            )
            self.datasets[logical] = ResolvedDataset(schema, view_name, source, actual)

    def inspect_schemas(self) -> SchemaInspection:
        return SchemaInspection(engine_version=__version__, datasets=[d.schema for d in self.datasets.values()])

    def dataset(self, logical: str) -> ResolvedDataset:
        dataset = self.datasets.get(logical)
        if not dataset:
            raise QueryValidationError(f"Unknown logical dataset: {logical}")
        return dataset

    def _coerce_value(self, value: Any, duckdb_type: str) -> Any:
        kind = duckdb_type.upper()
        try:
            if any(token in kind for token in ["TINYINT", "SMALLINT", "INTEGER", "BIGINT", "HUGEINT"]):
                if isinstance(value, bool):
                    raise ValueError("boolean is not an integer filter value")
                return int(value)
            if any(token in kind for token in ["DECIMAL", "DOUBLE", "FLOAT", "REAL"]):
                return float(value)
            if "BOOLEAN" in kind:
                if isinstance(value, bool):
                    return value
                if str(value).strip().casefold() in {"true", "1", "yes"}:
                    return True
                if str(value).strip().casefold() in {"false", "0", "no"}:
                    return False
                raise ValueError("not a boolean")
            if "DATE" in kind and "TIMESTAMP" not in kind:
                return str(value)
            return str(value) if value is not None else None
        except Exception as exc:
            raise QueryValidationError(
                f"Cannot coerce filter value {value!r} to DuckDB type {duckdb_type}"
            ) from exc

    def _compile_filter(
        self,
        dataset: ResolvedDataset,
        alias: str,
        spec: FilterSpec,
        parameters: list[Any],
    ) -> str:
        actual = dataset.actual_column(spec.column)
        column_type = next(c.duckdb_type for c in dataset.schema.columns if c.name == actual)
        ref = f"{quote_identifier(alias)}.{quote_identifier(actual)}"
        op_map = {"eq":"=", "ne":"<>", "gt":">", "ge":">=", "lt":"<", "le":"<="}
        if spec.operator in op_map:
            parameters.append(self._coerce_value(spec.value, column_type))
            return f"{ref} {op_map[spec.operator]} ?"
        if spec.operator in {"in", "not_in"}:
            values = [self._coerce_value(v, column_type) for v in (spec.values or [])]
            parameters.extend(values)
            operator = "IN" if spec.operator == "in" else "NOT IN"
            return f"{ref} {operator} ({', '.join('?' for _ in values)})"
        if spec.operator == "between":
            parameters.extend([
                self._coerce_value(spec.lower, column_type),
                self._coerce_value(spec.upper, column_type),
            ])
            return f"{ref} BETWEEN ? AND ?"
        if spec.operator == "is_null":
            return f"{ref} IS NULL"
        if spec.operator == "not_null":
            return f"{ref} IS NOT NULL"
        raise QueryValidationError(f"Unsupported filter operator: {spec.operator}")

    def _aggregate_sql(self, dataset: ResolvedDataset, alias: str, agg: AggregateSpec) -> str:
        if agg.function == "count" and agg.column is None:
            inner = "*"
        else:
            actual = dataset.actual_column(agg.column or "")
            inner = f"{quote_identifier(alias)}.{quote_identifier(actual)}"
            if agg.distinct:
                inner = f"DISTINCT {inner}"
        return f"{agg.function.upper()}({inner}) AS {quote_identifier(agg.alias)}"

    def compile(self, spec: QuerySpec) -> CompiledQuery:
        if spec.limit > self.config.max_result_rows:
            raise QueryValidationError(
                f"Requested limit {spec.limit} exceeds engine.max_result_rows={self.config.max_result_rows}"
            )
        base = self.dataset(spec.base_dataset)
        parameters: list[Any] = []
        relationship_ids: list[str] = []
        datasets = [spec.base_dataset]
        join_sql: list[str] = []
        joined_outputs: dict[tuple[str, str], tuple[str, str]] = {}

        for idx, join in enumerate(spec.joins):
            rel = self.catalog.relationship_by_id.get(join.relationship_id)
            if not rel:
                raise QueryValidationError(f"Unknown relationship_id: {join.relationship_id}")
            if rel.parent_dataset != spec.base_dataset:
                raise QueryValidationError(
                    f"Relationship '{rel.relationship_id}' cannot be used from base dataset "
                    f"'{spec.base_dataset}'"
                )
            if join.join_type not in rel.allowed_join_types:
                raise QueryValidationError(
                    f"Join type '{join.join_type}' is not approved for '{rel.relationship_id}'"
                )
            if not rel.aggregate_child_first:
                raise QueryValidationError(
                    f"Relationship '{rel.relationship_id}' is not certified for governed child preaggregation"
                )
            if [x.casefold() for x in rel.aggregation_keys] != [x.casefold() for x in rel.child_keys]:
                raise QueryValidationError(
                    f"Relationship '{rel.relationship_id}' must aggregate exactly to child join keys"
                )
            child = self.dataset(rel.child_dataset)
            child_alias = f"c{idx}"
            join_alias = f"j{idx}"
            key_selects = []
            for key in rel.aggregation_keys:
                actual = child.actual_column(key)
                key_selects.append(
                    f"{quote_identifier(child_alias)}.{quote_identifier(actual)} AS {quote_identifier(key)}"
                )
            agg_selects = [self._aggregate_sql(child, child_alias, agg) for agg in join.aggregates]
            child_where = [self._compile_filter(child, child_alias, f, parameters) for f in join.filters]
            child_query = (
                f"SELECT {', '.join(key_selects + agg_selects)} "
                f"FROM {quote_identifier(child.view_name)} AS {quote_identifier(child_alias)}"
            )
            if child_where:
                child_query += " WHERE " + " AND ".join(child_where)
            child_query += " GROUP BY " + ", ".join(
                f"{quote_identifier(child_alias)}.{quote_identifier(child.actual_column(k))}"
                for k in rel.aggregation_keys
            )
            on_parts = []
            for parent_key, child_key in zip(rel.parent_keys, rel.child_keys):
                parent_actual = base.actual_column(parent_key)
                on_parts.append(
                    f"{quote_identifier('b')}.{quote_identifier(parent_actual)} = "
                    f"{quote_identifier(join_alias)}.{quote_identifier(child_key)}"
                )
            join_sql.append(
                f"{join.join_type.upper()} JOIN ({child_query}) AS {quote_identifier(join_alias)} "
                f"ON {' AND '.join(on_parts)}"
            )
            for agg in join.aggregates:
                joined_outputs[(rel.child_dataset.casefold(), agg.alias.casefold())] = (join_alias, agg.alias)
            relationship_ids.append(rel.relationship_id)
            datasets.append(rel.child_dataset)

        select_sql: list[str] = []
        output_names: set[str] = set()
        for col in spec.columns:
            dataset_name = col.dataset or spec.base_dataset
            output_name = col.alias or col.column
            if output_name.casefold() in output_names:
                raise QueryValidationError(f"Duplicate output name: {output_name}")
            output_names.add(output_name.casefold())
            if dataset_name == spec.base_dataset:
                actual = base.actual_column(col.column)
                select_sql.append(
                    f"{quote_identifier('b')}.{quote_identifier(actual)} AS {quote_identifier(output_name)}"
                )
            else:
                joined = joined_outputs.get((dataset_name.casefold(), col.column.casefold()))
                if not joined:
                    raise QueryValidationError(
                        f"Joined dataset output '{dataset_name}.{col.column}' is not a certified child aggregate alias"
                    )
                alias, actual = joined
                select_sql.append(
                    f"{quote_identifier(alias)}.{quote_identifier(actual)} AS {quote_identifier(output_name)}"
                )

        for agg in spec.aggregates:
            if agg.alias.casefold() in output_names:
                raise QueryValidationError(f"Duplicate output name: {agg.alias}")
            output_names.add(agg.alias.casefold())
            select_sql.append(self._aggregate_sql(base, "b", agg))

        group_sql: list[str] = []
        for group in spec.group_by:
            dataset_name = group.dataset or spec.base_dataset
            if dataset_name != spec.base_dataset:
                joined = joined_outputs.get((dataset_name.casefold(), group.column.casefold()))
                if not joined:
                    raise QueryValidationError(
                        f"Unknown joined group expression '{dataset_name}.{group.column}'"
                    )
                group_sql.append(
                    f"{quote_identifier(joined[0])}.{quote_identifier(joined[1])}"
                )
            else:
                group_sql.append(
                    f"{quote_identifier('b')}.{quote_identifier(base.actual_column(group.column))}"
                )

        if spec.aggregates and spec.columns:
            selected_nonaggregates = []
            for col in spec.columns:
                ds_name = col.dataset or spec.base_dataset
                if ds_name == spec.base_dataset:
                    selected_nonaggregates.append(
                        f"{quote_identifier('b')}.{quote_identifier(base.actual_column(col.column))}"
                    )
                else:
                    joined = joined_outputs[(ds_name.casefold(), col.column.casefold())]
                    selected_nonaggregates.append(
                        f"{quote_identifier(joined[0])}.{quote_identifier(joined[1])}"
                    )
            if {x.casefold() for x in selected_nonaggregates} - {x.casefold() for x in group_sql}:
                raise QueryValidationError("Every non-aggregate output must be included in group_by")

        where_sql = [self._compile_filter(base, "b", f, parameters) for f in spec.filters]
        sql = (
            f"SELECT {', '.join(select_sql)} "
            f"FROM {quote_identifier(base.view_name)} AS {quote_identifier('b')}"
        )
        if join_sql:
            sql += " " + " ".join(join_sql)
        if where_sql:
            sql += " WHERE " + " AND ".join(where_sql)
        if group_sql:
            sql += " GROUP BY " + ", ".join(group_sql)
        if spec.order_by:
            order_parts = []
            for order in spec.order_by:
                if order.output.casefold() not in output_names:
                    raise QueryValidationError(
                        f"order_by output '{order.output}' is not present in the select list"
                    )
                order_parts.append(f"{quote_identifier(order.output)} {order.direction.upper()}")
            sql += " ORDER BY " + ", ".join(order_parts)
        sql += f" LIMIT {spec.limit}"
        fingerprint_payload = json.dumps(
            {"sql": sql, "parameters": parameters, "relationships": relationship_ids},
            sort_keys=True,
            default=str,
        ).encode("utf-8")
        display = sql
        for value in parameters:
            replacement = quote_literal(str(value)) if isinstance(value, str) else str(value)
            display = display.replace("?", replacement, 1)
        return CompiledQuery(
            sql=sql,
            display_sql=display,
            parameters=parameters,
            query_fingerprint=sha256(fingerprint_payload).hexdigest(),
            datasets=list(dict.fromkeys(datasets)),
            relationship_ids=relationship_ids,
        )

    def _execute_sql(self, sql: str, parameters: list[Any]) -> tuple[list[str], list[dict[str, Any]], float]:
        start = time.perf_counter()
        try:
            cursor = self.connection.execute(sql, parameters)
            names = [d[0] for d in cursor.description]
            raw_rows = cursor.fetchall()
        except Exception as exc:
            raise ExecutionError(str(exc)) from exc
        elapsed = (time.perf_counter() - start) * 1000
        rows = [
            {name: json_safe(value) for name, value in zip(names, row)}
            for row in raw_rows
        ]
        return names, rows, elapsed

    def execute(self, spec: QuerySpec) -> QueryResult:
        compiled = self.compile(spec)
        columns, rows, elapsed = self._execute_sql(compiled.sql, compiled.parameters)
        file_metadata = []
        for logical in compiled.datasets:
            ds = self.dataset(logical)
            path = Path(ds.schema.physical_path)
            stat = path.stat()
            file_metadata.append({
                "logical_dataset": logical,
                "path": str(path),
                "size_bytes": stat.st_size,
                "modified_ns": stat.st_mtime_ns,
                "fixture_used": ds.schema.fixture_used,
                "source_file_id": ds.schema.source_file_id,
            })
        return QueryResult(
            columns=columns,
            rows=rows,
            row_count=len(rows),
            compiled=compiled,
            execution_metadata={
                "engine_version": __version__,
                "duckdb_version": duckdb.__version__,
                "executed_at": datetime.now(timezone.utc).isoformat(),
                "elapsed_ms": round(elapsed, 3),
                "files": file_metadata,
                "schemas": self.inspect_schemas().model_dump(mode="json"),
                "variance_estimation": "NOT_IMPLEMENTED",
            },
        )
