# AHS Research Copilot execution and certification report

## Current status

**Declared package version:** `0.10.0`  
**Authoritative branch:** `chat_gpt_branch`  
**Current release certification: NOT YET RECORDED**

A clean full regression, Docker sample-mode smoke test, and CI result must be recorded against the exact release commit before the repository is described as certified or release-ready.

## Historical baseline only

On July 19, 2026, an earlier `0.7.0` source tree reported:

```text
48 passed
```

That result predates the Day 6 evaluation/red-team changes and the Day 7 packaging changes. It is retained only as historical evidence and is not the current test count.

## Required clean verification

Run from a fresh checkout of the authoritative branch:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev,ui]'
python -m pip check
python -m compileall -q src tests scripts
bash -n scripts/start.sh scripts/docker-doctor.sh
python -m pytest -q
```

Verify the evaluation CLI with its complete one-case smoke artifacts:

```bash
ahs-eval \
  --evaluation-set evaluation/example_refusal_eval.json \
  --responses evaluation/example_refusal_response.json \
  --output sample_outputs/example_refusal_report.json
```

Verify Docker configuration and sample startup:

```bash
cp .env.example .env
./scripts/docker-doctor.sh
docker compose config --quiet
docker compose --profile sample up --build -d
```

Then wait for the service to become healthy and inspect it:

```bash
docker compose --profile sample ps
curl --fail --silent http://127.0.0.1:8501/_stcore/health
docker compose --profile sample logs --no-color ahs-sample
docker compose --profile sample down --remove-orphans
```

## Evidence to record after execution

Update this document only with observed values:

- Verification date and timezone.
- Branch and complete commit SHA.
- Operating system and architecture.
- Python, DuckDB, Pydantic, LangGraph, Streamlit, and pytest versions.
- Exact commands.
- Complete test counts.
- Evaluation and red-team test counts.
- Docker image digest.
- Docker Compose version.
- Sample-container health result.
- Any skipped tests or environmental limitations.

Do not convert an unexecuted command, a prior branch result, or a sample response envelope into a current certification claim.
