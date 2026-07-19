# AHS 2023 Research Copilot — Day 3 v0.5.1 handoff

The deterministic engine, survey-estimation layer, and AnalysisPlan validator are packaged in this repository. The durable project-source correction is complete: project row identity is unresolved/optional, `CONTROL` is the only required project relationship key, and household joins still require project preaggregation exactly to `CONTROL`.

Public commands:

```bash
ahs-query inspect --config config/ahs_engine.example.toml
ahs-query compile examples/household_filter.json --config config/ahs_engine.example.toml
ahs-query run examples/household_with_project_aggregation.json --config config/ahs_engine.example.toml
ahs-query survey-run examples/survey_tenure_comparison.json --config config/ahs_engine.example.toml
ahs-plan --config config/ahs_engine.example.toml --plan examples/analysis_plan_high_burden_by_tenure.json --action execute
```

The next phase should build plan authoring and human approval around these deterministic interfaces without permitting arbitrary SQL.
