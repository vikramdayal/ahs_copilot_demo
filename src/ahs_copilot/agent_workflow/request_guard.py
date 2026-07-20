from __future__ import annotations

import re

from .models import RequestGuardDecision, RequestGuardFinding
from .prompt_security import contains_prompt_injection, normalize_untrusted_text


def _patterns(*values: str) -> tuple[re.Pattern[str], ...]:
    return tuple(re.compile(value, re.IGNORECASE) for value in values)


_SQL_PATTERNS = _patterns(
    r"\b(run|execute|use)\s+(this\s+)?sql\b",
    r"\bselect\s+.+\s+from\s+[a-z_][a-z0-9_]*\b",
    r"\b(drop|truncate|alter|attach|detach|pragma)\s+(table|database|schema|[a-z_])",
    r";\s*--",
)
_STATE_PATTERNS = _patterns(
    r"\bstate[- ]level\b",
    r"\bby\s+state\b",
    r"\bacross\s+(all\s+)?states\b",
    r"\ball\s+50\s+states\b",
    r"\brank\s+(the\s+)?states\b",
    r"\bstate\s+estimates?\b",
    r"\bwhich\s+state\b",
)
_IUF_PATTERNS = _patterns(
    r"\bIUF\b",
    r"\binternal\s+use\s+file\b",
    r"\brestricted[- ]use\s+(data|file)\b",
)
_PRIVACY_PATTERNS = _patterns(
    r"\bwhich\s+households?\b",
    r"\bidentify\s+(the\s+)?(households?|respondents?|people|families)\b",
    r"\b(list|show|return)\s+(the\s+)?(individual|raw|microdata)\s+(rows?|records?)\b",
    r"\b(predict|likely|risk)\b.{0,40}\b(evict|eviction|foreclos|default|homeless)\w*\b",
    r"\bre[- ]?identify\b",
    r"\baddresses?\b",
)
_CAUSAL_PATTERNS = _patterns(
    r"\bprove\s+that\b",
    r"\bcaus(e|es|ed|ing|al|ality)\b",
    r"\bresponsible\s+for\b",
    r"\bthe\s+effect\s+of\b",
)
_PROTECTED_GROUP_PATTERNS = _patterns(
    r"\b(?:race|racial|ethnic(?:ity)?)\b",
    r"\b(?:immigrants?|nationality|religion)\b",
    r"\b(?:disabled|disability)\b",
    r"\b(?:gender|women|men)\b",
)
_STEREOTYPE_PATTERNS = _patterns(
    r"\birresponsible\b",
    r"\blazy\b",
    r"\bcriminal\b",
    r"\bdishonest\b",
    r"\binferior\b",
    r"\bbad\s+with\s+money\b",
    r"\bmaking\s+(the\s+)?neighborhood\w*\s+worse\b",
)


def _matches(patterns: tuple[re.Pattern[str], ...], text: str) -> bool:
    return any(pattern.search(text) for pattern in patterns)


class AHSRequestGuard:
    """Deterministic pre-planning policy gate for unsupported or unsafe requests."""

    def evaluate(self, question: str, *, access_mode: str = "PUF") -> RequestGuardDecision:
        clean = normalize_untrusted_text(question)
        findings: list[RequestGuardFinding] = []

        if contains_prompt_injection(clean):
            findings.append(
                RequestGuardFinding(
                    code="DIRECT_PROMPT_INJECTION",
                    category="prompt_injection",
                    message="The request contains instruction-override or guardrail-bypass language.",
                )
            )
        if _matches(_SQL_PATTERNS, clean):
            findings.append(
                RequestGuardFinding(
                    code="ARBITRARY_SQL_REQUEST",
                    category="arbitrary_sql",
                    message="The copilot accepts only a typed AnalysisPlan and never executes user-supplied SQL.",
                )
            )
        if access_mode.upper() == "PUF" and _matches(_STATE_PATTERNS, clean):
            findings.append(
                RequestGuardFinding(
                    code="STATE_LEVEL_PUF_UNSUPPORTED",
                    category="puf_iuf",
                    message=(
                        "State-level estimates are not certified in the National PUF workflow; "
                        "use certified PUF geographies or a separately governed IUF workflow."
                    ),
                )
            )
        if access_mode.upper() == "PUF" and _matches(_IUF_PATTERNS, clean):
            findings.append(
                RequestGuardFinding(
                    code="IUF_REQUEST_IN_PUF_MODE",
                    category="puf_iuf",
                    message="Restricted/IUF data cannot be used by the PUF execution path.",
                )
            )
        if _matches(_PRIVACY_PATTERNS, clean):
            findings.append(
                RequestGuardFinding(
                    code="PRIVACY_SENSITIVE_INTERPRETATION",
                    category="privacy",
                    message=(
                        "The copilot returns aggregate descriptive statistics and cannot identify, "
                        "rank, or predict outcomes for individual households or respondents."
                    ),
                )
            )
        if _matches(_PROTECTED_GROUP_PATTERNS, clean) and _matches(_STEREOTYPE_PATTERNS, clean):
            findings.append(
                RequestGuardFinding(
                    code="DEMOGRAPHIC_STEREOTYPING",
                    category="stereotyping",
                    message="Stigmatizing or essentializing claims about demographic groups are refused.",
                )
            )

        refusal_findings = list(findings)
        if refusal_findings:
            return RequestGuardDecision(
                action="refuse",
                code="REQUEST_REFUSED",
                message=" ".join(item.message for item in refusal_findings),
                findings=refusal_findings,
                narrative_constraints=[
                    "Do not execute SQL or invoke the planner.",
                    "Explain the governed boundary without fabricating an alternative result.",
                ],
            )

        if _matches(_CAUSAL_PATTERNS, clean):
            finding = RequestGuardFinding(
                code="CAUSAL_CLAIM_UNSUPPORTED",
                category="causal_inference",
                message=(
                    "The current system supports descriptive estimates and associations only; "
                    "it cannot prove causation or estimate causal effects."
                ),
            )
            return RequestGuardDecision(
                action="clarify",
                code="REQUEST_CLARIFICATION_REQUIRED",
                message=(
                    finding.message
                    + " Rephrase the request as a descriptive comparison or association."
                ),
                findings=[finding],
                narrative_constraints=[
                    "Use association language only.",
                    "Do not emit significance, causal, or policy-effect claims.",
                ],
            )

        return RequestGuardDecision(
            action="allow",
            code="REQUEST_ALLOWED",
            message="No deterministic request-policy blocker was detected.",
            findings=[],
            narrative_constraints=[
                "Results are aggregate and descriptive only.",
                "Use only certified PUF variables, universes, weights, and joins.",
            ],
        )
