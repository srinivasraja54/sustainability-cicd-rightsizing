# Setup

## Prerequisites

- An Azure subscription you can deploy to.
- Azure CLI installed and logged in (`az login`).
- Docker (for building the runner image).
- An Azure OpenAI resource with a deployed chat model. `gpt-4o-mini` is plenty; you do not need GPT-4.
- A GitHub repository (you can fork or copy this one) and a PAT with `repo` + `workflow` scopes.

## 1. Deploy the infrastructure

```bash
# Edit infra/parameters/main.bicepparam first — set baseName, githubOwner,
# githubRepo, azureOpenAiEndpoint, azureOpenAiDeployment.

./scripts/deploy.sh my-rg eastus2
```

Outputs you'll need:

- ACR login server (e.g. `cicdrsacr.azurecr.io`)
- Managed identity client ID
- ACA environment name

## 2. Build & push the runner image

```bash
./scripts/build-runner-image.sh cicdrsacr 1.0.0
```

If your local machine is ARM (Apple Silicon) and ACA runs x86, build with buildx:

```bash
docker buildx build --platform linux/amd64 \
    -t cicdrsacr.azurecr.io/aca-gh-runner:1.0.0 \
    --push runner/
```

Update `runnerImage` in `main.bicepparam` and re-run the deploy if the image tag changed.

## 3. Grant the managed identity permission to start ACA Jobs

The orchestrator authenticates as the user-assigned managed identity and calls `Microsoft.App/jobs/start/action`. Easiest path: give it **Container Apps Contributor** on the resource group.

```bash
RG=my-rg
SUB=$(az account show --query id -o tsv)
MI_PRINCIPAL_ID=$(az identity show -g $RG -n cicdrs-id --query principalId -o tsv)

az role assignment create \
    --assignee-object-id "$MI_PRINCIPAL_ID" \
    --assignee-principal-type ServicePrincipal \
    --role "Container Apps Contributor" \
    --scope "/subscriptions/$SUB/resourceGroups/$RG"
```

## 4. Add GitHub repo secrets

| Secret | Value |
|---|---|
| `AZURE_OPENAI_ENDPOINT` | `https://<your-aoai>.openai.azure.com` |
| `AZURE_OPENAI_API_KEY` | Key 1 from the AOAI resource |
| `AZURE_OPENAI_DEPLOYMENT` | Deployment name, e.g. `gpt-4o-mini` |
| `AZURE_SUBSCRIPTION_ID` | Output of `az account show --query id -o tsv` |
| `AZURE_RESOURCE_GROUP` | The RG you deployed into |
| `RUNNER_REGISTRATION_PAT` | GitHub PAT (`repo` + `workflow` scopes) |

For production you'd swap key-based AOAI auth for managed identity (`DefaultAzureCredential` + `cognitiveservices.azure.com/.default`). Keys are fine for a hackathon demo.

## 5. (Optional) Configure GitHub OIDC instead of secrets

For everything *except* the AOAI key, OIDC is cleaner:

```yaml
- uses: azure/login@v2
  with:
    client-id: ${{ secrets.AZURE_CLIENT_ID }}
    tenant-id: ${{ secrets.AZURE_TENANT_ID }}
    subscription-id: ${{ secrets.AZURE_SUBSCRIPTION_ID }}
```

Then the Python orchestrator can use `DefaultAzureCredential` without an SP secret. Out of scope for the minimum demo.

## 6. Trigger a pipeline

Go to the Actions tab and run any of the sample workflows. You should see:

1. The `dispatch` job start on `ubuntu-latest`, log the sizing decision, and complete in ~10 seconds.
2. An ACA Job execution start (visible in the Azure portal under the relevant `cicdrs-runner-*` job).
3. The downstream job pick up on the new self-hosted runner.
4. The runner replica exit; the environment scale back to zero.

## Smoke test the orchestrator without Azure

```bash
cd orchestrator
pip install -r requirements.txt
python analyze_pipeline.py --workflow ../.github/workflows/02-medium-test.yml --no-llm
# → {"size": "medium", "label": "aca-medium", "reason": "unit test suite", "source": "rules"}
```
