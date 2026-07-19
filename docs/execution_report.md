# AHS deterministic core and LangGraph workflow execution report

**Checkpoint:** Deterministic `AnalysisPlan` execution core plus the LangGraph natural-language planning, approval, bounded-repair, execution, and result-validation workflow.

**Execution date:** 2026-07-19  
**Package version:** `ahs-copilot 0.7.0`  
**Runtime:** Python 3.13.5, DuckDB 1.5.4, Pydantic 2.13.4, LangGraph 1.2.9, LangChain Core 1.4.9, pytest 9.0.2

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

## LangGraph workflow controls added in 0.6.0 and result critic added in 0.7.0

1. `LangChainStructuredPlanModel` binds model output directly to the strict `AnalysisPlan` schema.
2. The model has no SQL tool, and `AgentWorkflowRequest` also rejects a supplied `sql` property.
3. JSON-serializable `AHSAgentState` supports durable LangGraph checkpointing.
4. Conditional edges implement plan proposal, deterministic validation, bounded repair, approval, compilation, execution, result checks, and terminal outcomes.
5. `max_plan_attempts` bounds both model/schema failures and validation-repair loops; a graph recursion limit provides a second guard.
6. `interrupt()` provides explicit human approval with approve, reject, and revise decisions.
7. `MockAnalysisPlanModel` provides network-free deterministic unit tests.
8. `AnalysisPlanService.compile_validated()` and `.execute_validated()` preserve the validated plan boundary without model involvement.
9. `AnalysisResultChecker` verifies fingerprints, SQL, parameters, datasets, join contracts, aliases, and the non-inferential statistical boundary.
10. Structured `WorkflowEvent` records are appended at every node and also emitted through Python logging.
11. The planning context keeps `CONTROL` as the sole required PUF project relationship key, omits unresolved `PROJECTNO` from planner-visible PUF fields, and requires project preaggregation to `CONTROL`.

## Exact verification commands

The following commands were executed from the reconstructed active Drive repository at `/mnt/data/ahs_repo`:

```bash
PYTHONPATH=src python -m compileall -q src tests
PYTHONPATH=src python -m pytest -q tests/test_agent_workflow.py
PYTHONPATH=src python -m pytest -q
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
ahs-copilot=0.7.0 (source tree)
duckdb=1.5.4
pydantic=2.13.4
langgraph=1.2.9
langchain-core=1.4.9
pytest=9.0.2
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

## LangGraph workflow and result-critic test result

```text
................                                                         [100%]
16 passed
```

The workflow tests cover successful execution, deterministic validation repair, model-output schema failure and retry exhaustion, interrupt/resume approval, rejection before compilation, human revision, the projects `CONTROL` invariant, result-tamper detection, SQL-field rejection, explicit binding of the LangChain model to `AnalysisPlan` structured output, denominator and percentage checks, missing groups, unexpected nulls, mutually exclusive categories, reference-estimate discrepancies, deterministic re-execution, and retry-budget rejection.

## Full regression result

```text
................................................                         [100%]
48 passed
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


## Result-critic verification

The result critic is deterministic and non-mutating. Its public decision is limited to `approve`, `reject`, or `request_reexecution`. It validates denominator arithmetic, percentage range and formulas, group completeness and exclusivity, unexpected nulls, and approved reference estimates with explicit tolerances. Re-execution uses the same validated plan and deterministic execution service; no critic field can replace an estimate.

```text
PYTHONPATH=src pytest -q
................................................                         [100%]
48 passed

PYTHONPATH=src python -m compileall -q src tests
PASS
```
