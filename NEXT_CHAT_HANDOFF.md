# AHS 2023 Research Copilot — Next Chat Checkpoint

**Checkpoint date:** July 20, 2026  
**Completed phase:** Day 6 — Evaluation, red teaming, and correction  
**Authoritative repository:** `vikramdayal/ahs_copilot_demo`  
**Authoritative branch:** `chat_gpt_branch`  
**Declared package version:** `0.10.0`

## Start here

Use GitHub repository `vikramdayal/ahs_copilot_demo`, branch `chat_gpt_branch`, as the sole authoritative source for the next chat. Do not use `main` unless the user explicitly changes the operating branch.

Before editing:

```bash
git fetch origin
git switch chat_gpt_branch
git pull --ff-only origin chat_gpt_branch
git status --short
python -m pip install -e '.[dev]'
```

Then establish a fresh baseline:

```bash
python -m compileall -q src tests
python -m pytest -q
```

Do not rely on the older `docs/execution_report.md` statement that 48 tests passed. That report predates the Day 6 evaluation and red-team additions and is now stale until the full suite is rerun.

## Durable project invariants

These decisions remain frozen:

1. The system accepts typed `AnalysisPlan` objects, not model-generated SQL.
2. Unknown fields are rejected by strict Pydantic schemas.
3. Variables must exist in both the approved semantic catalog and the inspected physical schema.
4. PUF/IUF access restrictions are enforced before SQL compilation.
5. Results are descriptive only.
6. Replicate-weight variance estimation is not implemented.
7. No valid standard errors, confidence intervals, p-values, significance claims, or causal effects may be returned.
8. Mortgage and project child rows must be preaggregated before household weighting.
9. `CONTROL` is the only required PUF projects relationship key.
10. `PROJECTNO` remains optional and unresolved and must not be invented.
11. Projects must be preaggregated to one row per `CONTROL` before household joins.
12. Direct mortgage-to-project joins are prohibited.
13. The interactive workflow retains an explicit plan-approval gate.
14. The result critic is deterministic and non-mutating.
15. Missing or uncertified mappings must fail closed rather than be guessed.

## Day 5 baseline that must be preserved

The repository already contains the governed Streamlit product workflow, including:

- Suggested AHS research questions.
- Natural-language input.
- Visible plan approval, revision, and rejection.
- Metric cards, charts, and result tables.
- Methodology, source-variable, filter, generated-SQL, and agent-trace disclosures.
- Warning banners for fixture, suppression, metadata, and statistical limitations.
- CSV and JSON audit downloads.
- Governed comparison workspace.
- Deterministic `Why should I trust this?` disclosure.
- No-network deterministic demo mode.

The trust disclosure must continue to report:

- Selected universe and resolved filters.
- Denominator role, formula, and observed values.
- Selected and resolved survey weight.
- Weight eligibility rule.
- Derived recodes, formulas, filters, and missing-value exclusions.
- Validation and critic checks.
- Reference comparison status.
- Explicitly recorded assumptions, or the precise statement `No assumptions recorded`.
- Plan, request, and SQL fingerprints.

## Day 6 deliverables now on `chat_gpt_branch`

### 1. Fifty-question evaluation set

The evaluation set covers:

- Affordability.
- Housing quality.
- Tenure.
- Demographics.
- Migration.
- Neighborhood satisfaction.
- Mortgage characteristics.
- Home improvements.
- Housing insecurity.

It contains valid, ambiguous, unsupported, and deliberately misleading questions. Each case records expected datasets, variables, universe, weight, grouping, expected disposition, and acceptance criteria.

Primary file:

```text
evaluation/ahs_eval_50.json
```

### 2. Automated evaluation harness

The repository includes the `ahs-eval` CLI:

```bash
ahs-eval   --evaluation-set evaluation/ahs_eval_50.json   --responses sample_outputs/evaluation_responses.json   --output sample_outputs/evaluation_report.json
```

The console entry point is registered in `pyproject.toml`.

Deterministic scoring covers:

| Criterion | Points |
|---|---:|
| Dataset selection | 10 |
| Variable selection and required grouping closure | 10 |
| Universe correctness | 10 |
| Weight correctness | 10 |
| Filter correctness | 10 |
| `AnalysisPlan` schema validity | 15 |
| SQL execution success | 10 |
| Numeric agreement | 15 |
| Appropriate refusal or clarification | 10 |

A deterministic score of 90% is required. Disposition, schema validity, execution success, and numeric agreement are hard gates when applicable.

Narrative quality is reported separately:

| Criterion | Points |
|---|---:|
| Citation completeness | 60 |
| Response quality and boundary language | 40 |

Narrative quality must never rescue deterministic failure.

Relevant files include:

```text
src/ahs_copilot/evaluation/
docs/evaluation_harness.md
evaluation/ahs_eval_50.json
evaluation/sample_candidate_responses.json
tests/test_evaluation.py
```

### 3. Red-team request guard and plan guardrails

The deterministic pre-planning guard now covers:

| Threat | Fail-closed behavior |
|---|---|
| Fabricated variables | Reject through semantic/physical schema validation |
| Invalid state-level PUF claims | `STATE_LEVEL_PUF_UNSUPPORTED` |
| Unweighted research statistics | Require explicit unweighted/sample wording |
| Percentage denominator mistakes | Require denominator eligibility filters in numerator |
| PUF/IUF confusion | `IUF_REQUEST_IN_PUF_MODE` or `PUF_INACCESSIBLE_FIELD` |
| Privacy-sensitive interpretation | Refuse identification, raw microdata, or household risk prediction |
| Causal claims | Require descriptive-association reframe |
| Demographic stereotyping | Refuse stigmatizing claims |
| Prompt injection in metadata/context | Normalize and replace suspicious instructions |
| Arbitrary SQL execution | Refuse before planner invocation |

Prompt-injection text is replaced with:

```text
[WITHHELD_POSSIBLE_PROMPT_INJECTION]
```

Relevant files include:

```text
src/ahs_copilot/agent_workflow/request_guard.py
src/ahs_copilot/agent_workflow/prompt_security.py
src/ahs_copilot/analysis_plan/guardrails.py
tests/test_red_team_guardrails.py
evaluation/red_team_cases.json
docs/red_team_guardrails.md
```

For refused or clarification-required requests, the workflow should return:

- `status="rejected"`.
- Zero planner attempts.
- No compiled SQL.
- No execution result.
- A typed request-guard decision.
- `REQUEST_REFUSED` or `REQUEST_CLARIFICATION_REQUIRED`.

## Current known issues and cautions

### Full regression status is not yet certified

The older execution report documents a 48-test baseline from July 19, 2026. Day 6 added new tests and modified existing validation behavior. A fresh full regression run must be completed and documented.

Run:

```bash
python -m compileall -q src tests
python -m pytest -q
python -m pytest -q tests/test_evaluation.py
python -m pytest -q tests/test_red_team_guardrails.py
```

Update `docs/execution_report.md` only with actual observed output.

### Sample candidate responses are not gold outputs

`evaluation/sample_candidate_responses.json` is a response-envelope example, not a complete passing 50-case evaluation run. Do not treat empty plans or placeholder result records as certified outputs.

The next implementation should add a workflow adapter that:

1. Runs each evaluation question through the request guard and workflow.
2. Captures the typed plan, validation result, SQL execution status, result records, narrative, citations, and refusal reason.
3. Produces exactly one `CandidateResponse` per evaluation case.
4. Writes a complete response file consumable by `ahs-eval`.
5. Fails if any evaluation case is missing or duplicated.

### Numeric gold results remain incomplete

The evaluation schema supports keyed numeric oracles with explicit absolute and relative tolerances, but most of the 50 questions do not yet have independently certified expected numbers.

Do not manufacture expected estimates from the same execution being evaluated. Numeric gold values should come from one of:

- Independently authored deterministic fixture calculations.
- Approved AHS Table Creator verification values.
- A separately reviewed reference implementation.

### Citation completeness needs production integration

The harness can score citation completeness, but the application/workflow must emit structured citations consistently. Citations should identify the relevant:

- Variable definition.
- Universe definition.
- Weight definition.
- Recode or formula.
- Geography mapping.
- Source table or verification estimate.

### Request guard is pattern-based

The preflight guard is deterministic and intentionally conservative, but regex-based language detection can have false positives and false negatives. Preserve semantic and schema validation as the authoritative second layer. Never allow the request guard to become the only protection.

### Geography certification remains fail closed

For metro comparisons, use only certified `OMB13CBSA` code-to-label mappings. The known target mappings are:

- New York: `35620`.
- Miami: `33100`.

Execution must still fail closed if those mappings are absent from the approved executable catalog. Do not hard-code labels only in prompt logic or UI code.

## Recommended next phase

### Priority 1 — certify the Day 6 implementation

1. Run the full regression suite on `chat_gpt_branch`.
2. Fix all failures without weakening fail-closed controls.
3. Update `docs/execution_report.md` with:
   - Date.
   - Branch and commit SHA.
   - Python and dependency versions.
   - Exact commands.
   - Complete test counts.
   - Evaluation and red-team test counts.
4. Add or verify CI for:
   - `compileall`.
   - Full `pytest`.
   - Evaluation tests.
   - Red-team tests.

### Priority 2 — build the evaluation workflow adapter

Implement a batch runner that transforms actual copilot executions into the harness `CandidateResponse` envelope.

Suggested CLI:

```bash
ahs-eval-run   --config config/ahs_engine.toml   --evaluation-set evaluation/ahs_eval_50.json   --responses-out sample_outputs/evaluation_responses.json   --report-out sample_outputs/evaluation_report.json   --provider no-network
```

Requirements:

- Stable case ordering.
- Per-case timeout/error capture.
- No background or asynchronous execution assumption.
- Deterministic no-network mode.
- Complete audit trail.
- Resumable output without silently skipping failed cases.
- Explicit distinction among completed, clarification, refusal, and error.
- No raw SQL input path.

### Priority 3 — populate certified numeric oracles

Start with deterministic synthetic-fixture cases whose results can be calculated independently. Add explicit keyed records and tolerances to the evaluation set.

Prioritize:

1. Weighted occupied-unit count.
2. Owner and renter weighted counts.
3. Severe cost-burden percentage.
4. Mean household income with missing codes.
5. Housing adequacy by tenure.
6. Mortgage household counts after `CONTROL` preaggregation.
7. Any-project household percentage after project preaggregation.

### Priority 4 — test narrative and citation production

Add regression tests ensuring completed answers contain:

- Descriptive-only wording.
- No significance or causal language.
- Explicit universe.
- Explicit denominator.
- Explicit weight.
- Missing-value handling.
- Required structured citations.
- Trust-disclosure fingerprints.

Refusals and clarifications should explain the blocking reason without inventing variables, codes, or access rights.

## Suggested opening prompt for the next chat

> Use GitHub repository `vikramdayal/ahs_copilot_demo`, branch `chat_gpt_branch`, and treat `NEXT_CHAT_HANDOFF.md` as authoritative. First run and document a clean full regression baseline for the Day 6 evaluation and red-team changes. Fix any failures without weakening fail-closed behavior. Then implement the batch evaluation workflow adapter that generates complete `CandidateResponse` records for all 50 cases and runs `ahs-eval`.

## Completion criteria for the next phase

The next phase is complete only when:

1. `python -m compileall -q src tests` passes.
2. The full pytest suite passes.
3. CI runs the full suite on the authoritative branch.
4. All 50 evaluation cases produce exactly one response record.
5. The evaluation harness produces a complete report.
6. Red-team requests do not invoke the planner or SQL compiler when refusal is required.
7. Clarification cases do not execute until ambiguity is resolved.
8. Valid cases use approved datasets, variables, universes, filters, weights, joins, and recodes.
9. Numeric-oracle cases pass independently reviewed tolerances.
10. Narrative scores remain separate from deterministic correctness.
11. The execution report is updated with actual Day 6 results.
12. No stale claim of “48 tests passed” is presented as the current regression result.

## GitHub integration note

At checkpoint creation, the connected GitHub integration could read `chat_gpt_branch` but returned `403 Resource not accessible by integration` for file creation. Therefore this checkpoint may need to be added manually or through a local authenticated Git workflow.

Recommended local command after downloading this file:

```bash
cp NEXT_CHAT_HANDOFF.md /path/to/ahs_copilot_demo/NEXT_CHAT_HANDOFF.md
cd /path/to/ahs_copilot_demo
git switch chat_gpt_branch
git add NEXT_CHAT_HANDOFF.md
git commit -m "Add Day 6 next-chat handover checkpoint"
git push origin chat_gpt_branch
```
