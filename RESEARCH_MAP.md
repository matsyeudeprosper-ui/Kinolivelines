# Research map — what is open, what is closed

**Synchronised 2026-08-03 (task 006)** against the completed committed studies, which are
the source of truth. An earlier version of this file still presented perp-index basis,
broker feed lag and DVOL as "run this first" / "run next" long after all three had been
tested and closed. Anyone reading it would have re-run dead research. That is corrected
below.

> **Exactly one hypothesis is open: liquidation cascades (H4), and it is gated.**
> Everything else on this page is closed. Do not re-open a closed family "with a different
> indicator, parameter or timeframe" — that is the same test.

Read [`HANDOFF.md`](HANDOFF.md) first, then this file, then [`FINDINGS.md`](FINDINGS.md).

---

## The cost structure that shapes everything

Spread is a fixed $10 on BTCUSDm. What that costs depends entirely on horizon:

| horizon | median ATR | spread as % of ATR | history |
|---|---|---|---|
| M15 | $85 | **11.8%** | 1.4 yr |
| H1 | $383 | 2.61% | 7.59 yr |
| H4 | $798 | 1.25% | 7.59 yr |
| D1 | $1,727 | **0.58%** | 7.59 yr |

**Carry, measured and asymmetric:** `swap_long` = −1248.8 points = **−$12.49/night/lot
(−7.24%/yr)**; `swap_short` = **exactly 0.00**. Triple charge on Fridays.

**The FX equivalent, measured in task 004A across all 19 executable pairs:** wherever the
policy-rate differential says a side should *earn* carry, the broker pays **exactly
0.00%** on that side and charges the other. Any family whose edge is *holding* rather than
*moving* collects nothing on this venue by construction.

---

## OPEN — the only live question

### H4 — Liquidation cascades. **GATED. Do not run the outcome test yet.**

- **Mechanism** — a forced liquidation is not a trade anyone chose to make, so the
  resulting market order carries no information about value. Price may extend, revert, or
  merely become more volatile; those are separated in the preregistration.
- **Frozen rules** — [`PREREGISTRATION_liquidations.md`](PREREGISTRATION_liquidations.md),
  written before any outcome was examined. Definitions, thresholds and pass/fail are fixed.
- **Gate** — **≥ 400 independent cascades in development AND ≥ 100 in untouched holdout.**
  The trigger is the **count**, never a date.
- **Status at 2026-08-03** (task 006 audit, read-only, no outcomes examined):

  | | |
  |---|---|
  | Events recorded | 2,947 over 3.22 days |
  | Independent cascades (4h separation, frozen definition) | **5** |
  | Development / holdout under the 75-25 split | **4 / 1** |
  | Remaining to gate | **396 development, 99 holdout** |
  | Rough pace, **not a deadline** | ~1.55 independent cascades/day |

- **The old "~85 days" estimate was wrong.** It came from `study/data_readiness.py`, which
  counts any 4-hour window containing one top-10%-by-size *event*. The frozen definition is
  stricter — a 5-minute **bucket** whose **total** size is top-5% against a **trailing
  30-day** distribution — and it also requires a holdout arm the old estimate ignored. On
  the frozen definition the honest figure at the current pace is **several hundred days**.
  Both numbers move with market regime; neither is a promise.
- **Caveat on the feed** — the OKX endpoint returns at most 100 events per poll and four
  minutes have already carried ≥ 90. Cascades are precisely the busiest minutes, so the
  feed may be truncating the very episodes the hypothesis is about. Flagged, not yet fixed.
- **The two recorders collecting this are IRREPLACEABLE.** Their history cannot be
  backfilled.

### H5 — Open-interest change. **NOT YET.**

719 hourly rows (OKX caps backfill at 30 days), ~180 non-overlapping 4h windows. Far too
few. Revisit as the live recorder extends it.

---

## CLOSED — do not revisit

| hypothesis | verdict | evidence |
|---|---|---|
| Price / OHLC / indicator timing on BTC (15 tests) | null | `FINDINGS.md` §1 |
| Funding rate as a DIRECTION signal | null | `funding_edge.py`, `funding_phases.py` |
| COT positioning as a direction signal | died out-of-sample on 20 unseen markets | `cot_*.py` |
| **H1 Perp-index basis / spot-perp spread** | **null** | `basis_edge.py` |
| **H3 Broker feed lag / latency arb** | **null on all 4 preregistered criteria** | `broker_lag2.py` |
| **H6 DVOL / variance risk premium** | **null; Q2 died out-of-sample** | `dvol_*.py` |
| Order-book imbalance | **real but 5× too small** — $2.04 move vs $10 cost | `orderflow_concentration.py` |
| Stop/target geometry search (30 shapes) | all tied; the loss is the spread | `sim_variants.py` |
| Cross-sectional momentum, 19 US stocks | null, MDE 1.47%/rebalance | `xs_momentum.py` |
| Cross-sectional momentum, 57 crypto perps | null, MDE 3.23%/rebalance | `xs_crypto.py` |
| Trend following, 13 instruments | **underpowered, NOT disproven** — MDE 10.2%/yr | `trend_following.py` |
| Horizontal levels as an entry trigger | null | `hline_*.py` |
| **FX cross-sectional momentum 3M-1M V1** | **FAILED** — see `FINDINGS.md` | `fx_momentum_v1.py` |
| **FX policy-rate differential V2** | **FAILED** — see `FINDINGS.md` | `fx_policy_differential_v2.py` |
| The demo↔live mirror as a money-maker | arithmetic: costs 2 spreads, cannot win | `KLMirror.mq5` |

### H2 — Carry asymmetry. **Not an edge in isolation; never to be claimed as one.**

Shorts pay zero financing on BTCUSDm and longs pay 7.24%/yr. That is a measured cash flow,
not a prediction. It is **~1/135th of daily noise**, so it is underpowered on its own and is
only meaningful as a tiebreaker applied to a rule that is already near-neutral. BTC also
appreciated across the sample, so a naive short bias loses on direction far faster than
carry can pay. Not a candidate family.

### Two things that measurably work — but not at this capital

Both documented in [`HANDOFF.md`](HANDOFF.md) §3, neither reachable at ~$1,000:
**delta-neutral perp carry** (needs spot+perp on one venue; Exness has no spot; premium
compressed to ~1–3%/yr) and a **diversified hold basket** (blocked by minimum lot sizes;
needs ~$13,200 at 1×).

---

## Standing constraint

The M15 bot is **authorised to trade on demo for forward observation, data collection and
execution validation. It is not authorised for real-money deployment, and is not considered
to have a validated edge.**

Its trades are forward data collection, not evidence. Two questions stay separate in every
report: *is the strategy profitable* (unproven, historical evidence negative) and *is the
live system executing its stated rules correctly* (testable now, and the point of the
exercise). Full constraints in [`README.md`](README.md).

## One distinction that must not be lost

A **current swap snapshot is not historical swap evidence.** Exness publishes no historical
swap rates and none have been collected, so no backtest in this project may charge or credit
a historical carry figure. Equally, measuring that this broker pays zero on V2's selected
side does **not** prove that every holding-based strategy on every venue is impossible — it
is one venue, one snapshot, one selected side.
