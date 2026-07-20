# Final repository audit

**Repository:** `vikramdayal/ahs_copilot_demo`  
**Branch audited:** `chat_gpt_branch`  
**Audited head observed:** `81685ea99d3b976fd62825bf928e0589d1713975`  
**Declared release:** `0.10.0`

## Executive result

The repository had several issues that could prevent a clean installation or cause the packaged demo to contradict its governance claims. The replacement files in this bundle correct the installation blockers and add automated checks for them. A current full regression and Docker smoke run still must execute against the exact corrected commit before release certification.

## Corrected release blockers

### 1. Package-version inconsistency

`pyproject.toml` declared `0.10.0`, while `ahs_copilot.__version__` still returned `0.7.0`. The package initializer now reports `0.10.0`, and a regression test requires exact agreement.

### 2. Streamlit script import failure

The implementation file uses a package-relative import, but the startup scripts launched that implementation directly as a filesystem script. A new complete `src/ahs_copilot/ui/streamlit_app.py` wrapper imports the application through the installed package. Docker and native instructions now launch the wrapper.

### 3. Missing explicit import dependency

The workflow imports `TypedDict` from `typing_extensions`, but the package relied on another dependency to install it transitively. `typing-extensions` is now an explicit runtime dependency.

### 4. Synthetic PUF project-key contradiction

The synthetic projects fixture manufactured `PROJECTNO`, although the frozen PUF contract states that `CONTROL` is the only required relationship key and project row identity is unresolved. Both the fixture generator and tracked CSV now omit `PROJECTNO`. The generator also repairs an existing fixture whose header is stale.

### 5. Non-executable evaluation instructions

The README instructed users to score a one-record envelope example against the 50-case evaluation set. The scorer correctly rejects that mismatch. The README now uses a complete one-case refusal smoke set and response that exercise the CLI successfully.

### 6. Stale execution certification

The execution report presented a historical `0.7.0` 48-test result as though it were current. The replacement report labels that result as historical and leaves current certification unset until observed commands are recorded against the corrected commit.

### 7. Docker Desktop readiness omitted

The macOS path assumed that Compose implied a running Docker Engine. A new `scripts/docker-doctor.sh` checks the CLI, Compose, daemon, context readiness, and Compose configuration before build instructions proceed.

## Corrected path and packaging problems

- Docker launches the stable package-import wrapper.
- Configuration paths continue to resolve relative to their TOML file; Docker metadata paths remain valid from `/app/config`.
- The Dockerfile copies only required runtime paths rather than the whole repository.
- The image explicitly installs the requested package extras and runs `pip check`.
- Default Docker model extras are reduced to `ui`; external provider adapters are opt-in.
- Sample mode is forced to the no-network provider.
- Host ports bind to `127.0.0.1` rather than all interfaces.
- Production data remains mounted read-only.
- Streamlit development reload and file watching are disabled.
- The health endpoint override is restricted to loopback HTTP URLs.

## Corrected secret and security problems

- Direct secret values and corresponding `*_FILE` variables are mutually exclusive.
- Secret files must exist and be non-empty.
- Secret-file path variables are removed from the child environment after loading.
- OpenAI-compatible base URLs reject embedded credentials.
- Startup diagnostics expose only the endpoint origin, not path or query text.
- AWS key pairs must be configured together.
- `.gitignore` and `.dockerignore` exclude environment files, local secret directories, AWS profiles, private keys, local data, and DuckDB files.
- The image uses a stable non-root UID/GID, a read-only root filesystem, dropped capabilities, `no-new-privileges`, and a PID limit.
- Docker sample mode does not restart indefinitely after an expected startup failure.

## Added test and CI coverage

The replacement `tests/test_packaging.py` checks:

- package-version consistency;
- explicit import dependencies;
- fixture-mode contracts;
- stable Streamlit entry point;
- localhost-only Compose ports;
- no-network sample provider;
- non-root image posture;
- development-mode Streamlit settings;
- blank tracked credential values;
- provider alias and validation behavior;
- URL credential rejection and redaction;
- absence of synthetic `PROJECTNO`;
- stale fixture repair;
- executable evaluation smoke artifacts;
- historical-versus-current execution-report wording;
- Python compilation of startup modules.

The new GitHub Actions workflow runs Python 3.11 and 3.13 tests, dependency checks, compilation, shell syntax, evaluation CLI smoke, Docker build, sample startup, health polling, logs, and cleanup.

## Incomplete placeholders and residual product gaps

The following are not clean-install blockers, but remain material before an enterprise release:

1. **Full 50-case workflow adapter:** the evaluator exists, but the repository still lacks a certified adapter that generates one real `CandidateResponse` for every evaluation case.
2. **Numeric oracles:** most 50-case questions still lack independently certified numeric reference values.
3. **Provider abstraction integration:** startup provider validation is centralized, but the Streamlit implementation still constructs provider SDK objects internally and requires the user to select the matching provider in the sidebar.
4. **Trust-disclosure wording:** the current no-assumption message is semantically correct but does not use the frozen exact phrase `No assumptions recorded`.
5. **Direct UI test coverage:** helper functions are tested, but the full Streamlit `main()` path and approval interactions are not browser-tested.
6. **External provider integration tests:** OpenAI, Anthropic, and Bedrock configuration validation is tested without live network calls; provider SDK construction and structured-output behavior require controlled integration tests.
7. **Production-scale performance:** national CSV memory/spill behavior has not been certified in the current execution report.
8. **Software license:** no explicit repository license is present. Redistribution rights remain unspecified until the owner selects a license.
9. **Current release evidence:** no current CI result or observed full-suite count was attached to the audited commit.

## Files supplied as complete replacements

- `.dockerignore`
- `.env.example`
- `.gitignore`
- `.github/workflows/ci.yml`
- `.streamlit/config.toml`
- `.streamlit/secrets.toml.example`
- `Dockerfile`
- `README.md`
- `docker-compose.yml`
- `docker-compose.aws.yml`
- `pyproject.toml`
- `scripts/docker-doctor.sh`
- `scripts/healthcheck.py`
- `scripts/preflight.py`
- `scripts/start.sh`
- `src/ahs_copilot/__init__.py`
- `src/ahs_copilot/model_providers.py`
- `src/ahs_copilot/query_engine/fixture.py`
- `src/ahs_copilot/ui/streamlit_app.py`
- `tests/fixtures/synthetic/projects.csv`
- `tests/test_packaging.py`
- `evaluation/example_refusal_eval.json`
- `evaluation/example_refusal_response.json`
- `docs/execution_report.md`
- `docs/final_repository_audit.md`

## Release gate

Do not describe the corrected repository as certified until the exact corrected commit passes:

```bash
python -m pip install -e '.[dev,ui]'
python -m pip check
python -m compileall -q src tests scripts
bash -n scripts/start.sh scripts/docker-doctor.sh
python -m pytest -q
ahs-eval \
  --evaluation-set evaluation/example_refusal_eval.json \
  --responses evaluation/example_refusal_response.json \
  --output sample_outputs/example_refusal_report.json
docker compose config --quiet
docker compose --profile sample up --build -d
curl --fail --silent http://127.0.0.1:8501/_stcore/health
```

Record actual output in `docs/execution_report.md`; do not infer it from prior runs.
