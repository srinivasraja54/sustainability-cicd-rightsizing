# Sustainability-Aware CI/CD

Right-sized, carbon-aware self-hosted GitHub Actions runners on Azure Container Apps Jobs.
Pick the smallest runner a job needs and, when nobody is waiting on it, run it while the grid is clean.

## How it works

**1. Right-size the runner.** A rules engine sizes each workflow (free, deterministic). Only
genuinely ambiguous workflows go to Azure OpenAI, and that verdict is cached under a SHA-256 of
the workflow, prompt and model deployment ([decision_cache.py](orchestrator/decision_cache.py)).
So the model runs once per workflow *change*, not once per run. A test dispatches the same
workflow 11 times and asserts exactly one model call
([test_analyze_pipeline.py](orchestrator/test_analyze_pipeline.py)).

**2. Shift it into a greener window.** Opt-in jobs (cron, nightly, `deferrable=true`) are checked
against the [Electricity Maps](https://www.electricitymaps.com/) forecast. If a window in the
next 8 hours is at least **20% cleaner**, the run is deferred onto an Azure Storage Queue with
the visibility timeout set to the delay, so it reappears exactly when the window opens
([carbon_scheduler.py](orchestrator/carbon_scheduler.py)). PR and push runs are never deferred.

**CI never blocks on a dependency.** If the model, the cache or the carbon API fails, the run
proceeds: the model falls back to a `medium` runner, the cache to a fresh model call, and the
carbon check to running now.

## Limits

- Deferral saves **emissions, not energy**: the same vCPU-seconds run on a cleaner grid.
  Right-sizing is what reduces kWh.
- In already-clean grids (`FR`, `NO`, `IS`) the 20% guardrail rightly defers nothing.
- The savings figures in [cost comparison](docs/cost-comparison.md) are estimates, not
  measurements.

## Try it locally (no Azure account, no API keys)

```bash
cd orchestrator
pip install -r requirements.txt pytest

python analyze_pipeline.py --workflow ../.github/workflows/01-small-lint.yml --no-llm   # aca-small
python analyze_pipeline.py --workflow ../.github/workflows/03-large-ml-training.yml --no-llm  # aca-large
CARBON_MOCK=high python -c "import carbon; print(carbon.decide('IN-SO').reason)"   # defers 2h
pytest -q   # full suite, model and storage faked
```

## Repo layout

`orchestrator/` Python sizing, cache, carbon and dispatch · `infra/` Bicep ·
`runner/` ephemeral runner image · `.github/workflows/` sample pipelines, dispatcher, scheduler ·
`docs/` [architecture](docs/architecture.md), [setup](docs/setup.md),
[demo steps](docs/demo-steps.md), [sustainability impact](docs/sustainability-impact.md),
[cost comparison](docs/cost-comparison.md), [pitch](docs/pitch.md)

MIT licensed.
