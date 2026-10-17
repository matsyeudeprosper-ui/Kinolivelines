# Broker cost curve (2026-10-16)

The proof page's 42-day Bitcoin tick replay (2026-08-28 -> 10-09, every recorded tick of BTCUSDm) rerun with the
spread forced to a constant around the mid price. Everything else unchanged (signals, stops, targets, money rules,
$0.35/lot slippage). Script `study/spread_whatif.py`; result `live/lab/spread_curve.json`, read by
`live/broker_book.py` to give any broker its verdict at sign-up without a replay.

| Spread per trade | Owl (42 d, $200) | Pekos owl (42 d, $200) |
|---|---|---|
| native (recorded ticks, median $10.00: Exness Standard's fixed spread, $6.40 since October) | +51.10 (83 trades) | +68.58 (79) |
| $10 forced | +50.76 (82) | +54.90 (77) |
| $20 forced | +56.66 (78) | +1.14 (72) |
| $40 forced (FOREX.com) | -5.30 (77) | -23.63 (68) |

Readings
- FOREX.com ($40 fixed) is RED for every robot: the sign-up card and the hint under the server field say so before a password is typed.
- Pekos owl is cost-sensitive (its 1R target leaves less room): a $20 broker already takes everything.
- Owl is nearly flat up to $20 and even ends higher there with 5 fewer trades. To audit (good results get audited hardest): which trades disappear and why - likely the engine's minimum-stop rule skipping tight stops that happened to lose.
- The live Pro accounts pay ~$4.48 (variable), BELOW the test's native cost: the proof is conservative for them.
- Zones: green = the best robot keeps >= 70 % of its native result; orange = positive but less; red = nothing positive; Exness = green by definition.

## 2026-10-17 — Audit: why the Owl at a $20 spread "beat" native (+56.66 vs +51.10)

study/spread_audit_owl20.py, result study/spread_audit_owl_20.json. Same ticks, same rules, spread forced to $20.
* 77 trades are shared: the wider spread costs them $8.24 (native +69.98 -> +61.74), exactly the expected drag.
* 6 trades exist only at native cost and all 6 LOST (-18.94 together: 09-06, 09-07, 09-10, 10-05, 10-08 x2).
  At $20 the entry rule does not fire on them (the wider spread moves the fill past the trigger), so they are skipped.
* 1 trade exists only at $20 and lost -5.06.
Net: +51.10 - (-18.94) ... = the "gain" at $20 is the accidental removal of six small losers, not a better robot.
Verdict: composition luck (6 of 83 trades). The cost curve keeps its meaning: wider spread = lower result; the
$20 point is a noise bump, not a feature to exploit. Nothing to change in the bots or the verdict card.
