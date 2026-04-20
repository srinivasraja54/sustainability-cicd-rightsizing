"""Pure sizing logic — no Azure side effects.

This is the bit a hackathon judge can run locally with::

    python orchestrator/analyze_pipeline.py \
        --workflow .github/workflows/02-medium-test.yml

It prints the decision and returns the size label on stdout. Useful for
unit tests, CI dry-runs, and demoing the rules-vs-LLM split.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from sizing_rules import decide_from_rules


def analyze(workflow_path: Path, allow_llm: bool = True) -> dict:
    text = workflow_path.read_text()

    decision = decide_from_rules(text)
    if decision is None:
        if not allow_llm:
            return {
                "size": "medium",
                "label": "aca-medium",
                "reason": "no rule matched; LLM disabled; defaulting to medium",
                "source": "default",
            }
        # Lazy import so the pure-rules path doesn't require openai SDK.
        from azure_openai_client import AzureOpenAIConfig, decide_with_llm

        cfg = AzureOpenAIConfig.from_env()
        decision = decide_with_llm(text, cfg)

    return {
        "size": decision.size,
        "label": decision.label,
        "reason": decision.reason,
        "source": decision.source,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Decide runner size for a workflow.")
    parser.add_argument("--workflow", required=True, type=Path)
    parser.add_argument("--no-llm", action="store_true",
                        help="Disable LLM fallback (rules + default only).")
    parser.add_argument("--format", choices=("json", "label"), default="json")
    args = parser.parse_args()

    result = analyze(args.workflow, allow_llm=not args.no_llm)

    if args.format == "json":
        print(json.dumps(result, indent=2))
    else:
        print(result["label"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
