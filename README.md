# Sustainability-Aware CI/CD: LLM-Driven Right-Sizing of Self-Hosted Runners on Azure

> Hackathon entry — theme: **Sustainability** — built on the Azure ecosystem (Container Apps Jobs + Azure OpenAI + GitHub Actions).

## The problem

Hosted CI runners — and the way teams *use* them — are systematically over-provisioned. A 30-second `npm install` runs on the same 4-vCPU / 16 GiB box as a nightly ML training job, because the runner label was hardcoded once and forgotten. Across an org with thousands of pipeline runs per day, this is a non-trivial source of wasted compute, wasted electricity, and wasted money.

## The idea

For every workflow run, decide the *smallest* runner size that can plausibly do the job, then start an ephemeral self-hosted runner of exactly that size on Azure Container Apps Jobs. Tear it down to zero the instant the job is done.

The decision is made by a tiny rules engine first (cheap, deterministic) and falls back to Azure OpenAI only when the workflow is genuinely ambiguous. The fallback decision is then cached per workflow-hash, so the LLM is called once per workflow change, not once per run.

## What's in this repo

```
.
├── .github/workflows/      Three sample pipelines (small / medium / large) + a reusable dispatcher
├── infra/                  Bicep IaC for ACA env, three sized runner jobs, ACR, identity
├── runner/                 Dockerfile + entrypoint for the ephemeral GitHub Actions runner
├── orchestrator/           Python: rules → Azure OpenAI fallback → start ACA Job execution
├── scripts/                deploy.sh, build-runner-image.sh
└── docs/                   architecture, setup, sustainability impact, cost comparison
```

## Quick links

- [Architecture](docs/architecture.md) — how the pieces fit together
- [Setup](docs/setup.md) — deploy it end to end
- [Sustainability impact](docs/sustainability-impact.md) — the energy/carbon story with numbers
- [Cost comparison](docs/cost-comparison.md) — **what would this save vs hardcoded labels?**

## Try the sizing logic locally (no Azure needed)

```bash
cd orchestrator
pip install -r requirements.txt
python analyze_pipeline.py --workflow ../.github/workflows/01-small-lint.yml --no-llm
python analyze_pipeline.py --workflow ../.github/workflows/03-large-ml-training.yml --no-llm
```

You should see `aca-small` and `aca-large` respectively, decided by rules without ever calling the model.
