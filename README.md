# AHS 2023 governed DuckDB query engine

This checkpoint extends the Day 2 semantic metadata contracts with a deterministic DuckDB execution core, a descriptive survey-estimation layer, and a validation-first structured `AnalysisPlan` service for the National PUF household, mortgage, and projects CSV relations.

## Security and statistical boundary

- The low-level query API accepts only `QuerySpec`; the research API accepts only `AnalysisPlan`. Neither has a raw-SQL field or raw-SQL execution method.
- Pydantic rejects unknown fields, including an attempted `sql` property.
- Dataset and column identifiers must match inspected schemas and are always quoted.
- Filter values are coerced to the inspected DuckDB type and sent as bound parameters.
- Joins are selected only from `metadata/execution_catalog.json`.
- Household-to-mortgage and household-to-project joins require child preaggregation exactly to `CONTROL`.
- Mortgage-to-project joins are not approved and are rejected.
- DuckDB scans CSV files directly through lazy views. Python does not load the source files into pandas or memory.
- Result rows are capped by `engine.max_result_rows`.
- The survey API supports weighted and unit-weight counts, percentages, means, explicit denominators, suppression flags, and grouped descriptive comparisons.
- Survey estimates require a housing-unit base relation. Weighted plans require an approved numeric base weight; unweighted plans use deterministic unit weight 1. Child relations remain preaggregated to `CONTROL` before they can affect a housing-unit estimate.
- Variance estimation remains separate and unavailable. Results explicitly state `variance.status: NOT_ESTIMATED`, `standard_errors_valid: false`, and return no standard errors, confidence intervals, p-values, or significance tests.

## Install and test

```bash
python -m pip install -e '.[dev]'
PYTHONPATH=src pytest -q
```

## Configuration

Copy the example and either set environment variables or edit paths:

```bash
cp config/ahs_engine.example.toml config/ahs_engine.toml
export AHS_HOUSEHOLD_CSV=/data/ahs/household.csv
export AHS_MORTGAGE_CSV=/data/ahs/mortgage.csv
export AHS_PROJECTS_CSV=/data/ahs/projects.csv
```

`fixture.mode = "auto"` creates deterministic synthetic files only for missing configured paths. Set it to `disabled` in production to fail closed, or `required` for reproducible demos/tests.

## Inspect schemas

```bash
ahs-query inspect --config config/ahs_engine.example.toml
```

The command returns each logical dataset, physical path, source-file contract, grain, join keys, whether a fixture was used, and every inspected DuckDB column type.

## Compile without executing

```bash
ahs-query compile examples/household_filter.json \
  --config config/ahs_engine.example.toml
```

The response contains parameterized SQL, display SQL, bound parameters, datasets, join contract IDs, and a query fingerprint.

## Execute

```bash
ahs-query run examples/household_filter.json \
  --config config/ahs_engine.example.toml

ahs-query run examples/household_with_mortgage_aggregation.json \
  --config config/ahs_engine.example.toml
```

## Structured AnalysisPlan

Validate before SQL generation:

```bash
ahs-plan --config config/ahs_engine.example.toml \
  --plan examples/analysis_plan_occupied_count.json \
  --action validate
```

Compile or execute only after validation:

```bash
ahs-plan --config config/ahs_engine.example.toml \
  --plan examples/analysis_plan_high_burden_by_tenure.json \
  --action compile

ahs-plan --config config/ahs_engine.example.toml \
  --plan examples/analysis_plan_high_burden_by_tenure.json \
  --action execute
```

The validator resolves named universes, PUF accessibility, inspected schemas, numerator/denominator compatibility, weight mode, approved recodes, required-variable closure, typed filters, and approved joins. See `docs/analysis_plan.md`.

## Descriptive survey estimates

```bash
ahs-query survey-compile examples/survey_tenure_comparison.json \
  --config config/ahs_engine.example.toml

ahs-query survey-run examples/survey_tenure_comparison.json \
  --config config/ahs_engine.example.toml

ahs-query survey-run examples/survey_mortgage_households.json \
  --config config/ahs_engine.example.toml
```

The deterministic formulas are:

- weighted count: `sum(w_i * I_i)`;
- weighted percentage: `100 * sum(w_i * I_i) / sum(w_i * D_i)`;
- weighted mean: `sum(w_i * y_i) / sum(w_i)` over nonmissing `y_i`.

Component sums use configured fixed-point DuckDB decimals. Final ratios use Python `Decimal` with `ROUND_HALF_EVEN`. When an `AnalysisPlan` is used, missing-value eligibility is derived only from approved semantic variable records and bound deterministically to the estimate. Direct `SurveyEstimateRequest` callers remain responsible for explicit missing-value rules.

Suppression thresholds are configuration-driven application controls, not official AHS publication rules. See `docs/survey_estimation.md` for the statistical contract and variance boundary.

## Python API

```python
from ahs_copilot.analysis_plan import AnalysisPlan, AnalysisPlanService
from ahs_copilot.query_engine import AHSQueryEngine, QuerySpec
from ahs_copilot.survey_estimation import SurveyEstimateRequest, SurveyEstimator

request = QuerySpec.model_validate_json(open("examples/household_filter.json").read())
with AHSQueryEngine("config/ahs_engine.example.toml") as engine:
    schemas = engine.inspect_schemas()
    compiled = engine.compile(request)
    result = engine.execute(request)

plan = AnalysisPlan.model_validate_json(
    open("examples/analysis_plan_occupied_count.json").read()
)
with AHSQueryEngine("config/ahs_engine.example.toml") as engine:
    plan_result = AnalysisPlanService(engine).execute(plan)

survey_request = SurveyEstimateRequest.model_validate_json(
    open("examples/survey_tenure_comparison.json").read()
)
with AHSQueryEngine("config/ahs_engine.example.toml") as engine:
    survey_result = SurveyEstimator(engine).execute(survey_request)
```

## Query contract

`QuerySpec` supports:

- one base logical dataset;
- typed filters: equality, comparison, membership, range, and null tests;
- plain column projections and deterministic aggregates;
- approved joins;
- mandatory child preaggregation for household-to-child joins;
- group-by and order-by over validated names;
- a bounded result limit.

Child aggregate aliases become the only child columns visible after a parent-to-child join. Raw child columns cannot leak through a housing-unit query.

## JSON schemas

Machine-readable contracts are in `schemas/query_spec.schema.json`, `schemas/query_result.schema.json`, and `schemas/dataset_schema.schema.json`.

Survey contracts are in `schemas/survey_estimate_request.schema.json` and `schemas/survey_estimate_result.schema.json`. Analysis-plan contracts are in `schemas/analysis_plan.schema.json`, `schemas/validated_analysis_plan.schema.json`, and `schemas/analysis_plan_execution_result.schema.json`.
