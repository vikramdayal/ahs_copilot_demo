from __future__ import annotations

import argparse
import json
from pathlib import Path

from ahs_copilot.query_engine import AHSQueryEngine

from .models import AnalysisPlan
from .service import AnalysisPlanService


def _json_default(value):
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Validate, compile, or execute a governed AHS AnalysisPlan"
    )
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--plan", required=True, type=Path)
    parser.add_argument(
        "--action", choices=["validate", "compile", "execute"], default="execute"
    )
    args = parser.parse_args()

    payload = json.loads(args.plan.read_text(encoding="utf-8"))
    plan = AnalysisPlan.model_validate(payload)
    with AHSQueryEngine(args.config) as engine:
        service = AnalysisPlanService(engine)
        if args.action == "validate":
            result = service.validate(plan).model_dump(mode="json")
        elif args.action == "compile":
            result = service.compile(plan).model_dump(mode="json")
        else:
            result = service.execute(plan).model_dump(mode="json")
    print(json.dumps(result, indent=2, default=_json_default))


if __name__ == "__main__":
    main()
