from __future__ import annotations

from pathlib import Path

import pytest

from ahs_copilot.query_engine import AHSQueryEngine


@pytest.fixture()
def config_path(tmp_path: Path) -> Path:
    repo_root = Path(__file__).resolve().parents[1]
    path = tmp_path / "engine.toml"
    path.write_text(
        f"""
[engine]
database = ":memory:"
memory_limit = "256MB"
temp_directory = "{(tmp_path / 'duckdb_tmp').as_posix()}"
threads = 2
max_result_rows = 100
preserve_insertion_order = false

[metadata]
source_files = "{(repo_root / 'metadata/source_files.json').as_posix()}"
execution_catalog = "{(repo_root / 'metadata/execution_catalog.json').as_posix()}"
semantic_catalog = "{(repo_root / 'metadata/semantic_catalog.json').as_posix()}"

[fixture]
mode = "required"
directory = "{(tmp_path / 'fixtures').as_posix()}"

[datasets.household]
source_file_id = "source_national_puf_household"
path = "{(tmp_path / 'missing_household.csv').as_posix()}"
aliases = ["hh"]

[datasets.mortgage]
source_file_id = "source_puf_mortgage"
path = "{(tmp_path / 'missing_mortgage.csv').as_posix()}"
aliases = ["mort"]

[datasets.projects]
source_file_id = "source_puf_projects"
path = "{(tmp_path / 'missing_projects.csv').as_posix()}"
aliases = ["project"]
""".strip()
        + "\n",
        encoding="utf-8",
    )
    return path


@pytest.fixture()
def engine(config_path: Path):
    with AHSQueryEngine(config_path) as instance:
        yield instance
