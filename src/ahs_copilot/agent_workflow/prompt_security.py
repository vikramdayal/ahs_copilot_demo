from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping, Sequence
from typing import Any

REDACTED_PROMPT_INJECTION = "[WITHHELD_POSSIBLE_PROMPT_INJECTION]"

_INJECTION_PATTERNS = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"\bignore\s+(all\s+)?(previous|prior|above)\s+instructions?\b",
        r"\b(disregard|override)\s+(the\s+)?(system|developer|previous)\s+(prompt|message|instructions?)\b",
        r"\byou\s+are\s+now\b",
        r"\bnew\s+(system|developer)\s+(prompt|message|instructions?)\b",
        r"\breveal\s+(the\s+)?(system|developer)\s+prompt\b",
        r"\bexecute\s+(this\s+)?(sql|code|command|tool)\b",
        r"\bcall\s+(the\s+)?[a-z0-9_.-]+\s+tool\b",
        r"\bbypass\s+(the\s+)?(guardrails?|validator|policy|approval)\b",
    )
)


def normalize_untrusted_text(value: str, *, max_length: int = 2000) -> str:
    """Normalize untrusted prompt-bound text and remove hidden/control characters."""

    normalized = unicodedata.normalize("NFKC", str(value))
    visible: list[str] = []
    for character in normalized:
        codepoint = ord(character)
        if 0xE0000 <= codepoint <= 0xE007F:  # Unicode tag characters / ASCII smuggling
            visible.append(" ")
            continue
        category = unicodedata.category(character)
        if category.startswith("C") and character not in {"\n", "\r", "\t"}:
            visible.append(" ")
            continue
        visible.append(character)
    clean = "".join(visible)
    clean = re.sub(r"[ \t]+", " ", clean)
    clean = re.sub(r"\s*\n\s*", "\n", clean).strip()
    return clean[:max_length]


def contains_prompt_injection(value: str) -> bool:
    clean = normalize_untrusted_text(value)
    return any(pattern.search(clean) for pattern in _INJECTION_PATTERNS)


def sanitize_prompt_text(value: str, *, max_length: int = 500) -> str:
    clean = normalize_untrusted_text(value, max_length=max_length)
    return REDACTED_PROMPT_INJECTION if contains_prompt_injection(clean) else clean


def sanitize_prompt_data(value: Any, *, max_depth: int = 8) -> Any:
    """Recursively sanitize metadata/user context before it is serialized into a prompt."""

    def visit(item: Any, depth: int) -> Any:
        if depth > max_depth:
            return "[TRUNCATED_NESTED_METADATA]"
        if isinstance(item, str):
            return sanitize_prompt_text(item)
        if isinstance(item, Mapping):
            output: dict[str, Any] = {}
            for index, (key, nested) in enumerate(item.items()):
                safe_key = sanitize_prompt_text(str(key), max_length=80)
                if safe_key == REDACTED_PROMPT_INJECTION or not safe_key:
                    safe_key = f"withheld_key_{index}"
                output[safe_key] = visit(nested, depth + 1)
            return output
        if isinstance(item, Sequence) and not isinstance(item, (bytes, bytearray, str)):
            return [visit(nested, depth + 1) for nested in item[:500]]
        if item is None or isinstance(item, (bool, int, float)):
            return item
        return sanitize_prompt_text(str(item))

    return visit(value, 0)
