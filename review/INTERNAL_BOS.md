# Internal-structure entries: the first backtest that includes them

Run 2026-09-30, engine `2026-09-29b`, BTCUSDm, 99 000 M1 bars, the Valère
package at two real balances. `review/internal_bos.py`,
`review/internal_bos.json`.

## Why this did not exist before

`lab/harness.py` had **zero** mentions of internal structure. The live bot
takes internal-structure entries; the simulation had never modelled one.
So every backtest number this desk has quoted — including the proof-of-
profitability page — excluded a trade type that really trades.

The harness now carries an `internal` dial: `0` off (old behaviour),
`1` the live rule (enter only when the internal trend agrees with the main
one), `2` also counter-trend, which the bot logs and refuses today.

The internal engine is not a reimplementation. It is
`owl_chart_feed.internal_structure()`, the same function the feed uses,
driven bar by bar, with the main levels read off the incremental
`structure_bos_bot.Struct` the way the feed's batch engine derives them
(`nxt` = hi_v/lo_v, `inv` = prot_lo/prot_hi). Each simulation gets its own
pin, because that function's docstring is explicit that two runs sharing one
corrupt each other — and `run_cfg` calls it three times.

## Two checks before any number was read

**Regression.** With the dial off, the patched harness reproduces the
pre-patch one exactly — same net, same trades, same drawdown, same win rate
— on four configurations, both versions loaded in one process and given the
identical bars. Comparing separate runs would have proved nothing: the bar
loader fetches the latest candles each time, so the market moves between
runs.

> A trap worth recording: the first attempt put the old copy in a scratchpad
> and it "failed" on all four. `harness.py` derives its data paths from
> `__file__`, so a copy outside `live/lab/` silently falls back to the
> default package for every config — it returned the same net for three
> different configs, which is what gave it away. The old copy has to sit
> beside the new one.

**Calibration.** A simulation that fires at the wrong rate is fiction. The
simulated rule fires **5.9 aligned internal signals a day**. The live bots
log **4.1/day** (Valère) and **8.6/day** (demo) — they differ from each
other because each bot runs its own main structure, so "aligned" is
account-specific. The simulation sits inside the live range.

## The result

| account | mode | net | h1 | h2 | trades | worst DD |
|---|---|---|---|---|---|---|
| Valère | main only | **+147.07** | +56.47 | +82.84 | 266 | 34.48 |
| Valère | + aligned | +84.16 | +56.23 | +25.11 | 373 | 43.63 |
| Valère | + both ways | +49.19 | +35.27 | +32.46 | 454 | 64.27 |
| Dépenses | main only | **+101.50** | +14.22 | +76.31 | 331 | 33.73 |
| Dépenses | + aligned | +44.56 | +13.71 | +29.38 | 399 | 35.77 |
| Dépenses | + both ways | +30.75 | +0.12 | +43.88 | 490 | 34.46 |

Cost of adding the live aligned rule: **−42.8 %** on Valère, **−56.1 %** on
Dépenses. Counter-trend on top: **−66.6 %** and **−69.7 %**.

**It is never positive.** Two accounts, two halves, two modes: every single
split is worse than or equal to main-structure-only. Nothing here flips
sign, which is exactly what the higher-timeframe and risk-cap studies could
not say.

On Valère it also nearly doubles the worst drawdown, 34.48 → 64.27.

Rough per-trade view: the aligned rule adds 107 trades and costs $62.91, so
about **−$0.59 per added trade**, against **+$0.55** for an average main
trade. Approximate, because an internal entry also blocks the next main
signal while it is open — but that displacement is real and would happen
live too.

## The honest limit

The simulation executes more internal trades than the live bot does. It
adds ~1.55 internal trades a day; Valère's journal shows ~0.33 a day. The
live `enter()` applies more refusals than the harness models (day cap,
weather, spread, debt state). So the **size** of the damage is probably
overstated. The **direction** is not: every split is negative, and the
per-trade average is negative.

## Recommendation

Turn the aligned internal rule **off** on the live accounts, and never turn
the counter-trend one on. Do it as a package dial so it can be switched back
and so one account can be left as a control, the same shape as the risk-cap
deployment.

Not done here — this is the measurement and the recommendation.

## Next

The wide-stop observation (an internal trade carried a 594 pt stop against a
214 pt main median) is now testable in this harness rather than arguable.
That is the next job.
