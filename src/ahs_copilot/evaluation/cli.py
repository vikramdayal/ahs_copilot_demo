from __future__ import annotations

import argparse
from pathlib import Path

from .runner import load_candidate_responses, load_evaluation_set, score_evaluation_set, write_report


def main() -> None:
    parser = argparse.ArgumentParser(description="Score AHS Research Copilot evaluation responses")
    parser.add_argument("--evaluation-set", required=True, type=Path)
    parser.add_argument("--responses", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    evaluation = load_evaluation_set(args.evaluation_set)
    candidates = load_candidate_responses(args.responses)
    report = score_evaluation_set(evaluation, candidates)
    write_report(report, args.output)
    print(report.model_dump_json(indent=2))


if __name__ == "__main__":
    main()
