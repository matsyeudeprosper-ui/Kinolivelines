# SCANNER-F1 - forward protocol for the setup scanner (virtual only)

Written 2026-10-11 on GPT's instruction (review of b8aea4d): "freeze a forward protocol before scoring; 42 calendar
days for the first review; target 100 closed trades per primary market; insufficient coverage = inconclusive."
This file is frozen by the FROZEN line at the bottom. Nothing in it changes after that line; a change needs a new
protocol with a new name.

## What is scored
* **Records:** `live/scanner/forward_v3.jsonl`, records tagged `"engine": "v3-quote"` only, with `detect` (open)
  inside the window. The v2 close-price records (`forward_v2_close.jsonl`) and every backtest are never scored here.
* **Model v3-quote** (live/owl_scanner.py): signals from the robot's own `structure_bos_bot.Struct` (seeded 3000
  closed M1 bars, stepped per closed bar), `pb_gate("trend")` on the pullback state of the last 8000 closed bars
  (no sticky chain), minimum stop = S_MIN_DIST (BTC) or 10/7 x spread; entry at a FRESH quote read at detection
  (ask for a buy, bid for a sell; poll every 5 s; quote older than 30 s or a candle closed more than 90 s ago =
  missed); stop = the engine's new protected dot; target 0.8 x the risk measured from the quote; exits on ticks
  strictly after the entry tick (stop filled at the crossing tick - slippage recorded; target filled at the
  target); one virtual position per market; results in R.
* **Code fingerprint:** SHA-256 of `owl_scanner.py`, `structure_bos_bot.py`, `pb_gate.py`, `owl_chart_feed.py`,
  stored in `live/scanner/protocol_fingerprint.json` at the freeze. The daemon re-checks every minute; on any change
  it opens no new virtual trade (logged `missed / code_drift`). A drifted period is NOT scored unless GPT issues a
  new frozen protocol.

## Window
42 calendar days, from the first full UTC minute after the FROZEN commit's timestamp. One review at the end. No
parameter, market list or rule changes during the window.

## Markets
* **Primary:** USTEC, XAUUSD - verdicts below; target **100 closed trades each**.
* **Secondary:** US30, US500 - same metrics, labelled descriptive. USTEC/US500 hourly returns correlate 0.90 and
  US30/US500 0.77 (60 days): they are largely the same bet and cannot count as independent confirmation.
* **Reference:** BTCUSD (the robot's own market) - descriptive.
* All other scanned markets: recorded, descriptive only, no verdict.

## Coverage (all required, else INCONCLUSIVE - never a pass)
1. >= 100 closed v3 trades for the market inside the window.
2. Daemon uptime >= 95 % of the window's minutes (`heartbeat.jsonl`, one line a minute).
3. Missed signals for operational reasons (late, no_quote, stale_quote) <= 5 % of the market's signals that
   reached the entry step.
4. No unresolved code drift inside the window.

## Primary metric and verdicts (per primary market)
Expectancy E = mean R per closed trade, fills as recorded (spread paid at entry, stop slippage included).
* **PASS:** coverage met AND E > 0 AND the one-sided 90 % lower bound of E from a day-block bootstrap (blocks =
  UTC days, 5000 resamples, seed 7) > 0 AND E above the 95th percentile of a matched random-entry control run on
  the same window with `study/scanner_research.py`'s procedure (same count, direction, stop distance, RR, entry
  and exit convention).
* **FAIL:** coverage met AND (E <= 0 OR the one-sided 90 % upper bound < 0).
* **INCONCLUSIVE:** everything else, including any coverage failure.
A PASS qualifies a market only for a next, separately specified test (for example a demo robot) decided by GPT and
the owner. It is never a deployment decision and never a recommendation to members.

## Always reported (pass or not)
Expectancy, sum R, max drawdown in R (closed-trade curve), win rate, cost in R (spread / risk), stop slippage in R,
detection latency and quote age (median, p95), missed signals by reason, refusals by reason (against_structure,
paused_wrong_side, no_structure, no_last_bos, position_open, stop_in_spread_zone, price_through_stop), bad ticks,
uptime, and the comparison with the bar-close backtest (labelled as a different model). Data limitations stated:
demo-server prices, broker spread only, no swaps or commissions, no brakes / recovery / sizing, no sticky chain.

## Separation
The scanner reads and writes only `live/scanner/`. It is not read by the shared demo / Compte pipeline, the lab,
the proof pages' numbers or the frozen entry study (`review/DELAYED_ENTRY_PREREG.md`), and none of them is read by
this protocol. The scheduled Valère fidelity diagnostic (Fri 2026-10-16 12:00 UTC) is unaffected.

## App wording during the window
"Bientôt" / "Prêt" = the price is near a trigger level; the page says these are not trading recommendations. The
page may show running virtual results; looking at them changes nothing in this protocol.

## FROZEN - 2026-10-11 23:39:26 UTC (commit 4211f73)
Window: 2026-10-11 23:40:00 UTC -> 2026-11-22 23:40:00 UTC (42 calendar days). Code fingerprint:
`live/scanner/protocol_fingerprint.json` (owl_scanner.py a548c7dd..., structure_bos_bot.py 23cb49b4...,
pb_gate.py 51a017db..., owl_chart_feed.py c9623da9...). v3 trades opened before 23:40:00 UTC (JP225, UK100, DE30,
opened during the test start) are outside the window and not scored.
