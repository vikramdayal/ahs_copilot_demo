from __future__ import annotations

from ahs_copilot.analysis_plan.models import AnalysisPlanExecutionResult, ValidatedAnalysisPlan
from ahs_copilot.survey_estimation.models import CompiledSurveyEstimate

from .models import ResultCheck, ResultCheckReport


class AnalysisResultChecker:
    """Deterministic post-execution integrity checks; no LLM participation."""

    @staticmethod
    def _check(check_id: str, passed: bool, message: str) -> ResultCheck:
        return ResultCheck(check_id=check_id, passed=passed, message=message)

    def check(
        self,
        validated: ValidatedAnalysisPlan,
        compiled: CompiledSurveyEstimate,
        execution: AnalysisPlanExecutionResult,
    ) -> ResultCheckReport:
        result = execution.result
        checks = [
            self._check(
                "PLAN_FINGERPRINT_MATCH",
                execution.plan_fingerprint == validated.plan_fingerprint,
                "Execution plan fingerprint matches the validated plan.",
            ),
            self._check(
                "REQUEST_FINGERPRINT_MATCH",
                result.metadata.request_fingerprint == compiled.request_fingerprint,
                "Execution request fingerprint matches deterministic compilation.",
            ),
            self._check(
                "PARAMETERIZED_SQL_MATCH",
                result.parameterized_sql == compiled.sql,
                "Executed parameterized SQL matches deterministic compilation.",
            ),
            self._check(
                "DISPLAY_SQL_MATCH",
                result.generated_sql == compiled.display_sql,
                "Reported SQL display matches deterministic compilation.",
            ),
            self._check(
                "BOUND_PARAMETERS_MATCH",
                result.parameters == compiled.parameters,
                "Executed bound parameters match deterministic compilation.",
            ),
            self._check(
                "JOIN_CONTRACTS_MATCH",
                result.metadata.join_contract_ids == compiled.join_contract_ids,
                "Execution used only the join contracts selected by the compiler.",
            ),
            self._check(
                "DATASETS_MATCH",
                [item.logical_name for item in result.metadata.datasets]
                == compiled.datasets_used,
                "Execution datasets match the deterministic compiler output.",
            ),
            self._check(
                "ESTIMATES_PRESENT",
                bool(result.estimates),
                "At least one descriptive estimate was returned.",
            ),
            self._check(
                "NO_UNSUPPORTED_INFERENCE",
                (
                    result.metadata.variance.standard_errors_valid is False
                    and all(item.standard_error is None for item in result.estimates)
                    and all(item.confidence_interval is None for item in result.estimates)
                    and all(item.p_value is None for item in result.comparisons)
                ),
                "No unsupported standard errors, confidence intervals, or p-values were emitted.",
            ),
            self._check(
                "OUTPUT_ALIAS_MATCH",
                {item.estimate_alias for item in result.estimates}
                == {validated.plan.measure.alias},
                "Returned estimate aliases match the validated plan.",
            ),
        ]
        return ResultCheckReport(passed=all(item.passed for item in checks), checks=checks)
