FROM: CLAUDE
TASK: 003A — CORRECTED FX MOMENTUM 3M-1M V1

ACK REBALANCE_OPEN_FIX_20260802

All six corrections applied to the existing `study/fx_momentum_v1.py`; the frozen strategy was
re-run unchanged. **No strategy, parameter, universe, stop size, schedule, pass criterion or
risk limit was altered.** The live bot was not modified and no order was placed or changed.

Task 003's report is preserved at `coordination/CLAUDE_REPORT_TASK003.md`.

---

# VERDICT UNCHANGED: **FAILED**

| | Old (003) | Corrected (003A) |
|---|---|---|
| Conditions passed | 5 / 13 | **4 / 13** (+1 NOT APPLICABLE) |
| Net, spread only | −$75.84 | **−$75.19** |
| Return | −7.75% | −7.68% |
| Profit factor | 0.529 | 0.533 |
| Final equity | $903.16 | $903.81 |

Every correction was real — five of the six changed numbers. **None changed the conclusion.**
The corrections moved the result by $0.65 on a −$75 outcome; the strategy still loses to a
random picker (p = 0.73) and its reverse is still profitable.

## Commit

| | |
|---|---|
| Commit SHA | `PENDING_SHA` |
| Branch | `main` |
| Parent | `9756412` |

## Commands run

```
python study/fx_momentum_v1.py
```

---

# The six corrections, and exactly what each changed

## 1. Unstopped trades now close at the OPEN of the next rebalance bar

**Defect.** The holding window ran `t_utc <= t_exit` and exited at that bar's **close**. Two
errors in one: the old position was monitored for stops *inside* the bar where the new position
opens, and it was credited a full extra hour of drift it could never have captured.

**Fix.** Holding window is now `[t_entry, t_exit)`; the bar at `t_exit` supplies only the exit
open. BUY exits at that open (bid), SELL at open + that bar's spread (ask).

**Effect.** All 8 unstopped trades repriced. Exit *times* did not change (0 of 22), exit
*prices* did. This is the dominant source of the net change.

**Assertion A1:** unstopped exit equals the next rebalance bar open — verified on 577 long legs
at bid and 498 short legs at ask across the full precompute.

## 2. The stop is now checked during the entry bar itself

**Defect.** The scan began at `seg.iloc[1:]`, skipping the entry bar. A position whose stop was
breached in its own first hour survived to the next bar — a free hour of immunity.

**Fix.** The stop scan now includes the entry bar. On that bar the position exists from the
open, so a gap fill cannot be worse than the entry price itself.

**Effect on results: none.** **0 entry-bar stops occur in the real data** — a 2-ATR stop is
simply too far away to be hit within the entry hour on these pairs. The defect was real but
dormant.

**Assertion A2:** because the real data cannot exercise this path, it is proven on a synthetic
bar series constructed so the entry bar's low breaches the stop. The assertion requires
`exit_reason == "stop"`, `entry_bar_stop == True`, and the exit timestamp to equal the entry
bar's. It passes. The real-data count (0) is also printed, so the dormancy is visible rather
than mistaken for a passing test.

## 3. Signal-only analysis is now a true monthly test

**Defect.** The old test stepped week by week and held one week. Its "n_months" column
reported 101, 124, 140 — those were **weeks**, roughly 4× overcounted, each measuring a
one-week horizon for a strategy that holds a month. Overlapping weekly draws also made the
observations serially dependent.

**Fix.** One signal and one outcome per scheduled calendar month: the signal is taken from the
last completed week before that month's first Monday, held to the corresponding week of the
next month. Non-overlapping.

**Effect — the largest change in the report:**

| Panel / period | Old (weeks) | Corrected (months) |
|---|---|---|
| canonical validation | 101 obs, −0.0764 | **25 obs, −0.1265** |
| canonical holdout | 124 obs, −0.0524 | **30 obs, −0.1454** |
| long_D1 development | 140 obs, −0.1299 | **33 obs, −0.0522** |
| long_D1 validation | 126 obs, −0.0571 | **29 obs, −0.2501** |
| long_D1 holdout | 135 obs, −0.0569 | **30 obs, −0.1454** |

Magnitudes move because the horizon changed from one week to one month. **Every sign stays
negative on both panels in every period.** Panel overlap is now 55 months (was 225 weeks):
same pair 72.7%, same direction 87.3% — both slightly higher than the weekly figures.

**Assertion A4:** every panel × formation combination has at most one observation per calendar
month and months are strictly ordered.

## 4. Conversion graphs now use the actual entry and exit timestamps

**Defect.** Risk, exposure **and** realised P&L were all converted with the **signal week's**
graph. For a month-long trade the exit was therefore converted at a rate up to five weeks
stale, injecting an FX error unrelated to the trade.

**Fix.** Risk and exposure use the newest completed graph at the **entry** timestamp; realised
P&L uses the graph at the **exit** timestamp.

**Effect.** **1,857 of 2,090** precomputed outcomes now use *different* graphs for entry and
exit. 15 of the 22 taken trades changed net P&L; largest single change −$1.01 (`EURJPYm`),
next +$0.99 (`CADJPYm`), +$0.97 (`AUDJPYm`). Changes are ±$1 because the FX drift over one
month is small relative to the position, and they partly cancel: total effect on net is well
under a dollar.

**Assertion A3:** every entry graph is dated strictly before its entry timestamp and every exit
graph strictly before its exit timestamp — no look-ahead was introduced by the fix.

## 5. Period drawdowns now use each period's actual starting equity

**Defect.** Every period was measured against the global $979 opening balance. The holdout
window actually began at **$882.52**, so its return was divided by the wrong base and its
drawdown was computed against a peak the account did not have while that period was running.

**Fix.** `window()` returns the equity the period actually opened with; `stats()` uses it as
the base for both return and drawdown.

**Effect — this is where the numbers move most:**

| Period | Old | Corrected | Period opened at |
|---|---|---|---|
| validation return | −9.83% | −9.85% | $979.00 |
| validation max DD | −9.83% | −9.85% | $979.00 |
| holdout return | +2.08% | **+2.41%** | **$882.52** |
| **holdout max DD** | **−13.74%** | **−4.98%** | $882.52 |

The old holdout drawdown of −13.74% was not a holdout drawdown at all — it was the drawdown
measured from the $979 high-water mark set during *validation*, before the holdout began. The
true holdout drawdown is **−4.98%**. Validation is unaffected because it does start at $979.

## 6. Condition 12 is NOT APPLICABLE when net profit is negative

**Defect.** With net profit negative there is no profit to concentrate, yet the condition
scored a free PASS.

**Fix.** It now reports `NOT APPLICABLE` and is **not counted as a pass**. A run cannot become
a PASS CANDIDATE while any condition is N/A.

**Effect.** Headline count drops from 5/13 to **4/13 (+1 N/A)**. No underlying number changed.

---

# Corrected results

## Baseline (canonical executable panel)

| Scenario | Trades | Net | Return | PF | Max DD | Win |
|---|---|---|---|---|---|---|
| Spread only | 22 | −$75.19 | −7.68% | 0.53 | −13.64% | 27.3% |
| + 1.5% financing | 22 | −$86.87 | −8.87% | 0.48 | −14.24% | 27.3% |
| + 3.0% financing | 22 | −$98.55 | −10.07% | 0.43 | −14.84% | 27.3% |
| 2026-08-02 swap snapshot | *sensitivity only* | −$76.86 | | | | |

The swap snapshot costs $1.66 and is **not** a historical cost — Exness publishes no historical
swap rates.

## Development

The canonical executable panel still has **no development period** — it begins 2021-08-02 and
development ends 2021-07-31. Long-D1 signal, development: **−0.0522** over 33 months. The
signal was already negative before the executable window opened.

## Validation (2021-08-01 → 2023-12-31), opened at $979.00

| Scenario | Trades | Net | Return | PF | Max DD |
|---|---|---|---|---|---|
| Spread only | 8 | −$96.48 | **−9.85%** | 0.00 | −9.85% |
| + 3.0% financing | 8 | −$100.94 | −10.31% | 0.00 | −10.31% |

Profit factor 0.00 — all eight validation trades lost money.

## Untouched holdout (2024-01-01 → 2026-07-31), opened at $882.52

| Scenario | Trades | Net | Return | PF | Max DD |
|---|---|---|---|---|---|
| Spread only | 14 | +$21.29 | **+2.41%** | 1.33 | **−4.98%** |
| + 3.0% financing | 14 | +$2.39 | +0.27% | 1.03 | −5.60% |

Holdout was reported only and **not used to alter anything**.

## Every pass condition, separately

| # | Condition | Result | |
|---|---|---|---|
| 1 | Canonical return positive in validation | −9.85% | **FAIL** |
| 2 | Canonical return positive in holdout | +2.41% | PASS |
| 3 | Positive under 3.0% financing stress | −10.07% | **FAIL** |
| 4 | Doubled-spread result positive | −$76.39 | **FAIL** |
| 5 | Long-D1 and canonical signal same sign | canon −0.2719 / D1 −0.3955 | PASS |
| 6 | Baseline beats median randomised | −$75.19 vs −$33.03 | **FAIL** |
| 7 | Randomisation p ≤ 0.10 | p = 0.7282 | **FAIL** |
| 8 | Reverse performs worse than baseline | +$27.86 vs −$75.19 | **FAIL** |
| 9 | At least 40 completed trades | 22 | **FAIL** |
| 10 | Max drawdown ≤ 20% | −13.64% | PASS |
| 11 | Profit factor > 1.10 | 0.533 | **FAIL** |
| 12 | No trade > 25% of net profit | NOT APPLICABLE (net ≤ 0) | **N/A** |
| 13 | No margin call / account failure | final equity $903.81 | PASS |

**4 of 13 passed, 1 not applicable.** Condition 5 still passes only because both panels agree
on a **losing** sign.

## Randomisation

10,000 within-month permutations, seed 20260802, schedule/universe/costs preserved.

| | Old | Corrected |
|---|---|---|
| Baseline | −$75.84 | −$75.19 |
| Median random | −$33.24 | −$33.03 |
| One-sided p | 0.7304 | **0.7282** |

**73% of random pair-and-direction pickers still beat the signal.**

The fast permutation engine was again asserted equal to the costed engine before use
(−$75.19, 22 trades — identical).

## Delayed-entry and doubled-spread controls

| Control | Old | Corrected |
|---|---|---|
| Baseline | −$75.84 | −$75.19 |
| Entry delayed 24 h | −$55.31 | −$63.69 (−6.51%, 23 trades) |
| Entry delayed 1 week | +$90.64 | **+$88.11 (+9.00%, 29 trades)** |
| Doubled spread | −$77.04 | −$76.39 (−7.80%, 22 trades) |
| Reverse | +$25.42 | **+$27.86** |

Delaying entry a full week still turns the strategy from −7.68% to **+9.00%**. Doubling every
spread still moves the result by only ~$1.20 — it fails on direction, not cost.

## Maximum drawdown

**−13.64%** overall (spread only), −14.84% under 3.0% financing. Validation −9.85%, holdout
**−4.98%** (was mis-stated as −13.74% before correction 5).

## Trades skipped

| Reason | Count |
|---|---|
| Stop risk > 1.50% of current equity | **33** |
| Exposure > 2.00× equity | 0 |
| Conversion unreliable | 0 |

Unchanged at 33 of 55 rebalances, all on the risk rule.

## Formation diagnostics — 4 and 26 weeks are diagnostics only

| Panel / period | 4w | 13w (frozen) | 26w |
|---|---|---|---|
| canonical validation | −0.2286 | −0.1265 | −0.0414 |
| canonical holdout | −0.1846 | −0.1454 | +0.0277 |
| long_D1 development | −0.0482 | −0.0522 | −0.0483 |
| long_D1 validation | −0.2696 | −0.2501 | −0.2614 |
| long_D1 holdout | −0.1359 | −0.1454 | +0.0223 |

Under the corrected monthly test the 26-week column is now negative in canonical validation too
(it was marginally positive before). It is positive only in the two holdout cells and negative
in all three D1 periods. Recorded because the spec required the diagnostic; **not** proposed.

## Errors and assumptions

- Assumptions from task 003 are unchanged: MT5 timestamps treated as UTC (corroborated —
  session open lands on exactly 17:00 NY); bars are BID (`chart_mode == 0`, last close
  reproduced the live bid exactly); quote→USD via the fitted currency graph because `GBPUSDm`
  is not executable; a canonical week is usable only when all 5 sessions are complete for all
  19 pairs.
- New in 003A: the entry-bar gap fill cannot be worse than the entry price, since the position
  exists from that bar's open.
- No exception occurred. All five assertions passed.
- Carried limitation: the executable panel spans 4.99 years, not 6.

## Files changed

| File | Status |
|---|---|
| `study/fx_momentum_v1.py` | modified — six corrections + five assertions |
| `study/results/fx_momentum_v1_trades.csv` | updated |
| `study/results/fx_momentum_v1_monthly.csv` | updated |
| `study/results/fx_momentum_v1_signal_tests.csv` | updated — now monthly |
| `study/results/fx_momentum_v1_controls.csv` | updated |
| `study/results/fx_momentum_v1_report.txt` | updated |
| `coordination/CLAUDE_REPORT.md` | this file (003A) |
| `coordination/CLAUDE_REPORT_TASK003.md` | renamed to preserve the 003 report |

Nothing under `live/` or `recorder/` was modified or committed.

---

V1 remains FAILED. No parameter change and no replacement strategy is recommended.
