#!/usr/bin/env bash
# Build the GitHub Actions runner image and push to ACR.
#
# Usage: ./scripts/build-runner-image.sh <acr-name> [tag]

set -euo pipefail

ACR="${1:?ACR name required (e.g. cicdrsacr)}"
TAG="${2:-1.0.0}"

az acr login -n "${ACR}"

docker build \
    -t "${ACR}.azurecr.io/aca-gh-runner:${TAG}" \
    -t "${ACR}.azurecr.io/aca-gh-runner:latest" \
    runner/

docker push "${ACR}.azurecr.io/aca-gh-runner:${TAG}"
docker push "${ACR}.azurecr.io/aca-gh-runner:latest"

echo "Pushed: ${ACR}.azurecr.io/aca-gh-runner:${TAG}"
