FROM: CLAUDE
TASK: 003B — FX SIMULATOR CERTIFICATION

Simulator certification, not strategy optimisation. **V1 remains permanently FAILED.** No V1
strategy rule, parameter, universe, schedule, stop, risk limit or pass condition was changed.
All 003A corrections are preserved. No V2 or replacement strategy is proposed.

The live bot was not modified and no order was placed or changed.

Earlier reports: `CLAUDE_REPORT_TASK001.md`, `_TASK002.md`, `_TASK003.md`, `_TASK003A.md`.

---

# CERTIFICATION RESULT: simulator now converts at the exact fill timestamp

Both defects were real. Neither changed the verdict.

| | 003A | 003B |
|---|---|---|
| **Conditions passed** | 4/13 (+1 N/A) | **4/13 (+1 N/A)** |
| Net, spread only | −$75.19 | **−$75.94** |
| Return | −7.68% | −7.76% |
| Profit factor | 0.533 | 0.529 |
| Final equity | $903.81 | $903.06 |
| Randomisation p | 0.7282 | 0.7286 |
| Reverse | +$27.86 | +$27.73 |

Net moved by **−$0.74** on a −$75 result. 17 of 22 trades changed, largest single change $0.49.

## Commit

| | |
|---|---|
| Commit SHA | `PENDING_SHA` |
| Branch | `main` |
| Parent | `0c633e2` |

## Commands run

```
python study/fx_momentum_v1.py
```

---

# Correction 1 — exact H1 currency graphs

**Defect.** `graph_at()` returned the newest completed **weekly** graph, so a conversion could
be up to five trading days stale at the moment of a fill.

**Fix.** The graph is now rebuilt at the exact H1 timestamp of every entry and every exit:

```
mid_open = bid_open + 0.5 * spread_points * point      per pair, at that bar
log(mid) = value(BASE) - value(QUOTE),  value(USD) = 0  fitted by least squares
q2u      = exp(value(QUOTE))
```

Midpoints rather than bids, because a currency value is a property of the market, not of one
side of the quote — fitting on bids would push a systematic half-spread into every currency and
therefore into every conversion.

- **Entry-timestamp graph** → stop risk and economic exposure
- **Exit-timestamp graph** → realised quote-currency P&L
- **A stop firing inside an H1 bar** is converted with the graph built from *that bar's* opening
  prices — the finest historical timestamp the data supports
- Rank-deficiency check: if the available pairs do not connect every currency back to USD the
  outcome is **skipped** rather than fitted from an under-determined system

**Certification evidence:**

| | |
|---|---|
| Rows priced with graph timestamp **equal** to the fill timestamp | **2,090 / 2,090** |
| Rows using a *different* graph at entry vs exit | **2,090 / 2,090** (was 1,857 under weekly) |
| Pairs contributing to each graph | **19 of 19**, min and max |
| Graph residual RMS, entry | median **2.14e-05**, max 6.30e-05 |
| Graph residual RMS, exit | median 2.27e-05 |
| Outcomes skipped for a disconnected graph | **0** |

The H1 midpoint graph is roughly **4× more triangularly consistent** than the weekly close
graph it replaces (2.1e-05 vs 9.5e-05), which is what one expects when the quotes being fitted
are simultaneous rather than spread across a week.

**Assertion A3 now demands equality**, not "graph is earlier":

```
entry_graph_timestamp == trade entry timestamp     (all 2,090 rows)
exit_graph_timestamp  == trade exit timestamp      (all 2,090 rows)
```

003A only proved the graph was not from the future — a five-day-stale graph passed that test.
Equality is the stronger claim and it now holds exactly.

**New columns in the trades CSV:** `entry_graph_timestamp`, `exit_graph_timestamp`,
`entry_graph_residual_rms`, `exit_graph_residual_rms`, `entry_graph_pairs`, `exit_graph_pairs`,
`q2u_entry`, `q2u_exit`.

**Effect:** 17 of 22 trades repriced, total −$0.74. USD-quoted pairs are unaffected by
construction (`q2u = 1.000000` exactly for `AUDUSDm`, `EURUSDm`), which is itself a sanity check
that the fit is behaving.

---

# Correction 2 — canonical signal-only priced at the real schedule

**Defect.** The canonical signal test still measured returns between **Friday weekly closes**,
while the strategy it represents enters at the Monday 20:00 New York H1 open and exits at the
next scheduled monthly open. Different prices, different days — the signal test and the
executable test were not measuring the same thing.

**Fix (canonical panel).** Enter at the actual scheduled H1 open, exit at the next actual
scheduled H1 open, with bid/ask applied by direction (bars are BID, so a BUY pays the spread on
entry and a SELL pays it on exit). Still no stop, no financing and no risk skipping — that is
what keeps it signal-only rather than the strategy itself. One observation per calendar month by
construction, since the schedule has one rebalance per month.

**Fix (long-D1 panel).** D1 has no intraday resolution, so the 20:00 New York open cannot be
reproduced. The nearest available broker D1 close at or after each scheduled first Monday is
used, **no spread applied**, and every row is labelled
`APPROXIMATE_broker_D1_close_no_spread` in `fx_momentum_v1_signal_tests.csv`. This panel is not
entitled to claim execution costs and does not.

**Effect:**

| Panel / period | 003A | 003B |
|---|---|---|
| canonical validation | 25 obs, −0.1265 | 25 obs, **−0.1439** |
| canonical holdout | 30 obs, −0.1454 | 30 obs, **−0.1278** |
| long_D1 development | 33 obs, −0.0522 | 33 obs, **−0.0396** |
| long_D1 validation | 29 obs, −0.2501 | 29 obs, **−0.2156** |
| long_D1 holdout | 30 obs, −0.1454 | 31 obs, **−0.1289** |

**Every sign remains negative on both panels in every period.** Observation counts are
essentially unchanged, confirming the 003A monthly restructuring was already correct — this
correction changed *prices*, not *cadence*.

**Panel agreement, recalculated:** 55 overlapping months, **same pair 72.7%, same direction
87.3%** — unchanged from 003A.

**Pass condition 5, recalculated:** canonical −0.2717 / long-D1 −0.3445 → **same sign, PASS**.
It still passes only because both panels agree on a *losing* sign.

---

# Certified results

## Baseline

| Scenario | Trades | Net | Return | PF | Max DD | Win |
|---|---|---|---|---|---|---|
| Spread only | 22 | −$75.94 | −7.76% | 0.53 | −13.66% | 27.3% |
| + 1.5% financing | 22 | −$87.61 | −8.95% | 0.47 | −14.26% | 27.3% |
| + 3.0% financing | 22 | −$99.29 | −10.14% | 0.42 | −14.86% | 27.3% |
| 2026-08-02 swap snapshot | *sensitivity only* | −$77.60 | | | | |

## Validation (opened at $979.00) and holdout (opened at $882.57)

| Period | Scenario | Trades | Net | Return | PF | Max DD |
|---|---|---|---|---|---|---|
| Validation | spread only | 8 | −$96.43 | −9.85% | 0.00 | −9.85% |
| Validation | + 3.0% fin | 8 | −$100.89 | −10.30% | 0.00 | −10.30% |
| Holdout | spread only | 14 | +$20.49 | +2.32% | 1.32 | −5.00% |
| Holdout | + 3.0% fin | 14 | +$1.60 | +0.18% | 1.02 | −5.63% |

Holdout was reported only and **not used to alter anything**.

## Every pass condition

| # | Condition | Result | |
|---|---|---|---|
| 1 | Canonical return positive in validation | −9.85% | **FAIL** |
| 2 | Canonical return positive in holdout | +2.32% | PASS |
| 3 | Positive under 3.0% financing stress | −10.14% | **FAIL** |
| 4 | Doubled-spread result positive | −$77.11 | **FAIL** |
| 5 | Long-D1 and canonical signal same sign | canon −0.2717 / D1 −0.3445 | PASS |
| 6 | Baseline beats median randomised | −$75.94 vs −$34.01 | **FAIL** |
| 7 | Randomisation p ≤ 0.10 | p = 0.7286 | **FAIL** |
| 8 | Reverse performs worse than baseline | +$27.73 vs −$75.94 | **FAIL** |
| 9 | At least 40 completed trades | 22 | **FAIL** |
| 10 | Max drawdown ≤ 20% | −13.66% | PASS |
| 11 | Profit factor > 1.10 | 0.529 | **FAIL** |
| 12 | No trade > 25% of net profit | NOT APPLICABLE (net ≤ 0) | **N/A** |
| 13 | No margin call / account failure | final equity $903.06 | PASS |

## Controls

| Control | 003A | 003B |
|---|---|---|
| Median random | −$33.03 | −$34.01 |
| One-sided p | 0.7282 | **0.7286** |
| Reverse | +$27.86 | **+$27.73** |
| Entry delayed 24 h | −$63.69 | −$65.00 (−6.64%, 23 trades) |
| Entry delayed 1 week | +$88.11 | **+$87.59 (+8.95%, 29 trades)** |
| Doubled spread | −$76.39 | −$77.11 (−7.88%, 22 trades) |

The fast permutation engine was again asserted equal to the costed engine (−$75.94, 22 trades).

## Trades skipped

| Reason | Count |
|---|---|
| Stop risk > 1.50% of current equity | **33** |
| Exposure > 2.00× equity | 0 |
| Conversion unreliable / disconnected graph | **0** |

Unchanged at 33 of 55 rebalances. Notably **zero** outcomes were lost to the stricter
conversion requirement — all 19 pairs are present at every fill timestamp.

## Formation diagnostics — 4 and 26 weeks remain diagnostics only

| Panel / period | 4w | 13w (frozen) | 26w |
|---|---|---|---|
| canonical validation | −0.1869 | −0.1439 | −0.0441 |
| canonical holdout | −0.2141 | −0.1278 | −0.0298 |
| long_D1 development | −0.0726 | −0.0396 | −0.0586 |
| long_D1 validation | −0.1904 | −0.2156 | −0.2065 |
| long_D1 holdout | −0.1628 | −0.1289 | +0.0042 |

Under exact H1 pricing the 26-week column is now **negative in 4 of 5 cells** — in 003A it was
positive in two. Its only remaining positive is long-D1 holdout at +0.004, which is
indistinguishable from zero. Recorded because the spec required the diagnostic; **not proposed**.

## Assertions — all five pass

| | |
|---|---|
| A1 | Unstopped exit == next rebalance bar open (577 long at bid, 498 short at ask) |
| A2 | Entry-bar stop detected on a synthetic breach; 0 occur in real data |
| A3 | **Graph timestamps EQUAL fill timestamps, all 2,090 rows** |
| A4 | Signal-only output ≤ 1 observation per calendar month, every panel × formation |
| A5 | Consecutive positions never overlap (55 signal legs) |

## Errors and assumptions

- All 003A assumptions preserved. New in 003B: currency graphs are fitted on **midpoints**, not
  bids, to avoid embedding a half-spread in every currency value.
- The long-D1 signal panel is **explicitly approximate** — nearest broker D1 close at or after
  the scheduled first Monday, no spread, labelled in the CSV.
- Dead code removed: the superseded weekly `signal_only()` (52 lines) was deleted rather than
  left in the file as an unused second path.
- No exception occurred; 0 outcomes skipped for conversion.
- Carried limitation: the executable panel spans 4.99 years, not 6.

## Files changed

| File | Status |
|---|---|
| `study/fx_momentum_v1.py` | modified — exact H1 graphs, scheduled-price signal test, A3 tightened |
| `study/results/fx_momentum_v1_trades.csv` | updated — 8 new graph/conversion columns |
| `study/results/fx_momentum_v1_monthly.csv` | updated |
| `study/results/fx_momentum_v1_signal_tests.csv` | updated — adds `pricing` label |
| `study/results/fx_momentum_v1_controls.csv` | updated |
| `study/results/fx_momentum_v1_report.txt` | updated |
| `coordination/CLAUDE_REPORT.md` | this file (003B) |
| `coordination/CLAUDE_REPORT_TASK003A.md` | renamed to preserve the 003A report |

Nothing under `live/` or `recorder/` was modified or committed.

---

The simulator is certified: conversions are now built at the exact fill timestamp and the signal
test is priced at the real schedule. **V1 remains FAILED.** No V2 or replacement strategy is
proposed.
