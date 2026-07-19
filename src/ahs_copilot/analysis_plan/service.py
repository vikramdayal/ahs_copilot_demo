from __future__ import annotations

from typing import Any

from ahs_copilot.query_engine.engine import AHSQueryEngine
from ahs_copilot.survey_estimation import CompiledSurveyEstimate, SurveyEstimator

from .models import AnalysisPlan, AnalysisPlanExecutionResult, ValidatedAnalysisPlan
from .validator import AnalysisPlanValidator


class AnalysisPlanService:
    """Validation-first facade. Invalid plans never reach SQL compilation."""

    def __init__(self, engine: AHSQueryEngine, semantic_catalog: str | None = None) -> None:
        self.engine = engine
        self.validator = AnalysisPlanValidator(engine, semantic_catalog)
        self.estimator = SurveyEstimator(engine)

    def validate(self, plan: AnalysisPlan | dict[str, Any]) -> ValidatedAnalysisPlan:
        return self.validator.validate(plan)

    def compile_validated(self, validated: ValidatedAnalysisPlan) -> CompiledSurveyEstimate:
        """Compile a previously validated plan through the deterministic estimator."""
        return self.estimator.compile(validated.survey_request)

    def execute_validated(
        self, validated: ValidatedAnalysisPlan
    ) -> AnalysisPlanExecutionResult:
        """Execute a previously validated plan and preserve its audit fingerprint."""
        result = self.estimator.execute(validated.survey_request)
        return AnalysisPlanExecutionResult(
            plan=validated.plan,
            plan_fingerprint=validated.plan_fingerprint,
            validation_messages=validated.validation_messages,
            output_format=validated.plan.output_format,
            result=result,
        )

    def compile(self, plan: AnalysisPlan | dict[str, Any]) -> CompiledSurveyEstimate:
        return self.compile_validated(self.validate(plan))

    def execute(self, plan: AnalysisPlan | dict[str, Any]) -> AnalysisPlanExecutionResult:
        return self.execute_validated(self.validate(plan))
