# Migration from v0.5.0 to v0.5.1

## Required metadata change

Replace the overloaded source-file field:

```json
"join_keys": ["CONTROL", "PROJECTNO"]
```

with explicit key roles:

```json
"relationship_keys": ["CONTROL"],
"row_identity_columns": [],
"declared_primary_key": null
```

For mortgage, preserve row identity separately:

```json
"relationship_keys": ["CONTROL"],
"row_identity_columns": ["CONTROL", "MORTLINE"],
"declared_primary_key": ["CONTROL", "MORTLINE"]
```

## Runtime behavior

- Schema inspection validates relationship keys, row identity, and declared primary keys independently.
- Empty `row_identity_columns` is valid.
- The project relation is accepted without `PROJECTNO`.
- `rel_household_projects_control` remains a one-to-many relationship using `CONTROL`.
- The child relation must be grouped exactly by `CONTROL` before joining to household.

## Configuration

No project key columns should be duplicated in TOML. Configuration binds the logical dataset to `source_puf_projects`; the metadata contract owns key semantics.

## Verification

```bash
python -m pip install -e '.[dev]'
./scripts/verify.sh
```
