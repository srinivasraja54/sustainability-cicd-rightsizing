"""Durable queue for carbon-deferred workflow runs.

When `dispatch_runner.py` decides to defer a workflow to a greener grid
window, it drops a message onto an Azure Storage Queue with a visibility
timeout equal to the delay. The message only becomes visible to the
scheduler when its scheduled time has arrived — so the scheduler is a
plain poll loop, no "scan for due rows" logic.

Queue name: `carbon-deferred` (created by storage.bicep).
Auth: DefaultAzureCredential — managed identity in CI, az-login locally.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone

from azure.identity import DefaultAzureCredential
from azure.storage.queue import QueueClient

QUEUE_NAME = "carbon-deferred"
MAX_VISIBILITY_SECONDS = 7 * 24 * 3600  # Azure hard limit


@dataclass(frozen=True)
class DeferredRun:
    repo: str
    workflow_path: str
    scheduled_for_utc: str
    original_run_id: str
    reason: str


def _queue_client(account_url: str | None = None) -> QueueClient:
    account_url = account_url or os.environ["CARBON_QUEUE_ACCOUNT_URL"]
    return QueueClient(
        account_url=account_url,
        queue_name=QUEUE_NAME,
        credential=DefaultAzureCredential(),
        message_encode_policy=None,
        message_decode_policy=None,
    )


def enqueue(run: DeferredRun) -> None:
    """Put a deferred run on the queue with delay = (scheduled_for - now)."""
    scheduled = datetime.fromisoformat(run.scheduled_for_utc)
    delay = (scheduled - datetime.now(timezone.utc)).total_seconds()
    delay = max(0, min(int(delay), MAX_VISIBILITY_SECONDS))

    payload = json.dumps(
        {
            "repo": run.repo,
            "workflow_path": run.workflow_path,
            "scheduled_for_utc": run.scheduled_for_utc,
            "original_run_id": run.original_run_id,
            "reason": run.reason,
        }
    )

    client = _queue_client()
    client.send_message(payload, visibility_timeout=delay)
    print(f"Enqueued deferred run (visible in {delay}s): {run.original_run_id}")
