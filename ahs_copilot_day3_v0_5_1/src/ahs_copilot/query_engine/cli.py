from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from ahs_copilot.survey_estimation import SurveyEstimateRequest, SurveyEstimator
from .contracts import QuerySpec
from .engine import AHSQueryEngine


def _write(payload: Any, output: str | None) -> None:
    text = json.dumps(payload, indent=2, ensure_ascii=False, default=str) + "\n"
    if output:
        path = Path(output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    else:
        print(text, end="")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ahs-query")
    sub = parser.add_subparsers(dest="command", required=True)

    inspect = sub.add_parser("inspect", help="Inspect configured physical CSV schemas")
    inspect.add_argument("--config", required=True)
    inspect.add_argument("--output")

    for command in ["compile", "run", "survey-compile", "survey-run"]:
        p = sub.add_parser(command)
        p.add_argument("request")
        p.add_argument("--config", required=True)
        p.add_argument("--output")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    with AHSQueryEngine(args.config) as engine:
        if args.command == "inspect":
            payload = engine.inspect_schemas().model_dump(mode="json")
        elif args.command in {"compile", "run"}:
            request = QuerySpec.model_validate_json(Path(args.request).read_text(encoding="utf-8"))
            payload = (
                engine.compile(request).model_dump(mode="json")
                if args.command == "compile"
                else engine.execute(request).model_dump(mode="json")
            )
        else:
            request = SurveyEstimateRequest.model_validate_json(Path(args.request).read_text(encoding="utf-8"))
            estimator = SurveyEstimator(engine)
            payload = (
                estimator.compile(request).model_dump(mode="json")
                if args.command == "survey-compile"
                else estimator.execute(request).model_dump(mode="json")
            )
        _write(payload, getattr(args, "output", None))


if __name__ == "__main__":
    main()
