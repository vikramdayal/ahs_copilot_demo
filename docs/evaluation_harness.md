# Automated evaluation harness

The evaluation harness scores each normalized agent response against one `EvaluationCase`. It deliberately separates **deterministic correctness** from **narrative quality**.

## Deterministic score

The deterministic section covers:

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

A deterministic score of 90% is required. In addition, the following are hard gates:

- the response disposition must match the expected execute, clarify, or refuse behavior;
- a completed response must have a schema-valid `AnalysisPlan`;
- a completed response must have successful deterministic SQL execution;
- when a numeric oracle is supplied, numeric agreement must pass.

A correct refusal or clarification makes plan and execution criteria not applicable. The harness therefore does not penalize a fail-closed response for correctly declining to create a plan.

## Narrative score

Narrative quality is reported separately and cannot rescue deterministic failure:

| Criterion | Points |
|---|---:|
| Citation completeness | 60 |
| Response quality and boundary language | 40 |

The current response-quality checks are deterministic hygiene checks: nonempty narrative, no unsupported causal or significance language, no raw-SQL adoption, explicit explanations for refusal/clarification, and resistance to false-premise phrasing in misleading questions. A future model-based rubric may be added as an optional secondary reviewer, but it must not alter deterministic scores.

## Numeric oracle

Cases may add `expected_numeric`:

```json
{
  "records": [{"tenure": "renter", "estimate": 25.0}],
  "key_fields": ["tenure"],
  "value_fields": ["estimate"],
  "absolute_tolerance": 0.01,
  "relative_tolerance": 0.000001
}
```

Agreement is evaluated by key and value field. A mismatch on any required numeric value fails the numeric hard gate.

## Filter oracle

Cases may add exact typed filters under `expected_filters`. When an evaluation case does not contain literal filter values, filter semantics are delegated to the governed `AnalysisPlanService` validator rather than guessed by the scorer. This prevents the harness from inventing AHS code values.

## Candidate response envelope

```json
{
  "case_id": "AHS-EVAL-001",
  "status": "completed",
  "plan": {},
  "plan_schema_valid": true,
  "plan_validation_errors": [],
  "sql_execution_succeeded": true,
  "execution_error": null,
  "result_records": [{"estimate": 25.0}],
  "narrative": "...",
  "citations": [
    {"topic": "variable definition", "source": "AHS metadata", "locator": "TOTHCPCT"}
  ],
  "refusal_or_clarification_reason": null
}
```

The workflow adapter should populate this envelope from the validated plan, execution result, narrative response, and trust-disclosure evidence. Do not infer successful validation or execution from prose.

## CLI

```bash
ahs-eval \
  --evaluation-set evaluation/ahs_eval_50.json \
  --responses sample_outputs/evaluation_responses.json \
  --output sample_outputs/evaluation_report.json
```

The report contains per-criterion details, separate normalized section scores, hard-gate failures, and aggregate pass/fail counts.
