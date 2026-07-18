# Structured `AnalysisPlan` contract

## Purpose

`AnalysisPlan` is the only high-level analysis input accepted by the validation-first service. It contains no SQL or expression string that can be executed. The service validates the plan against the approved semantic catalog, inspected DuckDB schemas, PUF access mode, universe registry, weight registry, recode registry, and relationship catalog before invoking the deterministic survey SQL compiler.

## Contract fields

| Field | Meaning |
|---|---|
| `user_question` | Original natural-language research question retained for audit. |
| `dataset` | Logical base dataset resolved through the configured source-file catalog. |
| `measure` | Count, percentage, or mean plus output alias and mean value variable when applicable. |
| `numerator` | Explicit role, description, and typed conditions. |
| `denominator` | Explicit role, description, and typed eligibility conditions. |
| `universe` | Approved named universe such as all, occupied, owner-occupied, or renter-occupied housing units. |
| `filters` | Additional typed analysis filters applied inside the approved universe. |
| `grouping_dimensions` | Validated PUF variables used for grouped output. |
| `weight` | Explicit `weighted` or `unweighted` mode; weighted plans require an approved PUF weight. |
| `required_variables` | Declared input-variable closure. Validation rejects any variable used but not declared. |
| `derived_recodes` | References to approved deterministic recode definitions; arbitrary formulas are prohibited. |
| `joins` | Optional approved relationships using the existing mandatory child-preaggregation contract. |
| `validation_checks` | Non-disableable validation controls recorded in the plan. |
| `output_format` | Output shape and audit fields, including generated SQL and execution metadata. |

Machine-readable schemas are in `schemas/analysis_plan.schema.json` and `schemas/validated_analysis_plan.schema.json`.

## Validation order

1. Parse the strict Pydantic contract and reject unknown properties, including `sql`.
2. Resolve the logical base dataset and every joined dataset.
3. Resolve the named universe and verify that it belongs to the base dataset.
4. Verify the base grain is `HOUSING_UNIT` for descriptive housing-unit estimation.
5. Validate every relationship and require child preaggregation exactly to the certified join key.
6. Resolve every referenced variable through the approved semantic catalog.
7. Reject IUF-only variables and recodes while the execution catalog is in PUF mode.
8. Verify each resolved PUF variable exists in the inspected physical CSV schema.
9. Verify measure, numerator, and denominator roles are compatible.
10. Validate filter operators and values against physical DuckDB types.
11. Verify weighted plans use an approved numeric PUF weight; unweighted plans use deterministic unit weight 1.
12. Compute the required-variable closure from the universe, measure, filters, groups, weight, joins, and recodes; reject missing declarations.
13. Bind declared missing-value codes to estimate eligibility.
14. Produce a normalized `SurveyEstimateRequest`; only then may SQL compilation begin.

Validation errors are returned as structured issue records with `code`, `path`, and `message`. `AnalysisPlanService.compile()` and `.execute()` always call the validator first. An invalid plan cannot reach the SQL compiler.

## Deterministic translation

- `count` maps to the governed count formula.
- `percentage` maps to an explicit numerator condition evaluated within the denominator.
- `mean` maps to a weighted or unit-weight value sum divided by the corresponding eligible denominator.
- Named universe filters come only from `metadata/semantic_catalog.json`.
- Missing codes come only from the variable records in that catalog.
- Approved recodes are catalog references, not user-authored SQL or Python.

## Descriptive versus variance estimation

This contract produces descriptive weighted or unweighted estimates only. Every execution still reports:

- `variance.status = NOT_ESTIMATED`;
- `replicate_weights_used = false`;
- `standard_errors_valid = false`;
- null standard errors, confidence intervals, and p-values;
- `inferential_test = NOT_PERFORMED` for comparisons.

No standard error is valid until replicate weights and an approved AHS variance method are implemented as a separate certified layer.

## CLI

```bash
ahs-plan --config config/ahs_engine.example.toml \
  --plan examples/analysis_plan_occupied_count.json \
  --action validate

ahs-plan --config config/ahs_engine.example.toml \
  --plan examples/analysis_plan_high_burden_by_tenure.json \
  --action compile

ahs-plan --config config/ahs_engine.example.toml \
  --plan examples/analysis_plan_high_burden_by_tenure.json \
  --action execute
```
