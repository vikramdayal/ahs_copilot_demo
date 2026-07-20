# AHS 2023 Research Copilot Streamlit interface

## Purpose

The Streamlit interface exposes the governed v0.7.0 workflow as a product demonstration without weakening the deterministic execution boundary. The planner may propose only a typed `AnalysisPlan`. The application displays the validated plan and pauses for explicit researcher approval before deterministic SQL compilation and execution.

## Features

- Three frozen suggested research questions.
- Natural-language research input.
- Visible plan approval, revision, and rejection controls.
- Metric cards, responsive bar charts, and result tables.
- Expandable methodology, source variables, filters, generated SQL, and agent trace.
- A structured **Why should I trust this?** disclosure panel covering scope, denominator, weight, transformations, validation evidence, reference comparisons, assumptions, and fingerprints.
- Warning banners for synthetic fixtures, suppression, unresolved metadata, and the descriptive-only statistical boundary.
- CSV result download and full JSON audit download.
- Local CSV execution through `config/ahs_engine.toml` or `config/ahs_engine.example.toml`.
- No-network deterministic demo planning plus optional OpenAI, Anthropic, and AWS Bedrock structured-output adapters.

## Install

From the repository root:

```bash
python -m pip install -e '.[ui,dev]'
```

Add one model integration only when needed:

```bash
python -m pip install -e '.[ui,model-openai]'
python -m pip install -e '.[ui,model-anthropic]'
python -m pip install -e '.[ui,model-bedrock]'
```

Model credentials are resolved from environment variables, `.streamlit/secrets.toml`, or password fields held in the current Streamlit session. The application does not write credentials to disk.

## Configure local AHS CSV files

Copy the example configuration and set absolute CSV paths:

```bash
cp config/ahs_engine.example.toml config/ahs_engine.toml
export AHS_HOUSEHOLD_CSV="$HOME/Data/AHS-2023/household.csv"
export AHS_MORTGAGE_CSV="$HOME/Data/AHS-2023/mortgage.csv"
export AHS_PROJECTS_CSV="$HOME/Data/AHS-2023/projects.csv"
```

The existing fixture mode remains available. Set `fixture.mode = "disabled"` for production-data-only runs.

## Run

```bash
streamlit run streamlit_app.py
```

The sidebar provides a **Test data** action that inspects the configured schemas without running a research analysis.

## No-network behavior

The no-network lane is intentionally narrow:

- The New York/Miami question is blocked until the approved semantic catalog contains exact code-to-label mappings for the requested geographies. The interface does not infer that a CBSA is a city.
- The housing-quality journey produces weighted counts by raw `TENURE`, `BLD`, and `ADEQUACY` codes. It does not invent category labels.
- The housing-insecurity journey is reframed as a descriptive distribution by `TENURE` and `HIWORRY`, respecting the two-dimension governance cap. It does not claim association, prediction, significance, or causality.
- Basic occupied-unit counts and high-cost-burden percentages by tenure are also supported.

External model providers can propose broader typed plans, but the deterministic validator remains authoritative and fails closed on missing or incompatible metadata.

## Statistical and governance boundary

Every completed result must retain its universe, weight, weighted and unweighted denominators, source files, missing-value exclusions, suppression status, generated SQL, and limitations. The current engine does not implement replicate-weight variance estimation, standard errors, confidence intervals, p-values, statistical significance, causal effects, or predictive effects.

Projects retain the durable relationship invariant: `CONTROL` is the only required PUF relationship key, project row identity is optional and unresolved, and project data must be preaggregated to one row per `CONTROL` before any household join.


## Comparison workspace

After a baseline analysis completes, the interface exposes a governed comparison workspace. The researcher can change approved geography, tenure, and structure-type selections without rewriting or replanning the research question. Year-built controls appear only when `YRBUILT` is present in the approved executable metadata catalog; otherwise the control is visibly disabled and the application fails closed.

The workspace clones the already validated `AnalysisPlan` and changes only the managed top-level filters for `OMB13CBSA`, `TENURE`, `BLD`, or `YRBUILT`. The original question, dataset, measure, universe, numerator, denominator, weight, grouping dimensions, joins, recodes, validation checks, and output contract remain unchanged. A structural contract fingerprint is checked before execution.

Each modified plan is deterministically revalidated, compiled, executed, checked, and reviewed by the result critic. The planner model is not called again. Identical comparison selections use a stable cache key and reuse the completed comparison result. The workspace displays the filter mutation audit, baseline and comparison fingerprints, generated SQL, result deltas, validation checks, critic decision, trace, and dedicated CSV/JSON downloads.


## Why should I trust this? disclosure panel

Every completed result includes a deterministic disclosure assembled from the validated `AnalysisPlan`, compiled formulas, execution metadata, result-integrity checks, and the non-mutating result critic. The panel shows:

- the selected universe and its resolved universe filters;
- the denominator role, filters, deterministic denominator formula, and observed weighted/unweighted denominator values;
- the selected and resolved survey-weight column plus its eligibility rule;
- recorded derived recodes, filters, formulas, missing-value exclusions, and arithmetic rules;
- plan-validation messages, deterministic integrity checks, critic checks, the critic decision, and failed check identifiers;
- the approved reference-comparison contract and whether reference checks passed, failed, or were not performed;
- explicitly recorded assumptions, if any; otherwise the precise statement **No assumptions recorded**, not an unsupported claim that no assumptions existed; and
- plan, request, and SQL fingerprints for provenance.

The disclosure builder does not infer missing facts. Unavailable evidence is labeled unavailable, and unresolved metadata remains blocked under the existing fail-closed governance policy.
