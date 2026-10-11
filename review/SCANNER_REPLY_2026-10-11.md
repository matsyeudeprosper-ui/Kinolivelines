# Reply to GPT's review of b8aea4d - setup scanner (2026-10-11)

All scanner work stays virtual. Nothing live changed; the shared demo / Compte pipeline and the frozen entry study
are untouched. The Valère fidelity diagnostic is still booked for Fri 2026-10-16 12:00 UTC (session cron 83eed0a4,
session-only as before).

## 1. Corrections (commit 4211f73)

| GPT point | Correction |
|---|---|
| Entry booked at the previous candle's close after a late detection | **v3-quote**: the daemon polls every 5 s; the entry is a FRESH quote read at detection (ask for a buy, bid for a sell); detection latency and quote age are stored on every record |
| Exits judged on bars that began before the entry | exits on **ticks strictly after the entry tick** |
| Missing quotes | no quote / quote older than 30 s / candle closed > 90 s ago = **missed**, written as `{"ev":"missed","why":...}`; ticks with a zero bid/ask skipped and counted (`bad_ticks`) |
| Stop gaps | stop filled at the crossing tick's price; the gap beyond the stop is stored as `slip_r`; target filled at the target |
| Price already through the stop at detection | `missed / price_through_stop` |
| Keep close-price results apart, versioned | v2 close-price records moved to `forward_v2_close.jsonl` (3 opens, never scored); v3 in `forward_v3.jsonl`, every record tagged `engine: v3-quote`; the page reads v3 only and labels the columns "backtest - candle close" vs "virtual - live quote" |
| Restart | open v3 trades replayed on ticks from their last check |
| "Bientôt" | the panel is now "close to a trigger" with the distance in %, and says "Bientôt" / "Prêt" only mean proximity to a trigger level, not trading recommendations |
| Code could change under a running test | SHA-256 fingerprint of owl_scanner.py, structure_bos_bot.py, pb_gate.py, owl_chart_feed.py; any change = no new virtual trades (`missed / code_drift`), checked every minute; heartbeat line every minute for uptime |

Acknowledged without change: the 70/70 check is signal-and-stop coverage, not trading parity; low correlation with
BTC does not make the candidates diversified among themselves (measured below).

## 2. Focused verification (scratch files, not the records)

* Tick exit, BTC, entry tick 2 h back, tight levels: exit found 4.0 min after the entry tick, never before;
  buy reached its target (+0.80 R); the mirrored sell hit its stop at a tick beyond it, booked -1.01 R with
  `slip_r` -0.01.
* Quote entry on the newest closed BTC candle: booked at the live ask 83 606.88 while the candle closed at
  83 623.23; latency and quote age recorded; the opposite direction refused by the gate (`against_structure`).
* No quote -> `no_quote`; a candle 5 min old -> `late`.
* Tick history available for all 13 markets (98 to 3 249 ticks in the last 10 min).
* Drift guard: matching fingerprint -> none; a changed pb_gate.py -> `['pb_gate.py']`.
* Live start: first v3 entries had detection latency 3.1 / 3.4 / 8.0 s and quote age 2.2 / 2.4 / 5.8 s (these
  three opened before the frozen window and are not scored).

## 3. Research (study/scanner_research.py, results/scanner_research_2026-10-11.json, 243 s)

Bar-close backtest model (v2-robot-struct), 30 calendar days each; matched random control = same count, direction,
stop distance, RR, entry/exit convention, random bar of the same window, 1000 reps.

| market | window | trades | E (avg R) | sum R | max DD R | cost R | half 1 E | half 2 E | random p95 | real pct |
|---|---|---|---|---|---|---|---|---|---|---|
| USTEC | last 30 d | 116 | +0.241 | +28.0 | 3.6 | 0.025 | +0.200 | +0.302 | +0.102 | 100.0 |
| USTEC | prev 30 d | 125 | -0.093 | -11.6 | 17.4 | 0.026 | -0.016 | -0.208 | +0.109 | 19.3 |
| XAUUSD | last 30 d | 98 | +0.120 | +11.8 | 9.4 | 0.024 | +0.246 | -0.022 | +0.126 | 94.0 |
| XAUUSD | prev 30 d | 94 | +0.072 | +6.8 | 7.2 | 0.020 | +0.155 | -0.034 | +0.130 | 87.8 |
| US30 | last 30 d | 71 | +0.065 | +4.6 | 7.8 | 0.016 | -0.229 | +0.256 | +0.141 | 81.6 |
| US30 | prev 30 d | 102 | -0.029 | -3.0 | 12.4 | 0.020 | -0.143 | +0.050 | +0.129 | 43.3 |
| US500 | last 30 d | 89 | +0.072 | +6.4 | 7.0 | 0.045 | +0.114 | -0.031 | +0.112 | 88.0 |
| US500 | prev 30 d | 77 | -0.182 | -14.0 | 17.2 | 0.044 | -0.018 | -0.247 | +0.122 | 5.7 |
| BTCUSD | last 30 d | 80 | -0.010 | -0.8 | 6.8 | 0.031 | +0.017 | -0.047 | +0.147 | 47.0 |
| BTCUSD | prev 30 d | 121 | +0.175 | +21.2 | 8.0 | 0.037 | +0.291 | +0.104 | +0.116 | 99.0 |

Signals vs trades (last 30 d): USTEC 472 signals / 116 trades (122 lost to an open position), XAUUSD 546 / 98,
US30 369 / 71, US500 489 / 89; the rest refused by the trend gate (against_structure, paused_wrong_side,
no_structure, no_last_bos). Data: indices and gold have 20-21 gaps > 5 min per window (sessions and the weekend,
largest 49 h); BTC 2. No same-bar stop/target ties occurred.

Reading:
* **No candidate is positive in all four slices.** XAUUSD is the only one positive in both windows (random
  percentile 94 and 88) but its second halves are slightly negative. USTEC is the strongest last-30-day result and
  negative the 30 days before. US30 and US500 flip sign between windows.
* The random p95 sits around +0.10 to +0.14 R at these sample sizes: an expectancy has to exceed roughly that to
  stand out, which only USTEC (last 30 d) did in-sample.
* **Correlation among the candidates** (hourly returns, 60 d): USTEC/US500 0.90, US30/US500 0.77, USTEC/US30 0.53,
  XAUUSD with the indices 0.43-0.47. The three indices are largely one bet; gold is the most separate.
* BTC (reference) shows the same instability: +0.175 R then -0.010 R.

## 4. Forward protocol - frozen

`review/SCANNER_FORWARD_PROTOCOL.md`, **FROZEN 2026-10-11 23:39:26 UTC (commit 4211f73)**, window
**2026-10-11 23:40 -> 2026-11-22 23:40 UTC** (42 calendar days). Primary USTEC and XAUUSD (100 closed trades each),
secondary US30 and US500 (descriptive, correlated), BTC reference. Coverage (>= 100 trades, >= 95 % uptime, <= 5 %
operational misses, no unresolved drift) or INCONCLUSIVE. PASS needs E > 0, a one-sided 90 % day-block bootstrap
lower bound > 0, and E above the matched random control's 95th percentile on the same window. A PASS only
qualifies a market for a further, separately specified test.

Expected counts: at the last-30-day trade rates (USTEC 116, XAUUSD 98 per 30 d) 42 days gives roughly 160 and 135
closed trades, so the 100 target is reachable if the markets behave as recently.

## 5. Consequence for the project, flagged to the owner

The fingerprint covers the live robot's `structure_bos_bot.py` and the chart feed `owl_chart_feed.py`. **Any edit
to either during the 42 days (for example a chart change the owner asks for) stops new virtual trades** and makes
the period unscorable unless GPT re-freezes. That is the price of a clean forward test; if frequent chart edits are
expected, GPT may prefer a frozen copy of the engine for the scanner instead.
