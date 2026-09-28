# Half target (TP 0.4 R instead of 0.8 R) - replayed (2026-09-28)

Owner: "replay Valere's trades to see what would have happened if we took
only half of the 0.8 TP". `half_tp_test.py`.

## Part 1 - Valere's real positions since 14/09 (38, broker history)
Walk the M1 bars after each real entry: which came first, the stop or the
half target? Wins pay 0.4 x dist x lots minus spread; losses keep their
real amount.

| | wins / losses | net |
|---|---|---|
| as traded, TP 0.8 R | 24 / 14 | +24.18 |
| half target, TP 0.4 R | 33 / 5 | +26.63 (+2.45) |

Nine losses would have been small wins (the −11.95 of 25/09 becomes +4.64,
the −7.54 of 27/09 becomes +2.87); every win is cut in half. Same money,
far fewer red trades.

## Part 2 - full 41.7-day replay, target as a fraction of the risk
| target | trades | win | net | worst debt | halves (net) | halves (worst debt vs A) |
|---|---|---|---|---|---|---|
| A deployed 0.8 R | 259 | 60.6% | +163.43 | 63.26 | +166 / −6 | — |
| 0.4 R (half) | 337 | 73.6% | +146.94 | **38.82** | +100 / +43 | −28 / −24 |
| 0.6 R | 306 | 66.0% | **+208.27** | 44.72 | +130 / +72 | −24 / −19 |
| 1.0 R | 217 | 57.1% | +159.85 | 62.40 | +168 / −17 | +1 / −18 |

## Verdict
- The half target is NOT a profit edge: −$16 over the full period, and the
  halves disagree on the net (−67 in the first, +49 in the second).
- It IS a smoothness change that held in BOTH halves: the worst debt drops
  by a third (63 -> 39), the win rate goes from 61% to 74%, and the second
  half turns from a loss into a gain.
- 0.6 R sits between: the most money over the full period (+$45 vs A) and
  the drawdown improves in both halves, but its net halves disagree too
  (−36 / +78). One sample; do not pick the best number from a row of four.
- Same shape as E008 (stop geometry is noise for the P&L) with one new
  fact: the TARGET geometry moves the drawdown consistently.

Not deployed. Owner's call; a target change is a strategy change (every
account, `package_parity.py`). Best next step if wanted: run 0.6 R as a
forward observation on the demo before touching a real account.
