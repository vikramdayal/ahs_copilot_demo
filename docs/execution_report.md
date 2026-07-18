# Day 3 critical-checkpoint execution report

**Checkpoint:** Structured `AnalysisPlan` contract, validation-first compilation, deterministic descriptive survey estimation, and required universe/access/join/error tests.

**Execution date:** 2026-07-18  
**Package version:** `ahs-copilot 0.5.0`  
**Runtime:** Python 3.13.5, DuckDB 1.5.4, Pydantic 2.13.4, pytest 9.1.1

## Implemented checkpoint controls

1. Strict `AnalysisPlan` Pydantic contract containing the user question, dataset, measure, numerator, denominator, universe, filters, grouping dimensions, weight mode, required variables, approved derived recodes, validation checks, and output format.
2. Optional joins represented only through the existing governed `JoinSpec`; no arbitrary join expression is accepted.
3. Strict unknown-field rejection, including a supplied `sql` property.
4. Named-universe resolution from `metadata/semantic_catalog.json`.
5. Approved PUF variable, weight, universe, missing-code, and recode registries.
6. PUF/IUF access enforcement before physical-schema checks.
7. Runtime CSV-schema verification for approved PUF variables.
8. Measure/numerator/denominator compatibility checks before SQL generation.
9. Typed-filter operator and scalar coercion checks before SQL generation.
10. Required-variable closure derived from the universe, measure, numerator, denominator, filters, groups, weight, joins, and recodes.
11. Approved relationship enforcement and mandatory child preaggregation.
12. Validation-first facade: `AnalysisPlanService.compile()` and `.execute()` cannot call the SQL compiler until validation succeeds.
13. Weighted estimates use the approved final housing-unit weight. Unweighted estimates use deterministic unit weight 1.
14. Declared missing codes are bound to denominator eligibility and missing-row diagnostics.
15. Empty denominators return an undefined estimate plus deterministic suppression reasons rather than division errors.
16. Variance remains explicitly separate and unavailable: no valid standard errors, confidence intervals, p-values, or significance tests are produced.

## Exact verification commands

The following commands were executed from `/mnt/data/ahs_copilot_day3`:

```bash
rm -rf /tmp/ahs_day3_checkpoint_venv
python -m venv /tmp/ahs_day3_checkpoint_venv
/tmp/ahs_day3_checkpoint_venv/bin/python -m pip install -e '.[dev]'
/tmp/ahs_day3_checkpoint_venv/bin/python -m pip check
/tmp/ahs_day3_checkpoint_venv/bin/python -m compileall -q src tests
/tmp/ahs_day3_checkpoint_venv/bin/python -m pytest -vv tests/test_analysis_plan.py
/tmp/ahs_day3_checkpoint_venv/bin/python -m pytest -q
```

The example artifacts were generated with:

```bash
PYTHONPATH=src python -m ahs_copilot.analysis_plan.cli \
  --config config/ahs_engine.example.toml \
  --plan examples/analysis_plan_occupied_count.json \
  --action validate \
  > sample_outputs/validated_analysis_plan_occupied_count.json

PYTHONPATH=src python -m ahs_copilot.analysis_plan.cli \
  --config config/ahs_engine.example.toml \
  --plan examples/analysis_plan_high_burden_by_tenure.json \
  --action compile \
  > sample_outputs/compiled_analysis_plan_high_burden.json

PYTHONPATH=src python -m ahs_copilot.analysis_plan.cli \
  --config config/ahs_engine.example.toml \
  --plan examples/analysis_plan_high_burden_by_tenure.json \
  --action execute \
  > sample_outputs/analysis_plan_high_burden_result.json
```

## Dependency and compilation results

```text
No broken requirements found.
compileall: PASS
```

The clean environment installed:

```text
ahs-copilot=0.5.0
duckdb=1.5.4
pydantic=2.13.4
pytest=9.1.1
```

## Critical AnalysisPlan test results

```text
============================= test session starts ==============================
platform linux -- Python 3.13.5, pytest-9.1.1, pluggy-1.6.0
collected 11 items

tests/test_analysis_plan.py::test_occupied_versus_all_housing_units PASSED
tests/test_analysis_plan.py::test_owner_versus_renter_universes PASSED
tests/test_analysis_plan.py::test_declared_missing_value_codes_are_excluded_deterministically PASSED
tests/test_analysis_plan.py::test_weighted_versus_unweighted_output PASSED
tests/test_analysis_plan.py::test_illegal_mortgage_project_join_rejected_before_sql_generation PASSED
tests/test_analysis_plan.py::test_empty_denominator_returns_flagged_undefined_estimate PASSED
tests/test_analysis_plan.py::test_unknown_variable_rejected PASSED
tests/test_analysis_plan.py::test_puf_inaccessible_field_rejected PASSED
tests/test_analysis_plan.py::test_missing_required_variable_declaration_rejected PASSED
tests/test_analysis_plan.py::test_approved_derived_recode_is_recorded_in_validated_plan PASSED
tests/test_analysis_plan.py::test_analysis_plan_rejects_raw_sql_property PASSED

============================== 11 passed in 0.70s ==============================
```

## Full regression result

```text
................................                                         [100%]
32 passed
```

## Required checkpoint matrix

| Required case | Test | Observed result |
|---|---|---|
| Occupied versus all housing units | `test_occupied_versus_all_housing_units` | Weighted all-unit count `84.000000`; occupied count `75.000000`. |
| Owner versus renter universes | `test_owner_versus_renter_universes` | Owner `21.000000` from 2 records; renter `47.000000` from 3 records. |
| Missing-value codes | `test_declared_missing_value_codes_are_excluded_deterministically` | `HINCP=-6` and null are excluded; denominator is weight `75.000000`, 6 records; 2 missing rows reported. |
| Weighted versus unweighted output | `test_weighted_versus_unweighted_output` | Occupied weighted count `75.000000`; unit-weight count `6.000000`; metadata distinguishes both modes. |
| Illegal mortgage/project joins | `test_illegal_mortgage_project_join_rejected_before_sql_generation` | Rejected with `ILLEGAL_JOIN_PATH`; monkeypatch confirms SQL compiler was not called. |
| Empty denominators | `test_empty_denominator_returns_flagged_undefined_estimate` | Estimate is null; denominator `0.000000`; `ZERO_OR_NONPOSITIVE_WEIGHTED_DENOMINATOR` flag returned. |
| Unknown variables | `test_unknown_variable_rejected` | Rejected with `UNKNOWN_VARIABLE` before SQL generation. |
| PUF-inaccessible fields | `test_puf_inaccessible_field_rejected` | IUF-only sentinel rejected with `PUF_INACCESSIBLE_FIELD`. |

## Statistical boundary verification

The executed AnalysisPlan sample contains:

```json
{
  "status": "NOT_ESTIMATED",
  "replicate_weights_used": false,
  "approved_method": null,
  "standard_errors_valid": false
}
```

Every estimate has `standard_error: null` and `confidence_interval: null`. Group comparisons have `inferential_test: "NOT_PERFORMED"` and `p_value: null`. The implementation makes no standard-error or significance claim.
