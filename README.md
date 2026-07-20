# AHS 2023 Research Copilot

A governed local research application for descriptive, survey-weighted analysis of the 2023 American Housing Survey Public Use File (PUF). The application combines a Streamlit interface, typed `AnalysisPlan` contracts, deterministic validation, a governed DuckDB execution engine, survey-weighted estimators, result criticism, and an auditable human-approval workflow.

The Docker packaging supports two deliberately separate runtime modes:

- **Sample mode** uses only deterministic synthetic fixtures and makes no model-network calls by default.
- **Production-data mode** mounts local AHS CSV files read-only and fails closed if any required file or approved schema element is unavailable.

## Statistical and governance boundary

The application produces descriptive estimates only. Replicate-weight variance estimation is not implemented, so the application must not return standard errors, confidence intervals, p-values, significance claims, causal effects, household-level predictions, or re-identification output.

Additional invariants:

- The planner may propose only typed `AnalysisPlan` objects; it cannot submit arbitrary SQL.
- Unknown fields are rejected by strict Pydantic schemas.
- Variables must exist in both the approved semantic catalog and the inspected physical schema.
- PUF/IUF access restrictions are enforced before SQL compilation.
- Mortgage and project child rows are preaggregated before household weighting.
- `CONTROL` is the only required PUF projects relationship key.
- `PROJECTNO` is optional and unresolved and is never invented.
- Direct mortgage-to-project joins are prohibited.
- Interactive execution retains an explicit plan-approval gate.
- Missing or uncertified mappings fail closed rather than being guessed.

## Architecture

```text
Browser
  -> Streamlit UI
     -> request guard
     -> model-provider adapter or deterministic demo planner
     -> typed AnalysisPlan
     -> deterministic validation
     -> human approval
     -> governed SQL compiler
     -> DuckDB CSV scans
     -> survey estimator
     -> deterministic result critic
     -> result, disclosures, generated SQL, and audit artifacts
```

The public request and plan contracts contain no raw-SQL field. DuckDB scans source CSVs lazily and may spill to the configured temporary directory; Python does not load the full national files into pandas.

## Repository layout

```text
config/                         Engine and Docker configuration templates
metadata/                       Approved source, semantic, and execution catalogs
src/ahs_copilot/                Application package
src/ahs_copilot/ui/app.py       Streamlit application
scripts/start.sh                Container entrypoint and secret-file loader
scripts/preflight.py            Fail-closed startup validation
scripts/healthcheck.py          Streamlit container health probe
tests/fixtures/synthetic/       Deterministic sample datasets
Dockerfile                      Non-root application image
docker-compose.yml              Sample and production Compose profiles
.env.example                    Non-secret runtime variable template
```

## Prerequisites

For Docker execution:

- Docker Engine or Docker Desktop
- Docker Compose v2.24 or newer
- At least 4 GB of available memory for production-sized work; larger CSVs may require more

For native execution:

- Python 3.11 or newer
- A virtual environment

## Quick start: deterministic sample mode

Sample mode is the recommended first run. It copies the tracked synthetic fixtures into temporary container storage, forces `fixture.mode = "required"`, and defaults to the no-network planner.

```bash
cp .env.example .env
docker compose --profile sample up --build
```

Open:

```text
http://localhost:8501
```

Stop the application:

```bash
docker compose --profile sample down
```

Run in the background and inspect health:

```bash
docker compose --profile sample up --build -d
docker compose --profile sample ps
docker compose --profile sample logs -f ahs-sample
```

A healthy container reports `healthy`. The probe calls Streamlit's loopback-only `/_stcore/health` endpoint.

## Production-data mode

Production mode forces `fixture.mode = "disabled"`. It will not substitute synthetic files when a CSV is missing, unreadable, or inconsistent with the approved executable catalog.

### 1. Prepare the data directory

By default, Compose mounts `./data` at `/data/ahs` read-only. Place the three PUF CSVs there:

```text
data/
  household.csv
  mortgage.csv
  projects.csv
```

The projects file requires `CONTROL`; `PROJECTNO` is not a required PUF relationship key.

A different host directory can be selected in `.env`:

```dotenv
AHS_DATA_DIR=/absolute/path/to/AHS-2023
```

The container-side paths can also be changed:

```dotenv
AHS_HOUSEHOLD_CSV=/data/ahs/household.csv
AHS_MORTGAGE_CSV=/data/ahs/mortgage.csv
AHS_PROJECTS_CSV=/data/ahs/projects.csv
```

These must be paths visible inside the container, not host-only paths.

### 2. Start the production profile

```bash
docker compose --profile production up --build
```

The entrypoint performs a blocking preflight before Streamlit starts. It validates:

- production mode uses `fixture.mode = "disabled"`;
- the selected model-provider contract is complete;
- all configured datasets resolve;
- physical schemas can be inspected;
- no synthetic dataset was selected.

If any check fails, the container exits and prints a non-secret diagnostic.

### 3. Resource tuning

The production template defaults to a 4 GB DuckDB memory limit. Override it in `.env`:

```dotenv
AHS_DUCKDB_MEMORY_LIMIT=8GB
```

DuckDB temporary files are written only to the container's `/tmp` tmpfs. Increase the `tmpfs` size in `docker-compose.yml` or use a controlled writable volume when production workloads require more spill capacity.

## Model-provider abstraction

The application supports four planner providers. Every external provider remains constrained to structured `AnalysisPlan` output and receives no arbitrary SQL tool.

| `AHS_MODEL_PROVIDER` | UI provider | Network | Credential mechanism |
|---|---|---:|---|
| `demo` | No-network certified demo | No | None |
| `openai` | OpenAI / OpenAI-compatible | Yes | `OPENAI_API_KEY` or secret file |
| `anthropic` | Anthropic | Yes | `ANTHROPIC_API_KEY` or secret file |
| `bedrock` | AWS Bedrock | Yes | Standard AWS credential chain |

The container validates provider configuration at startup through `ahs_copilot.model_providers`. Provider SDK imports remain lazy optional dependencies in the application.

### No-network demo

```dotenv
AHS_MODEL_PROVIDER=demo
AHS_MODEL_NAME=
```

This is the default and requires no API key.

### OpenAI or OpenAI-compatible gateway

```dotenv
AHS_MODEL_PROVIDER=openai
AHS_MODEL_NAME=<structured-output-capable-model>
OPENAI_API_KEY=<set-locally-only>
OPENAI_BASE_URL=
```

Set `OPENAI_BASE_URL` only for an approved OpenAI-compatible gateway.

### Anthropic

```dotenv
AHS_MODEL_PROVIDER=anthropic
AHS_MODEL_NAME=<anthropic-model-name>
ANTHROPIC_API_KEY=<set-locally-only>
```

### AWS Bedrock

```dotenv
AHS_MODEL_PROVIDER=bedrock
AHS_MODEL_NAME=<bedrock-model-id>
AWS_REGION=us-east-1
AWS_PROFILE=<optional-local-profile>
```

Bedrock uses the standard AWS credential chain. Prefer short-lived credentials, AWS SSO, or a mounted read-only credentials directory. Do not bake credentials into the image.

The Streamlit sidebar remains the final interactive provider control. Select the provider matching the startup configuration before running an externally planned question.

## Secrets and API-key handling

**Never commit `.env`, `secrets.toml`, API keys, AWS credentials, access tokens, or credential-bearing configuration files.** The repository tracks only `.env.example`, whose credential fields are blank.

Supported patterns:

### Local environment file

```bash
cp .env.example .env
chmod 600 .env
```

Populate `.env` locally. It is excluded by `.gitignore` and `.dockerignore`.

### Secret files

The entrypoint supports `*_FILE` variables and exports the secret only into the application process environment. Example Compose override:

```yaml
services:
  ahs-production:
    environment:
      OPENAI_API_KEY_FILE: /run/secrets/openai_api_key
    volumes:
      - ./local-secrets/openai_api_key:/run/secrets/openai_api_key:ro
```

The supported file variables are:

- `OPENAI_API_KEY_FILE`
- `ANTHROPIC_API_KEY_FILE`
- `AWS_ACCESS_KEY_ID_FILE`
- `AWS_SECRET_ACCESS_KEY_FILE`
- `AWS_SESSION_TOKEN_FILE`

Do not set both a direct variable and its corresponding `*_FILE` variable. Startup refuses ambiguous credential sources.

### Build-time safety

API keys are runtime-only. They must never be supplied as Docker build arguments, written into the Dockerfile, copied into image layers, or embedded in source-controlled Compose files.

## Docker security posture

The Compose configuration applies these controls:

- non-root `ahs` user;
- read-only root filesystem;
- all Linux capabilities dropped;
- `no-new-privileges` enabled;
- read-only production data mount;
- writable state limited to `/tmp` tmpfs;
- no host Docker socket;
- no embedded credentials;
- fail-closed startup inspection;
- process-level health check.

This is suitable for local demonstration and research use. It is not, by itself, a complete internet-facing production deployment. Add an authenticated reverse proxy, TLS, network policy, centralized secrets management, log retention controls, and organizational access governance before multi-user deployment.

## Configuration templates

| File | Purpose | Fixture behavior |
|---|---|---|
| `config/ahs_engine.example.toml` | Native/local template | `auto` |
| `config/docker.sample.toml` | Docker sample profile | `required` |
| `config/docker.production.toml` | Docker production profile | `disabled` |

Do not use `fixture.mode = "auto"` for a production-data claim. Production mode must fail closed.

Use a custom Docker configuration by mounting it at `/app/config/ahs_engine.toml` in a Compose override. Preserve the approved metadata paths, join restrictions, survey weight settings, and fail-closed fixture behavior.

## Building a smaller provider-specific image

The default image installs all optional model adapters so one image can run any supported provider. A smaller image can be built with only the UI and one provider:

```bash
AHS_MODEL_EXTRAS=ui,model-openai docker compose --profile sample build
```

Examples:

```text
ui
ui,model-openai
ui,model-anthropic
ui,model-bedrock
```

Selecting a provider whose optional dependency was omitted produces an explicit runtime error rather than falling back silently.

## Native Python execution

Install the core package, UI, and development dependencies:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e '.[dev,ui]'
```

Copy the native configuration template:

```bash
cp config/ahs_engine.example.toml config/ahs_engine.toml
```

For local fixtures, leave `fixture.mode = "auto"` or set it to `required`. For production files, set it to `disabled` and export absolute paths:

```bash
export AHS_HOUSEHOLD_CSV="$HOME/Data/AHS-2023/household.csv"
export AHS_MORTGAGE_CSV="$HOME/Data/AHS-2023/mortgage.csv"
export AHS_PROJECTS_CSV="$HOME/Data/AHS-2023/projects.csv"
```

Run schema inspection:

```bash
ahs-query inspect --config config/ahs_engine.toml
```

Run the UI:

```bash
streamlit run src/ahs_copilot/ui/app.py
```

## CLI examples

```bash
ahs-query inspect --config config/ahs_engine.example.toml
ahs-query run examples/household_filter.json --config config/ahs_engine.example.toml
ahs-query survey-run examples/survey_tenure_comparison.json --config config/ahs_engine.example.toml
ahs-plan --config config/ahs_engine.example.toml --plan examples/analysis_plan_high_burden_by_tenure.json --action validate
ahs-plan --config config/ahs_engine.example.toml --plan examples/analysis_plan_high_burden_by_tenure.json --action compile
ahs-plan --config config/ahs_engine.example.toml --plan examples/analysis_plan_high_burden_by_tenure.json --action execute
ahs-eval --evaluation-set evaluation/ahs_eval_50.json --responses evaluation/sample_candidate_responses.json --output sample_outputs/evaluation_report.json
```

The sample candidate-response file is an envelope example, not a certified passing 50-case run.

## Testing and validation

Install development dependencies and run:

```bash
python -m compileall -q src tests scripts
python -m pytest -q
python -m pytest -q tests/test_packaging.py
```

Validate Compose after creating `.env`:

```bash
docker compose config
```

Build and run the sample smoke test:

```bash
docker compose --profile sample up --build -d
docker compose --profile sample ps
docker compose --profile sample logs --no-color ahs-sample
docker compose --profile sample down
```

Do not repeat historical test counts as current certification. Record only results observed from the current branch and environment.

## Health checks and diagnostics

The image and Compose service both define a health check. Useful commands:

```bash
docker compose --profile sample ps
docker inspect --format='{{json .State.Health}}' ahs-copilot-ahs-sample-1
docker compose --profile sample logs --tail=200 ahs-sample
```

Startup preflight emits one redacted JSON summary. It includes the data mode, fixture mode, dataset count, synthetic dataset count, provider name, model name, endpoint, region, and credential source. It never prints API-key or session-token values.

## Troubleshooting

### Production container exits during preflight

Check the logs:

```bash
docker compose --profile production logs ahs-production
```

Common causes are missing CSVs, host paths not mounted into `/data/ahs`, incorrect column names, uncertified metadata mappings, or a provider selected without its model name or credentials.

### Projects schema reports missing `PROJECTNO`

The durable PUF relationship rule is that `CONTROL` is required. `PROJECTNO` is optional and unresolved. Confirm that the current executable catalog and physical-schema validator preserve that rule and that projects are preaggregated to one row per `CONTROL` before household joins.

### New York/Miami comparison is blocked

Metro execution must use certified `OMB13CBSA` mappings. The intended codes are New York `35620` and Miami `33100`, but execution must still fail closed when those mappings are absent from the approved executable catalog.

### Container is unhealthy but still running

Inspect Streamlit logs and test the endpoint from inside the container:

```bash
docker compose --profile sample exec ahs-sample \
  python /app/scripts/healthcheck.py
```

### Port 8501 is already in use

Set a different host port in `.env`:

```dotenv
AHS_SAMPLE_PORT=8502
```

Then open `http://localhost:8502`.

### Docker cannot read the data directory

Use an absolute `AHS_DATA_DIR`, confirm host permissions, and ensure Docker Desktop has permission to share the directory.

## Documentation

- `NEXT_CHAT_HANDOFF.md` — authoritative project checkpoint.
- `docs/analysis_plan.md` — structured plan contract and validation order.
- `docs/agent_workflow.md` — LangGraph workflow, approval, retries, and result checks.
- `docs/survey_estimation.md` — deterministic formulas, suppression, and variance boundary.
- `docs/evaluation_harness.md` — deterministic and narrative evaluation scoring.
- `docs/red_team_guardrails.md` — request and plan threat controls.
- `docs/execution_report.md` — observed verification commands and results; treat stale counts as historical only.
- `schemas/` — machine-readable input and result contracts.

## License and data responsibility

No AHS production microdata is included in the Docker image or repository. Users are responsible for obtaining authorized public-use files, complying with Census/AHS terms, protecting local data, and retaining the application's universe, weight, denominator, suppression, source, and limitation disclosures when sharing results.
