FROM: CLAUDE
RE: decisions arising from task 006, plus the three standing constraints

Full detail is in `coordination/CLAUDE_REPORT.md` (task 006). This file is the short
actionable list.

Two families are closed and must not be revisited: **FX cross-sectional momentum 3M-1M V1**
and **FX policy-rate differential V2**. Both simulators are certified and reusable.

**Exactly one hypothesis is open: liquidation cascades (H4), and it is gated.**

---

# A. Liquidation state — corrected in task 006A, nothing outstanding

## A1. ~~Feed truncation~~ — WITHDRAWN. There is no truncation problem.

Task 006 claimed the OKX endpoint caps liquidation *events* at 100 per poll and called it
urgent. **That was wrong and is withdrawn.** `limit=100` caps the **outer instrument
array**, not the events inside each `details` array.

Measured fresh on 2026-08-03 (`study/okx_liquidation_endpoint_audit.py`): **one call
returned 654 events spanning 22.6 hours**, from 16 outer objects. Commit `812ac5f` had
already established this on 2026-07-31, and `recorder/derivs_recorder.py` documents the
measured behaviour and paginates backwards with `after`.

**No decision needed. Do not shorten the 60-second poll interval.** The recorder was not
changed and needs no change.

## A2. ~~Two disagreeing readiness numbers~~ — FIXED in task 006A

`study/data_readiness.py` no longer computes its own cascade count. Both scripts now call
the single authoritative `study/liquidation_readiness.py`, and a deterministic assertion
fails loudly if they diverge. Verified agreeing on all 10 shared keys.

**No decision needed.**

## A3. Formal gate status — corrected, and no ETA is published

| | |
|---|---|
| **FORMAL cascades** | **0** |
| **FORMAL development / holdout** | **0 / 0** |
| Formal gate | **CLOSED** |
| Formal scoring begins in | **~26.8 days** |
| Provisional startup diagnostic | 5 — **not gate progress** |

Zero is correct, not pessimistic: the frozen rule ranks against a trailing 30-day window and
the feed is 3.22 days old, so nothing is yet scorable. Recorded as Amendment 1 in
`PREREGISTRATION_liquidations.md`, with every frozen parameter unchanged.

Both previous ETAs were wrong — "~85 days" (event rate, no holdout arm) and my "~340 days"
(a 3-day sample cannot forecast a 30-day-trailing statistic). **No ETA is published. The
trigger is the formal count.**

**Optional decision, no urgency:** if the gate or horizons are ever to be revisited, the
only honest moment is *before* any outcome is seen — which is still true today. I am not
proposing a change.

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
