from __future__ import annotations

import os
import re
import tomllib
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .errors import ConfigurationError

_ENV_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}")


class StrictConfigModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EngineOptions(StrictConfigModel):
    database: str = ":memory:"
    memory_limit: str = "1GB"
    temp_directory: Path = Path(".duckdb_tmp")
    threads: int = Field(default=4, ge=1)
    max_result_rows: int = Field(default=10_000, ge=1)
    preserve_insertion_order: bool = False


class MetadataOptions(StrictConfigModel):
    source_files: Path
    execution_catalog: Path
    semantic_catalog: Path | None = None


class FixtureOptions(StrictConfigModel):
    mode: Literal["auto", "disabled", "required"] = "auto"
    directory: Path = Path("tests/fixtures/synthetic")


class SuppressionOptions(StrictConfigModel):
    """Deterministic descriptive-release rules, not official AHS publication rules."""

    policy_id: str = "configured_unweighted_cell_thresholds_v1"
    minimum_unweighted_denominator: int = Field(default=1, ge=0)
    minimum_unweighted_numerator: int = Field(default=0, ge=0)
    minimum_unweighted_complement: int = Field(default=0, ge=0)
    action: Literal["flag", "null_estimate"] = "null_estimate"


class SurveyOptions(StrictConfigModel):
    default_weight_column: str = "WEIGHT"
    positive_weights_only: bool = True
    decimal_precision: int = Field(default=18, ge=10, le=18)
    decimal_scale: int = Field(default=6, ge=0, le=8)
    output_decimal_places: int = Field(default=6, ge=0, le=12)
    max_comparisons: int = Field(default=10_000, ge=1)
    suppression: SuppressionOptions = Field(default_factory=SuppressionOptions)


class CsvReadOptions(StrictConfigModel):
    header: bool = True
    delimiter: str = ","
    sample_size: int = Field(default=20480, ge=-1)
    all_varchar: bool = False
    ignore_errors: bool = False
    union_by_name: bool = True

    @field_validator("delimiter")
    @classmethod
    def validate_delimiter(cls, value: str) -> str:
        if len(value) != 1:
            raise ValueError("CSV delimiter must be exactly one character")
        return value


class DatasetOptions(StrictConfigModel):
    source_file_id: str
    path: Path
    aliases: list[str] = Field(default_factory=list)
    csv: CsvReadOptions = Field(default_factory=CsvReadOptions)


class AppConfig(StrictConfigModel):
    config_path: Path
    engine: EngineOptions
    metadata: MetadataOptions
    fixture: FixtureOptions
    survey: SurveyOptions = Field(default_factory=SurveyOptions)
    datasets: dict[str, DatasetOptions]


def _expand_env(value: str) -> str:
    def replace(match: re.Match[str]) -> str:
        name, default = match.group(1), match.group(2)
        actual = os.getenv(name)
        if actual is not None:
            return actual
        if default is not None:
            return default
        raise ConfigurationError(f"Environment variable {name} is required")

    return _ENV_PATTERN.sub(replace, value)


def _expand_tree(value: Any) -> Any:
    if isinstance(value, str):
        return _expand_env(value)
    if isinstance(value, list):
        return [_expand_tree(x) for x in value]
    if isinstance(value, dict):
        return {k: _expand_tree(v) for k, v in value.items()}
    return value


def _resolve_path(base: Path, value: Path) -> Path:
    return value if value.is_absolute() else (base / value).resolve()


def load_config(path: str | Path) -> AppConfig:
    config_path = Path(path).expanduser().resolve()
    if not config_path.exists():
        raise ConfigurationError(f"Configuration file not found: {config_path}")
    try:
        payload = _expand_tree(tomllib.loads(config_path.read_text(encoding="utf-8")))
    except (tomllib.TOMLDecodeError, OSError) as exc:
        raise ConfigurationError(f"Unable to read configuration: {exc}") from exc
    payload["config_path"] = config_path
    try:
        config = AppConfig.model_validate(payload)
    except Exception as exc:
        raise ConfigurationError(f"Invalid configuration: {exc}") from exc

    base = config_path.parent
    config.engine.temp_directory = _resolve_path(base, config.engine.temp_directory)
    config.metadata.source_files = _resolve_path(base, config.metadata.source_files)
    config.metadata.execution_catalog = _resolve_path(base, config.metadata.execution_catalog)
    if config.metadata.semantic_catalog is not None:
        config.metadata.semantic_catalog = _resolve_path(base, config.metadata.semantic_catalog)
    config.fixture.directory = _resolve_path(base, config.fixture.directory)
    for dataset in config.datasets.values():
        dataset.path = _resolve_path(base, dataset.path)
    return config
