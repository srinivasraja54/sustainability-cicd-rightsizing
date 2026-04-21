# Pitch

## Problem

Regulated enterprises — banks, insurers, pharma, government — can't use GitHub-hosted or Azure DevOps Microsoft-hosted runners. Data residency, egress control, private network access, mandatory hardened images, SIEM audit requirements, and HSM-backed secrets push CI onto self-hosted runner pools.

Their typical deployment: static VM scale sets or always-on AKS runner scale sets, sized for the worst-case workload. Reality across these estates:
- 5–10× overprovisioned, because resizing a fleet is operationally expensive.
- SaaS competitors (Depot, Blacksmith, Namespace) are off-limits — same compliance reasons that rule out Microsoft-hosted runners.
- Large regulated orgs don't have the appetite to build right-sizing from scratch, so they don't.

## Contribution

A deployable reference architecture for self-hosted GitHub Actions runners on Azure Container Apps that combines three things nobody has shipped together for this workload class:

1. **Rules-first + LLM-fallback sizing dispatcher** — cheap regex heuristics classify the majority of workflows; Azure OpenAI fallback handles the ambiguous minority. Keeps per-dispatch energy + latency down.
2. **Carbon-aware deferral** — time-flexible workflows (scheduled cron, nightly batch) opt into deferral to a greener grid window via Electricity Maps + a durable queue + re-trigger scheduler.
3. **Ephemeral ACA Jobs with scale-to-zero** — three size tiers (small/medium/large) backed by Manual-triggered Container Apps Jobs. Pay per replica-second, not per hour.

All three run on infrastructure a regulated enterprise already trusts: Azure Container Apps, user-assigned managed identity, private ACR, Log Analytics for audit, no SaaS dependencies.

## Positioning against existing work

- **Right-sizing CI runners** is a commodity for SaaS platforms (GitHub large runners, GitLab runner classes, Depot, Namespace, Blacksmith). None of them serve the self-hosted regulated-enterprise case. Our contribution is bringing that economics into the one place it's absent.
- **Carbon-aware scheduling** is well-explored in research (Green Software Foundation's Carbon Aware SDK, WattTime, Electricity Maps) and operational inside hyperscaler walled gardens (Google internal batch, some Azure first-party services). It is **absent from every major CI platform** (GitHub Actions, GitLab CI, CircleCI, Buildkite, Jenkins) and effectively absent from every enterprise CI deployment we can find. The novelty is integration, not the underlying idea.
- **LLM-classifies-config-file** has been done many times since 2024. What makes it defensible here is the rules-first architecture that avoids an LLM call on every dispatch — cost, latency, and energy all line up with the sustainability framing.

## Why enterprises haven't done this yet

1. **Cultural barrier.** Developers waiting on CI don't tolerate "deferred 4h for grid reasons." Adoption requires a workflow classification (urgent vs. deferrable) that most teams haven't bothered to establish.
2. **Measurement funds itself; behavior change doesn't.** ESG reports get budget. Reducing per-workflow watts is too small a unit to justify a new internal platform team, even if the fleet-level savings are meaningful.
3. **No vendor ships the integration.** Regulated enterprises are buyers, not builders. Once a platform (GitHub, Azure DevOps, or a hyperscaler) offers "deferrable CI" as a first-class SKU, adoption starts. Until then, it stays a whiteboard.

The same three barriers double as the reasons this reference architecture matters: it de-risks (1) by scoping deferral only to opt-in/scheduled workflows, folds (2) into a combined cost+carbon savings story so it can clear a single funding bar, and addresses (3) by being deployable in an afternoon.

## Roadmap — highest-leverage next features

Ordered by enterprise-credibility impact. Each is a single sprint's work.

1. **OIDC-based runner registration (drop the PAT).** The current `RUNNER_REGISTRATION_PAT` is a long-lived secret — instant fail in a bank security review. Swap to GitHub OIDC → Entra ID federated credential → short-lived registration token via GitHub API. Biggest single credibility unlock; ~50 lines of code.
2. **Per-language / per-team image variants.** Ephemeral runners only deliver their savings if the image ships with preinstalled tooling; otherwise every job reinstalls JDK/Node/Python. Build a matrix (`aca-gh-runner-python:small`, `aca-gh-runner-java:medium`) and extend the sizing decision to also pick the right tool image.
3. **FinOps chargeback via tags.** Accept a `cost-center` / `business-unit` input on each workflow, flow it through to ACA Job execution tags, ship a Kusto query that produces a per-BU monthly cost+carbon report. Makes savings attributable to the teams paying for them — which is what gets these projects funded internally.
4. **Hardened, scanned, signed image pipeline.** Replace the demo Dockerfile with: CIS-hardened base → Trivy scan gate → cosign-sign → push to ACR with customer-managed-key encryption. Even a stubbed version (Trivy step + cosign verification) signals enterprise readiness.
5. **Audit trail of every sizing decision.** Already have `source`, `reason`, `size` per decision. Persist to Log Analytics keyed by run ID; join with CPU/memory actuals from ACA metrics; build one Kusto chart — "sizing decision vs. actual utilization over 30 days." Doubles as the training data for a closed-loop ML sizer later.

## Demo-ready features as of today

- Rules-first + LLM-fallback sizing (local + Azure).
- Three right-sized ACA Jobs with managed-identity ACR pull, scale-to-zero.
- Carbon-aware deferral with `CARBON_MOCK=high|low` for deterministic stage demos.
- Durable deferred-run queue with managed-identity-only auth (no shared keys).
- Re-trigger scheduler workflow on a 10-minute cron.
- Four sample workflows covering small/medium/large/ambiguous, each evidencing a different code path of the dispatcher.

## The one-liner

> "Right-sized, carbon-aware CI for the enterprises that can't use hosted runners — deployable in a day on infrastructure they already trust."
