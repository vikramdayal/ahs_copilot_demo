from pathlib import Path
import json
import pytest
from ahs_copilot.query_engine import AHSQueryEngine
from ahs_copilot.query_engine.errors import SchemaValidationError

ROOT = Path(__file__).resolve().parents[1]

def test_project_fixture_intentionally_has_no_projectno():
    header = (ROOT / "tests/fixtures/synthetic/projects.csv").read_text().splitlines()[0].split(",")
    assert "CONTROL" in header
    assert "PROJECTNO" not in header

def test_inspection_accepts_projects_without_projectno(engine):
    inspection = engine.inspect_schemas()
    project = next(x for x in inspection.datasets if x.logical_dataset == "projects")
    assert project.relationship_keys == ["CONTROL"]
    assert project.row_identity_columns == []
    assert "PROJECTNO" not in [c.name for c in project.columns]

def test_missing_project_control_fails(tmp_path):
    fixture = tmp_path / "fixture"
    fixture.mkdir()
    for name in ["household.csv", "mortgage.csv"]:
        (fixture / name).write_text((ROOT / "tests/fixtures/synthetic" / name).read_text())
    (fixture / "projects.csv").write_text("JOBTYPE,JOBCOST\n32,100\n")
    cfg = (ROOT / "config/ahs_engine.example.toml").read_text()
    cfg = cfg.replace('../tests/fixtures/synthetic', str(fixture)).replace('mode = "auto"', 'mode = "required"')
    cfg = cfg.replace('../metadata/source_files.json', str(ROOT / 'metadata/source_files.json'))
    cfg = cfg.replace('../metadata/execution_catalog.json', str(ROOT / 'metadata/execution_catalog.json'))
    cfg = cfg.replace('../metadata/semantic_catalog.json', str(ROOT / 'metadata/semantic_catalog.json'))
    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text(cfg)
    with pytest.raises(SchemaValidationError, match="relationship key columns.*CONTROL"):
        AHSQueryEngine(cfg_path)
