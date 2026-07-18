from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from ahs_copilot.query_engine.errors import ConfigurationError
from ahs_copilot.query_engine.models import QualifiedColumn, TypedFilter


class StrictFrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class SemanticVariable(StrictFrozenModel):
    dataset: str
    name: str
    data_type: str
    access_level: Literal["PUF", "IUF"]
    role: Literal["identifier", "universe", "dimension", "measure", "weight", "other"]
    missing_codes: list[Any] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class SemanticUniverse(StrictFrozenModel):
    universe_id: str
    dataset: str
    label: str
    filters: list[TypedFilter] = Field(default_factory=list)
    required_variables: list[QualifiedColumn] = Field(default_factory=list)


class SemanticWeight(StrictFrozenModel):
    weight_id: str
    dataset: str
    column: str
    access_level: Literal["PUF", "IUF"]
    approved_universes: list[str]
    description: str


class SemanticRecode(StrictFrozenModel):
    recode_id: str
    source: QualifiedColumn
    access_level: Literal["PUF", "IUF"]
    description: str
    deterministic_definition: str
    required_variables: list[QualifiedColumn]


class SemanticCatalogDocument(StrictFrozenModel):
    catalog_version: str
    access_mode: Literal["PUF", "IUF"]
    variables: list[SemanticVariable]
    universes: list[SemanticUniverse]
    weights: list[SemanticWeight]
    recodes: list[SemanticRecode]


class SemanticCatalog:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        try:
            self.document = SemanticCatalogDocument.model_validate_json(
                self.path.read_text(encoding="utf-8")
            )
        except Exception as exc:
            raise ConfigurationError(f"Unable to load semantic catalog {self.path}: {exc}") from exc
        self._variables = {
            (item.dataset.lower(), item.name.upper()): item for item in self.document.variables
        }
        self._universes = {item.universe_id.lower(): item for item in self.document.universes}
        self._weights = {
            (item.dataset.lower(), item.column.upper()): item for item in self.document.weights
        }
        self._recodes = {item.recode_id.lower(): item for item in self.document.recodes}

    def variable(self, dataset: str, name: str) -> SemanticVariable | None:
        return self._variables.get((dataset.lower(), name.upper()))

    def universe(self, universe_id: str) -> SemanticUniverse | None:
        return self._universes.get(universe_id.lower())

    def weight(self, dataset: str, column: str) -> SemanticWeight | None:
        return self._weights.get((dataset.lower(), column.upper()))

    def recode(self, recode_id: str) -> SemanticRecode | None:
        return self._recodes.get(recode_id.lower())
