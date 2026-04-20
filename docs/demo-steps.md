# Steps for the demo

Two tracks: a **local-only demo** (fast, no Azure) and a **full end-to-end demo** (Azure + GitHub). Pick one based on how much time and infrastructure you have.

## Track 1 — Local demo (5 minutes, no Azure)

Shows the rules-vs-LLM sizing logic. Fastest way to prove the concept and capture results.

### Steps

```bash
cd orchestrator
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

mkdir -p ../demo-results

# Small (lint) — expect aca-small, source=rules
python analyze_pipeline.py --workflow ../.github/workflows/01-small-lint.yml --no-llm \
  | tee ../demo-results/01-small.json

# Medium (unit tests) — expect aca-medium, source=rules
python analyze_pipeline.py --workflow ../.github/workflows/02-medium-test.yml --no-llm \
  | tee ../demo-results/02-medium.json

# Large (ML training) — expect aca-large, source=rules
python analyze_pipeline.py --workflow ../.github/workflows/03-large-ml-training.yml --no-llm \
  | tee ../demo-results/03-large.json
```

Each JSON captures `size`, `label`, `reason`, `source` — these are your evidence artifacts.

### Optional: show the LLM fallback

Set Azure OpenAI env vars and drop `--no-llm` on a workflow the rules can't classify. `source` flips from `rules` to `llm`.

```bash
export AZURE_OPENAI_ENDPOINT=...
export AZURE_OPENAI_API_KEY=...
export AZURE_OPENAI_DEPLOYMENT=gpt-4o-mini

python analyze_pipeline.py --workflow <ambiguous.yml> | tee ../demo-results/llm-fallback.json
```

## Track 2 — End-to-end on Azure

Follows [setup.md](setup.md) — summarized here with the evidence-capture steps added.

1. **Deploy infra** — edit `infra/parameters/main.bicepparam`, then `./scripts/deploy.sh my-rg eastus2`. Capture the output (ACR login server, UAMI client ID, ACA env name).
2. **Build & push runner image** — `./scripts/build-runner-image.sh cicdrsacr 1.0.0` (or the `buildx --platform linux/amd64` variant on Apple Silicon).
3. **Grant RBAC** — Container Apps Contributor on the resource group to the user-assigned managed identity.
4. **Add GitHub secrets** — the six listed in [setup.md](setup.md#4-add-github-repo-secrets).
5. **Trigger each sample workflow** from the Actions tab:
   - [01-small-lint.yml](../.github/workflows/01-small-lint.yml)
   - [02-medium-test.yml](../.github/workflows/02-medium-test.yml)
   - [03-large-ml-training.yml](../.github/workflows/03-large-ml-training.yml)

### Evidence to capture per run

| Artifact | Where to get it |
|---|---|
| Dispatch job log showing `runner-label` + `size` output | GitHub Actions run → `dispatch` job |
| ACA Job execution (name, duration, vCPU/GiB) | Azure Portal → `cicdrs-runner-{small,medium,large}` → Executions |
| Runner replica logs (register → run → exit) | Log Analytics, or the execution's Console tab |
| Scale-to-zero confirmation | ACA env → replicas = 0 after job ends |
| Per-run billable seconds | Execution duration × size rate from [cost-comparison.md](cost-comparison.md) |

Screenshot each, or dump executions to a file:

```bash
az containerapp job execution list \
    -g my-rg -n cicdrs-runner-small  -o table > demo-results/executions-small.txt
az containerapp job execution list \
    -g my-rg -n cicdrs-runner-medium -o table > demo-results/executions-medium.txt
az containerapp job execution list \
    -g my-rg -n cicdrs-runner-large  -o table > demo-results/executions-large.txt
```

## Results summary to produce

Build a single table from the captured data to tell the story:

| Workflow | Decided size | Source (rules/llm) | Duration | Cost on right-sized | Cost if forced to `large` | Savings |
|---|---|---|---|---|---|---|
| 01-small-lint | aca-small | rules | ~Xs | $… | $… | …% |
| 02-medium-test | aca-medium | rules | ~Xs | $… | $… | …% |
| 03-large-ml-training | aca-large | rules | ~Xs | $… | $… | 0% (baseline) |

Use the per-second rates in [cost-comparison.md](cost-comparison.md#pricing-inputs) for the math. That table plus the rules-vs-LLM split is the demo.

## Cleanup (Track 2 only)

```bash
az group delete -n my-rg --yes --no-wait
```

Avoids lingering Log Analytics / ACR charges after the demo.
