# Architecture decisions — Day 3 v0.5.1

## ADR-005: Dataset grain, relationship keys, and row identity are distinct

**Status:** Accepted

A child dataset can participate in an approved relationship without exposing a certified row-level primary key. The runtime therefore models:

- `grain`: the semantic entity represented by a physical row;
- `relationship_keys`: physical columns required for an approved parent/child relationship;
- `row_identity_columns`: optional physical columns used to distinguish child rows;
- `declared_primary_key`: an optional uniqueness assertion that must be separately certified.

For `source_puf_projects`:

```json
{
  "grain": "PROJECT",
  "relationship_keys": ["CONTROL"],
  "row_identity_columns": [],
  "declared_primary_key": null
}
```

The engine must not require `PROJECTNO`. The approved household-to-project relationship remains one-to-many on `CONTROL`, and project data must be aggregated exactly to `CONTROL` before it can be joined to household records.

## ADR-006: Config does not duplicate metadata key declarations

Dataset configuration binds a logical dataset to a source-file contract and physical path. Key requirements are read only from `metadata/source_files.json`, preventing config and metadata from drifting independently.

## ADR-007: No raw SQL at public boundaries

Public CLI and Python entry points accept strict `QuerySpec`, `SurveyEstimateRequest`, or `AnalysisPlan` objects. Unknown properties, including `sql`, are rejected by Pydantic.

## ADR-008: Descriptive estimates remain separate from variance estimation

The repository supports deterministic descriptive estimates only. Replicate-weight variance requires a separate approved method and contract.
