# Tick engine - Infinity end-to-end validation (drag 0), regenerated on the final run

Engine baseline arm vs the harness bar-level baseline (same manifest package, dataset b).

| | harness (bars) | engine (ticks) |
|---|---|---|
| trades | 194 | 202 |
| net (engine: unrounded running balance) | 52.90 | 38.49 |
| engine: sum of the per-trade P&L rounded to cents | | 38.46 |
| common signals traded by both | 177 | |
| harness-only / engine-only trades | 17 | 25 |
| outcome agreement on common signals | 171 / 177 (96.6%) | |
| per-trade P&L difference on common signals (engine - harness) | mean -0.191, median 0.100, sum -33.76 | |
| of which the 6 outcome flips | -31.69 | |
| common wins (95): mean diff | -0.147 | |
| common losses (76): mean diff | 0.156 | |
| first path divergence (signal time) | 1787970120 (harness-only) | |

The $0.0x between the engine's net and the sum of its rounded per-trade rows is cent rounding of the
attribution (the running balance is unrounded internally; Reply 14 item 4). The gap to the harness is the
intended execution realism: the live ask-based target geometry flips a few bar-level wins into tick-level
losses, 1 s fills and the embedded bid/ask cost cents per trade, and the paths diverge where a tick exit
lands later than a bar-granular one (signals skipped while the engine's position was still open).
