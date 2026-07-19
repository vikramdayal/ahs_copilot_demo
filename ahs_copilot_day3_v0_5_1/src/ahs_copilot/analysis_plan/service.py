from __future__ import annotations

from ahs_copilot.query_engine.engine import AHSQueryEngine
from ahs_copilot.query_engine.errors import QueryValidationError
from ahs_copilot.survey_estimation import SurveyEstimateRequest, SurveyEstimator
from .contracts import AnalysisPlan, ValidatedAnalysisPlan, ValidationIssue


class AnalysisPlanValidationError(QueryValidationError):
    def __init__(self, issues: list[ValidationIssue]):
        self.issues = issues
        super().__init__("AnalysisPlan validation failed: " + "; ".join(x.message for x in issues))


class AnalysisPlanService:
    REQUIRED_CHECKS = [
        "schema_columns_exist",
        "puf_access_only",
        "universe_compatible",
        "weight_compatible",
        "required_variable_closure",
        "empty_denominator_flagged",
        "variance_boundary_reported",
    ]

    def __init__(self, engine: AHSQueryEngine):
        self.engine = engine
        self.estimator = SurveyEstimator(engine)

    def validate(self, plan: AnalysisPlan) -> ValidatedAnalysisPlan:
        issues: list[ValidationIssue] = []
        try:
            self.engine.dataset(plan.dataset)
        except Exception as exc:
            issues.append(ValidationIssue(code="UNKNOWN_DATASET", path="dataset", message=str(exc)))

        universe = self.engine.catalog.universe_by_id.get(plan.universe)
        if not universe:
            issues.append(ValidationIssue(code="UNKNOWN_UNIVERSE", path="universe", message=f"Unknown universe: {plan.universe}"))
        elif universe.dataset != plan.dataset:
            issues.append(ValidationIssue(code="UNIVERSE_DATASET_MISMATCH", path="universe", message="Universe does not belong to the selected dataset"))

        weight = self.engine.catalog.weight_by_id.get(plan.weight)
        if not weight:
            issues.append(ValidationIssue(code="UNKNOWN_WEIGHT", path="weight", message=f"Unknown weight: {plan.weight}"))
        elif weight.dataset != plan.dataset or weight.availability != "PUF":
            issues.append(ValidationIssue(code="WEIGHT_NOT_PUF_COMPATIBLE", path="weight", message="Weight is not approved for this PUF dataset"))

        closure: set[str] = set()
        if universe:
            closure.update(x.variable.upper() for x in universe.conditions)
        for condition in [*plan.numerator, *plan.denominator, *plan.filters]:
            closure.add(condition.variable.upper())
        closure.update(x.upper() for x in plan.grouping_dimensions)
        if plan.value_variable:
            closure.add(plan.value_variable.upper())
        if weight and weight.variable:
            closure.add(weight.variable.upper())

        for recode_id in plan.derived_recodes:
            recode = self.engine.catalog.recode_by_id.get(recode_id)
            if not recode:
                issues.append(ValidationIssue(code="UNKNOWN_RECODE", path="derived_recodes", message=f"Unknown recode: {recode_id}"))
                continue
            if recode.availability != "PUF":
                issues.append(ValidationIssue(code="IUF_RECODE_REJECTED", path="derived_recodes", message=f"Recode is not PUF-accessible: {recode_id}"))
            closure.update(x.upper() for x in recode.required_variables)

        for variable in sorted(closure):
            record = self.engine.catalog.variable_by_key.get((plan.dataset.casefold(), variable.casefold()))
            if not record:
                issues.append(ValidationIssue(code="UNKNOWN_VARIABLE", path="required_variables", message=f"Unknown approved variable: {variable}"))
                continue
            if record.availability != "PUF":
                issues.append(ValidationIssue(code="IUF_VARIABLE_REJECTED", path="required_variables", message=f"Variable is not PUF-accessible: {variable}"))
            try:
                self.engine.dataset(plan.dataset).actual_column(variable)
            except Exception as exc:
                issues.append(ValidationIssue(code="MISSING_PHYSICAL_COLUMN", path="required_variables", message=str(exc)))

        declared = {x.upper() for x in plan.required_variables}
        missing = sorted(closure - declared)
        if missing:
            issues.append(ValidationIssue(
                code="REQUIRED_VARIABLE_CLOSURE_INCOMPLETE",
                path="required_variables",
                message=f"required_variables is missing: {missing}",
            ))

        if plan.measure == "percentage" and not plan.numerator:
            issues.append(ValidationIssue(code="MISSING_NUMERATOR", path="numerator", message="Percentage plans require a numerator"))
        if plan.measure == "mean" and not plan.value_variable:
            issues.append(ValidationIssue(code="MISSING_VALUE_VARIABLE", path="value_variable", message="Mean plans require value_variable"))

        if issues:
            raise AnalysisPlanValidationError(issues)

        request = SurveyEstimateRequest(
            dataset=plan.dataset,
            measure=plan.measure,
            universe_id=plan.universe,
            numerator_conditions=plan.numerator,
            denominator_conditions=[*plan.denominator, *plan.filters],
            grouping_dimensions=plan.grouping_dimensions,
            weight_id=plan.weight,
            value_variable=plan.value_variable,
        )
        checks = list(dict.fromkeys([*self.REQUIRED_CHECKS, *plan.validation_checks]))
        return ValidatedAnalysisPlan(
            plan=plan,
            normalized_request=request,
            required_variable_closure=sorted(closure),
            validation_checks=checks,
        )

    def compile(self, plan: AnalysisPlan):
        validated = self.validate(plan)
        return {
            "validated_plan": validated.model_dump(mode="json"),
            "compiled": self.estimator.compile(validated.normalized_request).model_dump(mode="json"),
        }

    def execute(self, plan: AnalysisPlan):
        validated = self.validate(plan)
        result = self.estimator.execute(validated.normalized_request)
        return {
            "validated_plan": validated.model_dump(mode="json"),
            "result": result.model_dump(mode="json"),
        }
