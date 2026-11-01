"""Pure sizing logic — no Azure side effects.

This is the bit a hackathon judge can run locally with::

    python orchestrator/analyze_pipeline.py \
        --workflow .github/workflows/02-medium-test.yml

It prints the decision and returns the size label on stdout. Useful for
unit tests, CI dry-runs, and demoing the rules-vs-LLM split.

Three sources are possible in the output:

    "rules"      matched a pattern in sizing_rules.py — free, deterministic
    "llm"        ambiguous workflow, fresh Azure OpenAI call (and cached)
    "llm-cached" ambiguous workflow seen before, served from blob storage

The cache is what keeps the LLM to one call per workflow *change* rather
than one per run; see decision_cache.py.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from sizing_rules import decide_from_rules


def _default(reason: str) -> dict:
    return {
        "size": "medium",
        "label": "aca-medium",
        "reason": f"{reason}; defaulting to medium",
        "source": "default",
    }


def analyze(
    workflow_path: Path, allow_llm: bool = True, use_cache: bool = True
) -> dict:
    text = workflow_path.read_text()

    decision = decide_from_rules(text)
    if decision is None:
        if not allow_llm:
            return _default("no rule matched; LLM disabled")
        # Lazy imports so the pure-rules path doesn't require the openai or
        # azure SDKs — `--no-llm` stays runnable on a laptop with neither.
        import decision_cache
        from azure_openai_client import PROMPT_PATH, AzureOpenAIConfig, decide_with_llm

        try:
            cfg = AzureOpenAIConfig.from_env()
        except KeyError as e:
            print(f"WARN: Azure OpenAI not configured ({e} unset)", file=sys.stderr)
            return _default("no rule matched; LLM not configured")

        # Cache on the full input set — workflow text, prompt, deployment —
        # so the LLM is paid for once per workflow *change*, not once per run.
        key = None
        if use_cache and decision_cache.enabled():
            key = decision_cache.key_for(
                text, deployment=cfg.deployment, prompt=PROMPT_PATH.read_text()
            )
            decision = decision_cache.get(key)
        elif use_cache:
            print(
                f"sizing cache: disabled ({decision_cache.ACCOUNT_URL_ENV} unset); "
                "every ambiguous dispatch will call the LLM"
            )

        if decision is None:
            # Like the cache and the carbon check, an LLM outage (network,
            # throttling, bad JSON) must degrade to a default size, never to
            # a failed pipeline. The fallback is not cached, so the next
            # dispatch tries the LLM again.
            try:
                decision = decide_with_llm(text, cfg)
            except Exception as e:
                print(f"WARN: LLM sizing failed ({e})", file=sys.stderr)
                return _default("no rule matched; LLM call failed")
            if key is not None:
                decision_cache.put(key, decision)

    return {
        "size": decision.size,
        "label": decision.label,
        "reason": decision.reason,
        "source": decision.source,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Decide runner size for a workflow.")
    parser.add_argument("--workflow", required=True, type=Path)
    parser.add_argument(
        "--no-llm",
        action="store_true",
        help="Disable LLM fallback (rules + default only).",
    )
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="Bypass the sizing cache and force a fresh LLM call. Useful for "
        "demoing the miss/hit difference, or after editing the prompt.",
    )
    parser.add_argument("--format", choices=("json", "label"), default="json")
    args = parser.parse_args()

    result = analyze(
        args.workflow, allow_llm=not args.no_llm, use_cache=not args.no_cache
    )

    if args.format == "json":
        print(json.dumps(result, indent=2))
    else:
        print(result["label"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
