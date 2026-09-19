"""Content-addressed cache for LLM sizing decisions.

The rules engine is deterministic and costs nothing, so only the *fallback*
path is worth caching. An ambiguous workflow gets one Azure OpenAI call the
first time it is seen; every later dispatch of that unchanged workflow is
served from a blob in the storage account the deploy already provisions.
That is what makes "one LLM call per workflow change, not per run" true.

Key = sha256(deployment, prompt, workflow YAML). Editing the workflow,
revising the prompt, or swapping the model deployment all produce a new key,
so a cached decision can never outlive the inputs it was derived from. There
is no TTL and no invalidation logic to get wrong — staleness is impossible by
construction.

Container: `sizing-cache` (created by storage.bicep).
Auth: DefaultAzureCredential — same story as deferred_queue.py.

Design principle, borrowed from carbon.py: **the cache never blocks CI.** A
missing env var, a missing role assignment, a network failure or a corrupt
entry all degrade to a plain cache miss, and the caller falls through to the
live LLM call. Wrong sizing is expensive; a failed cache read is not.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from datetime import datetime, timezone

from azure.core.exceptions import AzureError, ResourceNotFoundError
from azure.identity import DefaultAzureCredential
from azure.storage.blob import ContainerClient
from sizing_rules import SIZES, SizingDecision, label_for

CONTAINER_NAME = "sizing-cache"
ACCOUNT_URL_ENV = "SIZING_CACHE_ACCOUNT_URL"

#: `source` reported for a decision served from the cache. Distinct from
#: "llm" so a demo (and the GH Actions output) can show the second run of an
#: ambiguous workflow costing nothing.
CACHED_SOURCE = "llm-cached"

# Failures we treat as "no cache today": missing env var (KeyError), any
# Azure SDK / auth / network error, or a local socket problem.
_SOFT_ERRORS = (AzureError, KeyError, OSError, ValueError)


def enabled() -> bool:
    """True when a cache account URL is configured.

    Callers check this so an unconfigured repo gets one quiet log line
    instead of a warning on every dispatch.
    """
    return bool(os.environ.get(ACCOUNT_URL_ENV))


def key_for(workflow_yaml: str, *, deployment: str, prompt: str) -> str:
    """Hash the full set of inputs the decision depends on.

    The NUL separators matter: without them, ("ab", "c") and ("a", "bc")
    would hash identically, and a prompt edit could be masked by a
    compensating workflow edit.
    """
    digest = hashlib.sha256()
    for part in (deployment, prompt, workflow_yaml):
        digest.update(part.encode("utf-8"))
        digest.update(b"\0")
    return digest.hexdigest()


def _blob_client(key: str, container: ContainerClient | None = None):
    container = container or ContainerClient(
        account_url=os.environ[ACCOUNT_URL_ENV],
        container_name=CONTAINER_NAME,
        credential=DefaultAzureCredential(),
    )
    return container.get_blob_client(f"{key}.json")


def get(key: str, *, container: ContainerClient | None = None) -> SizingDecision | None:
    """Return the cached decision for `key`, or None on any miss or failure."""
    try:
        raw = _blob_client(key, container).download_blob().readall()
    except ResourceNotFoundError:
        print(f"sizing cache: miss {key[:12]}")
        return None
    except _SOFT_ERRORS as e:
        print(f"WARN: sizing cache unreadable ({e}); calling the LLM", file=sys.stderr)
        return None

    try:
        payload = json.loads(raw)
        size = payload["size"]
    except (json.JSONDecodeError, TypeError, KeyError) as e:
        print(
            f"WARN: corrupt cache entry {key[:12]} ({e}); calling the LLM",
            file=sys.stderr,
        )
        return None

    if size not in SIZES:
        print(
            f"WARN: cached size {size!r} not in {SIZES}; calling the LLM",
            file=sys.stderr,
        )
        return None

    print(
        f"sizing cache: hit {key[:12]} (written {payload.get('cached_at', 'unknown')})"
    )
    return SizingDecision(
        size=size,
        label=label_for(size),
        reason=payload.get("reason", "cached llm decision (no reason recorded)"),
        source=CACHED_SOURCE,
    )


def put(
    key: str, decision: SizingDecision, *, container: ContainerClient | None = None
) -> bool:
    """Store `decision` under `key`. Returns False if the write failed.

    A failed write is logged and ignored: the run already has its decision,
    and the next dispatch simply pays for another LLM call.
    """
    payload = json.dumps(
        {
            "size": decision.size,
            "label": decision.label,
            "reason": decision.reason,
            "source": decision.source,
            "cached_at": datetime.now(timezone.utc).isoformat(),
        }
    )

    try:
        _blob_client(key, container).upload_blob(payload, overwrite=True)
    except _SOFT_ERRORS as e:
        print(f"WARN: could not write sizing cache ({e})", file=sys.stderr)
        return False

    print(f"sizing cache: stored {key[:12]}")
    return True
