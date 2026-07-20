"""Environment-backed model-provider configuration without secret persistence.

Provider SDK imports remain optional and lazy. This module validates only the
runtime contract and returns redacted diagnostics suitable for startup logs.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from os import environ
from pathlib import Path
from typing import Mapping
from urllib.parse import urlsplit, urlunsplit


class ProviderConfigurationError(ValueError):
    """Raised when a selected model provider is not safely configured."""


class ModelProvider(str, Enum):
    DEMO = "demo"
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    BEDROCK = "bedrock"

    @classmethod
    def parse(cls, value: str | None) -> "ModelProvider":
        normalized = (value or cls.DEMO.value).strip().lower().replace("_", "-")
        aliases = {
            "demo": cls.DEMO,
            "no-network": cls.DEMO,
            "offline": cls.DEMO,
            "openai": cls.OPENAI,
            "openai-compatible": cls.OPENAI,
            "anthropic": cls.ANTHROPIC,
            "bedrock": cls.BEDROCK,
            "aws-bedrock": cls.BEDROCK,
        }
        try:
            return aliases[normalized]
        except KeyError as exc:
            allowed = ", ".join(provider.value for provider in cls)
            raise ProviderConfigurationError(
                f"Unsupported AHS_MODEL_PROVIDER={value!r}; expected one of: {allowed}."
            ) from exc


@dataclass(frozen=True)
class ModelProviderSettings:
    provider: ModelProvider
    model_name: str | None
    base_url: str | None
    region: str | None
    credential_source: str

    @classmethod
    def from_environment(
        cls, values: Mapping[str, str] | None = None
    ) -> "ModelProviderSettings":
        env = environ if values is None else values
        provider = ModelProvider.parse(env.get("AHS_MODEL_PROVIDER"))
        model_name = _clean(env.get("AHS_MODEL_NAME"))
        base_url = _validated_base_url(_clean(env.get("OPENAI_BASE_URL")))
        region = _clean(env.get("AWS_REGION")) or _clean(env.get("AWS_DEFAULT_REGION"))

        if provider is ModelProvider.DEMO:
            return cls(provider, None, None, None, "none")

        if provider is not ModelProvider.OPENAI and base_url:
            raise ProviderConfigurationError(
                "OPENAI_BASE_URL is valid only for the OpenAI provider."
            )

        if not model_name:
            raise ProviderConfigurationError(
                f"AHS_MODEL_NAME is required when AHS_MODEL_PROVIDER={provider.value}."
            )

        if provider is ModelProvider.OPENAI:
            credential_source = _validate_single_secret_source(env, "OPENAI_API_KEY")
        elif provider is ModelProvider.ANTHROPIC:
            credential_source = _validate_single_secret_source(env, "ANTHROPIC_API_KEY")
        else:
            if not region:
                raise ProviderConfigurationError(
                    "AWS_REGION or AWS_DEFAULT_REGION is required for the Bedrock provider."
                )
            credential_source = _bedrock_credential_source(env)

        return cls(provider, model_name, base_url, region, credential_source)

    def redacted_summary(self) -> dict[str, str | None]:
        """Return diagnostics that cannot expose tokens, query strings, or URL userinfo."""
        return {
            "provider": self.provider.value,
            "model_name": self.model_name,
            "base_url_origin": _redacted_origin(self.base_url),
            "region": self.region,
            "credential_source": self.credential_source,
        }


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


def _validated_base_url(value: str | None) -> str | None:
    if value is None:
        return None
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ProviderConfigurationError(
            "OPENAI_BASE_URL must be an absolute HTTP or HTTPS URL."
        )
    if parsed.username or parsed.password:
        raise ProviderConfigurationError(
            "OPENAI_BASE_URL must not contain embedded credentials."
        )
    return value.rstrip("/")


def _redacted_origin(value: str | None) -> str | None:
    if value is None:
        return None
    parsed = urlsplit(value)
    host = parsed.hostname or ""
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    netloc = host
    if parsed.port is not None:
        netloc = f"{netloc}:{parsed.port}"
    return urlunsplit((parsed.scheme, netloc, "", "", ""))


def _secret_file(path_text: str) -> Path:
    path = Path(path_text).expanduser()
    if not path.is_file() or not path.stat().st_size:
        raise ProviderConfigurationError("Configured secret file is missing, unreadable, or empty.")
    return path


def _validate_single_secret_source(env: Mapping[str, str], name: str) -> str:
    direct = _clean(env.get(name))
    file_name = _clean(env.get(f"{name}_FILE"))
    if direct and file_name:
        raise ProviderConfigurationError(
            f"Set only one of {name} and {name}_FILE."
        )
    if direct:
        return "environment"
    if file_name:
        _secret_file(file_name)
        return "secret-file"
    raise ProviderConfigurationError(
        f"{name} or {name}_FILE is required for the selected provider."
    )


def _bedrock_credential_source(env: Mapping[str, str]) -> str:
    profile = _clean(env.get("AWS_PROFILE"))
    access_key = _clean(env.get("AWS_ACCESS_KEY_ID"))
    access_file = _clean(env.get("AWS_ACCESS_KEY_ID_FILE"))
    secret_key = _clean(env.get("AWS_SECRET_ACCESS_KEY"))
    secret_file = _clean(env.get("AWS_SECRET_ACCESS_KEY_FILE"))
    session_token = _clean(env.get("AWS_SESSION_TOKEN"))
    session_file = _clean(env.get("AWS_SESSION_TOKEN_FILE"))

    if access_key and access_file:
        raise ProviderConfigurationError(
            "Set only one of AWS_ACCESS_KEY_ID and AWS_ACCESS_KEY_ID_FILE."
        )
    if secret_key and secret_file:
        raise ProviderConfigurationError(
            "Set only one of AWS_SECRET_ACCESS_KEY and AWS_SECRET_ACCESS_KEY_FILE."
        )
    if session_token and session_file:
        raise ProviderConfigurationError(
            "Set only one of AWS_SESSION_TOKEN and AWS_SESSION_TOKEN_FILE."
        )

    has_access = bool(access_key or access_file)
    has_secret = bool(secret_key or secret_file)
    if has_access != has_secret:
        raise ProviderConfigurationError(
            "AWS access key and secret access key must be configured together."
        )
    for path_text in (access_file, secret_file, session_file):
        if path_text:
            _secret_file(path_text)

    if has_access:
        return "aws-static-environment-or-file"
    if profile:
        return "aws-profile"
    return "aws-default-chain"
