"""End-to-end dispatcher invoked from the GitHub Actions `dispatch` job.

Pipeline:

    1. Decide size  ──► sizing_rules (cheap)  ──► Azure OpenAI (fallback)
    2. Mint a one-shot GitHub runner registration token via the REST API.
    3. Start the matching ACA Job execution, overriding the env so the
       runner registers with the right URL/token/labels.
    4. Emit `runner-label` and `size` as GitHub Actions outputs so the
       calling workflow's next job can target the runner.

The container app job itself is created once by `infra/main.bicep`; we
only *start an execution* of it here. That's the right level of dynamism:
the IaC is declarative, the per-pipeline choice is imperative.
"""

from __future__ import annotations

import argparse
import os
import sys
import uuid
from pathlib import Path

import requests
from azure.identity import DefaultAzureCredential
from azure.mgmt.appcontainers import ContainerAppsAPIClient

from analyze_pipeline import analyze

GH_API = "https://api.github.com"


def get_jit_registration_token(repo: str, pat: str) -> str:
    """POST /repos/{owner}/{repo}/actions/runners/registration-token.

    Returns a one-shot token valid for ~1 hour. It's the canonical way
    to register an ephemeral runner without baking long-lived secrets
    into the image.
    """
    resp = requests.post(
        f"{GH_API}/repos/{repo}/actions/runners/registration-token",
        headers={
            "Authorization": f"Bearer {pat}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()["token"]


def start_runner_job(
    *,
    subscription_id: str,
    resource_group: str,
    base_name: str,
    size: str,
    runner_token: str,
    labels: str,
    repo: str,
) -> str:
    """Start one execution of the size-specific Container Apps Job.

    Returns the execution name so the caller can correlate logs.
    """
    owner, name = repo.split("/", 1)
    job_name = f"{base_name}-runner-{size}"

    client = ContainerAppsAPIClient(
        credential=DefaultAzureCredential(),
        subscription_id=subscription_id,
    )

    # The ACA Jobs start API requires `image` in the container override
    # (it does not inherit from the job definition). Fetch it.
    job = client.jobs.get(resource_group_name=resource_group, job_name=job_name)
    image = job.template.containers[0].image

    # Override env on this single execution so we can inject the
    # one-shot registration token without persisting it on the job def.
    template_override = {
        "containers": [
            {
                "name": "runner",
                "image": image,
                "env": [
                    {"name": "GH_OWNER", "value": owner},
                    {"name": "GH_REPO", "value": name},
                    {"name": "RUNNER_LABELS", "value": labels},
                    {"name": "RUNNER_TOKEN", "value": runner_token},
                ],
            }
        ]
    }

    poller = client.jobs.begin_start(
        resource_group_name=resource_group,
        job_name=job_name,
        template=template_override,
    )
    execution = poller.result()
    return execution.name


def write_gh_output(key: str, value: str) -> None:
    """Append to $GITHUB_OUTPUT so downstream jobs can read it."""
    out_path = os.environ.get("GITHUB_OUTPUT")
    if not out_path:
        print(f"::set-output name={key}::{value}")  # local fallback
        return
    with open(out_path, "a", encoding="utf-8") as f:
        f.write(f"{key}={value}\n")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workflow", required=True, type=Path)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--base-name", default=os.environ.get("ACA_BASE_NAME", "cicdrs"))
    args = parser.parse_args()

    decision = analyze(args.workflow, allow_llm=True)
    size = decision["size"]
    base_label = decision["label"]
    # Per-run label so the calling workflow targets *this* runner only.
    unique_label = f"{base_label}-{args.run_id}-{uuid.uuid4().hex[:6]}"
    full_labels = f"{base_label},{unique_label},ephemeral"

    print(f"Sizing decision: {decision}")
    print(f"Runner labels:   {full_labels}")

    repo = os.environ["GH_REPO"]
    pat = os.environ["GH_PAT"]
    token = get_jit_registration_token(repo, pat)

    execution = start_runner_job(
        subscription_id=os.environ["AZURE_SUBSCRIPTION_ID"],
        resource_group=os.environ["AZURE_RESOURCE_GROUP"],
        base_name=args.base_name,
        size=size,
        runner_token=token,
        labels=full_labels,
        repo=repo,
    )
    print(f"Started ACA Job execution: {execution}")

    write_gh_output("runner-label", unique_label)
    write_gh_output("size", size)
    write_gh_output("reason", decision["reason"])
    write_gh_output("source", decision["source"])

    return 0


if __name__ == "__main__":
    sys.exit(main())
