# AHS 2023 governed DuckDB research engine

This checkpoint implements a deterministic execution path from a structured `AnalysisPlan` to descriptive survey-weighted results over AHS household, mortgage, and projects CSV files.

## Implemented layers

- **Governed DuckDB query engine:** configuration-driven CSV resolution, runtime schema inspection, typed filters, bound parameters, certified joins, mandatory child preaggregation, generated SQL, and execution metadata.
- **Descriptive survey estimator:** weighted or unit-weight counts, percentages, means, explicit denominators, missing-code exclusions, suppression flags, grouped comparisons, and deterministic decimal arithmetic.
- **AnalysisPlan validator:** validates datasets, universes, PUF access, physical variables, filter types, weight compatibility, required-variable closure, recodes, grains, and joins before SQL generation.

The public contracts contain no raw-SQL field. Mortgage and project rows must be reduced to one row per `CONTROL` before household weighting. Mortgage-to-project joins are not approved.

## Statistical boundary

Results are descriptive only. Replicate weights and an approved variance method are not implemented. The package therefore returns no valid standard errors, confidence intervals, p-values, or significance claims. See `docs/survey_estimation.md`.

## Install and test

```bash
python -m pip install -e '.[dev]'
python -m pytest -q
```

The latest clean-environment run passed 32 tests; the 11-test critical AnalysisPlan checkpoint also passed. Exact commands and results are in `docs/execution_report.md`.

## Configuration and large CSVs

```bash
cp config/ahs_engine.example.toml config/ahs_engine.toml
export AHS_HOUSEHOLD_CSV=/data/ahs/household.csv
export AHS_MORTGAGE_CSV=/data/ahs/mortgage.csv
export AHS_PROJECTS_CSV=/data/ahs/projects.csv
```

DuckDB scans CSVs lazily and can spill through its configured temp directory. Python does not load entire source files into pandas. `fixture.mode = "auto"` supplies deterministic synthetic files only when configured files are absent; use `disabled` for production fail-closed behavior.

## CLI examples

```bash
ahs-query inspect --config config/ahs_engine.example.toml
ahs-query run examples/household_filter.json --config config/ahs_engine.example.toml
ahs-query survey-run examples/survey_tenure_comparison.json --config config/ahs_engine.example.toml
ahs-plan --config config/ahs_engine.example.toml --plan examples/analysis_plan_high_burden_by_tenure.json --action validate
ahs-plan --config config/ahs_engine.example.toml --plan examples/analysis_plan_high_burden_by_tenure.json --action compile
ahs-plan --config config/ahs_engine.example.toml --plan examples/analysis_plan_high_burden_by_tenure.json --action execute
```

## Key documentation

- `NEXT_CHAT_HANDOFF.md` — authoritative current checkpoint and next steps.
- `docs/analysis_plan.md` — structured plan contract and validation order.
- `docs/survey_estimation.md` — deterministic formulas, suppression, and variance boundary.
- `docs/execution_report.md` — exact verification commands and test results.
- `docs/RUN_ON_MAC.md` — macOS installation, verification, fixture, real-data, and troubleshooting instructions.
- `schemas/` — machine-readable input and result contracts.
