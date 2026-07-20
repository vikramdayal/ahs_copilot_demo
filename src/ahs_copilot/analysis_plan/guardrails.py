from __future__ import annotations

import json
import re
from typing import Any

from ahs_copilot.query_engine.models import TypedFilter

from .errors import AnalysisPlanValidationError
from .models import AnalysisPlan, PlanValidationIssue

_EXPLICIT_UNWEIGHTED = re.compile(
    r"\b(unweighted|unit[- ]weighted|raw\s+sample\s+count|sample\s+count|without\s+(survey\s+)?weights?)\b",
    re.IGNORECASE,
)
_STATE_LEVEL = re.compile(
    r"\b(state[- ]level|by\s+state|all\s+50\s+states|state\s+estimates?|rank\s+(?:the\s+)?states)\b",
    re.IGNORECASE,
)


def _canonical_value(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _filter_signature(item: TypedFilter) -> tuple[str, str, str, str]:
    return (
        item.column.dataset.lower(),
        item.column.column.upper(),
        item.operator,
        _canonical_value(item.value),
    )


class AnalysisPlanGuardrails:
    """Cross-field policy checks that supplement schema and semantic validation."""

    @staticmethod
    def _issue(code: str, path: str, message: str) -> PlanValidationIssue:
        return PlanValidationIssue(code=code, path=path, message=message)

    def validate(
        self,
        plan: AnalysisPlan,
        *,
        source_question: str | None = None,
        access_mode: str = "PUF",
    ) -> None:
        question = source_question or plan.user_question
        issues: list[PlanValidationIssue] = []

        if plan.weight.mode == "unweighted" and not _EXPLICIT_UNWEIGHTED.search(question):
            issues.append(
                self._issue(
                    "UNWEIGHTED_NOT_EXPLICITLY_REQUESTED",
                    "weight.mode",
                    (
                        "Unweighted analysis is allowed only when the original user request explicitly "
                        "asks for an unweighted/sample estimate. Default research estimates must use an "
                        "approved survey weight."
                    ),
                )
            )

        if plan.measure.statistic == "percentage" and plan.denominator.filters:
            numerator_filters = {_filter_signature(item) for item in plan.numerator.filters}
            for index, item in enumerate(plan.denominator.filters):
                if _filter_signature(item) not in numerator_filters:
                    issues.append(
                        self._issue(
                            "PERCENTAGE_DENOMINATOR_NOT_INCLUDED_IN_NUMERATOR",
                            f"denominator.filters[{index}]",
                            (
                                "Every explicit percentage-denominator filter must also be present in "
                                "the numerator so the numerator is deterministically a subset of the denominator."
                            ),
                        )
                    )

        if access_mode.upper() == "PUF" and _STATE_LEVEL.search(question):
            issues.append(
                self._issue(
                    "STATE_LEVEL_PUF_UNSUPPORTED",
                    "user_question",
                    "State-level claims are not certified in the National PUF execution path.",
                )
            )

        if issues:
            raise AnalysisPlanValidationError(issues)
