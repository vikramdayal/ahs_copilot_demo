from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .engine import AHSQueryEngine
from .fixture import create_synthetic_fixture
from .models import QuerySpec
from ahs_copilot.survey_estimation import SurveyEstimateRequest, SurveyEstimator


def _json_default(value: Any) -> Any:
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _write_or_print(payload: Any, output: str | None) -> None:
    text = json.dumps(payload, indent=2, ensure_ascii=False, default=_json_default) + "\n"
    if output:
        path = Path(output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    else:
        print(text, end="")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ahs-query")
    subparsers = parser.add_subparsers(dest="command", required=True)

    inspect_parser = subparsers.add_parser("inspect", help="Inspect configured CSV schemas")
    inspect_parser.add_argument("--config", required=True)
    inspect_parser.add_argument("--output")

    compile_parser = subparsers.add_parser("compile", help="Validate and compile a typed query JSON")
    compile_parser.add_argument("request")
    compile_parser.add_argument("--config", required=True)
    compile_parser.add_argument("--output")

    run_parser = subparsers.add_parser("run", help="Execute a typed query JSON")
    run_parser.add_argument("request")
    run_parser.add_argument("--config", required=True)
    run_parser.add_argument("--output")

    survey_compile_parser = subparsers.add_parser(
        "survey-compile", help="Validate and compile a descriptive survey-estimate JSON"
    )
    survey_compile_parser.add_argument("request")
    survey_compile_parser.add_argument("--config", required=True)
    survey_compile_parser.add_argument("--output")

    survey_run_parser = subparsers.add_parser(
        "survey-run", help="Execute deterministic descriptive weighted estimates"
    )
    survey_run_parser.add_argument("request")
    survey_run_parser.add_argument("--config", required=True)
    survey_run_parser.add_argument("--output")

    fixture_parser = subparsers.add_parser("fixture", help="Create deterministic synthetic CSVs")
    fixture_parser.add_argument("--output-dir", required=True)
    fixture_parser.add_argument("--overwrite", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "fixture":
        paths = create_synthetic_fixture(args.output_dir, overwrite=args.overwrite)
        _write_or_print({k: str(v) for k, v in paths.items()}, None)
        return 0

    with AHSQueryEngine(args.config) as engine:
        if args.command == "inspect":
            payload = {k: v.model_dump(mode="json") for k, v in engine.inspect_schemas().items()}
        elif args.command in {"survey-compile", "survey-run"}:
            request = SurveyEstimateRequest.model_validate_json(
                Path(args.request).read_text(encoding="utf-8")
            )
            estimator = SurveyEstimator(engine)
            if args.command == "survey-compile":
                payload = estimator.compile(request).model_dump(mode="json")
            else:
                payload = estimator.execute(request).model_dump(mode="json")
        else:
            request = QuerySpec.model_validate_json(Path(args.request).read_text(encoding="utf-8"))
            if args.command == "compile":
                payload = engine.compile(request).model_dump(mode="json")
            else:
                payload = engine.execute(request).model_dump(mode="json")
        _write_or_print(payload, args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
