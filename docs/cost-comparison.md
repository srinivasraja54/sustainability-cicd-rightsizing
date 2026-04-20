# Cost comparison: hardcoded labels vs dynamic right-sizing

> **Headline:** for a typical mixed-workload repo, dynamic right-sizing cuts CI compute cost by **~60–70%** vs hardcoded labels — and that ratio stays roughly constant whether you're running 100 jobs/month or 100,000.

This doc answers the question: *"if we don't implement the LLM/rules sizer and just hardcode `runs-on: self-hosted-large` on every workflow, how much money are we leaving on the table?"*

## Pricing inputs

Azure Container Apps Jobs (Consumption plan, US regions, illustrative — check current pricing):

| Resource | Rate |
|---|---|
| Active vCPU-second | $0.000024 |
| Active GiB-second | $0.000003 |
| Idle vCPU-second (when min-replicas > 0) | $0.000003 |
| Idle GiB-second | $0.000004 |
| First 180,000 vCPU-s and 360,000 GiB-s per month | free |

Our three sizes:

| Size | vCPU | RAM | Cost per second (active) |
|---|---|---|---|
| small  | 0.5 | 1 GiB | 0.5 × 0.000024 + 1 × 0.000003 = **$0.000015/s** |
| medium | 2.0 | 4 GiB | 2.0 × 0.000024 + 4 × 0.000003 = **$0.000060/s** |
| large  | 4.0 | 8 GiB | 4.0 × 0.000024 + 8 × 0.000003 = **$0.000120/s** |

**Per-job cost ratio: small : medium : large = 1 : 4 : 8.**

That ratio is the entire story.

## Per-job example (5-minute runtime)

| Size | Cost / 5-min job |
|---|---|
| small  | 300 × 0.000015 = **$0.0045** |
| medium | 300 × 0.000060 = **$0.0180** |
| large  | 300 × 0.000120 = **$0.0360** |

A small job that's been forced onto a large runner costs **8× more** than it should.

## Monthly comparison: 1,000 pipeline runs

Assume the workload mix is realistic: most jobs are lint, format, doc, or unit tests. A few are heavy.

### Scenario A — Hardcoded `self-hosted-large` (status quo at most orgs)

Every job runs on a large runner regardless of weight.

```
1,000 runs × $0.0360 = $36.00 / month
```

### Scenario B — Dynamic right-sizing, mix 70/20/10

```
700 small  × $0.0045 = $ 3.15
200 medium × $0.0180 = $ 3.60
100 large  × $0.0360 = $ 3.60
                       ──────
                       $10.35 / month
```

**Savings: $25.65/month, or 71%.**

### Scenario C — Dynamic right-sizing, mix 50/30/20

```
500 small  × $0.0045 = $ 2.25
300 medium × $0.0180 = $ 5.40
200 large  × $0.0360 = $ 7.20
                       ──────
                       $14.85 / month
```

**Savings: $21.15/month, or 59%.**

### Scenario D — Dynamic right-sizing, mix 30/40/30 (compute-heavy repo)

```
300 small  × $0.0045 = $ 1.35
400 medium × $0.0180 = $ 7.20
300 large  × $0.0360 = $10.80
                       ──────
                       $19.35 / month
```

**Savings: $16.65/month, or 46%.**

## Scaling up

The dollar figures look small at 1,000 runs. The ratio is what matters — multiply by the number of pipeline runs your org actually does:

| Pipeline runs / month | Hardcoded large | Right-sized (70/20/10) | Annual savings |
|---|---|---|---|
| 1,000      | $36       | $10        | ~$310 |
| 10,000     | $360      | $104       | ~$3.1k |
| 100,000    | $3,600    | $1,035     | ~$31k |
| 1,000,000  | $36,000   | $10,350    | ~$307k |

For comparison: GitHub-hosted Linux runners (4-vCPU) cost **$0.008/minute**, so the same 5-minute job is **$0.04** — comparable to Azure large but with no scale-to-zero between jobs.

## What the LLM costs

The fallback to Azure OpenAI is only invoked when the rules engine returns `None`. In practice that's ~5–15% of dispatches for a repo with stable workflows.

`gpt-4o-mini` pricing (illustrative): ~$0.15 per 1M input tokens, $0.60 per 1M output tokens. A typical workflow YAML is ~600 input tokens, response is ~50 output tokens. Per call: **~$0.00012**.

For 1,000 runs/month at 10% LLM-fallback rate:

```
100 LLM calls × $0.00012 = $0.012 / month
```

Negligible. The LLM is functionally free at this volume.

## Things this comparison does NOT include

- The fixed monthly cost of Log Analytics (a few dollars at this volume).
- ACR storage (cents).
- Azure OpenAI quota commitment if you've pre-purchased PTU.
- Engineering time saved by not having to manually right-size every new workflow (probably the largest hidden saving).
- Carbon-cost avoidance — see `sustainability-impact.md` for the kWh story.

## Summary for the pitch

> "If your pipelines hardcode runner labels, you're paying 2–8× more than necessary on every job. Our LLM-augmented dispatcher picks the right size automatically. For a 70/20/10 workload mix, that's a **71% reduction in CI compute cost** — and the same proportional reduction in vCPU-seconds, which is the proxy for energy use."
