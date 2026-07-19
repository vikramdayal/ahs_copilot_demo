from __future__ import annotations

from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ColumnSchema(StrictModel):
    name: str
    duckdb_type: str


class DatasetSchema(StrictModel):
    logical_dataset: str
    physical_path: str
    source_file_id: str
    grain: str
    relationship_keys: list[str]
    row_identity_columns: list[str]
    declared_primary_key: list[str] | None
    fixture_used: bool
    columns: list[ColumnSchema]


class SchemaInspection(StrictModel):
    engine_version: str
    datasets: list[DatasetSchema]


class FilterSpec(StrictModel):
    column: str
    operator: Literal["eq", "ne", "gt", "ge", "lt", "le", "in", "not_in", "between", "is_null", "not_null"]
    value: Any | None = None
    values: list[Any] | None = None
    lower: Any | None = None
    upper: Any | None = None

    @model_validator(mode="after")
    def validate_operands(self) -> "FilterSpec":
        if self.operator in {"eq", "ne", "gt", "ge", "lt", "le"} and self.value is None:
            raise ValueError(f"operator {self.operator} requires value")
        if self.operator in {"in", "not_in"} and not self.values:
            raise ValueError(f"operator {self.operator} requires a non-empty values list")
        if self.operator == "between" and (self.lower is None or self.upper is None):
            raise ValueError("between requires lower and upper")
        return self


class SelectColumn(StrictModel):
    dataset: str | None = None
    column: str
    alias: str | None = None


class AggregateSpec(StrictModel):
    function: Literal["count", "sum", "avg", "min", "max"]
    column: str | None = None
    alias: str
    distinct: bool = False

    @model_validator(mode="after")
    def validate_column(self) -> "AggregateSpec":
        if self.function != "count" and not self.column:
            raise ValueError(f"{self.function} requires a column")
        return self


class JoinSpec(StrictModel):
    relationship_id: str
    join_type: Literal["left", "inner"] = "left"
    aggregates: list[AggregateSpec]
    filters: list[FilterSpec] = Field(default_factory=list)

    @model_validator(mode="after")
    def require_aggregates(self) -> "JoinSpec":
        if not self.aggregates:
            raise ValueError("A governed child join requires at least one child aggregate")
        aliases = [a.alias.casefold() for a in self.aggregates]
        if len(aliases) != len(set(aliases)):
            raise ValueError("Child aggregate aliases must be unique")
        return self


class OrderSpec(StrictModel):
    output: str
    direction: Literal["asc", "desc"] = "asc"


class QuerySpec(StrictModel):
    base_dataset: str
    columns: list[SelectColumn] = Field(default_factory=list)
    aggregates: list[AggregateSpec] = Field(default_factory=list)
    filters: list[FilterSpec] = Field(default_factory=list)
    joins: list[JoinSpec] = Field(default_factory=list)
    group_by: list[SelectColumn] = Field(default_factory=list)
    order_by: list[OrderSpec] = Field(default_factory=list)
    limit: int = Field(default=1000, ge=1)

    @model_validator(mode="after")
    def require_output(self) -> "QuerySpec":
        if not self.columns and not self.aggregates:
            raise ValueError("At least one output column or aggregate is required")
        return self


class CompiledQuery(StrictModel):
    sql: str
    display_sql: str
    parameters: list[Any]
    query_fingerprint: str
    datasets: list[str]
    relationship_ids: list[str]


class QueryResult(StrictModel):
    columns: list[str]
    rows: list[dict[str, Any]]
    row_count: int
    compiled: CompiledQuery
    execution_metadata: dict[str, Any]
