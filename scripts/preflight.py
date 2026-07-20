#!/usr/bin/env python3
"""Fail-closed container startup validation."""

from __future__ import annotations

import argparse
import json
import sys
import tomllib
from pathlib import Path

from ahs_copilot.model_providers import (
    ModelProviderSettings,
    ProviderConfigurationError,
)
from ahs_copilot.query_engine import AHSQueryEngine


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--data-mode", choices=("sample", "production"), required=True)
    return parser.parse_args()


def validate_fixture_contract(config_path: Path, data_mode: str) -> str:
    with config_path.open("rb") as handle:
        document = tomllib.load(handle)
    fixture_mode = str(document.get("fixture", {}).get("mode", "")).strip().lower()
    expected = "required" if data_mode == "sample" else "disabled"
    if fixture_mode != expected:
        raise RuntimeError(
            f"{data_mode} startup requires fixture.mode={expected!r}; "
            f"configuration contains {fixture_mode!r}."
        )
    return fixture_mode


def main() -> int:
    args = parse_args()
    config_path = Path(args.config).resolve()
    if not config_path.is_file():
        raise FileNotFoundError(f"Configuration file does not exist: {config_path}")

    fixture_mode = validate_fixture_contract(config_path, args.data_mode)
    provider = ModelProviderSettings.from_environment()

    engine = AHSQueryEngine(str(config_path))
    try:
        inspected = engine.inspect_schemas()
        schemas = list(inspected.values()) if isinstance(inspected, dict) else list(inspected)
        if not schemas:
            raise RuntimeError("No governed datasets were resolved during startup inspection.")
        synthetic_count = sum(
            bool(getattr(schema, "synthetic_fixture", False)) for schema in schemas
        )
        if args.data_mode == "production" and synthetic_count:
            raise RuntimeError("Production mode resolved synthetic fixture data; startup refused.")
    finally:
        close = getattr(engine, "close", None)
        if callable(close):
            close()

    summary = {
        "status": "ok",
        "data_mode": args.data_mode,
        "fixture_mode": fixture_mode,
        "datasets": len(schemas),
        "synthetic_datasets": synthetic_count,
        "model_provider": provider.redacted_summary(),
    }
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ProviderConfigurationError, OSError, RuntimeError, ValueError) as exc:
        print(f"AHS startup preflight failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
