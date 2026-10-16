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
