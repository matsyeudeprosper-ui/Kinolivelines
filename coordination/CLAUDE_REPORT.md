FROM: CLAUDE
TASK: 005 — FX POLICY-RATE DIFFERENTIAL V2

FX_POLICY_DIFFERENTIAL_V2_20260802

Preregistered frozen strategy, implemented and tested exactly as specified. Nothing was
optimised, reinterpreted or substituted. No live deployment is recommended and no V3 is
proposed. The live bot was not touched and no order was placed or changed.

Task 004A's report is preserved at `coordination/CLAUDE_REPORT_TASK004A.md`.

---

# VERDICT: **FAILED** — 6 of 16 conditions passed, 1 not applicable

Per the specification V2 is reported FAILED and has **not** been optimised, repaired,
reversed, thresholded, or given a different stop after results were seen.

| Principal test — scenario 1, zero-credit execution | |
|---|---|
| Net | **−$49.93** (−5.10%) |
| Trades | 47 |
| Profit factor | **0.826** |
| Max drawdown | −9.42% |
| Win rate | 36.2% |
| Validation | **−$30.39** (−3.10%) |
| Holdout | **−$19.55** (−2.06%) |
| Randomisation p | **0.5525** |

## Commit

| | |
|---|---|
| Commit SHA | `PENDING_SHA` |
| Branch | `main` |
| Parent | `5e898b2` |

## Commands run

```
python study/fx_policy_differential_v2.py
```

---

## The single most informative number in this task

**The 2026 Exness swap sensitivity is exactly $0.00 on every one of the 47 trades.**

V2 always trades the side the policy differential favours. Task 004A found that for 0 of
19 pairs does the broker pay positive carry on that side — it zeroes it. So applying the
stored snapshot changes the result by nothing at all, on any trade, in either direction.

That is the cleanest possible confirmation of the 004A finding, arrived at independently:
**a policy-carry strategy on this broker collects no carry by construction.** It is left
as a directional bet, and as a directional bet it loses.

The non-executable benchmark makes the same point from the other side: crediting the full
theoretical differential would have improved the result from −$49.93 to **−$7.32** — still
negative. Even a broker that paid the entire differential would not have made V2 profitable.
That benchmark is diagnostic and cannot satisfy any condition.

---

## Exact frozen rules

```
signal        rate_differential = policy_rate(BASE) - policy_rate(QUOTE)
direction     >0 BUY, <0 SELL, ==0 not a candidate
selection     largest |differential|, ties alphabetical by symbol, no threshold,
              no discretionary filtering, one position maximum
schedule      first Monday of the month, 20:00 New York, first H1 bar at/after,
              no entry later than Tuesday 20:00
info cutoff   preceding completed Friday; source_observation_date <= cutoff
stop          1.5 x canonical New York-session ATR(20), live from the entry bar,
              never trailed, no take profit
ATR data      only canonical sessions completed on or before the Friday cutoff
size          broker minimum lot 0.01 only, never increased to reach a target
limits        stop risk <= 1.50% of current equity, exposure <= 2.00x, skip not violate
exit          stop, or the OPEN of the next scheduled rebalance bar; no re-entry after
              a stop within the same month
pricing       bars are BID; BUY enters ask exits bid, SELL enters bid exits ask;
              ask reconstructed from that bar's recorded historical spread
conversion    exact H1 midpoint graph at entry for risk/exposure, at exit for P&L,
              USD pinned to zero, disconnected graphs skipped
equity        $979.00
```

## Exact executable universe — 19 pairs

```
AUDCADm  AUDCHFm  AUDJPYm  AUDNZDm  AUDUSDm  CADJPYm  EURCADm  EURCHFm
EURGBPm  EURJPYm  EURNZDm  EURUSDm  GBPAUDm  GBPCHFm  NZDCADm  NZDJPYm
USDCADm  USDCHFm  USDJPYm
```

8 currencies: AUD, CAD, CHF, EUR, GBP, JPY, NZD, USD.

## Policy-rate availability checks

Policy data came from the 004A snapshots unaltered — 1,592 rows over 199 months, 1,551
available, 41 unavailable.

| Check | Result |
|---|---|
| Policy observation dates ≤ Friday cutoff | **PASS** — max age 1 day (base), 0 (quote) |
| Selected rates finite | **PASS** — 58 selections |
| No JPY selection while JPY unavailable | **PASS** — 41 JPY-unavailable months in the table |
| Unavailable rates imputed | **Never** |

The JPY unavailability window never binds in the traded period, because the canonical panel
begins 2021-08 and the QQE hole ends 2016-09-20. The check is enforced anyway, and it does
bind on the long-D1 panel, which reaches back to 2018-07.

## Trade and skip counts

| | |
|---|---|
| Rebalances scheduled | 60 (0 months lacked an entry bar) |
| Rebalances with eligible candidates | 58 |
| Eligible outcome rows precomputed | 2,172 |
| **Completed trades** | **47** |
| Skipped — stop risk > 1.50% of equity | **11** |
| Skipped — exposure > 2.00× | 0 |
| Skipped — conversion unreliable | 0 |

Eligibility skips (pair-months excluded before selection):

| Reason | Count |
|---|---|
| No ATR available at the cutoff | 19 |
| Zero differential — not a candidate | 16 |
| Policy rate unavailable | 0 (in the traded window) |

47 trades clears the 45-trade bar — the 1.5× ATR stop is tighter than V1's 2.0×, so fewer
months were lost to the risk limit (11 here versus 33 in V1).

Exits: 27 by stop, 20 at rebalance. Six distinct pairs traded, concentrated in `NZDJPYm`
(23), `USDCHFm` (9) and `GBPCHFm` (9) — a direct consequence of "largest absolute
differential", which repeatedly selects the same high-differential pairs. Absolute
differential ranged 0.88 to 5.60, median 4.35.

## Cost scenarios

| Scenario | Trades | Net | Return | PF | Max DD |
|---|---|---|---|---|---|
| **1 baseline, zero credit** (principal) | 47 | **−$49.93** | −5.10% | 0.83 | −9.42% |
| 2 financing stress 1.5% | 47 | −$78.94 | −8.06% | 0.74 | −10.47% |
| 3 financing stress 3.0% | 47 | −$107.96 | −11.03% | 0.65 | −12.56% |
| 4 current 2026 swap snapshot | 47 | **−$49.93** | −5.10% | — | — |
| 5 theoretical policy credit | 49 | −$7.32 | −0.75% | — | — |

Scenario 4 is **non-historical** and is not evidence of past cost; it is identical to
baseline for the reason given above. Scenario 5 is **non-executable** and cannot satisfy a
pass condition.

## Validation and holdout

| Period | Scenario | Trades | Net | Return | PF | Max DD | Opened at |
|---|---|---|---|---|---|---|---|
| Validation | baseline | 22 | −$30.39 | −3.10% | 0.79 | −8.12% | $979.00 |
| Validation | +3.0% fin | 22 | −$57.21 | −5.84% | 0.63 | −9.23% | $979.00 |
| Holdout | baseline | 25 | −$19.55 | −2.06% | 0.87 | −9.42% | $948.61 |
| Holdout | +3.0% fin | 25 | −$50.74 | −5.50% | 0.68 | −11.63% | $921.79 |

**The holdout is untouched for this policy-rate strategy family.** It is *not* globally
untouched by every prior study in this project — earlier work has examined this calendar
period for other questions. Holdout results were not used to change anything.

## D1 versus canonical signal-only results

| Panel | Development | Validation | Holdout |
|---|---|---|---|
| Canonical (scheduled H1, with spread) | n/a — panel starts 2021-08 | **−0.0624** (28 mo) | **+0.0554** (30 mo) |
| Long D1 (approximate, no spread) | **+0.0969** (36 mo) | **+0.0080** (29 mo) | **+0.0544** (31 mo) |

Broker D1 span 2018-07-03 → 2026-08-03, 97 scheduled months.

Overlap: **58 months, 100% same pair and 100% same direction** — the two panels agree
completely on what to trade, so the difference between them is pricing alone. Over that
overlap the canonical panel returns **−0.0071** while the approximate D1 panel returns
**+0.0367**. The gap is the spread and the scheduled-open pricing that D1 cannot represent.

That gap is the finding: the signal has a small positive drift when measured on unpriced
daily closes, and that drift does not survive being executed.

## Differential-tercile diagnostic

All eligible outcomes at the policy-implied direction, split by absolute differential:

| Tercile | n | Mean log-ret | Sum log-ret | Win % | Mean abs diff |
|---|---|---|---|---|---|
| Low | 380 | +0.000493 | +0.1875 | 33.7% | 0.45 |
| Middle | 344 | −0.001899 | −0.6533 | 31.7% | 1.42 |
| High | 362 | −0.000139 | −0.0502 | 39.2% | 3.71 |

**No monotonicity.** The relationship is non-ordered — the low tercile is the only positive
one and the middle is the worst. A larger policy differential did not produce a better
outcome. Diagnostic only; it is a property of eligible outcomes, not of the traded strategy,
and cannot satisfy a condition.

## Randomisation and controls

| Control | Result |
|---|---|
| 1 Random pair AND direction (10,000) | median **−$36.90**, baseline −$49.93, **p = 0.5525** |
| 2 Random pair, policy-implied direction (10,000) | median **−$28.63**, **p = 0.5979** |
| 3 Reverse | **−$137.88** |
| 4 Entry delayed 24 h | **−$26.39** (−2.70%, 47 trades) |
| 5 Entry delayed one week (diagnostic) | −$145.14 (−14.83%, 47 trades) |
| 6 Doubled historical spreads | −$55.47 (−5.67%, 47 trades) |
| 7 Current-swap static sensitivity | −$49.93 — **non-historical** |

p-value uses the specified formula `(1 + #{random ≥ baseline}) / 10001`.

Control 2 is the more searching of the two: even holding the policy-implied *direction* and
randomising only the *pair*, the median random selection (−$28.63) beats the frozen
largest-differential rule (−$49.93). **Choosing the biggest differential was worse than
choosing an arbitrary eligible pair with the same directional logic.**

Reverse loses much more than baseline (−$137.88), so unlike V1 this signal is not
merely inverted noise — but that satisfies only condition 10, not profitability. Doubling
spreads costs just $5.54, so again the failure is directional rather than cost-driven.

**No control is proposed as a strategy.**

## Complete pass-condition table

| # | Condition | Value | |
|---|---|---|---|
| 1 | Canonical validation net > 0 | −$30.39 | **FAIL** |
| 2 | Canonical holdout net > 0 | −$19.55 | **FAIL** |
| 3 | Combined canonical > 0 under 3.0% financing | −$107.96 | **FAIL** |
| 4 | Doubled-spread result > 0 | −$55.47 | **FAIL** |
| 5 | Long-D1 validation signal-only > 0 | +0.0080 | PASS |
| 6 | Long-D1 holdout signal-only > 0 | +0.0544 | PASS |
| 7 | Canonical and long-D1 overlap both positive | canon −0.0071, D1 +0.0367 | **FAIL** |
| 8 | Baseline beats median random pair+direction | −$49.93 vs −$36.90 | **FAIL** |
| 9 | Randomisation p ≤ 0.10 | p = 0.5525 | **FAIL** |
| 10 | Reverse ≤ 0 and worse than baseline | −$137.88 vs −$49.93 | PASS |
| 11 | ≥ 45 completed canonical trades | 47 | PASS |
| 12 | Profit factor > 1.10 | 0.826 | **FAIL** |
| 13 | Max drawdown ≤ 20% | −9.42% | PASS |
| 14 | No trade > 25% of total positive net profit | NOT APPLICABLE (net ≤ 0) | **N/A** |
| 15 | 24-hour delayed entry remains positive | −$26.39 | **FAIL** |
| 16 | No margin call / negative equity / overlap | min equity $920.51 | PASS |

**6 passed, 9 failed, 1 not applicable.** Per the specification, condition 14 being N/A with
non-positive net profit means V2 still fails.

## Assertions and results — 13 of 13 pass

| Assertion | Result |
|---|---|
| Policy observation dates ≤ Friday cutoff | **PASS** (max age 1 day) |
| Selected currency rates available and finite | **PASS** (58 selections) |
| JPY pairs unselectable while JPY unavailable | **PASS** |
| One baseline selection per calendar month | **PASS** (58 months) |
| ATR uses no data after the cutoff | **PASS** |
| Entry graph timestamp == entry fill | **PASS** (2,172 rows) |
| Exit graph timestamp == exit fill | **PASS** (2,172 rows) |
| Entry-bar stops detected (synthetic breach) | **PASS** (0 occur in real data) |
| Unstopped exit == next rebalance open | **PASS** (461 long at bid, 394 short at ask) |
| Consecutive positions never overlap | **PASS** (58 legs) |
| Stop risk ≤ 1.50% at entry | **PASS** (enforced; 11 months skipped) |
| Exposure ≤ 2.00× at entry | **PASS** (0 skips needed) |
| Random controls use the baseline's eligible set | **PASS** (58 months, 2,172 outcomes) |
| Fast control engine reproduces the costed engine | **PASS** (−$49.93, 47 trades, identical) |

Graph residual RMS median 2.17e-05; conversion is fitted at the exact fill timestamp
throughout.

## Errors and assumptions

- **Defect I found and fixed mid-task.** My first build derived the "long-D1" panel by
  resampling the H1 files. Dense H1 only begins 2021-08, so that panel silently covered the
  same window as the canonical one and reported an empty development period while calling
  itself long-history. Conditions 5, 6 and 7 read off it. Rebuilt from **broker D1 bars**
  (2018-07-03 → 2026-08-03) on an independent monthly schedule; conditions 5 and 6 changed
  from FAIL to PASS as a result. The canonical executable path was untouched by the fix, so
  the baseline and conditions 1–4 and 8–16 are unchanged.
- **Assumption:** the long-D1 panel is explicitly approximate — nearest broker daily close at
  or after each scheduled first Monday, no spread. It is labelled
  `APPROXIMATE_daily_close_no_spread` in the signal-tests CSV and makes no claim of intraday
  execution.
- **Assumption:** Sunday D1 candles are merged into the following Monday, consistent with
  tasks 002 and 004A.
- **Assumption:** the theoretical policy-credit benchmark accrues `direction × differential`
  annualised on notional, prorated by holding days. Since direction always equals the sign of
  the differential, this is always a credit for the baseline.
- Task 004A data rules were not altered in any way.
- No exception occurred. All 13 assertions passed.

## Files changed

| File | Status |
|---|---|
| `study/fx_policy_differential_v2.py` | new |
| `study/results/fx_policy_differential_v2_trades.csv` | new — 47 trades |
| `study/results/fx_policy_differential_v2_monthly.csv` | new |
| `study/results/fx_policy_differential_v2_signal_tests.csv` | new — both panels, 3 periods |
| `study/results/fx_policy_differential_v2_controls.csv` | new — all 7 controls |
| `study/results/fx_policy_differential_v2_pass_conditions.csv` | new — 16 conditions |
| `study/results/fx_policy_differential_v2_report.txt` | new — full run log |
| `coordination/CLAUDE_REPORT.md` | this file (005) |
| `coordination/CLAUDE_REPORT_TASK004A.md` | renamed to preserve the 004A report |

Nothing under `live/` or `recorder/` was modified or committed.

---

V2 is reported FAILED. No live deployment is recommended and no V3 is proposed.
