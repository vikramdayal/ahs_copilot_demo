from __future__ import annotations

from pathlib import Path

from ahs_copilot.query_engine.config import load_config


def test_environment_path_expansion(monkeypatch, tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    household = tmp_path / "real-household.csv"
    monkeypatch.setenv("TEST_HOUSEHOLD", household.as_posix())
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        f"""
[engine]
temp_directory = "tmp"

[metadata]
source_files = "{(repo_root / 'metadata/source_files.json').as_posix()}"
execution_catalog = "{(repo_root / 'metadata/execution_catalog.json').as_posix()}"

[fixture]
mode = "auto"
directory = "fixture"

[datasets.household]
source_file_id = "source_national_puf_household"
path = "${{TEST_HOUSEHOLD}}"
""".strip()
        + "\n",
        encoding="utf-8",
    )
    config = load_config(config_path)
    assert config.datasets["household"].path == household.resolve()
    assert config.engine.temp_directory == (tmp_path / "tmp").resolve()
