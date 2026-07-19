# Execution report — v0.5.1

Verification commands:

```bash
python -m compileall -q src tests
python -m pytest -ra
ahs-query inspect --config config/ahs_engine.example.toml
ahs-query run examples/household_with_project_aggregation.json --config config/ahs_engine.example.toml
ahs-query survey-run examples/survey_tenure_comparison.json --config config/ahs_engine.example.toml
ahs-plan --config config/ahs_engine.example.toml --plan examples/analysis_plan_high_burden_by_tenure.json --action execute
```

Regression coverage includes a physical project CSV without `PROJECTNO`. Inspection must succeed, while removing `CONTROL` must fail with a relationship-key-specific error.

## Verified results

```text
compileall: PASS
pytest: 21 passed
CLI inspect: PASS
CLI governed project aggregation: PASS
CLI survey execution: PASS
CLI AnalysisPlan execution: PASS
```

The inspected project contract reported `relationship_keys=["CONTROL"]`, `row_identity_columns=[]`, and physical columns `CONTROL`, `JOBTYPE`, `JOBCOST`, and `JOBDIY`.
