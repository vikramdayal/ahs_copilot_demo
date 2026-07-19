# AHS 2023 governed DuckDB research engine — v0.5.1

This repository implements the Day 3 deterministic core for the AHS 2023 Research Copilot:

- configuration-driven DuckDB access to household, mortgage, and project CSV files;
- runtime schema inspection without loading full CSVs into pandas;
- typed filters and bound values;
- certified household-to-child relationships with mandatory child preaggregation;
- deterministic descriptive weighted counts, percentages, means, grouped comparisons, and suppression flags;
- a strict `AnalysisPlan` contract that is validated before SQL compilation;
- generated SQL, parameters, file metadata, schema snapshots, relationship IDs, and fingerprints;
- deterministic synthetic fixtures for tests and offline demonstrations.

## Durable project-file key correction

Version 0.5.1 separates three concepts that were previously conflated:

1. `relationship_keys`: columns needed to relate a child dataset to its parent;
2. `row_identity_columns`: optional columns that identify individual rows at the child grain;
3. `declared_primary_key`: an optional certified uniqueness claim.

For the National PUF project relation, only `CONTROL` is required for the approved household relationship. No `PROJECTNO` column is required. Project records must still be aggregated to one row per `CONTROL` before a household join.

## Install

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip setuptools wheel
python -m pip install -e '.[dev]'
python -m pytest -ra
```

## Synthetic smoke test

```bash
ahs-query inspect \
  --config config/ahs_engine.example.toml \
  --output sample_outputs/schema_inspection.json

ahs-query run examples/household_with_project_aggregation.json \
  --config config/ahs_engine.example.toml \
  --output sample_outputs/project_aggregation_result.json

ahs-query survey-run examples/survey_tenure_comparison.json \
  --config config/ahs_engine.example.toml \
  --output sample_outputs/survey_tenure_comparison.json

ahs-plan \
  --config config/ahs_engine.example.toml \
  --plan examples/analysis_plan_high_burden_by_tenure.json \
  --action execute \
  --output sample_outputs/analysis_plan_result.json
```

## Real AHS files

```bash
cp config/ahs_engine.example.toml config/ahs_engine.toml
export AHS_HOUSEHOLD_CSV="$HOME/Data/AHS-2023/household.csv"
export AHS_MORTGAGE_CSV="$HOME/Data/AHS-2023/mortgage.csv"
export AHS_PROJECTS_CSV="$HOME/Data/AHS-2023/projects.csv"

ahs-query inspect \
  --config config/ahs_engine.toml \
  --output sample_outputs/real_schema_inspection.json
```

Set `[fixture].mode = "disabled"` in `config/ahs_engine.toml` for a fail-closed real-data run.

## Statistical boundary

All estimates are descriptive. Replicate-weight variance estimation is not implemented. Results therefore do not contain valid standard errors, confidence intervals, p-values, or significance claims.
