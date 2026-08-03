FROM: CLAUDE
RE: three structural constraints to settle before the third strategy family

Supersedes the earlier version of this file. Its task-002 and task-003 items were all
answered by the specs that followed.

Two families are now closed and must not be revisited:

- **FX CROSS-SECTIONAL MOMENTUM 3M-1M V1** — FAILED (tasks 003, 003A, 003B)
- **FX POLICY-RATE DIFFERENTIAL V2** — FAILED (tasks 005, 005A)

Both simulators are certified. The infrastructure is reusable; the strategies are not.

Everything below is a **property of this account and this broker**, not of either failed
idea. A third family inherits all three unless the spec says otherwise. None of this is a
strategy proposal — each is a measured constraint with the options it implies, and the
choice is the strategy lead's.

---

## 1. The broker pays zero carry on the side that should earn it

**Measured, task 004A, all 19 executable pairs.** Wherever the policy-rate differential says
a side should receive carry, the Exness snapshot for that side is **exactly 0.00%**, and the
opposite side is charged. Median markup 1.38 pp long, 0.60 pp short; worst 4.35 pp
(`AUDCHFm`).

Task 005 then confirmed it from inside a backtest without being asked to: V2 always trades
the theoretically positive side, so applying the stored swap snapshot changed the result by
**$0.00 on every one of 47 trades**.

**Why it matters beyond V2.** This is structural. Any family whose edge is *holding* rather
than *moving* — carry, rate differential, roll, term structure — collects nothing here by
construction and is left as a pure directional bet.

**What I need:** whether the third family is allowed to depend on being paid to hold. If it
is, the venue has to change, because this one does not pay. If it is not, the family should
be one whose edge lives in price movement.

Related measurement already in hand: delta-neutral perpetual carry does pay, but needs spot
plus perp on one venue — not Exness — and the premium has compressed to roughly 1–3%/yr.

## 2. Stop size, not signal quality, decides whether a sample exists

On $979 with minimum lot, the 1.50%-of-equity risk gate binds directly against the trade
count, and the stop multiple is the lever:

| | V1 (2.0 × ATR) | V2 (1.5 × ATR) |
|---|---|---|
| Rebalances | 55 | 58 |
| Skipped on the risk gate | **33** | **11** |
| Completed trades | **22** | **47** |
| Trade-count condition | ≥ 40 — **failed** | ≥ 45 — **passed** |

A 2-ATR stop at minimum lot costs about **$14** against a **$14.69** budget — the rule sits
almost exactly on top of the cheapest position the broker will open, so small ATR changes
flip whole months in or out.

**What I need:** the stop multiple and the trade-count bar decided **together**, before the
run rather than after. Any monthly-rebalance family on this account inherits a hard ceiling
of ~60 trades in five years before any skipping at all.

## 3. The executable panel has no development period

The canonical H1 panel begins **2021-08-02**; every spec so far has ended development on
**2021-07-31**. Development on the executable panel has therefore been **empty in both
families**, and only the broker-D1 panel has one.

The two panels are not interchangeable. Broker D1 reaches 2018-07 and gives a real
development window, but it cannot be cut to the 17:00 New York session boundary and cannot
price execution — task 005 measured that gap directly: over 58 overlapping months the two
panels agreed on **100% of pairs and 100% of directions**, yet returned **+0.0367** on
unpriced daily closes against **−0.0071** once executed. The difference was entirely
spread and scheduled-open pricing.

**What I need:** either a different split for the canonical panel so development is
non-empty, or an explicit acceptance that development is D1-only and that a D1 result is a
directional check which says nothing about executability.

---

## Not asked

No third family, no parameter, no threshold and no repair of either failed strategy is
proposed here or anywhere in the task 003–005A reports. This file raises only the
constraints whose answers change what I build next.
