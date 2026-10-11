# SCANNER-F2 - forward protocol for the setup scanner (virtual only)

Replaces SCANNER-F1 (`review/SCANNER_FORWARD_PROTOCOL.md`, frozen 4211f73, kept unchanged as a record) on GPT's
review of 59f09ee: F1's random control was the bar-close procedure, not comparable with v3 quote entries and tick
exits; F1 imported working engine files; its guard failed open. **F1 was never scored and no F1 outcome was
inspected** (the scorer did not exist; the records were not read). F2 is frozen by the FROZEN line at the bottom;
nothing in it changes after that line.

## What is scored
* **Strategy records:** `live/scanner/forward_v3.jsonl`, `engine: v3-quote`, whose OPEN (`detect`) lies inside the
  window. v2 close-price records and every backtest are never scored here.
* **Engine:** loaded ONLY from the isolated bundle `live/scanner/engine_f2/` (built by
  `live/scanner/build_engine_bundle.py`; paths rewritten into the bundle; inert stand-ins for the robot module's
  import-time files). `BUNDLE_MANIFEST.json` holds the SHA-256 of every bundle file and of the runner
  `live/owl_scanner.py`. The working robot / chart files are taken off the import path, so product updates do not
  touch the study.
* **Guard (fails closed):** no new strategy OR control entry unless the manifest exists, parses, lists every
  required file, every hash matches, the runner's hash matches, and every engine module in memory was loaded from
  the bundle. Checked at startup before the first entry, then every minute; blocked minutes are written to
  `heartbeat.jsonl` (`drift` field).
* **Execution (v3-quote):** signals from the bundle's `Struct` (seeded 3000 closed M1 bars), `pb_gate("trend")` on
  the pullback state of the last 8000 closed bars (no sticky chain), min stop S_MIN_DIST (BTC) / 10/7 x spread;
  poll every 5 s; entry at a fresh quote (ask buy / bid sell); quote > 30 s old, candle closed > 90 s ago, no quote,
  or price already through the stop = missed (logged); stop = the engine's new protected dot; target 0.8 x the risk
  from the quote; exits on ticks strictly after the entry tick (stop filled at the crossing tick, slippage in R;
  target at target); one strategy position per market; restart replays open positions on ticks.
* **End of window (strategy and controls alike):** every position still open at the window's end is closed at the
  current quote (bid for a buy, ask for a sell), flagged `eow`, and counts.

## Controls (live, same execution path) - `live/scanner/control_v3.jsonl`
For USTEC, XAUUSD, US30, US500, BTCUSD: **40 independent streams per variant**, each with ONE position at a time:
* `coin`: direction by a fair coin;
* `trend`: direction = the pullback trend at entry (no trend = wait), i.e. "the background trend without the
  robot's timing".
A flat stream schedules its next entry after an exponential wait with the market's mean time between strategy
trades; stop distance = a random draw from the market's strategy stop distances as a share of price; frozen in
`engine_f2/control_params.json` (from the last-30-calendar-day bar backtest). Entries only with a fresh quote and an
open market (otherwise retried a minute later), at the 5-s poll (latency recorded), same min-stop rule, same RR,
same tick exits, same costs, same end-of-window rule. Guard blocks controls too.

## Window
42 calendar days from the first full UTC minute after the FROZEN commit's timestamp
(`live/scanner/protocol_window.json`). One review at the end with `study/scanner_score_f2.py` (committed with this
protocol). No rule, parameter or market change during the window.

## Markets
* **Primary:** USTEC, XAUUSD - verdicts; target **100 closed trades each**.
* **Secondary:** US30, US500 - descriptive. They correlate 0.77-0.90 with each other / USTEC (hourly, 60 d): not
  independent confirmation.
* **Reference:** BTCUSD - descriptive. Other scanned markets: descriptive.

## Coverage (all required, else INCONCLUSIVE - never a pass)
1. >= 100 closed strategy trades in the window for the market.
2. Uptime >= 95 % (heartbeat minutes / window minutes).
3. Operational misses (late, no_quote, stale_quote) <= 5 % of (opens + operational misses) for the market.
4. Zero guard-blocked minutes in the window.

## Verdicts (primary markets)
E = mean R per closed strategy trade, fills as recorded (entry spread paid, stop slippage included).
* **PASS:** coverage met AND E > 0 AND the one-sided 90 % day-block bootstrap lower bound of E > 0 (UTC-day blocks,
  5000 resamples, seed 7) AND **net under stress**: E > 0 after subtracting 1.0 x the entry spread per trade (in R)
  as extra commission / slippage AND E above the 95th percentile of the stream E's for BOTH control variants
  (each with >= 20 streams of >= 5 closed trades).
* **FAIL:** coverage met AND (E <= 0 OR the one-sided 90 % upper bound < 0).
* **INCONCLUSIVE:** anything else.
Results are called "net" only under the 1.0-spread stress. A PASS qualifies a market only for a separately specified
next test; never a deployment, never a member recommendation, never automatic promotion.

## Always reported
E, sum R, max DD R, win rate, cost R, slippage R, E at +0.5 and +1.0 spread stress, bootstrap bounds, latency and
quote age, missed by reason, refusals, end-of-window closes, uptime, guard blocks, control distributions per variant,
and the backtest comparison labelled as a different model (bar close). Data limitations: demo-server prices, broker
spread only, no swaps or commissions beyond the stress, no robot brakes / recovery / sizing, no sticky chain.
In-sample percentiles from `study/scanner_research.py` are EXPLORATORY.

## Separation
Writes only `live/scanner/`. Not read by, and does not read, the shared demo / Compte pipeline, the lab, the proof
numbers, the frozen entry study, or the separate portfolio study (`review/PORTFOLIO_STUDY_SPEC.md`). The Valère
fidelity diagnostic (Fri 2026-10-16 12:00 UTC) is unaffected.
