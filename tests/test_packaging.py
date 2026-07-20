from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path

import pytest

from ahs_copilot import __version__
from ahs_copilot.evaluation import (
    load_candidate_responses,
    load_evaluation_set,
    score_evaluation_set,
)
from ahs_copilot.model_providers import (
    ModelProvider,
    ModelProviderSettings,
    ProviderConfigurationError,
)
from ahs_copilot.query_engine.fixture import PROJECT_ROWS, create_synthetic_fixture


ROOT = Path(__file__).resolve().parents[1]


def _pyproject() -> dict[str, object]:
    with (ROOT / "pyproject.toml").open("rb") as handle:
        return tomllib.load(handle)


def test_version_is_consistent() -> None:
    assert __version__ == _pyproject()["project"]["version"] == "0.10.0"


def test_explicit_runtime_import_dependencies_are_declared() -> None:
    dependencies = set(_pyproject()["project"]["dependencies"])
    assert any(item.startswith("typing-extensions") for item in dependencies)


def test_docker_configuration_files_use_fail_closed_fixture_modes() -> None:
    with (ROOT / "config/docker.sample.toml").open("rb") as handle:
        sample = tomllib.load(handle)
    with (ROOT / "config/docker.production.toml").open("rb") as handle:
        production = tomllib.load(handle)
    assert sample["fixture"]["mode"] == "required"
    assert production["fixture"]["mode"] == "disabled"


def test_streamlit_wrapper_imports_installed_package() -> None:
    wrapper = (ROOT / "src/ahs_copilot/ui/streamlit_app.py").read_text(encoding="utf-8")
    start = (ROOT / "scripts/start.sh").read_text(encoding="utf-8")
    assert "from ahs_copilot.ui.app import main" in wrapper
    assert "streamlit_app.py" in start
    assert "/ui/app.py" not in start


def test_compose_is_localhost_only_and_sample_is_no_network() -> None:
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    assert '127.0.0.1:${AHS_SAMPLE_PORT:-8501}:8501' in compose
    assert '127.0.0.1:${AHS_PRODUCTION_PORT:-8501}:8501' in compose
    sample_section = compose.split("ahs-sample:", 1)[1].split("ahs-production:", 1)[0]
    assert "AHS_MODEL_PROVIDER: demo" in sample_section
    assert 'restart: "no"' in sample_section


def test_image_is_non_root_and_does_not_copy_repository_secrets() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    dockerignore = (ROOT / ".dockerignore").read_text(encoding="utf-8")
    assert re.search(r"^USER\s+10001:10001$", dockerfile, re.MULTILINE)
    assert "COPY --chown=ahs:ahs . ." not in dockerfile
    for ignored in (".env", ".streamlit/secrets.toml", "local-secrets", ".aws"):
        assert ignored in dockerignore


def test_streamlit_runtime_disables_development_reload() -> None:
    with (ROOT / ".streamlit/config.toml").open("rb") as handle:
        config = tomllib.load(handle)
    assert config["server"]["runOnSave"] is False
    assert config["server"]["fileWatcherType"] == "none"
    assert config["server"]["enableXsrfProtection"] is True


def test_env_template_contains_no_credential_values() -> None:
    env_text = (ROOT / ".env.example").read_text(encoding="utf-8")
    for key in (
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_SESSION_TOKEN",
    ):
        match = re.search(rf"^{key}=(.*)$", env_text, re.MULTILINE)
        assert match is not None
        assert match.group(1) == ""


def test_provider_aliases_and_demo_default() -> None:
    assert ModelProvider.parse(None) is ModelProvider.DEMO
    assert ModelProvider.parse("no-network") is ModelProvider.DEMO
    assert ModelProvider.parse("openai-compatible") is ModelProvider.OPENAI
    assert ModelProvider.parse("aws_bedrock") is ModelProvider.BEDROCK


def test_external_provider_requires_model_name() -> None:
    with pytest.raises(ProviderConfigurationError, match="AHS_MODEL_NAME"):
        ModelProviderSettings.from_environment(
            {"AHS_MODEL_PROVIDER": "openai", "OPENAI_API_KEY": "not-a-real-key"}
        )


def test_provider_rejects_embedded_url_credentials() -> None:
    with pytest.raises(ProviderConfigurationError, match="embedded credentials"):
        ModelProviderSettings.from_environment(
            {
                "AHS_MODEL_PROVIDER": "openai",
                "AHS_MODEL_NAME": "test-model",
                "OPENAI_API_KEY": "not-a-real-key",
                "OPENAI_BASE_URL": "https://user:password@example.test/v1",
            }
        )


def test_provider_validates_secret_file_and_redacts_url(tmp_path: Path) -> None:
    secret = tmp_path / "secret"
    secret.write_text("not-a-real-key", encoding="utf-8")
    settings = ModelProviderSettings.from_environment(
        {
            "AHS_MODEL_PROVIDER": "openai",
            "AHS_MODEL_NAME": "test-model",
            "OPENAI_API_KEY_FILE": str(secret),
            "OPENAI_BASE_URL": "https://gateway.example.test/v1?token=hidden",
        }
    )
    assert settings.credential_source == "secret-file"
    assert settings.redacted_summary()["base_url_origin"] == "https://gateway.example.test"


def test_synthetic_projects_never_invent_projectno(tmp_path: Path) -> None:
    assert PROJECT_ROWS
    assert all("PROJECTNO" not in row for row in PROJECT_ROWS)
    paths = create_synthetic_fixture(tmp_path, overwrite=True)
    assert paths["projects"].read_text(encoding="utf-8").splitlines()[0] == (
        "CONTROL,PROJECTCOST,PROJECTTYPE"
    )


def test_fixture_rewrites_stale_project_header(tmp_path: Path) -> None:
    stale = tmp_path / "projects.csv"
    stale.write_text("CONTROL,PROJECTNO,PROJECTCOST\n1001,1,10\n", encoding="utf-8")
    create_synthetic_fixture(tmp_path)
    assert "PROJECTNO" not in stale.read_text(encoding="utf-8").splitlines()[0]


def test_evaluation_cli_smoke_artifacts_are_complete() -> None:
    evaluation = load_evaluation_set(ROOT / "evaluation/example_refusal_eval.json")
    responses = load_candidate_responses(ROOT / "evaluation/example_refusal_response.json")
    report = score_evaluation_set(evaluation, responses)
    assert report.total_cases == 1
    assert report.pass_count == 1


def test_historical_execution_report_is_not_current_certification() -> None:
    report = (ROOT / "docs/execution_report.md").read_text(encoding="utf-8")
    assert "Historical baseline only" in report
    assert "Current release certification: NOT YET RECORDED" in report


def test_runtime_python_files_compile() -> None:
    for path in (
        ROOT / "scripts/healthcheck.py",
        ROOT / "scripts/preflight.py",
        ROOT / "src/ahs_copilot/model_providers.py",
        ROOT / "src/ahs_copilot/ui/streamlit_app.py",
    ):
        source = path.read_text(encoding="utf-8")
        compile(source, str(path), "exec")


def test_evaluation_examples_are_valid_json() -> None:
    for name in ("example_refusal_eval.json", "example_refusal_response.json"):
        json.loads((ROOT / "evaluation" / name).read_text(encoding="utf-8"))
