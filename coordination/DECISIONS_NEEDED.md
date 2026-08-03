FROM: CLAUDE
RE: decisions arising from task 006, plus the three standing constraints

Full detail is in `coordination/CLAUDE_REPORT.md` (task 006). This file is the short
actionable list.

Two families are closed and must not be revisited: **FX cross-sectional momentum 3M-1M V1**
and **FX policy-rate differential V2**. Both simulators are certified and reusable.

**Exactly one hypothesis is open: liquidation cascades (H4), and it is gated.**

---

# A. New — three decisions from the task 006 audit

## A1. The liquidation feed may be truncating the cascades themselves ⚠ most urgent

The OKX endpoint returns **at most 100 events per poll**. Four minutes have already carried
**≥ 90 events**; the busiest carried **193**.

Cascades are *by definition* the busiest minutes, so the feed may be silently dropping the
largest part of exactly the episodes H4 is about. A cascade whose true size is clipped is
recorded as a smaller bucket, which can push it below the top-5% threshold and out of the
sample entirely.

This is a **data-loss risk that compounds every day it is not addressed**, and the history
cannot be backfilled.

I did **not** change it: task 006 forbade modifying recorder settings, and I kept to that.

**Decision needed:** whether to shorten the derivs recorder's poll interval (30 s was the
suggestion already in `data_readiness.py`) or otherwise raise the cap. This is a recorder
change, so it needs an explicit instruction — and ideally soon, because every day at the
current interval is a day of possibly-clipped cascades.

## A2. `study/data_readiness.py` does not implement the frozen definition

It reports **14** independent cascades where the preregistered rule gives **5**, and it is
the origin of the "~85 days" figure that had propagated into `HANDOFF.md`.

Three divergences, all loosening:

| | `data_readiness.py` | Frozen preregistration |
|---|---|---|
| Unit | individual **event** | 5-minute **bucket**, total size |
| Threshold | 90th percentile | **95th** percentile |
| Ranked against | whole sample | **trailing 30 days** |
| Holdout arm | ignored (targets 400) | required (needs ~533 total) |

I left it unchanged — out of scope for task 006 — and documented the divergence in
`HANDOFF.md` and `RESEARCH_MAP.md`.

**Decision needed:** align `data_readiness.py` with the frozen definition, or retire its H4
row and point it at `study/liquidation_readiness_audit.py`. Leaving two disagreeing numbers
in the repo is how the wrong one got into the handoff in the first place.

## A3. The gate is far further away than the project believed

Corrected position under the frozen definition:

| | |
|---|---|
| Independent cascades so far | **5** (4 development, 1 holdout) |
| Remaining | **396 development, 99 holdout** |
| Rough pace | ~1.55/day → **several hundred days**, not 85 |

The trigger remains the **count**, never a date, and pace is regime-dependent.

**Decision needed:** whether the project waits, or whether the gate/horizon assumptions are
revisited **now, before any outcome is seen**. Changing a preregistered gate after looking at
results would destroy its purpose; changing it now, with no outcome examined, is legitimate
and must be logged as a dated amendment in `PREREGISTRATION_liquidations.md`.

I am not proposing a change — only flagging that if one is wanted, this is the only honest
moment for it.

---

# B. Standing — the three constraints from before task 006

Unchanged and still unanswered. These are properties of the **account and broker**, not of
either failed idea, so any future family inherits them.

## B1. The broker pays zero carry on the side that should earn it

Measured across all 19 executable pairs (004A), then confirmed inside a backtest (005): the
2026 swap snapshot moved V2's result by **$0.00 on every one of 47 trades**. Any family whose
edge is *holding* rather than *moving* collects nothing here by construction.

**Needed:** may a future family depend on being paid to hold? If yes, the venue must change.

## B2. Stop size decides whether a sample exists

| | V1 (2.0 × ATR) | V2 (1.5 × ATR) |
|---|---|---|
| Skipped on the risk gate | 33 of 55 | 11 of 58 |
| Completed trades | 22 (bar 40 — failed) | 47 (bar 45 — passed) |

The 1.50% risk gate sits almost exactly on the cheapest position the broker will open.

**Needed:** stop multiple and trade-count bar fixed **together, before the run**.

## B3. The executable panel has no development period

Canonical H1 starts 2021-08-02; development has ended 2021-07-31 in every spec, so it has
been **empty in both families**. The D1 panel has one but cannot price execution — across 58
overlapping months the panels agreed on 100% of pairs and directions yet returned **+0.0367**
unpriced against **−0.0071** executed.

**Needed:** re-split the canonical panel, or accept development is D1-only and directional-only.

---

## Not asked

No new family, parameter, threshold, gate change or repair is proposed here. A1 is the only
item with a time cost attached; the rest can wait for the next task.
