"""Rules-first sizing.

The vast majority of CI workflows fall into recognisable patterns. Rather
than calling a model on every dispatch (which costs energy and latency),
we apply cheap regex / structural heuristics first. Only when the rules
return ``None`` (genuinely ambiguous workflow) do we fall back to the LLM.

Each tier maps to an ACA Job size and a runner label:

    small   0.5 vCPU /  1 GiB    label: aca-small
    medium  2.0 vCPU /  4 GiB    label: aca-medium
    large   4.0 vCPU /  8 GiB    label: aca-large
"""

from __future__ import annotations

import re
from dataclasses import dataclass

SIZES = ("small", "medium", "large")


@dataclass(frozen=True)
class SizingDecision:
    size: str
    label: str
    reason: str
    source: str  # "rules" or "llm"


def _label(size: str) -> str:
    return f"aca-{size}"


# Patterns that strongly indicate a heavy workload. Order matters —
# first match wins, and we check large → medium → small so an ML
# training step doesn't get downsized just because it also runs lint.
_LARGE_PATTERNS = [
    (r"\b(train|training|fit_model)\b", "ML training step detected"),
    (r"\bdocker\s+build\b.*--platform", "multi-arch docker build"),
    (r"\bk6\s+run\b|\blocust\b|\bartillery\b", "load testing tool"),
    (r"\b(cypress|playwright)\s+run\b", "headless browser e2e suite"),
    (r"\bgradle.*assemble(Release)?\b", "android release build"),
    (r"\bxcodebuild\b.*archive", "ios archive build"),
    (r"\bcargo\s+build\s+--release\b", "rust release build"),
]

_MEDIUM_PATTERNS = [
    (r"\bdocker\s+build\b", "single-arch docker build"),
    (r"\bpytest\b|\bjest\b|\bvitest\b|\bgo\s+test\b", "unit test suite"),
    (r"\bnpm\s+(ci|install)\b.*&&.*build", "npm install + build"),
    (r"\bmvn\b.*\b(package|test)\b", "maven build"),
    (r"\btsc\b|\bnext\s+build\b|\bvite\s+build\b", "frontend build"),
]

_SMALL_PATTERNS = [
    (r"\b(ruff|black|flake8|eslint|prettier|gofmt)\b", "lint/format only"),
    (r"\bmarkdownlint\b|\byamllint\b", "doc lint"),
    (r"\bgit\s+(log|diff|status)\b", "git introspection only"),
    (r"\bcurl\b.*-X\s+(GET|POST)", "single API call"),
    (r"\b(echo|cat|grep|sed|awk)\b", "shell text manipulation"),
]


def decide_from_rules(workflow_yaml: str) -> SizingDecision | None:
    """Return a decision if the workflow matches a known pattern, else None.

    We collapse the YAML to a single line to make patterns simpler; we
    don't actually parse the YAML structure here because we're only
    looking at command text.
    """
    haystack = re.sub(r"\s+", " ", workflow_yaml)

    for pattern, reason in _LARGE_PATTERNS:
        if re.search(pattern, haystack, re.IGNORECASE):
            return SizingDecision("large", _label("large"), reason, "rules")

    for pattern, reason in _MEDIUM_PATTERNS:
        if re.search(pattern, haystack, re.IGNORECASE):
            return SizingDecision("medium", _label("medium"), reason, "rules")

    # Only return small if we *also* see no medium/large signals AND we
    # see at least one small signal — pure heuristic to avoid downsizing
    # workflows we don't understand.
    for pattern, reason in _SMALL_PATTERNS:
        if re.search(pattern, haystack, re.IGNORECASE):
            return SizingDecision("small", _label("small"), reason, "rules")

    return None


def label_for(size: str) -> str:
    if size not in SIZES:
        raise ValueError(f"Unknown size {size!r}; expected one of {SIZES}")
    return _label(size)
