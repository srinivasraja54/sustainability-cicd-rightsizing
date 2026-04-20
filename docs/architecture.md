# Architecture

## End-to-end flow

```
GitHub event (push / PR / cron)
        │
        ▼
┌────────────────────────┐
│  dispatch job          │  runs on ubuntu-latest (free, fast, ~5s of work)
│  (in calling workflow) │
│                        │  ┌──────────────────────────────┐
│  python                │──┤ orchestrator/dispatch_runner │
│   dispatch_runner.py   │  │   1. analyze workflow YAML   │
└────────────────────────┘  │      a. rules first          │
        │                   │      b. Azure OpenAI fallback│
        │                   │   2. mint JIT GH token       │
        │                   │   3. start ACA Job execution │
        │                   └──────────────────────────────┘
        │  outputs: runner-label, size
        ▼
┌────────────────────────┐        ┌──────────────────────────┐
│  work job              │ ──────►│ ACA Job replica          │
│  runs-on:              │        │ (small | medium | large) │
│   self-hosted          │        │ - registers as ephemeral │
│   <runner-label>       │        │   GH runner              │
└────────────────────────┘        │ - picks up THIS job only │
                                  │ - exits → scale to zero  │
                                  └──────────────────────────┘
```

## Why Azure Container Apps Jobs (and not the alternatives)

| Option | Why not |
|---|---|
| Azure VM scale set | Always-on cost, slow scale-out (minutes), VM image management overhead. |
| AKS + virtual-kubelet | Powerful but heavyweight for a hackathon; you'd manage a cluster. |
| Azure Container Instances | Works, but no first-class job-completion semantics; you'd build the lifecycle yourself. |
| **Container Apps Jobs** | Purpose-built for ephemeral, event-/manual-triggered work. Per-second billing. Scale to zero. Native managed identity + ACR + Log Analytics integration. |

## Why three pre-baked job definitions instead of one dynamic one

We define `cicdrs-runner-small`, `cicdrs-runner-medium`, `cicdrs-runner-large` once in Bicep. The orchestrator picks one and starts an *execution* of it.

We deliberately do **not** create a fresh Job resource per pipeline run. Reasons:
- Job creation has higher latency than job-execution start.
- ARM throttling on resource-create is much tighter than on action-start.
- IaC stays declarative (you can `az deployment what-if` and see drift). Per-run choice is imperative — exactly the right level of dynamism.

## Why rules first, LLM second

A regex check costs ~microseconds and zero electricity. A Sonnet/4o-mini call costs ~hundreds of milliseconds and a measurable (small) amount of energy. Most workflows match obvious patterns (`pytest`, `npm ci && npm run build`, `cargo build --release`). Calling the LLM on every dispatch would burn more energy than the right-sizing saves on those simple cases.

The LLM earns its keep on workflows that mix steps in unusual ways or use tools the rules don't know — the long tail. We treat it as a fallback, not a primary brain.

## Components in this repo

| Path | Purpose |
|---|---|
| `infra/main.bicep` | Top-level IaC: Log Analytics, ACR, managed identity, ACA env, three runner jobs. |
| `infra/modules/aca-environment.bicep` | The Container Apps Environment (consumption profile). |
| `infra/modules/runner-job.bicep` | Per-size Container Apps Job definition. |
| `infra/modules/managed-identity.bicep` | UAMI + AcrPull role assignment. |
| `runner/Dockerfile` | Azure-Linux-based ephemeral GitHub runner image. |
| `runner/entrypoint.sh` | Registers (`--ephemeral --unattended`), runs one job, exits. |
| `orchestrator/sizing_rules.py` | Cheap regex/heuristic sizer. |
| `orchestrator/azure_openai_client.py` | Calls Azure OpenAI deployment with `response_format=json_object`. |
| `orchestrator/analyze_pipeline.py` | Pure decision function (no Azure side effects, easy to test/demo). |
| `orchestrator/dispatch_runner.py` | End-to-end: decide → mint token → start ACA Job execution → emit GH outputs. |
| `.github/workflows/dispatcher-reusable.yml` | Reusable workflow other pipelines can `uses:`. |
| `.github/workflows/0[1-3]-*.yml` | Three sample pipelines demonstrating the three tiers. |

## Security notes

- **Managed identity** for ACR pulls and ACA Job control. No long-lived service principal credentials in CI.
- **JIT registration tokens** are minted per-run, valid ~1 hour, used once. They never live in the image.
- **GitHub PAT** for token minting is the one persistent secret. Scope it to `repo` + `workflow` only.
- **Per-run runner label** (`aca-medium-<run-id>-<rand>`) so two parallel pipelines can't accidentally pick up each other's runner.
