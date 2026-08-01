# Pre-registration — liquidation cascade hypotheses (H4)

**Written 2026-08-01, before any outcome was examined.** Definitions, thresholds and
pass/fail rules are frozen here so that the test cannot be shaped by what the data turns
out to say. Nothing below may be adjusted once outcomes have been looked at; if a
definition proves unworkable the change must be recorded as an amendment with its date
and reason, and the analysis re-run from scratch.

This exists because the project has already produced one result that passed every check
in discovery and died on holdout, and one "absent" verdict that was really an
underpowered sample. Freezing the rules first is the cheapest defence against both.

---

## Economic mechanism

A forced liquidation is not a trade anyone chose to make. When a leveraged position is
closed by the exchange, the resulting market order carries no information about value —
it is a mechanical consequence of a margin threshold being crossed. Three things could
follow, and they are mutually exclusive enough to be worth separating:

- the selling itself pushes price into further liquidation levels, so the move **extends**
- the price impact is pure liquidity demand and **reverts** once it stops
- neither direction persists but the episode leaves the market **more volatile**

Only the first two are directly tradeable. The third would be a risk input, and the
project has already learned that a risk-only finding may never reach a strategy.

---

## Frozen definitions

| term | definition |
|---|---|
| **event** | one row of `liquidations_BTC.csv` (OKX BTC-USDT swap, state filled) |
| **cascade** | a 5-minute bucket whose **total liquidated size** sits in the top 5% of all non-empty 5-minute buckets, ranked against a **trailing 30-day** distribution only |
| **cascade direction** | the sign of net liquidated size: `long` liquidations are forced **selling**, `short` liquidations forced **buying** |
| **OI collapse** | open interest falling by ≥2% within the hour containing the cascade, from `derivs_BTC.csv` |
| **taker imbalance** | `(taker_buy − taker_sell)/(taker_buy + taker_sell)` in the same 5-minute bucket, from `derivs_BTC.csv` |
| **entry** | the first BTCUSDm M15 close **after** the cascade bucket ends — never inside it |
| **horizons** | 15 minutes, 1 hour, 4 hours |
| **costs** | the real $10 BTCUSDm spread on entry, plus $2/side assumed slippage |

The trailing-30-day ranking is not optional: ranking against the whole sample would let a
future volatility regime decide what counted as a cascade in the past.

---

## The four hypotheses

**H4a — cascade continuation.** After a long-liquidation cascade, price continues lower
over the horizon. *Predicts:* mean return in the cascade direction > 0 net of costs.

**H4b — overshoot and reversal.** The cascade overshoots and price reverts. *Predicts:*
mean return **against** the cascade direction > 0 net of costs. H4a and H4b are mirrors;
at most one can pass, and if both appear to, the control is broken.

**H4c — volatility expansion.** Realised volatility over the horizon exceeds the trailing
estimate by more than it does after a volatility-matched non-cascade entry. *Predicts:*
ratio > 1 relative to control. Not directly tradeable — a risk input only.

**H4d — interaction.** The effect in H4a or H4b is materially stronger when the cascade
coincides with an OI collapse **and** taker imbalance pointing the same way. *Predicts:*
the conditioned subset beats the unconditioned cascade set by >2SE.

---

## Pass/fail — frozen

A hypothesis passes only if **all** of the following hold:

1. beats a **volatility-matched** random-entry control by more than 2SE — matched, because
   an unmatched control already produced a false positive on both mirror arms once
2. same sign in **at least 4 of 5** entry-volatility quintiles
3. holds on an **untouched final 25%** of the data, chronologically, never inspected
   during development
4. survives a **two-sided** rotation null at p ≤ 0.05
5. for H4a/H4b only: the expected capturable move exceeds **$14** (spread + slippage both
   ways) by a clear margin. A statistically real $3 effect is not an edge

Failing any one closes that hypothesis. Mirror-arm sanity check applies throughout: H4a
and H4b cannot both look good.

---

## Sample requirement — the gate for starting

Testing begins when **both**:

- **≥ 400 independent cascade events** in development, and
- **≥ 100** in the untouched holdout

At 400 the minimum detectable difference in a rate is about **5pp**, which is at the edge
of useful; below that a null would mean nothing, which is precisely the mistake made once
already with the crowding branch. Independence is enforced by requiring cascades to be
separated by at least one horizon length.

**Current status: ~6 independent windows.** Nowhere near. This will be re-checked by
`study/data_readiness.py`, and the trigger is the event count, **not** a date.

---

## Amendments

*(none yet — any change after outcomes are seen must be logged here with date and reason)*
