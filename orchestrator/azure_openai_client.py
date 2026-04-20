"""Thin wrapper around Azure OpenAI for the sizing-fallback call.

We keep the call cheap on purpose:
  - small/cheap deployment (gpt-4o-mini or gpt-35-turbo)
  - low max_tokens (we only need a JSON object)
  - response_format=json_object so we don't need to regex-parse prose
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from openai import AzureOpenAI

from sizing_rules import SIZES, SizingDecision, label_for

PROMPT_PATH = Path(__file__).parent / "prompts" / "sizing_prompt.txt"


@dataclass
class AzureOpenAIConfig:
    endpoint: str
    api_key: str
    deployment: str
    api_version: str = "2024-08-01-preview"

    @classmethod
    def from_env(cls) -> "AzureOpenAIConfig":
        return cls(
            endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
            api_key=os.environ["AZURE_OPENAI_API_KEY"],
            deployment=os.environ["AZURE_OPENAI_DEPLOYMENT"],
            api_version=os.environ.get(
                "AZURE_OPENAI_API_VERSION", "2024-08-01-preview"
            ),
        )


def decide_with_llm(workflow_yaml: str, cfg: AzureOpenAIConfig) -> SizingDecision:
    client = AzureOpenAI(
        azure_endpoint=cfg.endpoint,
        api_key=cfg.api_key,
        api_version=cfg.api_version,
    )

    system_prompt = PROMPT_PATH.read_text()

    response = client.chat.completions.create(
        model=cfg.deployment,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": workflow_yaml},
        ],
        max_tokens=200,
        temperature=0,
        response_format={"type": "json_object"},
    )

    raw = response.choices[0].message.content or "{}"
    parsed = json.loads(raw)

    size = parsed.get("size", "medium").lower()
    if size not in SIZES:
        size = "medium"  # safe default

    return SizingDecision(
        size=size,
        label=label_for(size),
        reason=parsed.get("reason", "llm decision (no reason given)"),
        source="llm",
    )
