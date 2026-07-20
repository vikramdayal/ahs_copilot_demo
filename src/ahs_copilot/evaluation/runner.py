from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

from .models import CandidateResponse, EvaluationRunReport, EvaluationSet
from .scoring import score_case


def load_evaluation_set(path: Path) -> EvaluationSet:
    return EvaluationSet.model_validate_json(path.read_text(encoding="utf-8"))


def load_candidate_responses(path: Path) -> list[CandidateResponse]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, dict) and "responses" in payload:
        payload = payload["responses"]
    if not isinstance(payload, list):
        raise ValueError("Candidate response file must be a list or contain a 'responses' list")
    return [CandidateResponse.model_validate(item) for item in payload]


def score_evaluation_set(evaluation: EvaluationSet, candidates: Iterable[CandidateResponse]) -> EvaluationRunReport:
    candidate_list = list(candidates)
    candidate_map = {candidate.case_id: candidate for candidate in candidate_list}
    duplicate_count = len(candidate_list)
    if duplicate_count != len(candidate_map):
        raise ValueError("Candidate responses must have unique case IDs")

    missing = [case.id for case in evaluation.questions if case.id not in candidate_map]
    extra = sorted(set(candidate_map) - {case.id for case in evaluation.questions})
    if missing:
        raise ValueError(f"Missing candidate responses: {', '.join(missing)}")
    if extra:
        raise ValueError(f"Unknown candidate response IDs: {', '.join(extra)}")

    results = [score_case(case, candidate_map[case.id]) for case in evaluation.questions]
    deterministic_mean = sum(item.deterministic.normalized for item in results) / len(results)
    narrative_mean = sum(item.narrative.normalized for item in results) / len(results)
    pass_count = sum(item.overall_status == "pass" for item in results)
    return EvaluationRunReport(
        evaluation_title=evaluation.title,
        evaluation_version=evaluation.version,
        total_cases=len(results),
        deterministic_mean=deterministic_mean,
        narrative_mean=narrative_mean,
        pass_count=pass_count,
        fail_count=len(results) - pass_count,
        results=results,
    )


def write_report(report: EvaluationRunReport, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(report.model_dump_json(indent=2), encoding="utf-8")
