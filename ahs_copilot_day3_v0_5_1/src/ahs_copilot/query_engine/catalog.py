from __future__ import annotations

import json
from pathlib import Path
from ahs_copilot.metadata.models import ExecutionCatalog, SemanticCatalog, SourceFileRecord
from .errors import CatalogError


def _load_json(path: Path):
    if not path.exists():
        raise CatalogError(f"Catalog file does not exist: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise CatalogError(f"Cannot parse catalog {path}: {exc}") from exc


class CatalogBundle:
    def __init__(self, source_files_path: Path, execution_catalog_path: Path, semantic_catalog_path: Path):
        self.source_files = [SourceFileRecord.model_validate(x) for x in _load_json(source_files_path)]
        self.execution = ExecutionCatalog.model_validate(_load_json(execution_catalog_path))
        self.semantic = SemanticCatalog.model_validate(_load_json(semantic_catalog_path))
        self.source_by_id = {x.source_file_id: x for x in self.source_files}
        self.relationship_by_id = {x.relationship_id: x for x in self.execution.relationships}
        self.variable_by_key = {(x.dataset.casefold(), x.name.casefold()): x for x in self.semantic.variables}
        self.universe_by_id = {x.universe_id: x for x in self.semantic.universes}
        self.weight_by_id = {x.weight_id: x for x in self.semantic.weights}
        self.recode_by_id = {x.recode_id: x for x in self.semantic.recodes}

        if len(self.source_by_id) != len(self.source_files):
            raise CatalogError("Duplicate source_file_id values")
        if len(self.relationship_by_id) != len(self.execution.relationships):
            raise CatalogError("Duplicate relationship_id values")
