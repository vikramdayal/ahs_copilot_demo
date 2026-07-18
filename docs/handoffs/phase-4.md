# Phase 4 handoff: structured AnalysisPlan validation

## Implemented

- Strict high-level AnalysisPlan contract and JSON schema.
- Approved semantic catalog for PUF variables, universes, final weight, missing codes, and deterministic recodes.
- Validation issue codes with paths and messages.
- Validation-first service that normalizes plans into the descriptive survey request only after every check passes.
- Weighted and deterministic unit-weight execution modes.
- Missing-code eligibility integrated into deterministic SQL and diagnostics.
- Critical checkpoint tests and a clean-environment execution report.

## Execution boundary

The LLM may propose an AnalysisPlan, but it cannot submit SQL. The deterministic validator owns dataset resolution, universe expansion, variable access, required-variable closure, join policy, weight selection, type compatibility, missing-code rules, and translation to the survey request.

## Statistical boundary

The output remains descriptive. Replicate weights and an approved AHS variance method are not implemented. No standard errors or inferential claims are valid.

## Next extension

Add a semantic-plan authoring agent that emits this contract, plus a human approval UI that displays the resolved universe, required variables, numerator, denominator, weight, recodes, and generated SQL before execution.
