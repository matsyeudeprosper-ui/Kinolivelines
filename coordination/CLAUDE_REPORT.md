FROM: CLAUDE
TASK: 001 — EXNESS FEASIBILITY CENSUS

Implementation and verification only. No strategy is chosen, no entry rule is proposed,
the live bot was not modified, and no order was placed, cancelled or changed.

---

## Commit

| | |
|---|---|
| Commit SHA | `16a8367853e861a9109b794c227bd2945878f00c` |
| Branch | `main` |
| Parent | `3c54055452d00ef45b00bdc1c5eeb8bfdc655249` |
| Date | 2026-08-02 |

## Environment measured

| | |
|---|---|
| Terminal | MetaTrader 5 build 6061, `C:\Program Files\MetaTrader 5` |
| Account | 436771046, Exness-MT5Trial9, Exness Technologies Ltd |
| Type | **DEMO**, leverage 1:2000 |
| Deposit currency | USD (live equity $954.57 at scan time) |
| Reference balance | **$979.00** — the figure named by the task, used for every risk and exposure test |

## Commands run

```
python study/exness_feasibility_census.py     # two-stage scan, 73.5 min
python study/verify_history_depth.py          # post-hoc integrity audit, filesystem only
```

## Symbols scanned

| | |
|---|---|
| Symbols on account | **356** (194 visible, 162 hidden — **all** scanned, hidden included) |
| Screened in stage 1 | **356** (≤ 400 D1 bars each) |
| Reached stage 2 | **92** (full depth, 20000 bars requested) |
| Stage-2 rows completed | 92 (none lost) |
| Measured cleanly | 224 |
| Could not be fully measured | 132 (all recorded, none hidden) |

## Group counts

| Group | Count |
|---|---|
| **A — TRADEABLE NOW** | **50** |
| **B — POSSIBLY TRADEABLE** | **67** |
| **C — NOT TRADEABLE** | **239** |

By asset class:

| Asset class | A | B | C |
|---|---|---|---|
| Forex | 16 | 27 | 98 |
| Stocks | 32 | 36 | 34 |
| Indices | 2 | 3 | 6 |
| Crypto | 0 | 1 | 30 |
| CryptoCross | 0 | 0 | 6 |
| Energies | 0 | 0 | 3 |
| Forex_Indicator | 0 | 0 | 59 |
| Idx_Enlarge | 0 | 0 | 3 |

All 50 group-A symbols trade **both long and short** and went through stage 2, so none carry
a 400-bar provisional history. 48 are corroborated `EXACT`; 2 are `EXACT_LOWER_BOUND` — see
the defect section below.

## Top 20 tradeable instruments

Ranked by the five criteria specified: lowest spread relative to D1 ATR, lowest holding
cost, most history, manageable minimum-lot risk, both sides available. Rank is the mean of
the four numeric rank positions; both-sides availability is a filter (every group-A symbol
satisfies it).

| # | Symbol | Class | Min lot | Notional | Expo | 2-ATR loss | Risk | Sprd/ATR | Long %/y | Short %/y | D1 bars | D1 start |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | USDCADm | Forex | 0.01 | $1,000 | 1.02x | $7.16 | 0.73% | 2.2% | -0.0 | -0.0 | 2522 | 2018-07-03 |
| 2 | AUDUSDm | Forex | 0.01 | $703 | 0.72x | $8.08 | 0.83% | 2.2% | -0.0 | 1.0 | 2522 | 2018-07-03 |
| 3 | NZDCADm | Forex | 0.01 | $589 | 0.60x | $6.89 | 0.70% | 2.7% | -0.0 | 0.6 | 2522 | 2018-07-03 |
| 4 | AUDNZDm | Forex | 0.01 | $703 | 0.72x | $6.41 | 0.65% | 3.3% | -0.0 | 2.6 | 2522 | 2018-07-03 |
| 5 | AUDCHFm | Forex | 0.01 | $704 | 0.72x | $7.62 | 0.78% | 2.9% | -0.0 | 6.2 | 2522 | 2018-07-03 |
| 6 | NFLXm | Stocks | 0.01 | $72 | 0.07x | $5.14 | 0.53% | 2.3% | 5.1 | 5.1 | 1603 | 2020-03-16 |
| 7 | AUDCADm | Forex | 0.01 | $703 | 0.72x | $6.80 | 0.69% | 3.8% | -0.0 | 3.1 | 2522 | 2018-07-03 |
| 8 | AUDJPYm | Forex | 0.01 | $704 | 0.72x | $9.31 | 0.95% | 2.5% | -0.0 | 0.5 | 2522 | 2018-07-03 |
| 9 | WMTm | Stocks | 0.01 | $111 | 0.11x | $5.04 | 0.51% | 2.0% | 6.6 | 13.2 | 1603 | 2020-03-16 |
| 10 | AUS200m | Indices | 0.06 | $377 | 0.39x | $8.97 | 0.92% | 2.8% | -0.0 | 10.6 | 2491 | 2018-06-12 |
| 11 | CADJPYm | Forex | 0.01 | $714 | 0.73x | $8.89 | 0.91% | 3.4% | -0.0 | 1.5 | 2522 | 2018-07-03 |
| 12 | NZDCHFm | Forex | 0.01 | $590 | 0.60x | $6.18 | 0.63% | 6.0% | -0.0 | 3.7 | 1705 | 2021-02-14 |
| 13 | NZDJPYm | Forex | 0.01 | $589 | 0.60x | $8.81 | 0.90% | 4.2% | -0.0 | 3.1 | 2522 | 2018-07-03 |
| 14 | KOm | Stocks | 0.01 | $88 | 0.09x | $3.85 | 0.39% | 5.2% | 4.1 | 33.2 | 1603 | 2020-03-16 |
| 15 | XOMm | Stocks | 0.01 | $156 | 0.16x | $6.96 | 0.71% | 2.9% | 4.7 | 7.0 | 1603 | 2020-03-16 |
| 16 | CMCSAm | Stocks | 0.01 | $24 | 0.02x | $1.53 | 0.16% | 7.8% | 0.0 | 91.2 | 1413 | 2020-12-14 |
| 17 | HK50m | Indices | 0.07 | $232 | 0.24x | $7.83 | 0.80% | 4.6% | -0.0 | 6.3 | 1968 | 2019-07-10 |
| 18 | WFCm | Stocks | 0.01 | $87 | 0.09x | $3.87 | 0.40% | 5.2% | 4.2 | 21.0 | 1603 | 2020-03-16 |
| 19 | MOm | Stocks | 0.01 | $68 | 0.07x | $4.09 | 0.42% | 3.4% | 5.4 | 16.1 | 1413 | 2020-12-14 |
| 20 | BILIm | Stocks | 0.01 | $19 | 0.02x | $1.41 | 0.14% | 7.1% | 0.0 | 0.0 | 1216 | 2021-09-27 |

Full ranked list of all 50 is in the report and CSV.

---

## Calculation formulas

```
notional_usd      = order_calc_profit(BUY, sym, vol_min, ask, ask*1.01) / 0.01
margin_usd        = order_calc_margin(BUY, sym, vol_min, ask)          both sides computed
pl_1pct           = order_calc_profit(BUY, sym, vol_min, ask, ask*1.01)
ATR20_D1          = SMA of the last 20 Wilder True Ranges on D1 completed bars
loss_k_atr        = |order_calc_profit(BUY, sym, vol_min, ask, ask - k*ATR20)|
spread_pct_of_atr = (ask - bid) / ATR20_D1 * 100
swap_usd_day_side = order_calc_profit(BUY, sym, vol_min, ask, ask + swap_pts_side*point)
annual_cost_pct   = -(swap_usd_day * 365) / notional_usd * 100     positive = you pay
risk_2atr_pct     = loss_2_atr / 979 * 100
exposure_x_equity = notional_usd / 979
```

### Unit-conversion assumptions (all recorded, none guessed)

1. **Economic notional is NOT `price × contract_size`.** That product is denominated in the
   *profit currency*. Notional is recovered from the terminal's own converter, so all
   cross-rate conversion is done by MT5 rather than assumed. This mattered enormously:
   **131 of 240** measurable symbols diverge more than 1% from the naive product.

   | Symbol | Profit ccy | price×contract | True USD notional | Error factor |
   |---|---|---|---|---|
   | ETHBTCm | BTC | 0.0295 | $1,866 | 63,209× |
   | BTCXAUm | XAU | 0.156 | $633 | 4,047× |
   | BTCXAGm | XAG | 549 | $31,614 | 57.6× |
   | ZARJPYm | JPY | 9,547 | $60 | 0.006× |
   | EURJPYm | JPY | 181,812 | $1,154 | 0.006× |

   `raw_price_x_contract` and `notional_vs_raw_ratio` are both kept in the CSV so the
   divergence is auditable per symbol.

2. **Margin** always from `order_calc_margin()`, never notional/leverage — Exness applies
   per-symbol and tiered leverage that one account-level number does not capture.

3. **Swap mode is confirmed before any conversion.** Only modes 0 (DISABLED) and 1 (POINTS)
   occur on this account; the census asserts this per symbol and records
   `swap_converted=False` for any other mode rather than converting it silently. All 224
   cleanly-measured symbols are POINTS. Points are converted to deposit currency using the
   terminal itself, which applies contract size, volume and FX exactly as an equivalent
   price move would. Sign preserved: positive = credit.

4. **Annual overnight cost** assumes a charge on all 365 calendar days — a triple-swap day
   means a 7-day week is billed across 5 trading days, so a year is ~365 swap-days, not
   ~252. Triple-swap day is recorded per symbol (Wednesday for 232 symbols, Friday for 124).

5. **Spread** is recorded twice: `spread_price_live` (a single ask−bid snapshot, which can
   be unrepresentative) and `spread_price_med_d1` (median of the spread on each D1 bar).
   Item 21 is reported from the live spread as asked; the **ranking and the
   "too expensive" test use the median**, because a snapshot has misled on this account before.

6. **ATR-loss fallback**: if `ask − 2·ATR ≤ 0` the terminal cannot price it and a linear
   fallback is used, flagged in `atr_loss_method`. **0 symbols** needed it.

7. **Price source** falls back to the last D1 close if a market is closed, flagged in
   `price_source`. **0 symbols** needed it — every symbol had a live quote.

### Grouping rules

- **A** — 2-ATR stop at min lot ≤ 1.00% of $979, exposure ≤ 3× equity, both sides tradeable,
  ≥ 250 D1 bars, spread ≤ 10% of D1 ATR.
- **B** — fails A but within 3× those limits (≤ 3% risk, ≤ 9× exposure), spread ≤ 25% of ATR.
- **C** — everything else.
- **Stage-2 survivor rule** (as specified): ≥ 250 bars, usable profit calc, spread not
  clearly excessive, and either (risk ≤ 1.00% AND expo ≤ 3.00×) or exactly **one** of those
  missed by ≤ 25% (risk ≤ 1.25%, or expo ≤ 3.75×). Failing both, even slightly, disqualifies.

---

## Exact vs provisional

| Label | Count | Meaning |
|---|---|---|
| `EXACT` | 90 | `d1_start`, `d1_bars` final and independently corroborated |
| `EXACT_LOWER_BOUND` | 2 | true history is deeper than recorded (see below) |
| `PROVISIONAL` | 264 | stage 1 only; `d1_bars` capped at 400, `d1_start` is a lower bound |

250 of the provisional rows hit the 400-bar ceiling. For **every** provisional row, all
sizing, spread, swap, margin, risk and exposure figures are still **exact** — only depth of
history is unresolved, and each was excluded for a reason history cannot change.

All 50 group-A rows went through stage 2 (48 `EXACT`, 2 `EXACT_LOWER_BOUND`); none is
`PROVISIONAL`.

## Errors and missing data

| Status | Count | Examples |
|---|---|---|
| `not_tradeable` (trade_mode=DISABLED) | 115 | BCHUSDm, LTCUSDm, XRPUSDm, AAVEUSDm |
| `no_history` | 16 | AUDSGDm, CADCHFm, DKKJPYm, DXYm, EURAUDm |
| `no_quote` | 1 | XAUUSD247m |
| **Total not fully measured** | **132** | all retained in the CSV, none dropped |

Group C failure reasons (a symbol can fail for several):

| Reason | Count |
|---|---|
| not tradeable at all | 115 |
| spread too expensive | 63 |
| min-lot risk too large | 44 |
| not tradeable both sides | 19 |
| no history | 16 |
| exposure too large | 6 |
| history inadequate | 3 |
| no quote | 1 |

Zero symbols had an unconvertible swap. Zero needed the ATR-loss fallback.

### Defect found and corrected

The census initially labelled all 92 stage-2 rows `EXACT`. An independent audit
(`verify_history_depth.py`, filesystem only, no terminal calls) compared each reported D1
start against the earliest non-stub yearly file in the terminal's own minute-history cache.
**2 of 92 were understated:**

- `EURCHFm` — recorded 403 bars from 2025-04-18, cache reaches **2021** (4 years missing)
- `EURCADm` — recorded 409 bars from 2025-04-11, cache reaches **2024** (1 year missing)

Cause: MetaTrader answered the deep request from a D1 cache it had not finished building,
returning a truncated series rather than an error. Minute data from 2021 cannot coexist with
a genuine D1 history starting 2025, which is what exposed it.

Blast radius is depth-of-history only. ATR(20) reads the most recent 20 bars and is
unaffected; sizing, margin, notional, spread, swap and the risk/exposure tests never use
history depth. Both symbols already clear the ≥250-bar test on the short count and the true
count can only be larger. Understated history can only push a symbol **down** the group-A
ranking, so the ranking is conservative with respect to this defect, not inflated — and both
sit at ranks 47 and 49 of 50.

## Terminal contention

| | |
|---|---|
| Latency probes | 128 |
| Median / p95 / max | 0 ms / 2 ms / 7,909 ms |
| Slow-terminal pauses | 1 |
| Aborted for contention | **No** |

One event: at `TRYJPYm` during stage 2 the probe returned 7,909 ms, the census paused 20 s,
re-probed at 0.1 ms and resumed. **No result was taken from a strained terminal** — the
census waits for normal response before measuring anything further.

Requests were strictly sequential, one symbol at a time, with a delay between them and a
larger one between deep downloads. Market Watch was restored in a `finally:` block, verified
back to its exact 194-symbol baseline; symbols already visible were never touched. The bot
and both recorders were left running and were not modified.

## Timing

| Phase | Duration |
|---|---|
| Stage 1 (356 symbols, shallow) | 24.0 min |
| Stage 2 (92 survivors, full depth) | 49.5 min |
| **Total download time** | **73.5 min** |

The two-stage design was necessary: deep history forces MetaTrader to download every yearly
file per symbol (~8.8 each) and the server feeds them at roughly 6–9 files/min. Full depth
across all 356 symbols measured out at ~4 hours of continuous downloading against the same
terminal the live bot polls. Restricting deep history to the 92 survivors cut that to 73.5
minutes with no loss of fidelity for any symbol that could plausibly be traded.

## Files changed

| File | Status |
|---|---|
| `study/exness_feasibility_census.py` | new — two-stage census |
| `study/verify_history_depth.py` | new — history-depth integrity audit |
| `study/results/exness_feasibility_census.csv` | new — 356 rows × 76 columns, failures included |
| `study/results/exness_feasibility_report.txt` | new — full report + audit addendum |
| `study/results/history_depth_audit.csv` | new — per-symbol audit table |
| `coordination/CLAUDE_REPORT.md` | new — this file |

Nothing under `live/` or `recorder/` was modified or committed; those files carry the
running bot's in-flight state and are not part of task 001.

---

No strategy recommendations are made in this document.
