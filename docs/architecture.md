# Architecture

## End-to-end flow

```
GitHub event (push / PR / cron / workflow_dispatch)
        │
        ▼
┌────────────────────────┐
│  dispatch job          │  runs on ubuntu-latest (free, fast, ~5s of work)
│  (in calling workflow) │
│                        │  ┌──────────────────────────────────────────┐
│  python                │──┤ orchestrator/dispatch_runner.py          │
│   dispatch_runner.py   │  │                                          │
│   [--deferrable]       │  │  if --deferrable:                        │
└────────────────────────┘  │    A. carbon.decide(zone)                │
        │                   │       (Electricity Maps forecast)        │
        │                   │    B. if defer:                          │
        │                   │         enqueue → carbon-deferred queue  │
        │                   │         emit deferred=true → exit 0      │
        │                   │                                          │
        │                   │  otherwise:                              │
        │                   │    1. analyze workflow YAML              │
        │                   │       a. rules first                     │
        │                   │       b. Azure OpenAI fallback           │
        │                   │    2. mint JIT GH token                  │
        │                   │    3. start ACA Job execution            │
        │                   └──────────────────────────────────────────┘
        │  outputs: runner-label, size, deferred, scheduled-for
        ▼
┌────────────────────────┐        ┌──────────────────────────┐
│  work job              │ ──────►│ ACA Job replica          │
│  if: deferred != true  │        │ (small | medium | large) │
│  runs-on:              │        │ - registers as ephemeral │
│   self-hosted          │        │   GH runner              │
│   <runner-label>       │        │ - picks up THIS job only │
└────────────────────────┘        │ - exits → scale to zero  │
                                  └──────────────────────────┘

Deferred branch (parallel, runs every 10 min):

┌────────────────────────────┐      ┌──────────────────────────────┐
│ carbon-scheduler.yml       │ ────►│ Azure Storage Queue          │
│ cron: */10 * * * *         │      │  carbon-deferred             │
│  python carbon_scheduler   │      │  - message visible at        │
│    .py                     │      │    scheduled green window    │
└────────────────────────────┘      └──────────────────────────────┘
        │  for each due message:
        │  POST /actions/workflows/{wf}/dispatches
        ▼  with inputs.deferrable=false → re-enters dispatch flow
```

## Carbon-aware deferral

Time-flexible workflows (cron schedules, nightly batches, opt-in `deferrable=true` via `workflow_dispatch`) can wait for a greener grid window. PR/push triggers stay synchronous — developers don't tolerate "deferred 4h for grid reasons."

### Decision logic ([carbon.py](../orchestrator/carbon.py))

1. Hit the Electricity Maps `/carbon-intensity/forecast` endpoint for `GRID_ZONE` (default `IN-SO`).
2. If current grid intensity is already below `threshold_gco2` (default 250 gCO2/kWh) → run now.
3. Otherwise look at the next `max_defer_hours` (default 8h). Pick the cleanest forecast point.
4. Only defer if the cleanest window is at least **20% cleaner** than now — otherwise the deferral isn't worth the latency hit.
5. Any error (no API key, network failure, empty forecast) → run now. **CI must never block on a third-party dependency.**

Demo hooks: `CARBON_MOCK=high` forces a deferral; `CARBON_MOCK=low` forces an immediate run. Useful for stage demos where the real forecast won't cooperate on cue.

### Durable queue ([deferred_queue.py](../orchestrator/deferred_queue.py))

Azure Storage Queue named `carbon-deferred`. Auth is **managed identity only** — `allowSharedKeyAccess: false` on the storage account, so there are no SAS tokens or access keys to leak.

Trick: when we enqueue, we set the message's **visibility timeout** equal to `(scheduled_for - now)`. The message simply isn't visible until its green window arrives. The scheduler is then a plain poll loop — no "scan for due rows" logic, no separate state store.

### Re-trigger scheduler ([carbon_scheduler.py](../orchestrator/carbon_scheduler.py) + [carbon-scheduler.yml](../.github/workflows/carbon-scheduler.yml))

A GitHub Actions workflow on a 10-minute cron drains the queue and calls `POST /repos/{owner}/{repo}/actions/workflows/{wf}/dispatches` for each due message. The re-triggered run receives `inputs.deferrable=false` so it doesn't enter another deferral loop.

If the dispatch fails, the message stays in-flight — the visibility timeout (60s) lets it reappear so the next cron tick retries.

**Enterprise upgrade path:** swap the GitHub-hosted cron for an ACA Job with `triggerType: Schedule` pointing at the same `carbon_scheduler.py`. Same script, same queue — only the host changes.

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
| `infra/main.bicep` | Top-level IaC: Log Analytics, ACR, managed identity, ACA env, storage+queue, three runner jobs. |
| `infra/modules/aca-environment.bicep` | The Container Apps Environment (consumption profile). |
| `infra/modules/runner-job.bicep` | Per-size Container Apps Job definition. |
| `infra/modules/managed-identity.bicep` | UAMI + AcrPull role assignment. |
| `infra/modules/storage.bicep` | Storage account + `carbon-deferred` queue + Queue Sender/Processor RBAC for the UAMI. Shared-key access disabled. |
| `runner/Dockerfile` | Azure-Linux-based ephemeral GitHub runner image. |
| `runner/entrypoint.sh` | Registers (`--ephemeral --unattended`), runs one job, exits. |
| `orchestrator/sizing_rules.py` | Cheap regex/heuristic sizer. |
| `orchestrator/azure_openai_client.py` | Calls Azure OpenAI deployment with `response_format=json_object`. |
| `orchestrator/analyze_pipeline.py` | Pure decision function (no Azure side effects, easy to test/demo). |
| `orchestrator/carbon.py` | Electricity Maps client + defer/no-defer decision (with `CARBON_MOCK` demo hooks). |
| `orchestrator/deferred_queue.py` | Azure Storage Queue wrapper; visibility-timeout = delay-until-green-window. |
| `orchestrator/dispatch_runner.py` | End-to-end: (optional) carbon check → decide → mint token → start ACA Job execution → emit GH outputs. |
| `orchestrator/carbon_scheduler.py` | Drains the `carbon-deferred` queue and calls `workflow_dispatch` for each due run. |
| `.github/workflows/dispatcher-reusable.yml` | Reusable workflow other pipelines can `uses:`. |
| `.github/workflows/carbon-scheduler.yml` | Cron (`*/10 * * * *`) wrapper that runs `carbon_scheduler.py`. |
| `.github/workflows/0[1-3]-*.yml` | Three sample pipelines demonstrating the size tiers (03 also opts into deferral). |
| `.github/workflows/04-ambiguous-terraform.yml` | Sample pipeline that exercises the LLM fallback (no rule matches `terraform`). |

## Security notes

- **Managed identity** for ACR pulls, ACA Job control, *and* the carbon-deferred queue (both enqueue and drain). No long-lived service principal credentials for any Azure plane.
- **Storage account is key-less.** `allowSharedKeyAccess: false` — the queue is reachable only via Entra-ID-issued tokens. No SAS, no access keys to leak.
- **JIT registration tokens** are minted per-run, valid ~1 hour, used once. They never live in the image.
- **GitHub PAT** for token minting is the one persistent secret. Scope it to `repo` + `workflow` only. (Roadmap item: replace with OIDC + short-lived registration token — see [pitch.md](pitch.md#roadmap--highest-leverage-next-features).)
- **Per-run runner label** (`aca-medium-<run-id>-<rand>`) so two parallel pipelines can't accidentally pick up each other's runner.
- **Carbon API failures fail open**, not closed: if Electricity Maps is down or the key is missing, the workflow runs immediately rather than blocking CI.
