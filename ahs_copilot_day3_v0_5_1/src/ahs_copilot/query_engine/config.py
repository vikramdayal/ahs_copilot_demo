from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os
import tomllib

from .errors import ConfigurationError


@dataclass(frozen=True)
class DatasetConfig:
    logical_dataset: str
    source_file_id: str
    env: str | None
    path: Path
    fixture_file: str


@dataclass(frozen=True)
class EngineConfig:
    config_path: Path
    memory_limit: str
    temp_directory: Path
    threads: int
    preserve_insertion_order: bool
    max_result_rows: int
    csv_sample_size: int
    fixture_mode: str
    fixture_directory: Path
    source_files_path: Path
    execution_catalog_path: Path
    semantic_catalog_path: Path
    datasets: dict[str, DatasetConfig]
    decimal_scale: int
    minimum_unweighted_n: int
    null_suppressed_estimates: bool


def _resolve(base: Path, value: str) -> Path:
    expanded = Path(os.path.expandvars(os.path.expanduser(value)))
    return expanded if expanded.is_absolute() else (base / expanded).resolve()


def load_config(path: str | Path) -> EngineConfig:
    config_path = Path(path).expanduser().resolve()
    if not config_path.exists():
        raise ConfigurationError(f"Config file does not exist: {config_path}")
    data = tomllib.loads(config_path.read_text(encoding="utf-8"))
    base = config_path.parent
    engine = data.get("engine", {})
    fixture = data.get("fixture", {})
    metadata = data.get("metadata", {})
    survey = data.get("survey", {})
    mode = fixture.get("mode", "auto")
    if mode not in {"auto", "required", "disabled"}:
        raise ConfigurationError("fixture.mode must be auto, required, or disabled")

    datasets: dict[str, DatasetConfig] = {}
    for logical, raw in data.get("datasets", {}).items():
        env_name = raw.get("env")
        env_value = os.getenv(env_name) if env_name else None
        selected = env_value or raw.get("path")
        if not selected:
            raise ConfigurationError(f"Dataset '{logical}' has no configured path")
        datasets[logical] = DatasetConfig(
            logical_dataset=logical,
            source_file_id=raw["source_file_id"],
            env=env_name,
            path=_resolve(base, selected),
            fixture_file=raw.get("fixture_file", f"{logical}.csv"),
        )
    if not datasets:
        raise ConfigurationError("No datasets were configured")

    return EngineConfig(
        config_path=config_path,
        memory_limit=str(engine.get("memory_limit", "512MB")),
        temp_directory=_resolve(base, engine.get("temp_directory", "../.duckdb_tmp")),
        threads=int(engine.get("threads", 4)),
        preserve_insertion_order=bool(engine.get("preserve_insertion_order", False)),
        max_result_rows=int(engine.get("max_result_rows", 10000)),
        csv_sample_size=int(engine.get("csv_sample_size", 20480)),
        fixture_mode=mode,
        fixture_directory=_resolve(base, fixture.get("directory", "../tests/fixtures/synthetic")),
        source_files_path=_resolve(base, metadata["source_files"]),
        execution_catalog_path=_resolve(base, metadata["execution_catalog"]),
        semantic_catalog_path=_resolve(base, metadata["semantic_catalog"]),
        datasets=datasets,
        decimal_scale=int(survey.get("decimal_scale", 6)),
        minimum_unweighted_n=int(survey.get("minimum_unweighted_n", 1)),
        null_suppressed_estimates=bool(survey.get("null_suppressed_estimates", True)),
    )
