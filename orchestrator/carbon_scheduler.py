"""Poll the carbon-deferred queue and re-trigger each due run.

Invoked by `.github/workflows/carbon-scheduler.yml` on a cron schedule
(every 10 min by default). Reads all currently-visible messages from the
`carbon-deferred` queue, calls GitHub's `workflow_dispatch` endpoint for
each one, and deletes the message on success.

Enterprise upgrade path: swap this GitHub-hosted cron for an ACA Job with
`triggerType: Schedule` using the same script. The script itself is
host-agnostic — only the invocation differs.
"""

from __future__ import annotations

import json
import os
import sys

import requests

from deferred_queue import QUEUE_NAME, _queue_client

GH_API = "https://api.github.com"
BATCH_SIZE = 32  # max messages to drain per invocation


def _trigger_workflow_dispatch(
    repo: str, workflow: str, pat: str, deferred_from: str
) -> None:
    """POST /repos/{repo}/actions/workflows/{wf}/dispatches.

    `workflow` can be a filename (e.g. "03-large-ml-training.yml") or the
    relative path; GitHub accepts the filename portion directly.
    """
    wf_filename = workflow.rsplit("/", 1)[-1]
    resp = requests.post(
        f"{GH_API}/repos/{repo}/actions/workflows/{wf_filename}/dispatches",
        headers={
            "Authorization": f"Bearer {pat}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        json={
            "ref": "main",
            "inputs": {
                # Pass-through so the re-triggered run knows not to defer again.
                "deferrable": "false",
                "deferred_from": deferred_from,
            },
        },
        timeout=15,
    )
    resp.raise_for_status()


def drain_once() -> int:
    """Return the number of messages processed in this invocation."""
    client = _queue_client()
    pat = os.environ["GH_PAT"]

    messages = list(
        client.receive_messages(
            messages_per_page=BATCH_SIZE,
            visibility_timeout=60,  # hide while we process; delete on success
        )
    )
    if not messages:
        print(f"{QUEUE_NAME}: no due messages")
        return 0

    processed = 0
    for msg in messages:
        try:
            payload = json.loads(msg.content)
            print(
                f"Re-triggering {payload['workflow_path']} "
                f"(deferred from run {payload['original_run_id']})"
            )
            _trigger_workflow_dispatch(
                repo=payload["repo"],
                workflow=payload["workflow_path"],
                pat=pat,
                deferred_from=payload["original_run_id"],
            )
            client.delete_message(msg)
            processed += 1
        except Exception as e:
            # Leave the message in-flight; visibility timeout will let it
            # reappear so the next scheduler run can retry.
            print(f"WARN: failed to re-trigger; will retry: {e}", file=sys.stderr)

    print(f"{QUEUE_NAME}: processed {processed}/{len(messages)}")
    return processed


if __name__ == "__main__":
    sys.exit(0 if drain_once() >= 0 else 1)
