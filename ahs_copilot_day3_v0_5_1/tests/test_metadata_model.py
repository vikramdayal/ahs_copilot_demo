import json
from pathlib import Path
from ahs_copilot.metadata.models import SourceFileRecord

ROOT = Path(__file__).resolve().parents[1]

def test_projects_contract_does_not_require_projectno():
    records = [SourceFileRecord.model_validate(x) for x in json.loads((ROOT / "metadata/source_files.json").read_text())]
    project = next(x for x in records if x.source_file_id == "source_puf_projects")
    assert project.relationship_keys == ["CONTROL"]
    assert project.row_identity_columns == []
    assert project.declared_primary_key is None
    assert "PROJECTNO" not in project.required_physical_columns

def test_mortgage_still_has_row_identity():
    records = [SourceFileRecord.model_validate(x) for x in json.loads((ROOT / "metadata/source_files.json").read_text())]
    mortgage = next(x for x in records if x.source_file_id == "source_puf_mortgage")
    assert mortgage.relationship_keys == ["CONTROL"]
    assert mortgage.row_identity_columns == ["CONTROL", "MORTLINE"]
