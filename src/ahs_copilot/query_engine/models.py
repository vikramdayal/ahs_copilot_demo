from __future__ import annotations

from datetime import datetime
from typing import Any, Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

_IDENTIFIER_PATTERN = r"^[A-Za-z_][A-Za-z0-9_]*$"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class QualifiedColumn(StrictModel):
    dataset: str = Field(pattern=_IDENTIFIER_PATTERN)
    column: str = Field(pattern=_IDENTIFIER_PATTERN)


FilterOperator = Literal[
    "eq",
    "ne",
    "lt",
    "le",
    "gt",
    "ge",
    "in",
    "not_in",
    "between",
    "is_null",
    "is_not_null",
]


class TypedFilter(StrictModel):
    column: QualifiedColumn
    operator: FilterOperator
    value: Any = None

    @model_validator(mode="after")
    def validate_shape(self) -> "TypedFilter":
        if self.operator in {"is_null", "is_not_null"}:
            if self.value is not None:
                raise ValueError(f"{self.operator} does not accept a value")
            return self
        if self.value is None:
            raise ValueError(f"{self.operator} requires a value")
        if self.operator in {"in", "not_in"}:
            if not isinstance(self.value, list) or not self.value:
                raise ValueError(f"{self.operator} requires a non-empty list")
        if self.operator == "between":
            if not isinstance(self.value, list) or len(self.value) != 2:
                raise ValueError("between requires a two-item list")
        return self


class ColumnProjection(StrictModel):
    kind: Literal["column"] = "column"
    column: QualifiedColumn
    alias: str | None = Field(default=None, pattern=_IDENTIFIER_PATTERN)


AggregateFunction = Literal["count", "count_distinct", "sum", "avg", "min", "max"]


class AggregateProjection(StrictModel):
    kind: Literal["aggregate"] = "aggregate"
    function: AggregateFunction
    column: QualifiedColumn | None = None
    alias: str = Field(pattern=_IDENTIFIER_PATTERN)

    @model_validator(mode="after")
    def validate_count_star(self) -> "AggregateProjection":
        if self.column is None and self.function != "count":
            raise ValueError("Only count may omit column (COUNT(*))")
        return self


Projection = Annotated[Union[ColumnProjection, AggregateProjection], Field(discriminator="kind")]


class ChildAggregate(StrictModel):
    function: AggregateFunction
    column: str | None = Field(default=None, pattern=_IDENTIFIER_PATTERN)
    alias: str = Field(pattern=_IDENTIFIER_PATTERN)

    @model_validator(mode="after")
    def validate_count_star(self) -> "ChildAggregate":
        if self.column is None and self.function != "count":
            raise ValueError("Only count may omit column (COUNT(*))")
        return self


class ChildAggregation(StrictModel):
    group_by: list[str] = Field(default_factory=lambda: ["CONTROL"])
    filters: list[TypedFilter] = Field(default_factory=list)
    aggregates: list[ChildAggregate] = Field(min_length=1)

    @field_validator("group_by")
    @classmethod
    def validate_group_by(cls, values: list[str]) -> list[str]:
        if not values:
            raise ValueError("Child aggregation must have at least one grouping key")
        for value in values:
            if not value or not value.replace("_", "a").isalnum() or value[0].isdigit():
                raise ValueError(f"Invalid grouping identifier: {value!r}")
        if len(set(v.upper() for v in values)) != len(values):
            raise ValueError("Child aggregation grouping keys must be unique")
        return values

    @model_validator(mode="after")
    def validate_aliases(self) -> "ChildAggregation":
        aliases = [x.alias.upper() for x in self.aggregates]
        if len(aliases) != len(set(aliases)):
            raise ValueError("Child aggregate aliases must be unique")
        return self


class JoinSpec(StrictModel):
    dataset: str = Field(pattern=_IDENTIFIER_PATTERN)
    how: Literal["inner", "left"] = "left"
    aggregation: ChildAggregation | None = None


class OrderBy(StrictModel):
    output_alias: str = Field(pattern=_IDENTIFIER_PATTERN)
    direction: Literal["asc", "desc"] = "asc"


class QuerySpec(StrictModel):
    """The only executable query input. There is intentionally no raw SQL field."""

    base_dataset: str = Field(pattern=_IDENTIFIER_PATTERN)
    select: list[Projection] = Field(min_length=1)
    filters: list[TypedFilter] = Field(default_factory=list)
    joins: list[JoinSpec] = Field(default_factory=list)
    group_by: list[QualifiedColumn] = Field(default_factory=list)
    order_by: list[OrderBy] = Field(default_factory=list)
    limit: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def validate_unique_joins(self) -> "QuerySpec":
        names = [x.dataset.lower() for x in self.joins]
        if len(names) != len(set(names)):
            raise ValueError("A dataset may be joined at most once")
        return self


class ColumnSchema(StrictModel):
    name: str
    duckdb_type: str
    nullable: bool


class DatasetSchema(StrictModel):
    logical_name: str
    source_file_id: str
    source_name: str
    relation: str
    grain: str
    join_keys: list[str]
    physical_path: str
    synthetic_fixture: bool
    columns: list[ColumnSchema]


class CompiledQuery(StrictModel):
    sql: str
    display_sql: str
    parameters: list[Any]
    effective_limit: int
    canonical_spec: dict[str, Any]
    query_fingerprint: str
    datasets_used: list[str]
    join_contract_ids: list[str]


class DatasetExecutionMetadata(StrictModel):
    logical_name: str
    source_file_id: str
    physical_path: str
    synthetic_fixture: bool
    size_bytes: int | None
    modified_ns: int | None
    columns: list[ColumnSchema]


class ExecutionMetadata(StrictModel):
    run_id: str
    query_fingerprint: str
    sql_fingerprint: str
    started_at: datetime
    finished_at: datetime
    elapsed_ms: float
    duckdb_version: str
    database: str
    memory_limit: str
    temp_directory: str
    threads: int
    datasets: list[DatasetExecutionMetadata]
    join_contract_ids: list[str]
    rows_returned: int
    result_truncated: bool
    variance_estimation: Literal["NOT_IMPLEMENTED"] = "NOT_IMPLEMENTED"


class QueryResult(StrictModel):
    columns: list[str]
    rows: list[dict[str, Any]]
    generated_sql: str
    parameterized_sql: str
    parameters: list[Any]
    metadata: ExecutionMetadata
