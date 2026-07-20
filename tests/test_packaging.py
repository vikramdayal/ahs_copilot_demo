from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest

from ahs_copilot.model_providers import (
    ModelProvider,
    ModelProviderSettings,
    ProviderConfigurationError,
)

ROOT = Path(__file__).resolve().parents[1]


def test_docker_modes_are_fail_closed() -> None:
    with (ROOT / "config/docker.sample.toml").open("rb") as handle:
        sample = tomllib.load(handle)
    with (ROOT / "config/docker.production.toml").open("rb") as handle:
        production = tomllib.load(handle)

    assert sample["fixture"]["mode"] == "required"
    assert production["fixture"]["mode"] == "disabled"
    assert production["datasets"]["projects"]["path"].endswith("projects.csv}")


def test_env_template_contains_no_credentials() -> None:
    text = (ROOT / ".env.example").read_text(encoding="utf-8")
    sensitive_names = (
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_SESSION_TOKEN",
    )
    for name in sensitive_names:
        match = re.search(rf"^{name}=(.*)$", text, flags=re.MULTILINE)
        assert match is not None
        assert match.group(1).strip() == ""
    assert "sk-" not in text
    assert "AKIA" not in text


def test_provider_alias_and_redacted_summary() -> None:
    assert ModelProvider.parse("no-network") is ModelProvider.DEMO
    settings = ModelProviderSettings.from_environment(
        {
            "AHS_MODEL_PROVIDER": "openai-compatible",
            "AHS_MODEL_NAME": "example-model",
            "OPENAI_API_KEY_FILE": "/run/secrets/openai",
            "OPENAI_BASE_URL": "https://gateway.example/v1",
        }
    )
    assert settings.provider is ModelProvider.OPENAI
    assert settings.credential_source == "secret-file"
    assert "api_key" not in settings.redacted_summary()


def test_external_provider_requires_model_name() -> None:
    with pytest.raises(ProviderConfigurationError):
        ModelProviderSettings.from_environment(
            {"AHS_MODEL_PROVIDER": "anthropic", "ANTHROPIC_API_KEY": "not-returned"}
        )


def test_packaging_files_exist() -> None:
    required = (
        "Dockerfile",
        "docker-compose.yml",
        ".dockerignore",
        ".env.example",
        "scripts/start.sh",
        "scripts/preflight.py",
        "scripts/healthcheck.py",
    )
    for path in required:
        assert (ROOT / path).is_file(), path
