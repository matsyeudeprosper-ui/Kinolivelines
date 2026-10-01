# The movement brake: measured for the first time

Run 2026-10-01, engine `2026-09-29b`, BTCUSDm, 99 000 M1 bars.
`review/movement_brake.py`, `review/movement_brake.json`.

**Verdict: it stays, and it is not close.**

## Why this had never been measured

The brake — no entry unless the market made at least one big move in the
last two hours — was **hard-coded** into the harness, not a setting that
happened to be on. Every backtest this desk has run therefore *assumed* it
was right, and nothing could have said otherwise.

It only became measurable on 2026-09-30, when `movement` was added as a dial
to close one of the three holes the parity check found. The owner asked the
right question within a day: does the indicator still hold after all the
harness work?

Pre-registered before reading anything: both reference shapes plus two real
balances, full period and both halves, and **the brake stays unless removing
it wins on every reference and in both halves**. A brake that blocks trades
has already earned its place; the burden is on the case for removing it.

## The result

| shape | brake ON | brake OFF | cost of removing |
|---|---|---|---|
| base | **+186.95** | +105.81 | −43.4 % |
| valere | **+150.41** | +58.34 | −61.2 % |
| Valère ($270.75) | **+140.86** | +57.57 | −59.1 % |
| Dépenses ($200) | **+95.39** | +33.88 | −64.5 % |

Worst drawdown, which is the part that matters most:

| shape | ON | OFF |
|---|---|---|
| base | 50.23 | **89.53** |
| valere | 34.48 | **84.20** |
| Valère | 34.48 | **84.20** |
| Dépenses | 33.73 | **41.26** |

Removing the brake roughly **doubles the worst hole** on three of four
shapes while cutting profit by half. It buys 9 to 51 more trades and they
are not worth having.

## The honest wrinkle

The halves do not agree, and that is worth saying rather than burying.

| shape | first half | second half |
|---|---|---|
| base | −16.4 % | −59.5 % |
| valere | **+1.3 %** | −71.7 % |
| Valère | **+21.1 %** | −71.7 % |
| Dépenses | **+51.8 %** | −87.0 % |

In the **first half**, removing the brake was sometimes *better* for profit.
In the second half it is catastrophic everywhere. So the brake's value is
concentrated, not uniform — it earns its keep in one kind of market and
costs a little in another.

That does not change the verdict, for two reasons. The pre-registered rule
needed removal to win everywhere and it does not. And the drawdown figures
are full-period and consistent: even where the first half looked better
without it, the worst hole over the whole period was far deeper.

What it does mean: **this brake is a drawdown control, not a profit engine.**
It should be described that way, and nobody should be surprised to see a
quiet stretch where it looks like it is costing money.

## Not done

No tuning of the threshold. The question was whether the brake holds, not
what the best number of moves or hours is, and inventing a second question
after seeing the first answer is how a measurement turns into a fit.
