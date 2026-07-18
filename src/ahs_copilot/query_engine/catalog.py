from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from ahs_copilot.metadata.models import SourceFileRecord

from .config import AppConfig
from .errors import ConfigurationError, DatasetResolutionError, JoinPolicyError


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class RelationshipContract(StrictModel):
    relationship_id: str
    parent_relation: str
    child_relation: str
    keys: list[str]
    parent_to_child: Literal["ONE_TO_MANY"]
    child_to_parent: Literal["MANY_TO_ONE"]
    permitted_directions: list[Literal["parent_to_child", "child_to_parent"]]
    parent_to_child_requires_preaggregation: bool = True
    preaggregation_grain: str = "HOUSING_UNIT"
    notes: list[str] = Field(default_factory=list)


class ExecutionCatalog(StrictModel):
    catalog_version: str
    access_mode: Literal["PUF", "IUF"]
    approved_relations: list[str]
    relationships: list[RelationshipContract]


class DatasetBinding(StrictModel):
    logical_name: str
    source: SourceFileRecord
    configured_aliases: list[str]


class CatalogRegistry:
    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.source_files = self._load_source_files(config.metadata.source_files)
        self.execution_catalog = self._load_execution_catalog(config.metadata.execution_catalog)
        self._source_by_id = {x.source_file_id: x for x in self.source_files}
        self._bindings: dict[str, DatasetBinding] = {}
        self._aliases: dict[str, set[str]] = defaultdict(set)
        self._relationships = {x.relationship_id: x for x in self.execution_catalog.relationships}
        self._bind_configured_datasets()

    @staticmethod
    def _load_source_files(path: Path) -> list[SourceFileRecord]:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            return [SourceFileRecord.model_validate(x) for x in payload]
        except Exception as exc:
            raise ConfigurationError(f"Unable to load Day 2 source-file metadata {path}: {exc}") from exc

    @staticmethod
    def _load_execution_catalog(path: Path) -> ExecutionCatalog:
        try:
            return ExecutionCatalog.model_validate_json(path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise ConfigurationError(f"Unable to load certified execution catalog {path}: {exc}") from exc

    def _bind_configured_datasets(self) -> None:
        for logical_name, dataset_config in self.config.datasets.items():
            source = self._source_by_id.get(dataset_config.source_file_id)
            if source is None:
                raise ConfigurationError(
                    f"Dataset {logical_name!r} references unknown source_file_id {dataset_config.source_file_id!r}"
                )
            if source.access_level != self.execution_catalog.access_mode:
                raise ConfigurationError(
                    f"Dataset {logical_name!r} is {source.access_level}, but execution catalog is {self.execution_catalog.access_mode}"
                )
            if source.relation not in self.execution_catalog.approved_relations:
                raise ConfigurationError(f"Relation {source.relation!r} is not approved for execution")
            binding = DatasetBinding(
                logical_name=logical_name,
                source=source,
                configured_aliases=dataset_config.aliases,
            )
            self._bindings[logical_name] = binding
            aliases = {
                logical_name,
                source.source_file_id,
                source.name,
                source.relation,
                *source.aliases,
                *dataset_config.aliases,
            }
            for alias in aliases:
                self._aliases[alias.strip().lower()].add(logical_name)

    def resolve(self, name: str) -> DatasetBinding:
        normalized = name.strip().lower()
        if normalized in self._bindings:
            return self._bindings[normalized]
        matches = self._aliases.get(normalized, set())
        if not matches:
            raise DatasetResolutionError(f"Unknown logical dataset or alias: {name!r}")
        if len(matches) > 1:
            raise DatasetResolutionError(f"Ambiguous dataset alias {name!r}: {sorted(matches)}")
        return self._bindings[next(iter(matches))]

    def relationship(self, left_relation: str, right_relation: str) -> tuple[RelationshipContract, str]:
        for contract in self.execution_catalog.relationships:
            if left_relation == contract.parent_relation and right_relation == contract.child_relation:
                if "parent_to_child" not in contract.permitted_directions:
                    break
                return contract, "parent_to_child"
            if left_relation == contract.child_relation and right_relation == contract.parent_relation:
                if "child_to_parent" not in contract.permitted_directions:
                    break
                return contract, "child_to_parent"
        raise JoinPolicyError(
            f"No approved relationship between {left_relation!r} and {right_relation!r}; "
            "cross-child joins such as mortgage-to-projects are prohibited"
        )

    @property
    def bindings(self) -> dict[str, DatasetBinding]:
        return dict(self._bindings)
