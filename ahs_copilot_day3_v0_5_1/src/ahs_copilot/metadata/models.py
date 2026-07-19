from __future__ import annotations

from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SourceFileRecord(StrictModel):
    source_file_id: str
    logical_dataset: str
    label: str
    access_level: Literal["PUF", "IUF"]
    grain: str
    relationship_keys: list[str] = Field(default_factory=list)
    row_identity_columns: list[str] = Field(default_factory=list)
    declared_primary_key: list[str] | None = None
    notes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_key_roles(self) -> "SourceFileRecord":
        def clean(values: list[str]) -> list[str]:
            normalized = [v.strip().upper() for v in values]
            if any(not v for v in normalized):
                raise ValueError("Key columns cannot be blank")
            if len(normalized) != len(set(normalized)):
                raise ValueError("Key columns cannot contain duplicates")
            return normalized

        self.relationship_keys = clean(self.relationship_keys)
        self.row_identity_columns = clean(self.row_identity_columns)
        if self.declared_primary_key is not None:
            self.declared_primary_key = clean(self.declared_primary_key)
        return self

    @property
    def required_physical_columns(self) -> list[str]:
        values = [*self.relationship_keys, *self.row_identity_columns]
        if self.declared_primary_key:
            values.extend(self.declared_primary_key)
        return list(dict.fromkeys(values))


class RelationshipRecord(StrictModel):
    relationship_id: str
    parent_dataset: str
    child_dataset: str
    parent_keys: list[str]
    child_keys: list[str]
    cardinality: Literal["ONE_TO_ONE", "ONE_TO_MANY", "MANY_TO_ONE", "MANY_TO_MANY"]
    aggregate_child_first: bool = False
    aggregation_keys: list[str] = Field(default_factory=list)
    allowed_join_types: list[Literal["left", "inner"]] = Field(default_factory=lambda: ["left"])

    @model_validator(mode="after")
    def validate_relationship(self) -> "RelationshipRecord":
        if len(self.parent_keys) != len(self.child_keys):
            raise ValueError("parent_keys and child_keys must have equal length")
        if self.aggregate_child_first and not self.aggregation_keys:
            raise ValueError("aggregation_keys are required when aggregate_child_first is true")
        return self


class ExecutionCatalog(StrictModel):
    version: str
    access_level: Literal["PUF", "IUF"]
    relationships: list[RelationshipRecord]


class VariableRecord(StrictModel):
    dataset: str
    name: str
    availability: Literal["PUF", "IUF_ONLY"]
    roles: list[str] = Field(default_factory=list)
    missing_codes: list[Any] = Field(default_factory=list)


class ConditionRecord(StrictModel):
    variable: str
    operator: str
    value: Any | None = None
    values: list[Any] | None = None
    lower: Any | None = None
    upper: Any | None = None


class UniverseRecord(StrictModel):
    universe_id: str
    dataset: str
    conditions: list[ConditionRecord] = Field(default_factory=list)


class WeightRecord(StrictModel):
    weight_id: str
    dataset: str
    variable: str | None = None
    availability: Literal["PUF", "IUF_ONLY"]


class RecodeRecord(StrictModel):
    recode_id: str
    dataset: str
    required_variables: list[str]
    availability: Literal["PUF", "IUF_ONLY"]


class SemanticCatalog(StrictModel):
    version: str
    variables: list[VariableRecord]
    universes: list[UniverseRecord]
    weights: list[WeightRecord]
    recodes: list[RecodeRecord]
