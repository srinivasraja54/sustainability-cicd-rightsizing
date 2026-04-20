#!/usr/bin/env bash
# Ephemeral GitHub Actions runner. Registers with a JIT config token,
# picks up exactly one job, then exits — which causes the ACA Job
# replica to terminate, returning compute to zero.
#
# Required env vars (injected by orchestrator at job-start time):
#   GH_OWNER         - GitHub org/user
#   GH_REPO          - Repo name
#   RUNNER_LABELS    - Comma-separated labels (e.g. "aca-medium,ephemeral")
#   RUNNER_TOKEN     - One-shot registration token from GitHub API
#                      (POST /repos/{owner}/{repo}/actions/runners/registration-token)

set -euo pipefail

: "${GH_OWNER:?GH_OWNER required}"
: "${GH_REPO:?GH_REPO required}"
: "${RUNNER_LABELS:?RUNNER_LABELS required}"
: "${RUNNER_TOKEN:?RUNNER_TOKEN required}"

RUNNER_NAME="aca-${HOSTNAME:-runner}-$(date +%s)"

cd /home/runner

./config.sh \
    --url "https://github.com/${GH_OWNER}/${GH_REPO}" \
    --token "${RUNNER_TOKEN}" \
    --name "${RUNNER_NAME}" \
    --labels "${RUNNER_LABELS}" \
    --ephemeral \
    --unattended \
    --replace

cleanup() {
    ./config.sh remove --token "${RUNNER_TOKEN}" || true
}
trap cleanup EXIT

./run.sh
