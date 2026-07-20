# Day 6 red-team guardrails

This layer supplements the typed `AnalysisPlan`, semantic catalog validation, governed SQL compiler, and result critic. It is deterministic and runs before planner invocation or SQL compilation.

## Threats and mitigations

| Threat | Mitigation | Fail-closed signal |
|---|---|---|
| Fabricated variables | Semantic and physical-schema validation | `UNKNOWN_VARIABLE` or `VARIABLE_NOT_IN_PHYSICAL_SCHEMA` |
| State-level PUF claims | Request preflight plus plan-question guard | `STATE_LEVEL_PUF_UNSUPPORTED` |
| Unweighted estimates presented as research estimates | Unweighted mode requires explicit wording in the original request | `UNWEIGHTED_NOT_EXPLICITLY_REQUESTED` |
| Percentage denominator mistakes | Every explicit denominator filter must also be included in the numerator | `PERCENTAGE_DENOMINATOR_NOT_INCLUDED_IN_NUMERATOR` |
| PUF/IUF confusion | PUF preflight refuses IUF/restricted-use requests; semantic validation rejects IUF-only fields | `IUF_REQUEST_IN_PUF_MODE` or `PUF_INACCESSIBLE_FIELD` |
| Privacy-sensitive interpretation | Refuse household identification, raw microdata disclosure, and individual risk prediction | `PRIVACY_SENSITIVE_INTERPRETATION` |
| Causal claims | Require a descriptive comparison/association reframe before planning | `CAUSAL_CLAIM_UNSUPPORTED` |
| Demographic stereotyping | Refuse stigmatizing claims about protected groups | `DEMOGRAPHIC_STEREOTYPING` |
| Prompt injection in metadata/context | Unicode/control normalization, instruction-pattern withholding, bounded recursive serialization, explicit system-prompt isolation | `DIRECT_PROMPT_INJECTION` for direct requests; metadata is replaced with `[WITHHELD_POSSIBLE_PROMPT_INJECTION]` |
| Arbitrary SQL | Refuse SQL-shaped requests before planner invocation; schemas still forbid an `sql` field | `ARBITRARY_SQL_REQUEST` |

## Workflow behavior

`AHSAgentWorkflow.invoke()` evaluates the request before calling the planner. A refused or clarification-required request returns a final `AgentWorkflowResult` with:

- `status="rejected"`;
- zero planner attempts;
- no compiled SQL or execution output;
- a typed `request_guard` decision and findings;
- `REQUEST_REFUSED` or `REQUEST_CLARIFICATION_REQUIRED` in the workflow error.

Allowed requests carry the guard decision into the audit result. User context and semantic metadata are sanitized before they enter any model prompt.

## Statistical boundary

These controls do not convert the system into an inferential or causal estimator. Results remain aggregate, descriptive, survey-weighted outputs. Standard errors, confidence intervals, p-values, causal effects, and household-level predictions remain unavailable.
