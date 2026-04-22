# Setup

## Prerequisites

- An Azure subscription you can deploy to.
- Azure CLI installed and logged in (`az login`).
- Docker (for building the runner image).
- An Azure OpenAI resource with a deployed chat model. `gpt-4o-mini` is plenty; you do not need GPT-4.
- A GitHub repository (you can fork or copy this one) and a PAT with `repo` + `workflow` scopes.
- (Optional, for real carbon-aware deferral) An [Electricity Maps](https://www.electricitymaps.com/) API key. Without one, the carbon check fails open and runs immediately. For demos you can use `CARBON_MOCK=high|low` instead.

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
- Carbon queue account URL (e.g. `https://cicdrssa.queue.core.windows.net`) — surfaced as the `carbonQueueAccountUrl` output. Goes into the `CARBON_QUEUE_ACCOUNT_URL` GitHub secret below.

The deploy provisions a storage account with `allowSharedKeyAccess: false` and a `carbon-deferred` queue, and grants the managed identity the **Storage Queue Data Message Sender** + **Processor** built-in roles. No keys to copy out.

## 2. Build & push the runner image

The first deploy in step 1 runs with `deployRunnerJobs=false` (the default in [main.bicep](../infra/main.bicep)) so the foundation lands without referencing an image that doesn't exist yet. Now build the image, push it, then re-deploy with `deployRunnerJobs=true` to actually create the three runner jobs.

```bash
./scripts/build-runner-image.sh cicdrsacr 1.0.0
```

The script tags both `:1.0.0` and `:latest` and pushes both.

On Apple Silicon (or any ARM host), `docker build` produces an ARM image that ACA — which runs x86 — won't execute. Use `buildx` with an explicit platform instead:

```bash
BASE=cicdrs   # match `baseName` in main.bicepparam
az acr login -n ${BASE}acr

docker buildx build --platform linux/amd64 \
    -t ${BASE}acr.azurecr.io/aca-gh-runner:1.0.0 \
    -t ${BASE}acr.azurecr.io/aca-gh-runner:latest \
    --push runner/
```

Then re-deploy, this time with `deployRunnerJobs=true` and the image tag you just pushed:

```bash
RG=my-rg
BASE=cicdrs

az deployment group create \
    --resource-group $RG \
    --template-file infra/main.bicep \
    --parameters infra/parameters/main.bicepparam \
    --parameters deployRunnerJobs=true \
                 runnerImage=${BASE}acr.azurecr.io/aca-gh-runner:1.0.0 \
    -o table
```

After this second deploy, `az containerapp job list -g $RG -o table` should show `cicdrs-runner-{small,medium,large}`.

### Updating the image later

When you change anything under `runner/` (Dockerfile, entrypoint, baked-in tooling), bump the tag, rebuild, push, and re-deploy with the new `runnerImage`:

```bash
TAG=1.1.0
BASE=cicdrs
RG=my-rg

az acr login -n ${BASE}acr

docker buildx build --platform linux/amd64 \
    -t ${BASE}acr.azurecr.io/aca-gh-runner:${TAG} \
    -t ${BASE}acr.azurecr.io/aca-gh-runner:latest \
    --push runner/

az deployment group create \
    --resource-group $RG \
    --template-file infra/main.bicep \
    --parameters infra/parameters/main.bicepparam \
    --parameters deployRunnerJobs=true \
                 runnerImage=${BASE}acr.azurecr.io/aca-gh-runner:${TAG} \
    -o table
```

Bump tags rather than overwriting `:latest` only — the bicep deploy is idempotent on identical inputs and will skip the job update if `runnerImage` hasn't changed, so a fresh tag forces ACA to pick up the new image on the next execution.

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
| `AZURE_CLIENT_ID` / `AZURE_CLIENT_SECRET` / `AZURE_TENANT_ID` | Service principal used by `azure/login@v2` in the dispatcher and carbon-scheduler workflows. |
| `ACA_BASE_NAME` | The `baseName` parameter from `main.bicepparam` (default `cicdrs`). |
| `RUNNER_REGISTRATION_PAT` | GitHub PAT (`repo` + `workflow` scopes) |
| `CARBON_QUEUE_ACCOUNT_URL` | `carbonQueueAccountUrl` output from the Bicep deploy (e.g. `https://cicdrssa.queue.core.windows.net`). Required for carbon-aware deferral. |
| `ELECTRICITYMAPS_API_KEY` | API key from Electricity Maps. Optional — without it, the carbon check fails open and runs immediately. |

### GitHub Actions repo *variables* (not secrets)

| Variable | Value |
|---|---|
| `GRID_ZONE` | Electricity Maps zone code (e.g. `IN-SO`, `US-CAL-CISO`, `DE`). Defaults to `IN-SO` if unset. |
| `CARBON_MOCK` | Optional. Set to `high` to force a deferral, `low` to force an immediate run. Leave unset for real Electricity Maps lookups. Useful for stage demos. |

For production you'd swap key-based AOAI auth for managed identity (`DefaultAzureCredential` + `cognitiveservices.azure.com/.default`), and replace the Azure SP with OIDC federated credentials. Keys are fine for a hackathon demo.

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

## Smoke test the carbon-aware deferral

To verify the deferral logic without burning Electricity Maps quota or waiting for a real bad-carbon day, set `CARBON_MOCK` as a repo variable and trigger [03-large-ml-training.yml](../.github/workflows/03-large-ml-training.yml) from the Actions tab with `deferrable=true`:

- `CARBON_MOCK=high` → dispatch job logs `MOCK: current 420 gCO2/kWh → defer 2h…`, emits `deferred=true`, the `train` job is skipped, a message lands in the `carbon-deferred` queue. The next [carbon-scheduler.yml](../.github/workflows/carbon-scheduler.yml) cron tick (within 10 min) re-triggers the workflow with `deferrable=false`, which then runs normally.
- `CARBON_MOCK=low` → runs immediately, no queue activity.
- Unset → real Electricity Maps lookup against `GRID_ZONE`.
