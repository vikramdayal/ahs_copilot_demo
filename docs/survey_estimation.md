# Deterministic descriptive survey-estimation layer

## Scope

This layer produces descriptive weighted or deterministic unit-weight estimates at the certified housing-unit grain. It accepts a typed `SurveyEstimateRequest`; there is no raw-SQL field. It reuses the governed DuckDB dataset resolver, typed filters, schema validation, and approved relationship catalog.

The estimator currently requires a `HOUSING_UNIT` base dataset. Weighted requests require a numeric weight on that base relation; unweighted requests assign unit weight 1 to each eligible row. Mortgage and project information may enter a housing-unit estimate only after the existing relationship contract reduces the child relation to one row per `CONTROL`. Mortgage-grain or project-grain estimates are not certified by this layer.

## Deterministic formulas

For eligible housing units indexed by `i`, survey weight `w_i`, denominator indicator `D_i`, numerator indicator `I_i`, and analysis value `y_i`:

### Weighted count

`weighted_count = sum(w_i * I_i)`

The output also reports the weighted and unweighted denominator defined by `D_i`. The denominator is audit information and is not part of the weighted-count calculation.

### Weighted percentage

`weighted_percentage = 100 * sum(w_i * I_i) / sum(w_i * D_i)`

The numerator must be a subset of the denominator. Missing-value eligibility belongs in `denominator_filters`; it is never guessed from labels or variable names.

### Weighted mean

`weighted_mean = sum(w_i * y_i) / sum(w_i)`

Both terms use the same rows: the requested universe and denominator filters, an eligible weight, and nonmissing `y_i`.

### Arithmetic policy

Component sums are computed in DuckDB using configurable fixed-point `DECIMAL(precision, scale)` casts. Final divisions and differences use Python `Decimal` and `ROUND_HALF_EVEN` to the configured output precision. This makes formula selection, eligibility, parameter binding, and output rounding deterministic.

By default, eligible weights are non-null and greater than zero. The execution metadata records the exact weight column, eligibility rule, decimal arithmetic rule, SQL, parameters, and fingerprints.

## Denominators and diagnostics

Each estimate returns:

- weighted numerator;
- weighted denominator;
- unweighted numerator;
- unweighted denominator;
- unweighted complement for percentages;
- rows excluded for invalid weights;
- rows excluded because a required estimate variable is null or has an approved missing-value code.

A direct `SurveyEstimateRequest` should provide `missing_value_rules` when declared missing codes must be excluded. The higher-level `AnalysisPlan` validator derives those rules from the approved semantic catalog and applies them before SQL generation.

## Suppression

Suppression uses an explicit deterministic policy with these configurable thresholds:

- minimum unweighted denominator;
- minimum unweighted numerator for counts and percentages;
- minimum unweighted complement for percentages.

The policy action is either `flag` or `null_estimate`. Every output includes a suppression decision, policy ID, and reason codes.

These thresholds are application controls, **not an official AHS publication-suppression standard**. No reliability or coefficient-of-variation suppression is applied because valid variance estimates are not yet available.

## Grouped comparisons

Requests may group by one or more validated columns and request:

- comparisons against a typed reference group; or
- all pairwise comparisons.

The layer returns arithmetic differences and optional ratios. A zero reference estimate leaves the difference available and marks the ratio undefined. A comparison is suppressed when either input estimate is suppressed or undefined.

These are descriptive comparisons only. The layer does not calculate significance tests, p-values, or comparison standard errors.

## Variance boundary

Every result contains:

- `variance.status = "NOT_ESTIMATED"`;
- `replicate_weights_used = false`;
- `approved_method = null`;
- `standard_errors_valid = false`;
- `standard_error = null` and `confidence_interval = null` for every estimate;
- `inferential_test = "NOT_PERFORMED"` and `p_value = null` for comparisons.

Valid standard errors require replicate weights plus an approved AHS variance method. Until both are implemented and tested, this package must not label any uncertainty measure as a valid standard error.

## CLI

Compile without execution:

```bash
ahs-query survey-compile examples/survey_tenure_comparison.json \
  --config config/ahs_engine.example.toml
```

Execute:

```bash
ahs-query survey-run examples/survey_tenure_comparison.json \
  --config config/ahs_engine.example.toml

ahs-query survey-run examples/survey_mortgage_households.json \
  --config config/ahs_engine.example.toml
```

## Python API

```python
from ahs_copilot.query_engine import AHSQueryEngine
from ahs_copilot.survey_estimation import SurveyEstimateRequest, SurveyEstimator

request = SurveyEstimateRequest.model_validate_json(
    open("examples/survey_tenure_comparison.json").read()
)
with AHSQueryEngine("config/ahs_engine.example.toml") as engine:
    result = SurveyEstimator(engine).execute(request)
```
