"""Environment-backed model-provider configuration without secret persistence.

This module intentionally contains no provider SDK imports. It validates the
runtime contract and returns only non-secret metadata. Provider SDKs remain
lazy optional dependencies owned by the Streamlit application.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from os import environ
from typing import Mapping


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
        base_url = _clean(env.get("OPENAI_BASE_URL"))
        region = _clean(env.get("AWS_REGION")) or _clean(env.get("AWS_DEFAULT_REGION"))

        if provider is ModelProvider.DEMO:
            return cls(provider, None, None, None, "none")

        if not model_name:
            raise ProviderConfigurationError(
                f"AHS_MODEL_NAME is required when AHS_MODEL_PROVIDER={provider.value}."
            )

        if provider is ModelProvider.OPENAI:
            if not _has_value(env, "OPENAI_API_KEY"):
                raise ProviderConfigurationError(
                    "OPENAI_API_KEY or OPENAI_API_KEY_FILE is required for the OpenAI provider."
                )
            credential_source = _credential_source(env, "OPENAI_API_KEY")
        elif provider is ModelProvider.ANTHROPIC:
            if not _has_value(env, "ANTHROPIC_API_KEY"):
                raise ProviderConfigurationError(
                    "ANTHROPIC_API_KEY or ANTHROPIC_API_KEY_FILE is required for the Anthropic provider."
                )
            credential_source = _credential_source(env, "ANTHROPIC_API_KEY")
        else:
            if not region:
                raise ProviderConfigurationError(
                    "AWS_REGION or AWS_DEFAULT_REGION is required for the Bedrock provider."
                )
            # Authentication is delegated to the standard AWS credential chain.
            credential_source = "aws-default-chain"

        return cls(provider, model_name, base_url, region, credential_source)

    def redacted_summary(self) -> dict[str, str | None]:
        """Return diagnostics that cannot contain API-key or session-token values."""
        return {
            "provider": self.provider.value,
            "model_name": self.model_name,
            "base_url": self.base_url,
            "region": self.region,
            "credential_source": self.credential_source,
        }


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


def _has_value(env: Mapping[str, str], name: str) -> bool:
    return bool(_clean(env.get(name)) or _clean(env.get(f"{name}_FILE")))


def _credential_source(env: Mapping[str, str], name: str) -> str:
    if _clean(env.get(f"{name}_FILE")):
        return "secret-file"
    if _clean(env.get(name)):
        return "environment"
    return "none"
