FROM: CLAUDE
TASK: 003 — FX MOMENTUM 3M-1M V1

Implementation and verification only. The strategy was specified entirely by the strategy
lead; nothing here was tuned, optimised or substituted. The live bot was not modified and no
order was placed or changed.

Earlier reports: `CLAUDE_REPORT_TASK001.md`, `CLAUDE_REPORT_TASK002.md`.

---

# VERDICT: **FAILED** — 5 of 13 conditions passed

Per the specification, V1 is reported FAILED and has **not** been optimised or repaired. No
parameter change or replacement strategy is proposed anywhere in this document.

The failure is not marginal. The strategy loses money, loses to a random pair-and-direction
picker, and its exact reverse is profitable.

| | Result |
|---|---|
| Net (spread only) | **−$75.84** (−7.75%), 22 trades, 27.3% win rate |
| Profit factor | **0.53** |
| Under 3.0% financing stress | **−$99.20** (−10.13%) |
| Median random strategy | **−$33.24** — baseline is *worse* |
| Reverse strategy | **+$25.42** — the inverse is profitable |
| Randomisation p-value | **0.7304** |
| Final equity | $903.16 (no margin call) |

---

## Commit

| | |
|---|---|
| Commit SHA | `PENDING_SHA` |
| Branch | `main` |
| Parent | `4a26af2` |
| Date | 2026-08-02 |

## Commands run

```
python study/fx_momentum_v1.py
```

## Executable universe — exactly 19 pairs, printed before any test

```
AUDCADm  AUDCHFm  AUDJPYm  AUDNZDm  AUDUSDm  CADJPYm  EURCADm  EURCHFm
EURGBPm  EURJPYm  EURNZDm  EURUSDm  GBPAUDm  GBPCHFm  NZDCADm  NZDJPYm
USDCADm  USDCHFm  USDJPYm
```

8 currencies: AUD, CAD, CHF, EUR, GBP, JPY, NZD, USD.

Dropped from the task-002 23, all on revised canonical risk > 1.50%:
`CHFJPYm` 1.716%, `GBPJPYm` 1.929%, `GBPNZDm` 1.575%, `GBPUSDm` 1.662%.
`NZDCHFm` remains excluded from task 002 (spread 6.02%); **the 6.00% limit was not rounded.**

Note `GBPUSDm` is not executable, so there is no direct GBP/USD column — GBP conversion runs
through the fitted currency graph.

## Formulas

```
currency system   log(pair) = value(BASE) - value(QUOTE),  value(USD) = 0
                  solved by least squares each completed week; residual rms recorded
conversion        XXX->USD rate = exp(value(XXX))        <- the contemporaneous graph
currency_score    value(latest completed Friday) - value(13 completed weeks earlier)
pair_score        currency_score(BASE) - currency_score(QUOTE)
selection         the pair with the largest |pair_score|; >0 BUY, <0 SELL; no threshold
ATR               SMA of 20 True Ranges on canonical 17:00-NY sessions completed before entry
stop              entry -/+ 2.0 x canonical ATR(20), never trailed
BUY               enter ask = bar + spread, exit bid = bar,          stop on bar low
SELL              enter bid = bar,          exit ask = bar + spread, stop on bar high + spread
gap fill          worse of the stop price or the first tradeable price
P&L               (exit - entry) x direction x 100000 x 0.01 x quote->USD (contemporaneous)
financing         notional_usd x rate / 365 x days_held
```

**Broker facts verified, not assumed:** `symbol_info('EURUSDm').chart_mode == 0`
(SYMBOL_CHART_MODE_BID), and the last H1 close reproduced the live bid exactly (1.15284 vs bid
1.15284, ask 1.15332). So historical OHLC are **bid** prices and the ask side is reconstructed
by adding the bar's own recorded spread. Contract 100,000, min lot 0.01 for all 19.

## Data corrections made

**1. Strengthened completeness audit found defects task 002 could not see.** Task 002 measured
gaps only *inside* the span of bars that arrived, so a session missing its first or last hour
looked complete. Here the expected 24-slot hourly grid is constructed from the session
definition itself, in New York local time:

| | |
|---|---|
| Sessions audited | 24,681 |
| Complete | 24,355 |
| Incomplete | **326** |
| Missing **opening** hour | **96** ← invisible to the task-002 audit |
| Missing **closing** hour | **133** ← invisible to the task-002 audit |

**2. Bug found and fixed during the build.** The canonical file holds all 23 task-002 pairs
while this task trades 19, so the "all symbols present" week test could never be satisfied and
produced 0 usable weeks. Fixed by restricting the panel to the 19 before grouping.

**3. Permutation engine rewritten.** The first run died partway through the 10,000 permutations
because the inner loop used pandas filtering. It was re-indexed into plain arrays, and the fast
path is **asserted equal to the costed engine** before use — it reproduced the baseline exactly
(−$75.84, 22 trades). The assertion is in the script, not just in this report.

## Panels

| Panel | Weeks total | Usable | Excluded | Span |
|---|---|---|---|---|
| Canonical (executable) | 261 | **239** | 22 | 2021-08 → 2026-07 |
| Long D1 (signal only) | 422 | **415** | 7 | 2018-07-13 → 2026-07-31 |

7,961 Sunday D1 candles merged into the following Monday. No forward-filling anywhere.
Currency-fit residual rms: canonical median 9.52e-05 (max 1.11e-03), D1 median 1.23e-04 — the
broker's quotes are triangularly consistent to ~1e-4, and the residual is recorded rather than
smoothed away.

Monthly schedule: **60 rebalances, 0 months skipped** — an H1 bar was always available between
Monday 20:00 and Tuesday 20:00 New York.

## Development results

**The canonical executable panel has no development period** — it begins 2021-08-02 and
development ends 2021-07-31, so 0 months exist. This is a direct consequence of the H1 history
limit reported in task 002, not an omission.

Long-D1 signal, development (through 2021-07-31): **−0.1299** sum log return over 140 months.
The signal was already negative in development.

## Validation results (2021-08-01 → 2023-12-31)

| Scenario | Trades | Net | Return | PF | Max DD |
|---|---|---|---|---|---|
| Spread only | 8 | −$96.25 | **−9.83%** | 0.00 | −9.83% |
| + 3.0% financing | 8 | −$100.71 | −10.29% | 0.00 | −10.29% |

Profit factor 0.00 — **all eight validation trades lost money.**

## Untouched holdout results (2024-01-01 → 2026-07-31)

| Scenario | Trades | Net | Return | PF | Max DD |
|---|---|---|---|---|---|
| Spread only | 14 | +$20.41 | **+2.08%** | 1.32 | −13.74% |
| + 3.0% financing | 14 | +$1.51 | +0.15% | 1.02 | −14.94% |

Holdout is mildly positive but is destroyed by financing stress, and it does not rescue the
combined result. **Holdout was not used to alter anything.**

## Every pass condition, separately

| # | Condition | Result | |
|---|---|---|---|
| 1 | Canonical return positive in validation | −9.83% | **FAIL** |
| 2 | Canonical return positive in holdout | +2.08% | PASS |
| 3 | Positive under 3.0% financing stress | −10.13% | **FAIL** |
| 4 | Doubled-spread result positive | −$77.04 | **FAIL** |
| 5 | Long-D1 and canonical signal same sign | canon −0.1288 / D1 −0.1140 | PASS |
| 6 | Baseline beats median randomised | −$75.84 vs −$33.24 | **FAIL** |
| 7 | Randomisation p ≤ 0.10 | p = 0.7304 | **FAIL** |
| 8 | Reverse performs worse than baseline | +$25.42 vs −$75.84 | **FAIL** |
| 9 | At least 40 completed trades | 22 | **FAIL** |
| 10 | Max drawdown ≤ 20% | −13.74% | PASS |
| 11 | Profit factor > 1.10 | 0.529 | **FAIL** |
| 12 | No trade > 25% of net profit | n/a (net negative) | PASS |
| 13 | No margin call / account failure | final equity $903.16 | PASS |

Condition 5 passes only because **both** panels are negative — agreement on a losing sign.
Condition 12 passes vacuously: with net profit negative there is no profit to concentrate.

## Randomisation

10,000 within-month permutations, seed 20260802, preserving schedule, universe and trading
costs; each draws a random pair and direction from that month's available set.

| | |
|---|---|
| Baseline | −$75.84 |
| Median random | **−$33.24** |
| One-sided p (random ≥ baseline) | **0.7304** |

**73% of random strategies beat the signal.** The signal is not merely absent — it selects
worse than chance over this sample.

## Delayed-entry and doubled-spread controls

| Control | Net | Return | Trades |
|---|---|---|---|
| Baseline | −$75.84 | −7.75% | 22 |
| Entry delayed 24 h | −$55.31 | −5.65% | 23 |
| Entry delayed 1 week | **+$90.64** | **+9.26%** | 29 |
| Doubled spread | −$77.04 | −7.87% | 22 |
| Reverse | **+$25.42** | — | 22 |

Delaying entry by a full week turns the strategy from −7.75% to **+9.26%**. Together with the
profitable reverse and p = 0.73, the timing the signal specifies is worse than both its own
inverse and a one-week-stale version of itself.

Doubling the spread changes the result by only $1.20, because at 22 trades on minimum lot the
spread is not what is losing the money — direction is.

## Maximum drawdown

**−13.74%** (spread only), −14.94% under 3.0% financing. Within the 20% limit; this is the one
risk condition the strategy comfortably meets, largely because minimum-lot sizing keeps every
position small relative to equity.

## Trades skipped

| Reason | Count |
|---|---|
| Stop risk > 1.50% of current equity | **33** |
| Exposure > 2.00× equity | 0 |
| Conversion unreliable | 0 |

**33 of 55 rebalances were skipped**, all on the risk rule — which is why only 22 trades
completed against a required 40. A 2-ATR stop at minimum lot on the JPY crosses costs roughly
$14 against a $14.69 budget, so as equity fell the budget shrank and skips increased. This is
the frozen rule behaving exactly as written ("do not increase size to reach 1.50%"), not a
defect, but it means **the 40-trade condition was close to unreachable by construction** on a
$979 account with this stop and this schedule.

Of the 22 trades taken: 14 exited on the stop, 8 at rebalance; 16 long, 6 short; 10 distinct
pairs, concentrated in `AUDJPYm` (6) and `AUDUSDm` (4). Best +$26.29, worst −$13.62.

## Signal-only tests (no costs, direction only)

| Panel | Development | Validation | Holdout |
|---|---|---|---|
| Canonical | n/a (panel starts 2021-08) | −0.0764 | −0.0524 |
| Long D1 | −0.1299 | −0.0571 | −0.0569 |

**Negative in every period on both panels**, including 8 years of D1 history. Panel overlap
(225 weeks): same pair chosen 67.6% of the time, same direction 84.4%.

Formation diagnostics — **4 and 26 weeks are diagnostics only and cannot replace the frozen 13
now that results have been seen:**

| Panel / period | 4w | 13w (frozen) | 26w |
|---|---|---|---|
| canonical validation | −0.1343 | −0.0764 | +0.0029 |
| canonical holdout | −0.2180 | −0.0524 | +0.0049 |
| long_D1 development | −0.2228 | −0.1300 | −0.1601 |
| long_D1 validation | −0.0689 | −0.0571 | −0.1022 |
| long_D1 holdout | −0.1567 | −0.0569 | −0.0658 |

The 26-week column is marginally positive on the canonical panel and negative on all three D1
periods, which is what an unstable estimate looks like rather than a finding. I am recording it
because the specification required the diagnostic, and explicitly **not** proposing it.

## Errors and assumptions

- **Assumption (spec-directed):** MT5 timestamps treated as UTC. Independently corroborated in
  task 002 — observed session open lands on exactly 17:00 NY, Friday close on 16:00 NY.
- **Assumption:** quote→USD conversion uses the fitted currency graph, `exp(value(QUOTE))`,
  because `GBPUSDm` is not in the executable universe so no direct column exists. Residuals are
  ~1e-4, so the conversion error is immaterial next to a −7.75% result.
- **Assumption:** a canonical week is usable only when all 5 sessions are complete for **all 19**
  pairs — the cross-sectional requirement. 22 of 261 weeks excluded.
- **Interpretation:** "formation, entry or exit week" enforced on the two formation endpoint
  weeks plus the entry and exit weeks.
- **Limitation carried from task 002:** the executable panel spans 4.99 years, not the 6
  requested. Development on the canonical panel is therefore empty.
- No error or exception occurred in the final run. All 19 pairs built; 0 symbols failed.

## Files changed

| File | Status |
|---|---|
| `study/fx_momentum_v1.py` | new |
| `study/results/fx_momentum_v1_trades.csv` | new — 22 trades |
| `study/results/fx_momentum_v1_monthly.csv` | new |
| `study/results/fx_momentum_v1_signal_tests.csv` | new — 18 panel/formation/period rows |
| `study/results/fx_momentum_v1_controls.csv` | new — all controls |
| `study/results/fx_momentum_v1_report.txt` | new — full run log |
| `coordination/CLAUDE_REPORT.md` | this file (task 003) |
| `coordination/CLAUDE_REPORT_TASK002.md` | renamed to preserve task 002 |

Nothing under `live/` or `recorder/` was modified or committed.

---

V1 is reported FAILED. No parameter change and no replacement strategy is recommended here.
