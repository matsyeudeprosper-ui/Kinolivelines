# E025 — Trading against the higher timeframes: does it cost more?

**Verdict C. Closed.** Run 2026-09-30, engine `2026-09-29b`,
`review/htf_risk.py`, result in `review/htf_risk.json`.

## The question, and why it is not E012 again

E012 (2026-09-12) closed higher-timeframe alignment as an **entry filter**:
it does not predict whether a trade reaches its target or its stop. Blind
AUC 0.499 on TEST and 0.504 on V2. That question is about the **direction**
of the outcome and it stays closed.

It never asked about the **size** of the loss. That distinction matters here
because it is the shape the crowding result took on this desk: crowding was
never an entry signal, it widened the adverse excursion, so it belonged in
the risk rules. The same could have been true of alignment.

Pre-registered, one question only:

> Among losing trades, is the loss bigger when the trade direction opposes
> the majority of M15, H1 and H4?

Decided before looking: median and p95 of the loss split by aligned against
opposed; 200 shuffles of the label as the control; the gap must hold in both
halves with the same sign; A only if the control and both halves pass;
otherwise C and closed, with no second cut.

## How the higher timeframes were built

From the same M1 bars the simulation runs on, resampled to M15, H1 and H4,
each fed to `structure_bos_bot.Struct` — the engine the bot itself uses. A
candle enters its timeframe only once it has **closed**, so the trend known
at a trade's entry minute is a trend a live bot could have known. No
lookahead.

Sample: BTCUSDm, 99 000 M1 bars, 23 July to 30 September 2026. Rules were
one real account's own deployed package, not a generic account. 293 trades
simulated, 287 with a higher-timeframe majority, 112 of them losing.

## The result

| losing trades | n | median loss | p95 loss |
|---|---|---|---|
| against the big picture | 59 | $2.93 | $8.44 |
| aligned with it | 53 | $2.47 | $7.59 |

The gap is **+$0.46**, in the expected direction: fighting the higher
timeframes does look more expensive.

It does not survive either check.

- **Control.** Shuffling the aligned/opposed label over the same 112 losses
  produces a gap of +$0.75 at its 95th percentile. The real gap sits at the
  80th percentile of pure chance. A label that means nothing produces a
  bigger gap than this one, one time in five.
- **Halves.** First half **−$0.20**, second half **+$0.86**. The sign flips.

Both checks were declared before the numbers were seen, and both fail.

## What this closes

Alignment does not predict the direction of the outcome (E012) and it does
not size the loss either (here). The family is closed on this engine.

Practical consequences:

1. **Do not re-propose higher-timeframe alignment as a filter, a stake
   rule, or a target rule on this engine without new data.**
2. The "Les temps du marché" card in the app is **context, not a signal**.
   It says what the market looks like at four speeds. It carries no claim
   about whether the next trade is better, and the card should say so, or a
   member will assume alignment means a better trade.

## What was not tested

Adverse excursion itself. This measured the realised loss, which the stop
truncates, so a wider excursion that still ends at the same stop is
invisible here. Testing that needs per-trade maximum adverse excursion,
which the harness trace does not record today. It is the only honest way
back into this question, and it needs the trace extended first.
