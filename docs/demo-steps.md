# Steps for the demo

Three tracks:

1. **Local-only demo** — rules-vs-LLM sizing logic. Fast, no Azure, ~5 min.
2. **End-to-end on Azure** — right-sized ACA Job execution per pipeline.
3. **Carbon-aware deferral** — workflow defers itself to a greener grid window, scheduler re-triggers it. Requires Track 2 deployed.

Pick based on how much time and infrastructure you have.

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

[04-ambiguous-terraform.yml](../.github/workflows/04-ambiguous-terraform.yml) is deliberately written so none of its commands (`terraform init/plan/apply`) match any regex in [sizing_rules.py](../orchestrator/sizing_rules.py) — so `decide_from_rules` returns `None` and the analyzer hands off to Azure OpenAI.

First, confirm the rules don't classify it (should print `"source": "default"`):

```bash
python analyze_pipeline.py --workflow ../.github/workflows/04-ambiguous-terraform.yml --no-llm
```

Then set the Azure OpenAI env vars and rerun without `--no-llm` — `source` flips to `llm`:

```bash
export AZURE_OPENAI_ENDPOINT=...
export AZURE_OPENAI_API_KEY=...
export AZURE_OPENAI_DEPLOYMENT=gpt-5-nano

python analyze_pipeline.py --workflow ../.github/workflows/04-ambiguous-terraform.yml \
  | tee ../demo-results/04-llm-fallback.json
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

| Artifact                                                | Where to get it                                                              |
| ------------------------------------------------------- | ---------------------------------------------------------------------------- |
| Dispatch job log showing `runner-label` + `size` output | GitHub Actions run → `dispatch` job                                          |
| ACA Job execution (name, duration, vCPU/GiB)            | Azure Portal → `cicdrs-runner-{small,medium,large}` → Executions             |
| Runner replica logs (register → run → exit)             | Log Analytics, or the execution's Console tab                                |
| Scale-to-zero confirmation                              | ACA env → replicas = 0 after job ends                                        |
| Per-run billable seconds                                | Execution duration × size rate from [cost-comparison.md](cost-comparison.md) |

Screenshot each, or dump executions to a file:

```bash
az containerapp job execution list \
    -g my-rg -n cicdrs-runner-small  -o table > demo-results/executions-small.txt
az containerapp job execution list \
    -g my-rg -n cicdrs-runner-medium -o table > demo-results/executions-medium.txt
az containerapp job execution list \
    -g my-rg -n cicdrs-runner-large  -o table > demo-results/executions-large.txt
```

## Track 3 — Carbon-aware deferral

Demonstrates that a deferrable workflow waits for a greener grid window and is re-triggered automatically. Uses `CARBON_MOCK` so you don't have to wait for a real bad-carbon day.

### Setup (one-time)

In the GitHub repo settings → **Secrets and variables → Actions → Variables**, add:

- `CARBON_MOCK` = `high`  (forces the dispatcher to defer)
- `GRID_ZONE` = e.g. `IN-SO`  (only used when `CARBON_MOCK` is unset, but harmless to set)

Confirm `CARBON_QUEUE_ACCOUNT_URL` is set in **Secrets** (from the Bicep deploy output — see [setup.md](setup.md#1-deploy-the-infrastructure)).

### Demo flow

1. **Trigger the deferrable workflow.** From the Actions tab, run [03-large-ml-training.yml](../.github/workflows/03-large-ml-training.yml) with `deferrable=true` (the default).
2. **Show the dispatch job log.** It should print:
   ```
   Carbon check (IN-SO): MOCK: current 420 gCO2/kWh → defer 2h to 140 gCO2/kWh window
   Enqueued deferred run (visible in 7200s): <run-id>
   ```
   Outputs: `deferred=true`, `scheduled-for=<future ISO timestamp>`, `current-gco2=420`, `scheduled-gco2=140`.
3. **Show the `train` job is skipped.** Its `if: needs.dispatch.outputs.deferred != 'true'` gate keeps it from consuming a runner.
4. **Show the queue.** In the Azure Portal → Storage account → Queues → `carbon-deferred`, the message is present but **not visible** until its scheduled time.
   ```bash
   az storage message peek \
       --account-name <your-sa> --queue-name carbon-deferred \
       --auth-mode login
   # → empty list (message is hidden)
   ```
5. **Show automatic re-trigger.** Either wait for the next [carbon-scheduler.yml](../.github/workflows/carbon-scheduler.yml) cron tick (≤10 min), or manually run it from the Actions tab. For an instant demo, lower the mock delay in [carbon.py](../orchestrator/carbon.py) to e.g. 30s before the demo.
6. **Show the re-triggered run.** A new run of `03-large-ml-training.yml` appears with `inputs.deferrable=false` and `inputs.deferred_from=<original-run-id>` — proving the loop closes without entering another deferral.
7. **Flip to `low` to show fail-open.** Set `CARBON_MOCK=low` and re-trigger; dispatch logs `MOCK: current 140 gCO2/kWh already green` and the workflow runs immediately.

### Evidence to capture

| Artifact | Where |
|---|---|
| Dispatch log: carbon decision + queue enqueue | GitHub Actions run → `dispatch` job |
| `train` job skipped | GitHub Actions run → `train` job ("Skipped") |
| Queue message hidden until scheduled time | Azure Portal → Storage → Queues, or `az storage message peek` |
| Carbon scheduler workflow draining the queue | Actions tab → "Carbon-Deferred Run Scheduler" run logs |
| Re-triggered workflow run with `deferred_from` set | Actions tab → original workflow → new run |

### Talking point

> "The same workload, same code, ran when the grid was 67% cleaner — without a developer having to think about it. PR builds stay synchronous; only opt-in deferrable workflows wait."

## Results summary to produce

Build a single table from the captured data to tell the story:

| Workflow             | Decided size | Source (rules/llm) | Duration | Cost on right-sized | Cost if forced to `large` | Savings       |
| -------------------- | ------------ | ------------------ | -------- | ------------------- | ------------------------- | ------------- |
| 01-small-lint        | aca-small    | rules              | ~Xs      | $…                  | $…                        | …%            |
| 02-medium-test       | aca-medium   | rules              | ~Xs      | $…                  | $…                        | …%            |
| 03-large-ml-training | aca-large    | rules              | ~Xs      | $…                  | $…                        | 0% (baseline) |

Use the per-second rates in [cost-comparison.md](cost-comparison.md#pricing-inputs) for the math. That table plus the rules-vs-LLM split is the demo.

## Cleanup (Tracks 2 & 3)

```bash
az group delete -n my-rg --yes --no-wait
```

Avoids lingering Log Analytics / ACR / storage charges after the demo. Also clear the `CARBON_MOCK` repo variable if you set it for Track 3 — otherwise every subsequent run of `03-large-ml-training.yml` will try to defer.
