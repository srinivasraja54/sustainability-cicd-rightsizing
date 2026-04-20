#!/usr/bin/env bash
# One-shot deploy of the right-sizing CI/CD demo.
#
# Prereqs:
#   - az CLI logged in (`az login`)
#   - target subscription set (`az account set --subscription <id>`)
#   - an Azure OpenAI resource exists with a deployment (e.g. gpt-4o-mini)
#   - GitHub PAT with `repo` + `workflow` scopes for the target repo
#
# Usage:
#   ./scripts/deploy.sh <resource-group> <location>

set -euo pipefail

RG="${1:?resource group required}"
LOC="${2:-eastus2}"

az group create -n "${RG}" -l "${LOC}" -o none

az deployment group create \
    --resource-group "${RG}" \
    --template-file infra/main.bicep \
    --parameters infra/parameters/main.bicepparam \
    -o table

echo
echo "Deployment complete. Next steps:"
echo "  1. Build & push the runner image to the ACR shown above."
echo "  2. Add these secrets to your GitHub repo:"
echo "       AZURE_OPENAI_ENDPOINT"
echo "       AZURE_OPENAI_API_KEY"
echo "       AZURE_OPENAI_DEPLOYMENT"
echo "       AZURE_SUBSCRIPTION_ID"
echo "       AZURE_RESOURCE_GROUP"
echo "       RUNNER_REGISTRATION_PAT"
echo "  3. Trigger one of the sample workflows (Actions tab)."
