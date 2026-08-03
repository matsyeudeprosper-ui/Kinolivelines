FROM: CLAUDE
TASK: 005A — V2 INFRASTRUCTURE CERTIFICATION

V2_ENGINE_CERTIFICATION_20260802

Infrastructure verification only. **FX POLICY-RATE DIFFERENTIAL V2 remains permanently
FAILED.** No signal, pair selection, schedule, stop, sizing, risk limit, exposure limit,
cost assumption or pass condition was changed. No V3 is proposed. The live bot was not
touched and no order was placed or changed.

Task 005's report is preserved at `coordination/CLAUDE_REPORT_TASK005.md`.

---

# VERDICT UNCHANGED: **FAILED** — 6 of 16, 1 not applicable

| | Task 005 | Task 005A certified |
|---|---|---|
| Conditions passed | 6/16 (+1 N/A) | **6/16 (+1 N/A)** |
| Baseline net | −$49.93 | **−$49.93** (unchanged) |
| Condition 6, long-D1 holdout | +0.0544 | **+0.0393** |
| Long-D1 holdout months | 31 | **30** |
| D1 panel end | 2026-08-03 | **2026-07-31** |
| D1 schedule months | 97 | **96** |
| Assertions | 13 | **16** |

Only the D1-derived numbers moved. The canonical executable strategy was untouched, exactly
as required.

## Commit

| | |
|---|---|
| Commit SHA | `6d2f0cb06ed5b763678697541867db45f9bbd05b` |
| Branch | `main` |
| Parent | `0de1c15` |

## Commands run

```
python study/fx_policy_differential_v2.py
```

---

## 1. Broker D1 completeness — a forming bar was being used

**The anomaly was real and it was a leak.** Evidence, measured rather than assumed:

| | |
|---|---|
| D1 retrieval timestamp (UTC) | **2026-08-02 23:22:21Z** |
| MT5 server clock at that moment | 2026-08-02 23:22:18 |
| Measured offset | **−0.0 h → the MT5 server frame IS UTC** |
| D1 timestamp convention | **bar OPEN time, on the UTC day boundary** |
| Last fully completed broker D1 session | **2026-07-31 (Friday)** |
| Forming sessions excluded | **19 — exactly one per pair** |
| Dropped session | **2026-08-03**, still open at retrieval |

**What was happening.** The FX week opens Sunday ~21:00 UTC, so Sunday carries a partial D1
bar — on 2026-08-02 it held **2,969 ticks against 31,000–58,000 for a full weekday**. That
bar was still forming at retrieval (last H1 bar 23:00 UTC, retrieval 23:22 UTC), and the
Sunday→Monday merge relabelled it **2026-08-03**. That is why task 005 reported a panel
ending a day *after* the run date.

**Rule applied:** a merged session dated D is closed only once the whole UTC day D has
elapsed at the recorded retrieval timestamp. One forming bar per pair was excluded.

**Deterministic assertion added and passing:**

> *every D1 bar used in a signal or return calculation was fully closed before the recorded
> retrieval timestamp* — last completed session 2026-07-31, retrieval 2026-08-02 23:22Z,
> 19 forming bars excluded.

**Rerun scope:** only the D1 signal-only analysis and conditions 5, 6 and 7, as instructed.

| | Task 005 | Certified |
|---|---|---|
| Long-D1 development | +0.0969 (36 mo) | **+0.0969 (36 mo)** — unchanged |
| Long-D1 validation | +0.0080 (29 mo) | **+0.0080 (29 mo)** — unchanged |
| **Long-D1 holdout** | **+0.0544 (31 mo)** | **+0.0393 (30 mo)** |
| Condition 5 | PASS | **PASS** |
| Condition 6 | PASS | **PASS** |
| Condition 7 | FAIL | **FAIL** |

The forming bar had inflated the holdout signal by **+0.0151**, roughly 28% of the reported
figure. Conditions 5 and 6 still pass and 7 still fails, so the verdict is unaffected — but
the number was wrong and is now right. Canonical results are byte-identical.

## 2. Random-control equity paths — verified independent

Each of the 10,000 simulations already walked its own account. `run_fast()` initialises
`eq = $979` locally on every call and recomputes **both** gates against that path's evolving
equity; the baseline's monthly pass/fail, trade count and equity curve are never consulted.
Only market outcomes (gross P&L, notional, stop risk, days held) are precomputed, and those
are path-independent by construction.

The distributions now prove it rather than asserting it:

### Control 1 — random pair AND direction

| | |
|---|---|
| Net: median / 5th / 95th | **−$36.90** / −$172.33 / +$135.38 |
| Trades: median / min / max | **51 / 39 / 58** (baseline 47) |
| Risk skips: median / min / max | **7 / 0 / 19** (baseline 11) |
| One-sided p | **0.5525** |

### Control 2 — random pair, policy-implied direction

| | |
|---|---|
| Net: median / 5th / 95th | **−$28.63** / −$161.63 / +$135.35 |
| Trades: median / min / max | **51 / 36 / 58** (baseline 47) |
| Risk skips: median / min / max | **7 / 0 / 22** (baseline 11) |
| One-sided p | **0.5979** |

Trade counts spanning 36–58 and risk skips spanning 0–22 are only possible if each path
gates on its own equity. A shared or fixed $979 budget would have produced one skip count
for every simulation.

p-values use the specified `(1 + #{random ≥ baseline}) / 10001`.

**Synthetic assertion added and passing** — one candidate, two accounts:

> at $979 the 1.50% budget is **$14.69** and a $12.00 stop risk is taken; at $700 the budget
> is **$10.50** and the *same* candidate is skipped.

## 3. JPY reporting correction

Task 005 stated the 2013–2016 JPY no-policy-rate interval *"does bind on the long-D1 panel,
which reaches back to 2018-07."* **That was wrong.** The interval ends **2016-09-20**; the D1
panel begins **2018-07-03**. It cannot bind, and it binds nowhere in task 005 — neither the
traded canonical period (from 2021-08) nor the D1 period.

The corrected position: **the JPY unavailable interval does not affect any task-005 result.**

An independent historical assertion is retained to prove the availability rule works, worded
so it makes no claim about task-005 periods:

> *JPY unavailable across 2013-04-04..2016-09-20 (historical check only)* — 41 months, all
> unavailable; the interval ends before the 2018-07 D1 panel, so it does not bind in task 005.

The live selection guard (a JPY pair cannot be chosen while JPY is unavailable) is unchanged
and also passing.

## 4. Theoretical credit benchmark — the two versions disagree in sign

This is the most consequential finding of the certification.

| | Trades | Net | Return |
|---|---|---|---|
| Baseline, zero credit | 47 | −$49.93 | −5.10% |
| **A — fixed-baseline-trade credit counterfactual** | **47** | **+$19.87** | **+2.03%** |
| **B — recursively gated theoretical-credit path** | **49** | **−$7.32** | **−0.75%** |

**A** holds the 47 baseline trades fixed — same symbols, directions, entries, exits and skips
— and adds only the theoretical policy credit of **$69.80**.

**B** re-runs the account with the credit included, so the credit raises equity, which changes
which months clear the 1.50% risk gate, which changes the trade set (49 rather than 47).

**They disagree in sign.** Task 005 reported only B (−$7.32) and drew the conclusion that
even full credit leaves the strategy negative. On the apples-to-apples comparison that
conclusion does not hold: the same 47 trades with the differential credited would have
returned **+$19.87**. The difference is entirely the two extra trades the recursive path
takes once its equity is higher.

**Neither may satisfy a hard pass condition**, and neither does. The executable reality is
unchanged and is scenario 1: the broker pays $0.00 on the side V2 trades, so the credit does
not exist.

## Complete pass-condition table (certified)

| # | Condition | Value | |
|---|---|---|---|
| 1 | Canonical validation net > 0 | −$30.39 | **FAIL** |
| 2 | Canonical holdout net > 0 | −$19.55 | **FAIL** |
| 3 | Combined canonical > 0 under 3.0% financing | −$107.96 | **FAIL** |
| 4 | Doubled-spread result > 0 | −$55.47 | **FAIL** |
| 5 | Long-D1 validation signal-only > 0 | +0.0080 | PASS |
| 6 | Long-D1 holdout signal-only > 0 | **+0.0393** | PASS |
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

## Assertions — 16 of 16 pass

| Assertion | Result |
|---|---|
| Policy observation dates ≤ Friday cutoff | PASS (max age 1 day) |
| Selected rates available and finite | PASS (58 selections) |
| No JPY selection while JPY unavailable | PASS |
| One baseline selection per calendar month | PASS (58 months) |
| ATR uses no data after the cutoff | PASS |
| Entry graph timestamp == entry fill | PASS (2,172 rows) |
| Exit graph timestamp == exit fill | PASS (2,172 rows) |
| Entry-bar stop detected (synthetic) | PASS (0 in real data) |
| Unstopped exit == next rebalance open | PASS (461 long, 394 short) |
| Consecutive positions never overlap | PASS (58 legs) |
| Signal-only ≤ 1 observation per month | PASS (both panels) |
| **Every D1 bar fully closed before retrieval** | **PASS (new)** |
| **JPY unavailable 2013-04-04..2016-09-20, historical only** | **PASS (new)** |
| **Two paths at different equity skip differently** | **PASS (new)** |
| Random controls use the baseline's eligible set | PASS (58 months, 2,172 outcomes) |
| Fast control engine reproduces the costed engine | PASS (−$49.93, 47 trades, 11 skips) |

## Errors and assumptions

- **Bug hit during this task:** I referenced `BASE` before its definition when adding the
  credit scenarios; the run crashed at the cost-scenario stage. Fixed and re-run in full.
- **Assumption:** a merged Sunday→Monday session is complete only when the whole UTC day has
  elapsed. This is conservative — it excludes a session that is merely *probably* finished.
- **Assumption:** the D1 completeness rule is applied at load, so every downstream D1 use
  inherits it rather than relying on each consumer to re-check.
- The `Timestamp.utcnow` deprecation warning from pandas 4 is cosmetic and does not affect
  values; the timestamp is correct.
- Canonical executable results were not recomputed differently in any way — they reproduce
  exactly, which is itself the evidence that the D1 fix stayed in its lane.

## Files changed

| File | Status |
|---|---|
| `study/fx_policy_differential_v2.py` | modified — 4 certifications |
| `study/results/fx_policy_differential_v2_signal_tests.csv` | updated — D1 holdout 30 months |
| `study/results/fx_policy_differential_v2_controls.csv` | updated — full random distributions |
| `study/results/fx_policy_differential_v2_pass_conditions.csv` | updated |
| `study/results/fx_policy_differential_v2_report.txt` | updated |
| `study/results/fx_policy_differential_v2_trades.csv` | unchanged (canonical untouched) |
| `study/results/fx_policy_differential_v2_monthly.csv` | unchanged |
| `coordination/CLAUDE_REPORT.md` | this file (005A) |
| `coordination/CLAUDE_REPORT_TASK005.md` | renamed to preserve the 005 report |

Nothing under `live/` or `recorder/` was modified or committed.

---

V2 remains permanently FAILED. No V3 is proposed and no live deployment is recommended.
