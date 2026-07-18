# Phase 3 handoff: descriptive survey estimation

## Implemented

- Typed survey-estimate request and result contracts.
- Weighted counts, percentages, means, and explicit denominators.
- Deterministic fixed-point component arithmetic and decimal rounding.
- Configurable suppression flags and nulling behavior.
- Grouped reference and all-pairs descriptive comparisons.
- Certified household-grain use of preaggregated mortgage/project features.
- SQL, bound parameters, formulas, fingerprints, data provenance, and execution metadata.
- CLI, JSON schemas, examples, synthetic outputs, and tests.

## Statistical boundary

This is a descriptive estimator. Replicate weights, variance methods, standard errors, confidence intervals, p-values, and significance claims are not implemented. All result contracts explicitly encode this boundary.

## Next approved extension

Add replicate-weight metadata and one explicitly approved variance method only after the AHS weight contracts and expected verification estimates are available. Variance execution should be a separate service and result type rather than silently extending the descriptive formulas.
