from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from ahs_copilot.analysis_plan.models import AnalysisPlanExecutionResult, ValidatedAnalysisPlan
from ahs_copilot.survey_estimation.models import CompiledSurveyEstimate, SurveyEstimate

from .models import (
    MutuallyExclusiveGroupSet,
    ReferenceEstimate,
    ResultCriticCheck,
    ResultCriticConfig,
    ResultCriticReport,
)


class AnalysisResultCritic:
    """Deterministic, non-mutating review of executed estimates against the plan.

    The critic never returns revised estimates. Its only possible decisions are to
    approve the result, reject it, or request that the already validated plan be
    executed again by the deterministic service.
    """

    _STATISTIC_MAP = {
        "count": "weighted_count",
        "percentage": "weighted_percentage",
        "mean": "weighted_mean",
    }

    @staticmethod
    def _check(
        check_id: str,
        passed: bool | None,
        message: str,
        *,
        retryable: bool = False,
        details: dict[str, Any] | None = None,
    ) -> ResultCriticCheck:
        status = "not_applicable" if passed is None else "passed" if passed else "failed"
        return ResultCriticCheck(
            check_id=check_id,
            status=status,
            message=message,
            retryable=retryable if passed is False else False,
            details=details or {},
        )

    @staticmethod
    def _group_key(group: dict[str, Any]) -> tuple[tuple[str, str], ...]:
        return tuple(sorted((str(key), repr(value)) for key, value in group.items()))

    @staticmethod
    def _matches_selector(group: dict[str, Any], selector: dict[str, Any]) -> bool:
        return all(group.get(key) == value for key, value in selector.items())

    @staticmethod
    def _decimal_close(left: Decimal, right: Decimal, tolerance: Decimal) -> bool:
        return abs(left - right) <= tolerance

    def _denominator_checks(
        self,
        validated: ValidatedAnalysisPlan,
        estimates: list[SurveyEstimate],
        tolerance: Decimal,
    ) -> list[ResultCriticCheck]:
        checks: list[ResultCriticCheck] = []
        expected_statistic = self._STATISTIC_MAP[validated.plan.measure.statistic]
        expected_weighting = validated.plan.weight.mode

        for index, estimate in enumerate(estimates):
            key = {
                "estimate_index": index,
                "estimate_alias": estimate.estimate_alias,
                "group": estimate.group,
            }
            checks.append(
                self._check(
                    f"STATISTIC_MATCH[{index}]",
                    estimate.statistic == expected_statistic,
                    "Result statistic matches the validated AnalysisPlan measure.",
                    retryable=True,
                    details={**key, "expected": expected_statistic, "observed": estimate.statistic},
                )
            )
            checks.append(
                self._check(
                    f"WEIGHTING_MODE_MATCH[{index}]",
                    estimate.weighting_mode == expected_weighting,
                    "Result weighting mode matches the validated AnalysisPlan.",
                    retryable=True,
                    details={
                        **key,
                        "expected": expected_weighting,
                        "observed": estimate.weighting_mode,
                    },
                )
            )

            denominators_valid = (
                estimate.weighted_denominator >= 0
                and estimate.unweighted_denominator >= 0
                and estimate.unweighted_numerator >= 0
            )
            checks.append(
                self._check(
                    f"DENOMINATORS_NONNEGATIVE[{index}]",
                    denominators_valid,
                    "Weighted and unweighted denominators are nonnegative.",
                    retryable=True,
                    details={
                        **key,
                        "weighted_denominator": str(estimate.weighted_denominator),
                        "unweighted_denominator": estimate.unweighted_denominator,
                        "unweighted_numerator": estimate.unweighted_numerator,
                    },
                )
            )

            if estimate.statistic == "weighted_percentage":
                numerator_w = estimate.weighted_numerator
                weighted_consistent = (
                    numerator_w is not None
                    and numerator_w >= -tolerance
                    and numerator_w <= estimate.weighted_denominator + tolerance
                )
                unweighted_consistent = (
                    estimate.unweighted_numerator <= estimate.unweighted_denominator
                )
                expected_complement = (
                    estimate.unweighted_denominator - estimate.unweighted_numerator
                )
                complement_consistent = (
                    estimate.unweighted_complement == expected_complement
                )
                checks.extend(
                    [
                        self._check(
                            f"PERCENTAGE_WEIGHTED_NUMERATOR_WITHIN_DENOMINATOR[{index}]",
                            weighted_consistent,
                            "Percentage weighted numerator is within its weighted denominator.",
                            retryable=True,
                            details={
                                **key,
                                "weighted_numerator": (
                                    None if numerator_w is None else str(numerator_w)
                                ),
                                "weighted_denominator": str(
                                    estimate.weighted_denominator
                                ),
                            },
                        ),
                        self._check(
                            f"PERCENTAGE_UNWEIGHTED_NUMERATOR_WITHIN_DENOMINATOR[{index}]",
                            unweighted_consistent,
                            "Percentage unweighted numerator does not exceed its denominator.",
                            retryable=True,
                            details={
                                **key,
                                "unweighted_numerator": estimate.unweighted_numerator,
                                "unweighted_denominator": estimate.unweighted_denominator,
                            },
                        ),
                        self._check(
                            f"PERCENTAGE_COMPLEMENT_CONSISTENT[{index}]",
                            complement_consistent,
                            "Percentage complement equals denominator minus numerator.",
                            retryable=True,
                            details={
                                **key,
                                "expected_complement": expected_complement,
                                "observed_complement": estimate.unweighted_complement,
                            },
                        ),
                    ]
                )

            formula_expected: Decimal | None
            if estimate.weighted_denominator <= 0:
                formula_expected = None
            elif estimate.weighted_numerator is None:
                formula_expected = None
            elif estimate.statistic == "weighted_count":
                formula_expected = estimate.weighted_numerator
            elif estimate.statistic == "weighted_percentage":
                formula_expected = (
                    Decimal(100)
                    * estimate.weighted_numerator
                    / estimate.weighted_denominator
                )
            else:
                formula_expected = (
                    estimate.weighted_numerator / estimate.weighted_denominator
                )

            if estimate.estimate is None or formula_expected is None:
                formula_consistent = estimate.estimate is None and (
                    estimate.suppression.suppressed
                    or estimate.weighted_denominator <= 0
                )
            else:
                formula_consistent = self._decimal_close(
                    estimate.estimate, formula_expected, tolerance
                )
            checks.append(
                self._check(
                    f"DENOMINATOR_FORMULA_CONSISTENT[{index}]",
                    formula_consistent,
                    "The released estimate is consistent with its numerator and denominator.",
                    retryable=True,
                    details={
                        **key,
                        "observed_estimate": (
                            None if estimate.estimate is None else str(estimate.estimate)
                        ),
                        "formula_estimate": (
                            None if formula_expected is None else str(formula_expected)
                        ),
                        "tolerance": str(tolerance),
                    },
                )
            )

        return checks

    def _percentage_checks(
        self, estimates: list[SurveyEstimate], tolerance: Decimal
    ) -> list[ResultCriticCheck]:
        checks: list[ResultCriticCheck] = []
        percentage_estimates = [
            (index, item)
            for index, item in enumerate(estimates)
            if item.statistic == "weighted_percentage"
        ]
        if not percentage_estimates:
            return [
                self._check(
                    "PERCENTAGES_PLAUSIBLE",
                    None,
                    "The plan did not produce percentage estimates.",
                )
            ]
        for index, item in percentage_estimates:
            plausible = item.estimate is None or (
                item.estimate >= -tolerance and item.estimate <= Decimal(100) + tolerance
            )
            checks.append(
                self._check(
                    f"PERCENTAGE_RANGE[{index}]",
                    plausible,
                    "Released percentages fall between 0 and 100.",
                    retryable=True,
                    details={
                        "estimate_alias": item.estimate_alias,
                        "group": item.group,
                        "estimate": None if item.estimate is None else str(item.estimate),
                    },
                )
            )
        return checks

    def _group_checks(
        self,
        validated: ValidatedAnalysisPlan,
        compiled: CompiledSurveyEstimate,
        estimates: list[SurveyEstimate],
        config: ResultCriticConfig,
    ) -> list[ResultCriticCheck]:
        checks: list[ResultCriticCheck] = []
        observed_keys = [
            (item.estimate_alias, self._group_key(item.group)) for item in estimates
        ]
        checks.append(
            self._check(
                "MUTUALLY_EXCLUSIVE_RESULT_GROUP_KEYS",
                len(observed_keys) == len(set(observed_keys)),
                "Each estimate alias and full group key occurs at most once.",
                retryable=True,
            )
        )

        expected_group_aliases = set(compiled.group_aliases)
        group_shapes_valid = all(set(item.group) == expected_group_aliases for item in estimates)
        checks.append(
            self._check(
                "GROUP_SHAPE_MATCH",
                group_shapes_valid,
                "Every result group contains exactly the grouping aliases compiled from the plan.",
                retryable=True,
                details={"expected_group_aliases": sorted(expected_group_aliases)},
            )
        )

        if config.reject_null_group_values and expected_group_aliases:
            null_groups = [
                item.group
                for item in estimates
                if any(value is None for value in item.group.values())
            ]
            checks.append(
                self._check(
                    "NO_UNEXPECTED_NULL_GROUP_VALUES",
                    not null_groups,
                    "Grouping values do not contain unexpected nulls.",
                    retryable=True,
                    details={"null_groups": null_groups},
                )
            )
        else:
            checks.append(
                self._check(
                    "NO_UNEXPECTED_NULL_GROUP_VALUES",
                    None,
                    "Null grouping-value rejection was not applicable or was explicitly disabled.",
                )
            )

        expected = list(config.expected_groups)
        if compiled.normalized_reference_group is not None:
            from .models import ExpectedResultGroup

            expected.append(
                ExpectedResultGroup(
                    estimate_alias=validated.plan.measure.alias,
                    group=compiled.normalized_reference_group,
                )
            )
        if expected:
            missing: list[dict[str, Any]] = []
            for item in expected:
                matches = [
                    estimate
                    for estimate in estimates
                    if estimate.estimate_alias == item.estimate_alias
                    and estimate.group == item.group
                ]
                if len(matches) != 1:
                    missing.append(
                        {
                            "estimate_alias": item.estimate_alias,
                            "group": item.group,
                            "matches": len(matches),
                        }
                    )
            checks.append(
                self._check(
                    "EXPECTED_GROUPS_PRESENT",
                    not missing,
                    "Every configured or reference comparison group appears exactly once.",
                    retryable=True,
                    details={"missing_or_duplicate_groups": missing},
                )
            )
        else:
            checks.append(
                self._check(
                    "EXPECTED_GROUPS_PRESENT",
                    None,
                    "No expected result groups or reference group were configured.",
                )
            )

        for group_set in config.mutually_exclusive_group_sets:
            checks.extend(self._mutually_exclusive_checks(group_set, estimates))
        if not config.mutually_exclusive_group_sets:
            checks.append(
                self._check(
                    "CONFIGURED_MUTUALLY_EXCLUSIVE_CATEGORIES",
                    None,
                    "No metadata-backed mutually exclusive category set was configured.",
                )
            )
        return checks

    def _mutually_exclusive_checks(
        self,
        group_set: MutuallyExclusiveGroupSet,
        estimates: list[SurveyEstimate],
    ) -> list[ResultCriticCheck]:
        relevant = [
            item for item in estimates if item.estimate_alias == group_set.estimate_alias
        ]
        category_hits = [0 for _ in group_set.categories]
        overlapping_results: list[dict[str, Any]] = []
        for estimate in relevant:
            matches = [
                index
                for index, selector in enumerate(group_set.categories)
                if self._matches_selector(estimate.group, selector)
            ]
            for index in matches:
                category_hits[index] += 1
            if len(matches) > 1:
                overlapping_results.append(
                    {"group": estimate.group, "matching_category_indexes": matches}
                )

        selector_overlaps: list[dict[str, Any]] = []
        for left_index, left in enumerate(group_set.categories):
            for right_index in range(left_index + 1, len(group_set.categories)):
                right = group_set.categories[right_index]
                shared = set(left).intersection(right)
                incompatible = any(left[key] != right[key] for key in shared)
                if not incompatible:
                    selector_overlaps.append(
                        {
                            "left_index": left_index,
                            "right_index": right_index,
                            "left": left,
                            "right": right,
                        }
                    )

        checks = [
            self._check(
                f"CATEGORY_SELECTORS_MUTUALLY_EXCLUSIVE[{group_set.set_id}]",
                not selector_overlaps,
                "Configured category selectors are logically mutually exclusive.",
                retryable=False,
                details={"overlapping_selectors": selector_overlaps},
            ),
            self._check(
                f"RESULTS_MATCH_AT_MOST_ONE_CATEGORY[{group_set.set_id}]",
                not overlapping_results,
                "Each returned result matches at most one configured category.",
                retryable=True,
                details={"overlapping_results": overlapping_results},
            ),
        ]
        if group_set.require_all_categories:
            missing = [
                group_set.categories[index]
                for index, hit_count in enumerate(category_hits)
                if hit_count == 0
            ]
            checks.append(
                self._check(
                    f"ALL_MUTUALLY_EXCLUSIVE_CATEGORIES_PRESENT[{group_set.set_id}]",
                    not missing,
                    "Every configured mutually exclusive category is represented.",
                    retryable=True,
                    details={"missing_categories": missing},
                )
            )
        return checks

    def _unexpected_null_checks(
        self, estimates: list[SurveyEstimate]
    ) -> list[ResultCriticCheck]:
        unexpected: list[dict[str, Any]] = []
        for item in estimates:
            estimate_null_allowed = (
                item.suppression.suppressed
                or item.weighted_denominator <= 0
            )
            if item.estimate is None and not estimate_null_allowed:
                unexpected.append(
                    {
                        "estimate_alias": item.estimate_alias,
                        "group": item.group,
                        "field": "estimate",
                    }
                )
            if item.weighted_numerator is None and item.weighted_denominator > 0:
                unexpected.append(
                    {
                        "estimate_alias": item.estimate_alias,
                        "group": item.group,
                        "field": "weighted_numerator",
                    }
                )
            if (
                item.suppression.suppressed
                and item.suppression.action == "null_estimate"
                and item.estimate is not None
            ):
                unexpected.append(
                    {
                        "estimate_alias": item.estimate_alias,
                        "group": item.group,
                        "field": "suppressed_estimate_not_null",
                    }
                )
        return [
            self._check(
                "NO_UNEXPECTED_NULL_NUMERIC_RESULTS",
                not unexpected,
                "Null numeric fields occur only for suppression or nonpositive denominators.",
                retryable=True,
                details={"unexpected_nulls": unexpected},
            )
        ]

    def _reference_checks(
        self,
        estimates: list[SurveyEstimate],
        references: list[ReferenceEstimate],
    ) -> list[ResultCriticCheck]:
        if not references:
            return [
                self._check(
                    "REFERENCE_ESTIMATE_CONSISTENCY",
                    None,
                    "No approved reference estimates were supplied.",
                )
            ]
        checks: list[ResultCriticCheck] = []
        for index, reference in enumerate(references):
            matches = [
                item
                for item in estimates
                if item.estimate_alias == reference.estimate_alias
                and item.group == reference.group
            ]
            if len(matches) != 1:
                checks.append(
                    self._check(
                        f"REFERENCE_ESTIMATE_MATCH[{index}]",
                        False,
                        "The referenced estimate was not returned exactly once.",
                        retryable=True,
                        details={
                            "source_id": reference.source_id,
                            "estimate_alias": reference.estimate_alias,
                            "group": reference.group,
                            "matches": len(matches),
                        },
                    )
                )
                continue
            observed = matches[0].estimate
            if observed is None:
                checks.append(
                    self._check(
                        f"REFERENCE_ESTIMATE_MATCH[{index}]",
                        False,
                        "A null or suppressed result cannot be compared with the reference estimate.",
                        retryable=True,
                        details={
                            "source_id": reference.source_id,
                            "expected": str(reference.expected),
                            "observed": None,
                        },
                    )
                )
                continue
            difference = abs(observed - reference.expected)
            absolute_ok = (
                reference.absolute_tolerance is not None
                and difference <= reference.absolute_tolerance
            )
            relative_ok = False
            if reference.relative_tolerance is not None:
                if reference.expected == 0:
                    relative_ok = difference == 0
                else:
                    relative_ok = (
                        difference / abs(reference.expected)
                        <= reference.relative_tolerance
                    )
            checks.append(
                self._check(
                    f"REFERENCE_ESTIMATE_MATCH[{index}]",
                    absolute_ok or relative_ok,
                    "The deterministic result is within the explicitly supplied reference tolerance.",
                    retryable=True,
                    details={
                        "source_id": reference.source_id,
                        "estimate_alias": reference.estimate_alias,
                        "group": reference.group,
                        "expected": str(reference.expected),
                        "observed": str(observed),
                        "absolute_difference": str(difference),
                        "absolute_tolerance": (
                            None
                            if reference.absolute_tolerance is None
                            else str(reference.absolute_tolerance)
                        ),
                        "relative_tolerance": (
                            None
                            if reference.relative_tolerance is None
                            else str(reference.relative_tolerance)
                        ),
                    },
                )
            )
        return checks

    def critique(
        self,
        validated: ValidatedAnalysisPlan,
        compiled: CompiledSurveyEstimate,
        execution: AnalysisPlanExecutionResult,
        config: ResultCriticConfig,
        *,
        reexecution_count: int = 0,
    ) -> ResultCriticReport:
        """Return a decision without modifying any value in ``execution``."""

        try:
            tolerance = Decimal(config.numeric_tolerance)
        except (InvalidOperation, TypeError) as exc:  # defensive; Pydantic normally prevents this
            raise ValueError("numeric_tolerance must be a decimal") from exc

        estimates = execution.result.estimates
        checks: list[ResultCriticCheck] = []
        checks.extend(self._denominator_checks(validated, estimates, tolerance))
        checks.extend(self._percentage_checks(estimates, tolerance))
        checks.extend(self._group_checks(validated, compiled, estimates, config))
        checks.extend(self._unexpected_null_checks(estimates))
        checks.extend(self._reference_checks(estimates, config.reference_estimates))

        failures = [item for item in checks if item.status == "failed"]
        if not failures:
            decision = "approve"
        elif any(not item.retryable for item in failures):
            decision = "reject"
        elif reexecution_count < config.max_reexecutions:
            decision = "request_reexecution"
        else:
            decision = "reject"

        return ResultCriticReport(
            decision=decision,
            checks=checks,
            failed_check_ids=[item.check_id for item in failures],
            reexecution_count=reexecution_count,
            max_reexecutions=config.max_reexecutions,
        )
