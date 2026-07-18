from __future__ import annotations

from ahs_copilot.query_engine.errors import QueryValidationError

from .models import PlanValidationIssue


class AnalysisPlanValidationError(QueryValidationError):
    def __init__(self, issues: list[PlanValidationIssue]) -> None:
        self.issues = issues
        summary = "; ".join(f"{item.code} at {item.path}: {item.message}" for item in issues)
        super().__init__(summary)
