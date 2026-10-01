# The last two rules nobody had ever tested

Run 2026-10-01, engine `2026-09-29b`, 99 000 M1 bars, four shapes.
`review/untested_rules.py`, `review/untested_rules.json`.

**Both verdicts: keep what is deployed.** Neither challenger clears the bar.

## Why they were untested

The parity check lists three rules as "no dial, matches assumption". That
phrase is not reassurance — it means the harness silently assumes a value
and nobody has ever checked it. The movement brake was the third, and
measuring it found it worth 43–65 % of net. These are the other two.

* **debt_mode** — the bot has `hwm` (debt is the distance below the peak)
  and `half` (a ledger: a loss adds 0.5× itself, a win pays it down). Every
  account runs `hwm`. The harness could not express `half` at all until
  2026-09-30, so the two had never been compared on this engine.
* **max_trades_day** — a hard ceiling on entries per day, `None` on every
  account. Nobody had asked whether a cap would help.

Bar written down first: the deployed rule stays unless the challenger wins
on every shape **and** in both halves.

## debt_mode: hwm stays

| shape | hwm | half | first half | second half |
|---|---|---|---|---|
| base | **+189.25** | +120.97 | **+21.1 %** | −64.0 % |
| valere | **+156.81** | +105.48 | −3.7 % | −25.7 % |
| Valère | **+146.86** | +95.93 | −3.7 % | −25.7 % |
| Dépenses | **+96.92** | +36.00 | **+114.3 %** | −82.5 % |

`half` costs 33–63 % of net over the full period on all four shapes. Its
first half looks good on two of them, and that is exactly the pattern the
both-halves rule exists to catch. On `base` it also pushes the worst
drawdown from 50.23 to 70.02.

## A daily trade cap: no cap stays, and it is not close

| shape | no cap | max 2/day | max 3/day | max 5/day |
|---|---|---|---|---|
| base | **+189.25** | +33.76 | +55.26 | +86.52 |
| valere | **+156.81** | +37.26 | +42.09 | +64.99 |
| Valère | **+146.86** | +37.26 | +43.64 | +60.81 |
| Dépenses | **+96.92** | +18.15 | +26.89 | +33.62 |

Every dose loses 54–82 % of the net on every shape, and every dose is worse
in the second half on every shape. Tighter is worse, monotonically: 2 is
worse than 3 is worse than 5 is worse than no cap at all.

It does cut the worst drawdown a little (33.73 → 20.60 on Dépenses at two a
day), but it pays four fifths of the profit for it. That is a far worse
exchange rate than the per-trade risk ceiling, which buys a similar
reduction for a cost somewhere between nothing and 9 %.

## What this closes

All three "no dial, matches assumption" rules are now measured. The
assumptions the harness was making were right in every case — but they were
assumptions, and two days ago none of them could have been questioned at
all.

Do not re-propose a daily trade cap on this engine. If anyone wants fewer
trades, the per-trade risk ceiling is the instrument that has been shown to
cost less (`review/RISK_CAP.md`).

## Not done

No tuning. No cap at 8 or 10 a day, no `half` with a different multiplier.
The question was whether the deployed rules hold, and adding doses after
seeing the answer is how a measurement becomes a fit.
