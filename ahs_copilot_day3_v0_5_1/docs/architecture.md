# Day 3 component architecture

```text
AnalysisPlan JSON
      |
      v
AnalysisPlan validator ---- semantic_catalog.json
      |
      v
SurveyEstimateRequest
      |
      v
Deterministic survey compiler
      |
      v
Governed DuckDB engine ---- source_files.json
      |                  \-- execution_catalog.json
      v
Lazy CSV scans + certified child preaggregation
      |
      v
Descriptive estimate + SQL + parameters + audit metadata
```

The LLM boundary is outside this repository. An LLM may propose an `AnalysisPlan`; it cannot issue SQL or call DuckDB directly.
