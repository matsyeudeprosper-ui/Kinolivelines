FROM: CLAUDE
TASK: 004A — CORRECTED FX POLICY-RATE PANEL

Data correction only. No strategy returns were tested, no strategy parameter was chosen, the
live bot was not modified and no order was placed or changed.

Task 004's report is preserved at `coordination/CLAUDE_REPORT_TASK004.md`.

---

# Both defects were real, and one invalidated a headline claim

Task 004 reported **"zero gap-days"** and **199/199 complete months**. Both were wrong.

| | Task 004 | Task 004A |
|---|---|---|
| Non-finite values accepted as observations | **9,297** | **0** (rejected and logged) |
| JPY 2013–2016 | forward-filled at 0.05% | **unavailable, 1,266 dates** |
| Complete snapshot months | 199 / 199 | **158 / 199** |
| Max snapshot value age | 1,248 days | **7 days** |
| 2010+ continuous availability, all eight | "zero gap-days" | **False** |
| Long-panel rows | 48,432 (NaN rows dropped) | 48,432 (**unavailable rows kept and marked**) |

## Commit

| | |
|---|---|
| Commit SHA | `PENDING_SHA` |
| Branch | `main` |
| Parent | `452a23f` |

## Commands run

```
python study/build_fx_policy_rate_panel.py
```

---

## 1. Rejected non-finite values

**9,297 rejected**, all `NaN` string placeholders BIS writes on non-publication days. The
task-004 parser accepted every one because `float("NaN")` succeeds and returns a float.

| Currency | Rejected | Date range |
|---|---|---|
| CAD | **5,882** | 1960-07-30 … **2026-07-19** |
| NZD | **2,806** | 1985-01-05 … **2026-07-12** |
| GBP | 422 | 1975-01-01 … **2026-05-25** |
| AUD | 95 | 1976-04-16 … 1989-12-26 |
| CHF | 60 | 1991-01-01 … 1999-12-31 |
| EUR | 32 | **2024-09-21 … 2025-01-05** |
| JPY | 0 | — |
| USD | 0 | — |

Full log: `study/results/fx_policy_rate_rejected_values.csv` (currency, BIS area,
observation date, raw value, reason).

Two consequences that were not visible before:

- **These run to within days of the file date** — CAD to 2026-07-19, NZD to 2026-07-12. They
  are not an ancient-history artefact.
- **Observation counts and rate-change counts were both wrong.** With NaN rows removed, CAD
  drops from 23,040 to 17,158 observations, NZD from 15,148 to 12,342 — while *rate changes
  rise* (NZD 2,223 → 2,797, AUD 3,315 → 3,374), because a NaN sitting between two different
  values previously masked the change on either side of it.
- The EUR block (2024-09-21 … 2025-01-05) sits exactly at the MRO → deposit-facility
  transition, so it was a definition change showing up as missing data.

## 2. Japan's no-policy-rate regime

BIS states it verbatim in the series `COMPILATION` field:

> *"from 4 Apr 2013 to 20 Sep 2016: no policy rate"*

**Corrected interval: 2013-04-04 through 2016-09-20 inclusive — 1,266 calendar dates.**

- `policy_rate_pct` = empty
- `is_policy_rate_available` = false
- `availability_reason` = "BIS metadata: no policy rate under QQE regime"
- `is_forward_filled` = false (nothing was filled — the rate does not exist)
- `source_observation_date` = empty, so nothing implies a stale value is still valid

Task 004 forward-filled **0.05% flat across all 1,266 days**. No substitute Japanese rate was
used and no equivalent was invented. From 2016-09-21 the official observations resume normally.

Any future strategy using this panel must exclude a JPY pair whenever JPY is unavailable —
the field is there to make that enforceable rather than remembered.

## 3. Availability fields

Added to the long panel: `is_policy_rate_available`, `availability_reason`, `policy_regime`.
One row per currency per calendar date is kept, **including unavailable periods** — task 004
dropped null rows, which is precisely why the JPY hole was invisible in the committed data.

| | |
|---|---|
| Long-panel rows | 48,432 |
| Available | **47,166** |
| Unavailable | **1,266** (all JPY) |
| Empty cells in the wide panel | 1,266 — intentional unavailability, not missing source |

Snapshots carry the same three fields. **Completeness is now defined as: a row exists AND is
marked available AND carries a finite rate** — never row count alone.

| | Task 004 | Task 004A |
|---|---|---|
| Snapshot rows | 1,592 | 1,592 |
| Rows available | (not distinguished) | **1,551** |
| Rows unavailable | (not distinguished) | **41** |
| **Complete months** | **199 / 199** | **158 / 199** |
| Incomplete months | 0 | **41** (2013-05 … 2016-09) |
| Max value age | **1,248 days** | **7 days** |

The maximum age collapsing from 1,248 days to 7 is the clearest single symptom of the fix: the
old figure was entirely the JPY stale carry.

## 4. Corrected coverage — four categories kept separate

"Covered" now means source present **and** the policy rate intentionally available.

| Window | All eight continuously available | Intentionally unavailable days | Missing source days |
|---|---|---|---|
| **2010-01-01 onward** | **False** | **1,266** (JPY) | 0 |
| Exness D1 from 2018-07-03 | **True** | 0 | 0 |
| Canonical from 2021-08-02 | **True** | 0 | 0 |

This matches the expected interpretation exactly. Across all history: 9,297 rejected
non-finite values and 9,272 ordinary forward-filled unchanged days — reported as distinct
quantities, never merged into one "gap" number.

## 5. Regime and definition breaks

`study/results/fx_policy_rate_regime_breaks.csv` — **12 regimes, 5 flagged as comparability
breaks**, all transcribed verbatim from the BIS `COMPILATION` metadata rather than from my own
reading of monetary history.

| Currency | Start | End | Regime | Available | Break |
|---|---|---|---|---|---|
| JPY | 2010-10-05 | 2013-04-03 | UOCR around 0–0.1% | yes | |
| **JPY** | **2013-04-04** | **2016-09-20** | **NO POLICY RATE (QQE)** | **no** | **yes** |
| JPY | 2016-09-21 | 2024-03-20 | Short-term policy rate −0.1% with YCC | yes | **yes** |
| JPY | 2024-03-21 | 2024-07-31 | UOCR around 0–0.1% | yes | **yes** |
| JPY | 2024-08-01 | 2025-01-26 | UOCR around 0.25% | yes | |
| JPY | 2025-01-27 | 2025-12-21 | UOCR around 0.50% | yes | |
| JPY | 2025-12-22 | 2026-06-16 | UOCR around 0.75% | yes | |
| JPY | 2026-06-17 | open | UOCR around 1.00% | yes | |
| CHF | 2000-01-01 | 2019-06-12 | Mid-point of SNB target range | yes | |
| **CHF** | **2019-06-13** | open | **SNB policy rate** | yes | **yes** |
| EUR | 2008-10-15 | 2024-09-17 | MRO fixed rate | yes | |
| **EUR** | **2024-09-18** | open | **Deposit facility rate** | yes | **yes** |

All three breaks the task named are present, plus the subsequent JPY operating-target changes.
**No published value was altered around any valid definition change** — the table exists to
expose the breaks for later sensitivity tests, not to adjust the data.

## 6. Corrected release-date terminology

The HTTP header is the **bulk file's modification timestamp** and is now named as such
everywhere:

| Field | Value |
|---|---|
| `bulk_file_http_last_modified` | Thu, 30 Jul 2026 09:05:41 GMT |
| `historical_observation_release_date_available` | **false** |

The metadata JSON carries an explicit note: the BIS flat CSV contains no observation-level
release or vintage timestamp, so the header says only when the bulk file was last rebuilt. It
does **not** mean every historical observation was published on 30 July 2026, and **no
point-in-time or vintage claim can be made from this file** — revision effects are not
observable in it. The long panel column was renamed from `source_release_date` to
`bulk_file_http_last_modified` for the same reason.

## 7. Rebuilt swap comparison

Rebuilt on the corrected panel, using the newest date on which each currency is **both
available and finite** rather than simply the last row.

Latest available rates, all effective 2026-07-29: AUD 4.35, CAD 2.25, CHF 0.00, EUR 2.25,
GBP 3.75, JPY 1.00, NZD 2.50, USD 3.62.

**The finding survives the rebuild unchanged** — the output file is byte-identical to task
004's, because the corrections do not touch the latest values:

| | |
|---|---|
| Pairs compared | 19 |
| Sign agrees, long / short | 4 / 19 and 13 / 19 |
| Both directions charge a cost | 2 / 19 (`EURCADm`, `EURNZDm`) |
| **Theoretical positive-carry side also positive at the broker** | **0 / 19** |
| Median markup, long / short | **1.38 pp** / 0.60 pp |

Wherever the policy differential says a side should earn carry, the broker's snapshot for that
side is exactly **0.00%** and the opposite side is charged. Largest distortions where the
differential is largest: `AUDCHFm` 4.35 pp, `GBPCHFm` 3.75 pp, `USDCHFm` 3.62 pp.

Still a **2026 dated snapshot only**. Not applied historically; a policy differential is not
claimed to equal a retail CFD swap.

## Assertions and results

All pass:

| Assertion | Result |
|---|---|
| Every value marked available is finite | **PASS** (47,166 rows) |
| No available value is NaN or infinity | **PASS** |
| Every unavailable row has an empty rate | **PASS** (1,266 rows) |
| No unavailable row is marked forward-filled | **PASS** |
| No unavailable row points at a source observation date | **PASS** |
| Every non-null wide-panel cell is finite | **PASS** |
| Every available snapshot row carries a finite rate | **PASS** (1,551 rows) |

## Errors and assumptions

- **Assumption:** BIS `NaN` placeholders are non-publication days, not zero rates. They are
  rejected and the dates become ordinary forward-filled dates — the previous value stays in
  force, which is what the effective-date rule requires.
- **Assumption:** the JPY interval is taken exactly as BIS words it, 4 Apr 2013 to 20 Sep 2016
  inclusive. No judgement was applied to its boundaries.
- **Assumption:** regime rows are transcribed from the BIS `COMPILATION` string verbatim; where
  BIS gives a date without a year for a range end ("to 31 July" in the 2024 entry) it is read
  from the surrounding context as 2024-07-31.
- The forward-fill rule is unchanged from task 004 and still correct: rate on date *d* is the
  last **finite, available** observation with obs_date ≤ *d*.
- The wide panel now legitimately contains empty cells. Anything consuming it must treat empty
  as "no policy rate exists", not as a missing value to be imputed.
- No exception occurred; the run completed cleanly.

## Files changed

| File | Status |
|---|---|
| `study/build_fx_policy_rate_panel.py` | modified — 7 corrections |
| `study/data/fx_policy_rates_daily.csv` | updated — 1,266 empty JPY cells |
| `study/data/fx_policy_rates_long.csv` | updated — availability fields, unavailable rows kept |
| `study/data/fx_policy_rate_rebalance_snapshots.csv` | updated — availability fields |
| `study/data/external/bis_policy_rates_source.json` | updated — release-date terminology |
| `study/results/fx_policy_rate_data_audit.csv` | updated — four separated categories |
| `study/results/fx_policy_rate_swap_snapshot.csv` | rebuilt (identical values) |
| `study/results/fx_policy_rate_data_report.txt` | updated |
| `study/results/fx_policy_rate_rejected_values.csv` | **new** — 9,297 rejected rows |
| `study/results/fx_policy_rate_regime_breaks.csv` | **new** — 12 regimes, 5 breaks |
| `coordination/CLAUDE_REPORT.md` | this file (004A) |
| `coordination/CLAUDE_REPORT_TASK004.md` | renamed to preserve the 004 report |

Raw BIS bulk download still gitignored and not committed. Nothing under `live/` or `recorder/`
was modified or committed.

---

No strategy was tested and none is recommended.
