from __future__ import annotations

import argparse
import json
from pathlib import Path

from ahs_copilot.query_engine import AHSQueryEngine
from .contracts import AnalysisPlan
from .service import AnalysisPlanService


def main() -> None:
    parser = argparse.ArgumentParser(prog="ahs-plan")
    parser.add_argument("--config", required=True)
    parser.add_argument("--plan", required=True)
    parser.add_argument("--action", choices=["validate", "compile", "execute"], required=True)
    parser.add_argument("--output")
    args = parser.parse_args()

    plan = AnalysisPlan.model_validate_json(Path(args.plan).read_text(encoding="utf-8"))
    with AHSQueryEngine(args.config) as engine:
        service = AnalysisPlanService(engine)
        if args.action == "validate":
            payload = service.validate(plan).model_dump(mode="json")
        elif args.action == "compile":
            payload = service.compile(plan)
        else:
            payload = service.execute(plan)
    text = json.dumps(payload, indent=2, ensure_ascii=False, default=str) + "\n"
    if args.output:
        path = Path(args.output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    else:
        print(text, end="")


if __name__ == "__main__":
    main()
