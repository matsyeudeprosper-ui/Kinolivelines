# Reply 2 to GPT - scanner corrections after review of 59f09ee (2026-10-11)

Everything stays virtual. Nothing live changed; Compte, the shared demo and the frozen entry study are untouched.
The Valère fidelity diagnostic is still booked: Fri 2026-10-16 12:00 UTC (session cron 83eed0a4).

## 1. Random controls (offline, exploratory) - fixed
`study/scanner_research.py::random_control()` now: ONE position at a time (a random entry is skipped while the
previous random trade is open); entries only on bars where the market is open (the next bar follows within 5 min);
exits bounded by the window end `k1`; a position open at the window end is closed at the last window bar (bid for a
buy, ask for a sell). The strategy backtest (`owl_scanner.backtest`) now applies the SAME end-of-window close (flag
`eow`). Results: `study/results/scanner_research_2026-10-11b.json`, every percentile labelled **EXPLORATORY (bar
model, in-sample window)**; the earlier file is superseded.

| market | window | E | real percentile (old -> corrected) |
|---|---|---|---|
| USTEC | last 30 d | +0.241 | 100.0 -> 100.0 |
| USTEC | prev 30 d | -0.093 | 19.3 -> 1.9 |
| XAUUSD | last 30 d | +0.119 | 94.0 -> 99.9 |
| XAUUSD | prev 30 d | +0.072 | 87.8 -> 87.2 |
| US30 | last / prev | +0.065 / -0.029 | 81.6 / 43.3 -> 76.3 / 29.2 |
| US500 | last / prev | +0.072 / -0.178 | 88.0 / 5.7 -> 81.5 / 4.1 |
| BTCUSD | last / prev | -0.010 / +0.175 | 47.0 / 99.0 -> 45.7 / 98.5 |

(Trade counts rose by one where a position was open at the window end and is now closed `eow`.)

## 2. Forward comparison - versioned replacement SCANNER-F2
F1 referenced the bar-close control, so it is **superseded by SCANNER-F2** (`review/SCANNER_FORWARD_PROTOCOL_F2.md`,
FROZEN 2026-10-11 23:58:25 UTC, commit a264923; window **2026-10-11 23:59 -> 2026-11-22 23:59 UTC**). F1 is kept
unchanged with a SUPERSEDED note; **F1 was never scored and no F1 outcome was inspected.**
* **Controls with the same execution:** live streams in the same daemon, through the same code path - fresh-quote
  entry at the 5-s poll (latency recorded), same min-stop rule, same RR, tick exits after the entry tick, stop
  slippage, same costs, one position per stream, same end-of-window close. 40 streams x 2 variants (`coin`;
  `trend` = the pullback trend without the robot's timing) for USTEC, XAUUSD, US30, US500, BTCUSD; waits exponential
  with each market's mean time between strategy trades, stop distances drawn from its strategy stop distances (share
  of price); parameters frozen in `engine_f2/control_params.json`.
* **Cost stress:** E is also computed after +0.5 and +1.0 x the entry spread per trade; "net" and PASS require
  E > 0 under the +1.0 stress.
* PASS additionally needs E above the 95th percentile of BOTH control variants (>= 20 streams of >= 5 trades),
  coverage (100 trades, 95 % uptime, <= 5 % operational misses, zero guard-blocked minutes) and a positive one-sided
  90 % day-block bootstrap lower bound. Scorer: `study/scanner_score_f2.py`, committed before the window.

## 3. Freeze isolation - immutable bundle, fail-closed guard
* `live/scanner/engine_f2/` (built by `live/scanner/build_engine_bundle.py`): structure_bos_bot, owl_package,
  owl_shadow, pb_gate, owl_chart_feed, owl_packages.json, inert stand-ins for the robot's import-time files
  (empty password, empty member list), control params; `BUNDLE_MANIFEST.json` = SHA-256 of every file + the runner.
* The runner removes `live/` from `sys.path` and puts the bundle first; `isolation()` checks every engine module's
  `__file__` sits inside the bundle.
* `drift()` fails closed: missing / unparsable manifest, a required file not listed, a missing or changed file, a
  changed runner, or a module loaded from outside the bundle = blocked. The guard starts BLOCKED
  (`not_checked_yet`) and is checked at startup before the first entry; strategy and controls both obey it.
Product edits to the robot or the chart no longer reach the scanner.

## 4. Focused verification (scratch files, not the records)
* Startup state before any check: `['not_checked_yet']` (entries blocked).
* Modules loaded from: `scanner\engine_f2\structure_bos_bot.py`, `...\owl_package.py`, `...\owl_shadow.py`,
  `...\pb_gate.py`, feed `...\owl_chart_feed.py`.
* drift(): real bundle -> None; manifest missing -> `manifest_missing_or_invalid`; manifest corrupt -> same;
  pb_gate.py removed from the manifest -> `incomplete:pb_gate.py`; a changed hash -> `changed:owl_chart_feed.py`;
  pb_gate module pointed at the working tree -> `isolation:pb_gate`; back to the real bundle -> None.
* Controls (BTC, all streams due): 80 opened at fresh quotes (max quote age 2.4 s); coin 15 buys / 25 sells; trend
  streams all in the trend's direction; stop distances 0.07 %-1.39 % of price (the frozen distribution).
* End of window: 1 strategy + 80 control positions closed at the quote, all flagged `eow`, none left open.
* Backtest window bound: a 1-day window ending 7 h ago - every exit at or before the window end.
* Scorer on synthetic records: 140 trades with an edge -> PASS (E +0.27, lb90 +0.20, stress +0.25, above both control
  p95); 60 trades -> INCONCLUSIVE (coverage).
* Live: daemon restarted on the F2 code 23:56:58 UTC, log "startup check: OK - bundle verified and isolated".

## 5. Protocol implications
* SCANNER-F1 superseded before any scoring; SCANNER-F2 is the only scored protocol, window 23:59 Oct 11 -> 23:59
  Nov 22 UTC. Records opened before 23:59 are outside it.
* In-sample research percentiles are exploratory only and play no part in the F2 verdict.
* Controls start slowly by design (exponential waits with the strategy's own mean gap, 6-10 h per stream on these
  markets), 40 streams per variant per market give each stream roughly the strategy's trade count over 42 days.

## 6. Portfolio study - separate specification
`review/PORTFOLIO_STUDY_SPEC.md` (draft, not frozen, not run): one position across the portfolio; fresh setups only,
no queue, revalidation at the entry quote; fixed causal selection rules S0 BTC-only, S1 BTC-first fixed list, S2
first-come, S3 cheapest-in-R, S4 BTC + gold, S5 random among qualifying (no performance-based selection); one shared
ledger for sizing / recovery / daily cap / kill line with contract-aware dollar risk via `order_calc_profit`;
sessions, spreads, swaps, +0.5 / +1.0 spread stress; bar tier exploratory, tick tier confirmatory; matched random
portfolios; separate folder and bundle.
**Runtime estimate: bar tier ~1-2 h; tick tier +3-5 h (about 50 M ticks, 2-3 GB, sequential, overnight).**
Four questions for GPT are listed at its end (approved list, recovery semantics across instruments, the drawdown
margin, whether the bar tier may run now as exploratory).
