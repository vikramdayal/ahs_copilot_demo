# AHS Research Copilot comparison workspace v0.9.0

Apply from the root of the refreshed `ahs_copilot_demo` repository:

```bash
unzip -o ahs_copilot_comparison_workspace_v0_9_0.zip
python -m pip install -e '.[ui,dev]'
PYTHONPATH=src python -m compileall -q src tests
PYTHONPATH=src python -m pytest -q
streamlit run streamlit_app.py
```

## Behavior

- Reuses the completed, validated baseline `AnalysisPlan`.
- Keeps the original natural-language question unchanged.
- Mutates only approved top-level filters for:
  - `OMB13CBSA` geography codes
  - `TENURE`
  - `BLD` structure types
  - `YRBUILT` ranges, only when the executable catalog approves `YRBUILT`
- Revalidates, recompiles, executes, runs integrity checks, and invokes the deterministic result critic.
- Does not call the planning model again.
- Caches identical comparison selections by a stable fingerprint.
- Shows baseline/comparison results, deltas, fingerprints, SQL, trace, and downloads.
- Fails closed for unavailable metadata. In the current executable catalog, year-built is visibly disabled because `YRBUILT` is not approved.

## Verification

- Python compilation: passed
- Full reconstructed repository regression suite: 58 passed
- Streamlit AppTest initial render: no exceptions
- Explicit comparison replay:
  - changed only `OMB13CBSA`, `TENURE`, and `BLD`
  - preserved the question and statistical contract
  - generated a new validated plan fingerprint
  - completed SQL execution and result checks
  - result critic approved
