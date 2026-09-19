# Sustainability-Aware CI/CD: Right-Sized, Carbon-Aware Self-Hosted Runners on Azure

> Hackathon entry — theme: **Sustainability** — built on the Azure ecosystem (Container Apps Jobs + Azure OpenAI + GitHub Actions).

Pick the smallest runner a job actually needs, and — when the job isn't blocking a human — run it while the grid is clean.

## The problem

Hosted CI runners — and the way teams *use* them — are systematically over-provisioned. A 30-second `npm install` runs on the same 4-vCPU / 16 GiB box as a nightly ML training job, because the runner label was hardcoded once and forgotten. Across an org with thousands of pipeline runs per day, this is a non-trivial source of wasted compute, wasted electricity, and wasted money.

## The idea

Two levers, one dispatcher: **what size** a job runs on, and **when** it runs.

### Lever 1 — right-size the runner

For every workflow run, decide the *smallest* runner size that can plausibly do the job, then start an ephemeral self-hosted runner of exactly that size on Azure Container Apps Jobs. Tear it down to zero the instant the job is done.

The decision is made by a tiny rules engine first (cheap, deterministic) and falls back to Azure OpenAI only when the workflow is genuinely ambiguous. That fallback verdict is then cached in blob storage under a SHA-256 of the workflow text, the system prompt and the model deployment ([decision_cache.py](orchestrator/decision_cache.py)), so the LLM is called once per workflow *change*, not once per run. Edit the workflow, revise the prompt or swap the model and the key changes, so a stale verdict can't outlive its inputs.

That claim is a statement about call counts, so it's tested as one: [test_analyze_pipeline.py](orchestrator/test_analyze_pipeline.py) fakes the Azure OpenAI call, dispatches the same ambiguous workflow eleven times, and asserts the model was called once.

### Lever 2 — shift it into a greener grid window

Right-sizing is well-trodden ground; SaaS platforms have sold it for years. The half that isn't shipped anywhere is moving CI *in time*. A nightly retrain doesn't care whether it starts at 02:00 or 05:00 — but the grid does, and in a coal-heavy zone the difference between those two hours can be 2× the gCO2 per kWh.

Workflows that opt in — cron schedules, nightly batch, an explicit `deferrable=true` — are checked against the [Electricity Maps](https://www.electricitymaps.com/) forecast for their region. If the next 8 hours contain a window at least **20% cleaner** than now, the run is deferred to it; otherwise it runs immediately. PR and push triggers are never eligible: developers don't tolerate "queued 4h for grid reasons."

The scheduling primitive is the part worth looking at. A deferred run goes onto an Azure Storage Queue with the message's **visibility timeout set to the delay** — so the message is simply invisible until its green window arrives. The poller ([carbon_scheduler.py](orchestrator/carbon_scheduler.py)) is then a plain drain loop: no "scan for due rows" query, no separate state store, no cron drift to reconcile. Failed re-triggers stay in-flight and reappear on the next tick for free.

If Electricity Maps is unreachable, rate-limited, or no API key is set, the run proceeds immediately. **CI never blocks on a third-party dependency.**

Two limits worth stating up front:

- Deferral saves **emissions, not energy**. The same vCPU-seconds run; they just run against a cleaner grid. An organisation whose ESG reporting is on a kWh basis sees *zero* from this lever — the right-sizing half is what moves that number.
- In already-clean grids (`FR`, `NO`, `IS`) the 20% guardrail correctly declines to shift anything, because the latency cost buys no meaningful carbon saving.

Carbon-aware scheduling is not a new idea — the Green Software Foundation, WattTime and Electricity Maps have covered the ground thoroughly. It is, however, absent from every major CI platform. The contribution here is the integration, not the concept. [Sustainability impact](docs/sustainability-impact.md) has the per-zone forecast numbers and the rest of the caveats.

## What's in this repo

```
.
├── .github/workflows/      Four sample pipelines (small / medium / large / ambiguous),
│                           a reusable dispatcher, and the carbon re-trigger scheduler
├── infra/                  Bicep IaC: ACA env, three sized runner jobs, ACR, identity,
│                           storage (deferral queue + sizing cache)
├── runner/                 Dockerfile + entrypoint for the ephemeral GitHub Actions runner
├── orchestrator/           Python: rules → cache → Azure OpenAI fallback → start ACA Job,
│                           plus the carbon forecast client, deferral queue and scheduler
├── scripts/                deploy.sh, build-runner-image.sh
└── docs/                   pitch, architecture, setup, demo steps, sustainability impact,
                            cost comparison
```

## Quick links

- [Pitch](docs/pitch.md) — who this is for, and why no CI platform ships it
- [Architecture](docs/architecture.md) — how the pieces fit together
- [Setup](docs/setup.md) — deploy it end to end
- [Demo steps](docs/demo-steps.md) — a 5-minute local track and a full Azure track
- [Sustainability impact](docs/sustainability-impact.md) — the energy/carbon story with numbers, and the caveats
- [Cost comparison](docs/cost-comparison.md) — **what would this save vs hardcoded labels?**

## Try it locally (no Azure account, no API keys)

```bash
cd orchestrator
pip install -r requirements.txt pytest

# Lever 1 — sizing, decided by rules alone
python analyze_pipeline.py --workflow ../.github/workflows/01-small-lint.yml --no-llm
python analyze_pipeline.py --workflow ../.github/workflows/03-large-ml-training.yml --no-llm
```

You should see `aca-small` and `aca-large` respectively, decided by rules without ever calling the model.

```bash
# Lever 2 — the deferral decision, with a forced-dirty grid
CARBON_MOCK=high python -c "import carbon; print(carbon.decide('IN-SO').reason)"
# → MOCK: current 420 gCO2/kWh → defer 2h to 140 gCO2/kWh window

# ...and the fail-open path, with no API key configured
python -c "import carbon; print(carbon.decide('IN-SO').reason)"
# → no ELECTRICITYMAPS_API_KEY; running now
```

The full test suite runs offline too — it fakes the model and the storage layer:

```bash
pytest -q
```
