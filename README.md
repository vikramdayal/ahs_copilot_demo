# AHS 2023 Research Copilot

A governed local research application for descriptive, survey-weighted analysis of the 2023 American Housing Survey Public Use File (PUF). The application combines a Streamlit interface, typed `AnalysisPlan` contracts, deterministic validation, a governed DuckDB execution engine, survey-weighted estimators, result criticism, and an auditable human-approval workflow.

The Docker package provides two deliberately separate runtime modes:

- **Sample mode** uses generated deterministic fixtures and is forced to the no-network demo planner.
- **Production-data mode** mounts local AHS CSV files read-only and fails closed if a required file, schema element, or provider setting is unavailable.

## Statistical and governance boundary

The application produces descriptive estimates only. Replicate-weight variance estimation is not implemented, so the application must not return standard errors, confidence intervals, p-values, significance claims, causal effects, household-level predictions, or re-identification output.

Additional invariants:

- The planner may propose only typed `AnalysisPlan` objects; it cannot submit arbitrary SQL.
- Unknown fields are rejected by strict Pydantic schemas.
- Variables must exist in both the approved semantic catalog and the inspected physical schema.
- PUF/IUF access restrictions are enforced before SQL compilation.
- Mortgage and project child rows are preaggregated before household weighting.
- `CONTROL` is the only required PUF projects relationship key.
- `PROJECTNO` is optional and unresolved and is not manufactured in sample data.
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

The public request and plan contracts contain no raw-SQL field. DuckDB scans source CSVs lazily and may spill to a configured temporary directory; Python does not load the full national files into pandas.

## Repository layout

```text
config/                              Engine and Docker configuration templates
metadata/                            Approved source, semantic, and execution catalogs
src/ahs_copilot/                     Application package
src/ahs_copilot/ui/app.py            Streamlit application implementation
src/ahs_copilot/ui/streamlit_app.py  Stable script entry point
scripts/start.sh                     Container entrypoint and secret-file loader
scripts/preflight.py                 Fail-closed startup validation
scripts/healthcheck.py               Loopback-only Streamlit health probe
scripts/docker-doctor.sh             Docker Desktop/Engine readiness check
tests/fixtures/synthetic/            Deterministic sample datasets
Dockerfile                           Non-root application image
docker-compose.yml                   Sample and production Compose profiles
.env.example                         Non-secret runtime template
```

## Prerequisites

### Docker on macOS

Install and run Docker Desktop. Installing only the Docker CLI and Compose plugin is not sufficient because the Docker Engine runs inside Docker Desktop's Linux VM.

Confirm readiness before building:

```bash
open -a Docker
./scripts/docker-doctor.sh
```

The readiness script checks:

- the `docker` command;
- Docker Compose v2;
- a reachable Docker Engine;
- valid repository Compose configuration.

When `docker info` reports a missing `/var/run/docker.sock`, Docker Desktop is normally stopped or the CLI is using the wrong context. Inspect and repair the context:

```bash
docker context ls
docker context use desktop-linux   # only when listed
unset DOCKER_HOST DOCKER_CONTEXT
docker info
```

### Native Python

- Python 3.11 or newer
- A virtual environment

## Quick start: deterministic sample mode

```bash
cp .env.example .env
./scripts/docker-doctor.sh
docker compose --profile sample up --build
```

Targeting the service directly also activates its profile and is useful with older Compose clients:

```bash
docker compose up --build ahs-sample
```

Open:

```text
http://127.0.0.1:8501
```

The port is bound only to the local machine. Stop the application with:

```bash
docker compose --profile sample down --remove-orphans
```

Run in the background and inspect health:

```bash
docker compose --profile sample up --build -d
docker compose --profile sample ps
docker compose --profile sample logs -f ahs-sample
```

A healthy container reports `healthy`. The probe calls Streamlit's loopback-only `/_stcore/health` endpoint.

## Production-data mode

Production mode forces `fixture.mode = "disabled"`. It will not substitute sample files when a CSV is missing, unreadable, or inconsistent with the approved executable catalog.

### 1. Prepare the data directory

By default, Compose mounts `./data` at `/data/ahs` read-only:

```text
data/
  household.csv
  mortgage.csv
  projects.csv
```

The projects file requires `CONTROL`; `PROJECTNO` is not a required PUF relationship key.

Select a different host directory in `.env`:

```dotenv
AHS_DATA_DIR=/absolute/path/to/AHS-2023
```

The configured CSV paths must be visible inside the container:

```dotenv
AHS_HOUSEHOLD_CSV=/data/ahs/household.csv
AHS_MORTGAGE_CSV=/data/ahs/mortgage.csv
AHS_PROJECTS_CSV=/data/ahs/projects.csv
```

### 2. Select model dependencies and provider

The default image contains only the UI and deterministic planner:

```dotenv
AHS_MODEL_EXTRAS=ui
AHS_MODEL_PROVIDER=demo
AHS_MODEL_NAME=
```

For one external provider, install only that adapter at image build time:

```dotenv
AHS_MODEL_EXTRAS=ui,model-openai
AHS_MODEL_PROVIDER=openai
AHS_MODEL_NAME=replace-with-an-approved-model-name
```

Equivalent extras are `model-anthropic` and `model-bedrock`.

### 3. Start production mode

```bash
./scripts/docker-doctor.sh
docker compose --profile production up --build
```

The entrypoint performs a blocking preflight that verifies:

- production mode uses `fixture.mode = "disabled"`;
- the selected provider contract is complete;
- all configured datasets resolve;
- physical schemas can be inspected;
- no synthetic dataset was selected.

The service remains bound to `127.0.0.1`. Internet-facing or multi-user deployment requires an authenticated reverse proxy, TLS, access controls, network policy, centralized secrets management, and organizational logging and retention controls.

### 4. Resource tuning

The production template defaults to a 4 GB DuckDB memory limit:

```dotenv
AHS_DUCKDB_MEMORY_LIMIT=8GB
```

DuckDB temporary files are written to the container's `/tmp` tmpfs. Increase that tmpfs or mount an explicitly controlled writable volume for workloads requiring more spill space.

## Model-provider configuration

Every external provider remains constrained to structured `AnalysisPlan` output and receives no arbitrary SQL tool.

| `AHS_MODEL_PROVIDER` | Network | Credential mechanism |
|---|---:|---|
| `demo` | No | None |
| `openai` | Yes | `OPENAI_API_KEY` or readable secret file |
| `anthropic` | Yes | `ANTHROPIC_API_KEY` or readable secret file |
| `bedrock` | Yes | Standard AWS credential chain |

Startup validates provider settings through `ahs_copilot.model_providers`. Provider SDK imports remain lazy optional dependencies.

### OpenAI or compatible gateway

```dotenv
AHS_MODEL_EXTRAS=ui,model-openai
AHS_MODEL_PROVIDER=openai
AHS_MODEL_NAME=replace-with-an-approved-model-name
OPENAI_API_KEY=replace-locally-never-commit
OPENAI_BASE_URL=
```

`OPENAI_BASE_URL` must be an absolute HTTP or HTTPS URL and must not contain embedded credentials. Startup logs expose only its origin, never paths, query strings, or user information.

### Anthropic

```dotenv
AHS_MODEL_EXTRAS=ui,model-anthropic
AHS_MODEL_PROVIDER=anthropic
AHS_MODEL_NAME=replace-with-an-approved-model-name
ANTHROPIC_API_KEY=replace-locally-never-commit
```

### AWS Bedrock

```dotenv
AHS_MODEL_EXTRAS=ui,model-bedrock
AHS_MODEL_PROVIDER=bedrock
AHS_MODEL_NAME=replace-with-an-approved-bedrock-model-id
AWS_REGION=us-east-1
```

Prefer AWS SSO, a read-only mounted profile, workload identity, or short-lived credentials. For a local profile:

```bash
docker compose \
  -f docker-compose.yml \
  -f docker-compose.aws.yml \
  --profile production up --build
```

The Streamlit sidebar is the interactive provider control. For an external planner, select the same provider and model shown by the startup configuration before submitting a question. The startup abstraction validates configuration, while the current UI still constructs the provider-specific chat model.

## Secrets and API-key handling

Never commit `.env`, `secrets.toml`, API keys, AWS credentials, access tokens, certificate keys, or credential-bearing configuration files. The repository tracks only `.env.example`, whose credential values are blank.

Create a local environment file:

```bash
cp .env.example .env
chmod 600 .env
```

The entrypoint also supports these secret-file variables:

- `OPENAI_API_KEY_FILE`
- `ANTHROPIC_API_KEY_FILE`
- `AWS_ACCESS_KEY_ID_FILE`
- `AWS_SECRET_ACCESS_KEY_FILE`
- `AWS_SESSION_TOKEN_FILE`

Do not set both a direct variable and its corresponding `*_FILE` variable. Startup rejects ambiguous, unreadable, or empty secret sources. API keys are runtime-only and must never be Docker build arguments or image-layer content.

## Docker security posture

The local Compose configuration applies:

- non-root UID/GID `10001`;
- read-only root filesystem;
- all Linux capabilities dropped;
- `no-new-privileges`;
- PID limit;
- read-only production data mount;
- writable state restricted to `/tmp` tmpfs;
- localhost-only host ports;
- no host Docker socket;
- fail-closed startup inspection;
- process health checks.

This is a local demonstration posture, not a complete public deployment architecture.

## Configuration templates

| File | Purpose | Fixture behavior |
|---|---|---|
| `config/ahs_engine.example.toml` | Native/local template | `auto` |
| `config/docker.sample.toml` | Docker sample profile | `required` |
| `config/docker.production.toml` | Docker production profile | `disabled` |

Do not use `fixture.mode = "auto"` for a production-data claim.

## Native Python execution

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev,ui]'
python -m pip check
cp config/ahs_engine.example.toml config/ahs_engine.toml
```

For real data, set `fixture.mode = "disabled"` and export absolute paths:

```bash
export AHS_HOUSEHOLD_CSV="$HOME/Data/AHS-2023/household.csv"
export AHS_MORTGAGE_CSV="$HOME/Data/AHS-2023/mortgage.csv"
export AHS_PROJECTS_CSV="$HOME/Data/AHS-2023/projects.csv"
```

Inspect schemas and launch the stable UI entry point:

```bash
ahs-query inspect --config config/ahs_engine.toml
python -m streamlit run src/ahs_copilot/ui/streamlit_app.py
```

## CLI examples

```bash
ahs-query inspect --config config/ahs_engine.example.toml
ahs-query run examples/household_filter.json --config config/ahs_engine.example.toml
ahs-query survey-run examples/survey_tenure_comparison.json --config config/ahs_engine.example.toml
ahs-plan --config config/ahs_engine.example.toml --plan examples/analysis_plan_high_burden_by_tenure.json --action validate
ahs-plan --config config/ahs_engine.example.toml --plan examples/analysis_plan_high_burden_by_tenure.json --action compile
ahs-plan --config config/ahs_engine.example.toml --plan examples/analysis_plan_high_burden_by_tenure.json --action execute
```

The tracked `evaluation/sample_candidate_responses.json` is an envelope illustration, not a complete 50-case result. Do not run it against `evaluation/ahs_eval_50.json`; the scorer correctly rejects missing cases.

Use the executable one-case CLI smoke example instead:

```bash
ahs-eval \
  --evaluation-set evaluation/example_refusal_eval.json \
  --responses evaluation/example_refusal_response.json \
  --output sample_outputs/example_refusal_report.json
```

## Testing and release certification

```bash
python -m compileall -q src tests scripts
bash -n scripts/start.sh scripts/docker-doctor.sh
python -m pytest -q
```

Docker smoke test:

```bash
cp .env.example .env
./scripts/docker-doctor.sh
docker compose config --quiet
docker compose --profile sample up --build -d
docker compose --profile sample ps
curl --fail --silent http://127.0.0.1:8501/_stcore/health
docker compose --profile sample logs --no-color ahs-sample
docker compose --profile sample down --remove-orphans
```

`docs/execution_report.md` distinguishes the historical 48-test result from current release certification. Update it only with results observed against the exact release commit.

## Troubleshooting

### Docker reports a missing `/var/run/docker.sock`

The Compose plugin is present, but Docker Desktop or another Docker Engine is not running. Start Docker Desktop, wait for engine readiness, then run `./scripts/docker-doctor.sh`.

### Compose reports `unknown flag: --profile`

Use a current Docker Compose v2 installation, or target the service directly:

```bash
docker compose up --build ahs-sample
```

### Production container exits during preflight

```bash
docker compose --profile production logs ahs-production
```

Typical causes are missing CSVs, host paths not mounted into `/data/ahs`, incorrect physical columns, uncertified metadata, an omitted provider dependency, or incomplete provider credentials.

### Projects schema reports missing `PROJECTNO`

The PUF relationship rule requires only `CONTROL`. Confirm that the executable catalog uses `CONTROL`, that no validation layer requires `PROJECTNO`, and that projects are preaggregated to one row per `CONTROL` before household joins.

### New York/Miami comparison is blocked

Metro execution requires certified `OMB13CBSA` code-to-label mappings. Known target codes must still be represented in the approved executable metadata before execution; the application must not infer them from prose alone.

### Port 8501 is in use

```dotenv
AHS_SAMPLE_PORT=8502
```

Open `http://127.0.0.1:8502`.

### Docker cannot read the data directory

Use an absolute `AHS_DATA_DIR`, confirm host permissions, and permit Docker Desktop to share the directory.

## Documentation

- `NEXT_CHAT_HANDOFF.md` — authoritative project checkpoint.
- `docs/analysis_plan.md` — structured plan contract and validation order.
- `docs/agent_workflow.md` — workflow, approval, retries, and result checks.
- `docs/survey_estimation.md` — formulas, suppression, and variance boundary.
- `docs/evaluation_harness.md` — deterministic and narrative scoring.
- `docs/red_team_guardrails.md` — request and plan threat controls.
- `docs/final_repository_audit.md` — final audit findings, corrections, and residual risks.
- `docs/execution_report.md` — observed verification evidence and certification status.

## Data responsibility and licensing status

No AHS production microdata is included in the image or repository. Users are responsible for obtaining authorized public-use files, protecting local data, complying with applicable AHS/Census terms, and preserving universe, weight, denominator, suppression, source, and limitation disclosures when sharing results.

The repository currently has no explicit software license file. Repository owners must select and add an approved license before external redistribution or reuse is authorized.
