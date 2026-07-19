#!/usr/bin/env bash
set -euo pipefail

python -m compileall -q src tests
python -m pytest -ra

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

printf 'All deterministic verification checks passed.\n'
