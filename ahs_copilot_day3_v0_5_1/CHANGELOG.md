# Changelog

## 0.5.1 — durable dataset-key model

- Replaced overloaded source-file `join_keys` with `relationship_keys`, `row_identity_columns`, and `declared_primary_key`.
- Corrected the PUF project source contract: `relationship_keys=["CONTROL"]`, `row_identity_columns=[]`, and no declared primary key.
- Removed every executable dependency on `PROJECTNO`.
- Kept the certified household-to-project relationship on `CONTROL` with mandatory child preaggregation to `CONTROL`.
- Added regression tests using a project fixture that deliberately has no `PROJECTNO` column.
- Added distinct schema errors for missing relationship keys and missing declared row-identity columns.
- Updated inspection output, documentation, JSON schema, examples, and handoff notes.
