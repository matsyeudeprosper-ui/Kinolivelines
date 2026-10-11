# Setup scanner v2 - report for GPT (2026-10-11)

Owner request (Mike, 2026-10-11): make the Marché page a place where the app scans other symbols for the
robot's setup; **first version = virtual trades only**, keep records, and see whether each symbol's backtest
matches its forward test. Owner also asked to avoid symbols that move with BTC.

**Nothing live changed.** The live robot, its packages and the frozen entry study are untouched. The scanner
reads prices from the chart feed's demo terminal (attaches without logging in) and never sends an order.

## 1. What the scanner runs (live/owl_scanner.py, engine tag `v2-robot-struct`)

Signals come from the robot's own code, not a re-implementation:

* `structure_bos_bot.Struct` - the robot's incremental structure engine, imported (argv masked, `say` muted),
  seeded with `SEED_BARS` = 3000 closed M1 bars, then stepped on every closed bar like the bot's main loop.
* Entry = the bar the engine returns a signal on: **close beyond the BOS level** (ask = bid close + bar spread
  for a buy), **stop = the new protected dot** the engine returns, target = `RR` (0.8) x risk.
  (The live bot has `TOUCH_ENTRIES = False` on every variant since the 2026-09-11 execution audit; on the close
  path the `used_hi/used_lo` level marks are only set by the disabled touch path, so every engine signal is a
  candidate.)
* Trend gate: `pb_gate.pb_gate("trend", d, px, trend, choch, choch_lvl, last_bos)` - the same function the live
  bot calls - with the pullback state computed from the last 8000 closed bars by the feed's
  `build/engine/pullback_view` (the arithmetic of `structure_bos_bot.pb_state_now()`). Difference: **no sticky
  chain** (the live bot reads the feed's sticky pullback chain; the scanner cannot have one for every symbol's
  past, so backtest and forward both use the plain view).
* Minimum stop: `S_MIN_DIST` = 10 pts on BTC; on other symbols the same idea scaled to their spread
  (10/7 x bar spread, BTC's spread being 7).
* One virtual position per symbol at a time (`my_positions()`).
* Exits on M1 bars: buy closes at bid, sell at ask; SL and TP touched on the same bar = **loss** (order unknown).
* Results in **R** (result / risk) so symbols compare without contract sizes.
* Prices are scaled x10^(digits-2) before the feed's engine (it rounds to 2 dp); `Struct` gets raw prices.

**Not modelled:** weather brakes (nervosity, movement, awake), debt / recovery rules, lot sizing and adds, the
internal structure, day caps, kill line. The page states this.

The backtest (`--backtest SYM --days 30`) and the forward daemon call the same functions. 30 days = 17 s/symbol.

## 2. Fidelity check (BTC vs the witness account)

Last 30 days (2026-09-11 -> 2026-10-11), Valère journal `bos_journal_valere.csv`, main entries only (BOS and
FLIP-BOS; internal trades and adds excluded): **70 of 70 real entries coincide with an engine signal** (same side,
entry within bar close .. +150 s) and **all 70 have the same stop within 15 pts**. The engine produced 520 signals in
that period; the robot took 70 (brakes, recovery rules, open position, and - before 10-10 - no trend gate).

(v1 of the same day used the chart engine on a sliding 8000-bar window; it matched only 6 of 77. Archived in
`live/scanner/v1/`, not to be used.)

## 3. Symbol choice

Lowest cost (spread / H1 ATR) from `study/cost_census.csv`, spread across asset classes, then correlation of
hourly log returns with BTCUSD over ~60 days (shared consecutive hours):

| kept | corr | | kept | corr |
|---|---|---|---|---|
| XAUUSD | 0.31 | | UK100 | 0.14 |
| XAGUSD | 0.31 | | JP225 | 0.25 |
| USOIL | -0.14 | | EURUSD | 0.17 |
| US30 | 0.19 | | GBPUSD | 0.19 |
| USTEC | 0.32 | | USDJPY | -0.11 |
| US500 | 0.30 | | BTCUSD | reference |
| DE30 | 0.21 | | | |

ETHUSD dropped (0.85). The daemon recomputes the correlation every 6 h (`max_corr` flag 0.5).

## 4. Backtests, 30 days, same rule (live/scanner/backtest_<SYM>.json)

| symbol | trades | win % | avg R | sum R | PF |
|---|---|---|---|---|---|
| USTEC | 170 | 60.6 | +0.091 | +15.4 | 1.23 |
| XAUUSD | 141 | 59.6 | +0.072 | +10.2 | 1.18 |
| US30 | 134 | 58.2 | +0.048 | +6.4 | 1.11 |
| BTCUSD | 80 | 55.0 | -0.010 | -0.8 | 0.98 |
| JP225 | 189 | 52.4 | -0.057 | -10.8 | 0.88 |
| US500 | 144 | 52.1 | -0.062 | -9.0 | 0.87 |
| DE30 | 181 | 51.4 | -0.075 | -13.6 | 0.85 |
| USOIL | 141 | 51.1 | -0.081 | -11.4 | 0.83 |
| EURUSD | 140 | 50.0 | -0.100 | -14.0 | 0.80 |
| UK100 | 152 | 47.4 | -0.147 | -22.4 | 0.72 |
| USDJPY | 131 | 47.3 | -0.148 | -19.4 | 0.72 |
| XAGUSD | 119 | 46.2 | -0.168 | -20.0 | 0.69 |
| GBPUSD | 161 | 38.5 | -0.307 | -49.4 | 0.50 |

Break-even win rate at 0.8R with no cost slippage beyond the bar spread is 55.6 %.

**Caveats, stated to the owner:** one 30-day window, no random-entry control yet, no halves split, M1-bar exits
(conservative on same-bar ties), demo-server prices, spread from the bar's spread field, no brakes. The three
positive symbols are **leads, not evidence**.

## 5. Forward record

`live/scanner/forward.jsonl` - every virtual open/close (engine tag v2), from 2026-10-11 ~22:40 UTC. The page
(Marché > Scanner > Résultats) shows backtest vs virtual avg R per symbol; levels only for Stratégie / admin.

## 6. Proposed next steps (for GPT to decide)

1. **Random-entry control per symbol**: same count, same direction rule and stop-distance distribution, random
   bars - does the setup beat random on USTEC / XAUUSD / US30?
2. **Halves and a second window** (e.g. the 30 days before) on the three leads.
3. **Preregister** a forward criterion before any symbol is considered for money: e.g. >= 30 virtual trades,
   forward avg R within the backtest's bootstrap interval and > 0, after a cost haircut.
4. Optional: model the weather brakes in the scanner so the BTC line can be compared to the real account's
   *taken* trades, not only its signals.

## 7. Also in this commit

The frozen entry study bundle: 8 bundle files on disk already matched the FROZEN manifest
(`review/entry_study_manifest.json`, 21/21 hashes OK) but had never been committed at the freeze (git HEAD
differed). They are committed now unchanged; `owl_secrets.json` stays out of git. Nothing in the study changed.

## 8. Product changes of the day (no strategy rule touched)

Landing page (proof card, worst-moment card, calculator, Telegram weekly summary, share image, funnel events),
home page theme pass (one label style, rattrapage / week-month / progression / market cards, "Le robot en ce
moment" card with honest timing, lab latest-clue card), Historique / Réglages / Robot view theme pass, and
restart.ps1 no longer starts a duplicate app when a watchdog relaunched it.
