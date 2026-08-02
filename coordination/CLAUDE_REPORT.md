FROM: CLAUDE
TASK: 004 — FX POLICY-RATE DATA PANEL

Data task only. No trading performance was tested, no lookback or entry threshold was
chosen, no trade rule is recommended, the live bot was not modified and no order was placed
or changed. No V2 parameters are proposed.

Task 003B's report is preserved at `coordination/CLAUDE_REPORT_TASK003B.md`.

---

## The one finding that matters most for a carry family

**For 0 of the 19 executable pairs does the theoretical positive-carry direction actually
pay under the current Exness swap snapshot.**

Every pair where the policy differential favours being long shows a broker long carry of
**exactly 0.00%**, and every pair where it favours being short shows a broker short carry of
**0.00%**. The broker does not pay the positive-carry side at all — it zeroes it and charges
the other. Median markup is **1.38 pp** on the long side and **0.60 pp** on the short.

This is a **current dated diagnostic**, not a historical result, and it is reported because
the task asked for it — not as an argument about strategy design, which is not mine to make.

---

## Commit

| | |
|---|---|
| Commit SHA | `42dafef493842f8d724a84a979f018da1e5feaf1` |
| Branch | `main` |
| Parent | `f7fca9f` |

## Commands run

```
python study/build_fx_policy_rate_panel.py
```

## BIS source and checksum

| | |
|---|---|
| Dataset | `BIS:WS_CBPOL(1.0)` — Central bank policy rates |
| Resolved URL | `https://data.bis.org/static/bulk/WS_CBPOL_csv_flat.zip` |
| File in archive | `WS_CBPOL_csv_flat.csv` (469,780,817 bytes uncompressed) |
| **SHA-256** | `f0f4c42a3cdeb14984bd2e0938ce807a16a409b65ac38ab99565d355068a2ec6` |
| Download size | 4,094,197 bytes |
| Retrieval timestamp (UTC) | 2026-08-02 22:04:57Z |
| **BIS release date** | Thu, 30 Jul 2026 09:05:41 GMT (HTTP `Last-Modified`) |
| Latest reference date | **2026-07-29** |
| Frequency selected | `D` (daily) |
| Frequencies present in file | `{M: 25,023, D: 706,078}` |
| Units | Per cent per year (`UNIT_MEASURE 368`), `UNIT_MULT 0` |
| Daily rows kept | 157,126 across 8 currencies |

No substitute source was used anywhere. The script `fail()`s loudly rather than falling back
to FRED or a web scrape if the BIS file cannot be downloaded or parsed, and it validates the
column layout before trusting it.

The full raw download lives at `study/data/external/raw/WS_CBPOL_csv_flat.zip`, which is
**gitignored and not committed**. Only the filtered panel and the metadata JSON are committed.

## The exact eight series

Each is the BIS designated main policy rate for its economy, selected by `REF_AREA` and
`FREQ=D`. No choice among competing national rates was made — and none could have been made
on trading results, since no returns are computed in this task.

| Currency | BIS series ID | Economy | Publication source |
|---|---|---|---|
| AUD | `BIS:WS_CBPOL(1.0):D.AU` | Australia | Reserve Bank of Australia |
| CAD | `BIS:WS_CBPOL(1.0):D.CA` | Canada | Bank of Canada |
| CHF | `BIS:WS_CBPOL(1.0):D.CH` | Switzerland | Swiss National Bank |
| EUR | `BIS:WS_CBPOL(1.0):D.XM` | Euro area | European Central Bank |
| GBP | `BIS:WS_CBPOL(1.0):D.GB` | United Kingdom | Bank of England |
| JPY | `BIS:WS_CBPOL(1.0):D.JP` | Japan | Bank of Japan |
| NZD | `BIS:WS_CBPOL(1.0):D.NZ` | New Zealand | Reserve Bank of New Zealand |
| USD | `BIS:WS_CBPOL(1.0):D.US` | United States | US Federal Reserve System |

## Coverage for every currency

| Currency | First obs | Last obs | Obs | Rate changes | Min | Max | Latest |
|---|---|---|---|---|---|---|---|
| AUD | 1976-04-07 | 2026-07-23 | 12,842 | 3,315 | 0.100 | 85.00 | 4.350 |
| CAD | 1960-07-27 | 2026-07-28 | 23,040 | 1,025 | 0.250 | 21.24 | 2.250 |
| CHF | 1946-01-01 | 2026-07-29 | 21,022 | 89 | **−0.750** | 7.00 | **0.000** |
| EUR | 1999-01-01 | 2026-07-29 | 10,072 | 60 | **0.000** | 4.75 | 2.250 |
| GBP | 1946-01-01 | 2026-07-28 | 23,826 | 318 | 0.100 | 17.00 | 3.750 |
| JPY | 1946-01-01 | 2026-07-29 | 24,850 | 89 | **−0.100** | 9.00 | 1.000 |
| NZD | 1985-01-04 | 2026-07-17 | 15,148 | 2,223 | 0.250 | 265.00 | 2.500 |
| USD | 1954-07-01 | 2026-07-29 | 26,326 | 5,700 | 0.125 | 22.36 | 3.625 |

Negative rates (CHF to −0.75%, JPY to −0.10%) and legitimate zero rates (CHF 0.00% latest,
EUR floor 0.000) are **preserved exactly**, not clipped or treated as missing.

**All three required windows are fully covered by all eight currencies, with zero gap-days:**

| Window | All eight covered | Gap-days |
|---|---|---|
| 2010-01-01 onward | Yes | **0** |
| Exness D1 period from 2018-07-03 | Yes | **0** |
| Canonical executable period from 2021-08-02 | Yes | **0** |

## Missing-data findings

**The material one: JPY has a 1,267-day stale interval inside the panel, 2013-04-03 →
2016-09-21.** The BIS series carries no observation across it; the rate on either side moves
from +0.05% to −0.10%. Forward fill therefore holds **0.05% constant for three and a half
years**, which is the rule exactly as specified — but it means the panel shows a flat rate
through the QQE period, when Japanese policy in fact changed substantially. This is flagged
in the audit CSV (`stale_intervals_over_90d`) and printed in the report rather than patched,
because inventing observations BIS does not publish would be worse than showing the hole.

BIS documents the instrument history for JPY in its `COMPILATION` field, which is preserved
verbatim in `bis_policy_rates_source.json` along with the `SUPP_INFO_BREAKS` links.

It is the only stale interval over 90 days in the whole 2010+ panel:

| Currency | Longest stale, all history | Longest stale, inside panel | Intervals > 90d in panel |
|---|---|---|---|
| AUD | 6 d | 6 d | 0 |
| CAD | 3 d | 3 d | 0 |
| CHF | 3 d | 3 d | 0 |
| EUR | 1 d | 1 d | 0 |
| GBP | 3 d | 3 d | 0 |
| **JPY** | **1,817 d** | **1,267 d** | **1** |
| NZD | 8 d | 8 d | 0 |
| USD | 2 d | 2 d | 0 |

Other findings:

- **Duplicates: 0** across all eight series.
- **Uneven last observations.** NZD stops at 2026-07-17 and AUD at 2026-07-23, while the
  other six run to 2026-07-28/29. Any cross-sectional read on the latest date is therefore
  comparing values of differing freshness — NZD is 12 days stale at the file's own latest
  reference date.
- **No wide-panel NaN.** All 6,054 calendar dates × 8 currencies are populated, because every
  currency's first observation predates 2010 by decades.

## Effective-date and forward-fill methodology

One rule governs the whole panel:

```
rate(currency, date d) = value of the LAST observation whose obs_date <= d
```

- a rate change is **never** moved earlier than its official observation date;
- forward fill happens **only after** an observation becomes effective;
- **nothing is backward-filled** before a currency's first observation (moot here — all eight
  begin well before 2010, but the guard is in the code);
- no future publication or effective value is used on an earlier date;
- negative and zero rates preserved; values kept as published, unrounded.

Every long-format row carries `source_observation_date` and `is_forward_filled`, so staleness
is visible per cell rather than assumed.

## Monthly snapshot counts

| | |
|---|---|
| Snapshot rows | **1,592** |
| Months covered | **199** (2010-01-04 → 2026-07-06) |
| Months with all eight currencies | **199 / 199** |
| Median value age | **0 days** |
| Maximum value age | **1,248 days** |
| Rows with age > 90 days | **38**, all JPY |

Each first Monday takes its information cutoff as the **preceding completed Friday**
(`first_monday − 3 days`) and uses only observations effective on or before it. The 38 stale
rows are exactly the JPY QQE hole described above.

No strategy returns were calculated at any snapshot.

## Current Exness swap comparison — dated diagnostic

Uses the **2026-08-02 snapshot already stored from task 002**. The live account was not
queried or changed. The 2026 snapshot is **not applied to any historical date**, and a policy
differential is **not** claimed to equal a retail CFD swap — measuring the distance between
them is the entire point.

Latest BIS rates used: AUD 4.35, CAD 2.25, CHF 0.00, EUR 2.25, GBP 3.75, JPY 1.00, NZD 2.50,
USD 3.62 (per cent per year).

| | |
|---|---|
| Pairs compared | 19 |
| Sign agrees, long side | **4 / 19** |
| Sign agrees, short side | **13 / 19** |
| Both directions charge a cost | **2 / 19** (`EURCADm`, `EURNZDm`) |
| Swap-free both directions | 1 (`USDCADm`) |
| **Theoretical positive-carry side also positive at the broker** | **0 / 19** |
| Median markup, long side (theory − broker) | **1.38 pp** (range 0.08 → 4.35) |
| Median markup, short side | **0.60 pp** (range −2.83 → 1.87) |

The pattern is uniform: wherever the policy differential says one side should earn carry, the
broker's snapshot for that side is exactly **0.00%**, while the opposite side is charged. The
largest distortions sit where the theoretical differential is largest — `AUDCHFm` 4.35 pp,
`USDCHFm` 3.62 pp, `GBPCHFm` 3.75 pp.

Full per-pair table: `study/results/fx_policy_rate_swap_snapshot.csv`.

## Errors and assumptions

- **`requests` is not installed on this machine.** The first run silently skipped the header
  fetch and reported the BIS release date as unavailable. Rewritten to use stdlib
  `urllib.request`, and the release date is now captured correctly.
- **Assumption:** the BIS release date is taken from the bulk file's HTTP `Last-Modified`
  header. BIS does not expose a per-file release field in the flat CSV itself.
- **Assumption:** `REF_AREA=XM` is the euro area series for EUR. This is the BIS designated
  euro-area aggregate, not any member state's national rate.
- **Assumption:** where BIS publishes a daily observation on a non-business day, it is taken at
  face value; no trading calendar was imposed on the rate series.
- The panel is built on **calendar** dates, not trading dates, so it can be joined to any
  trading calendar later without re-deriving effective dates.
- Layout validation: the script checks BIS's column names before parsing and stops if they
  have changed, rather than mis-parsing a renamed schema.
- No exception occurred. 157,126 daily rows parsed; 0 unparseable dates; 0 rows dropped for
  bad values among the eight economies.

## Files changed

| File | Status |
|---|---|
| `study/build_fx_policy_rate_panel.py` | new |
| `study/data/fx_policy_rates_daily.csv` | new — 6,054 dates × 8 currencies |
| `study/data/fx_policy_rates_long.csv` | new — 48,432 rows |
| `study/data/fx_policy_rate_rebalance_snapshots.csv` | new — 1,592 rows, 199 months |
| `study/data/external/bis_policy_rates_source.json` | new — source metadata + per-series BIS fields |
| `study/results/fx_policy_rate_data_audit.csv` | new — per-currency audit |
| `study/results/fx_policy_rate_swap_snapshot.csv` | new — 19-pair diagnostic |
| `study/results/fx_policy_rate_data_report.txt` | new — full run report |
| `FINDINGS.md` | updated — added the closed FX momentum section |
| `.gitignore` | updated — `study/data/external/raw/` |
| `coordination/CLAUDE_REPORT.md` | this file (004) |
| `coordination/CLAUDE_REPORT_TASK003B.md` | renamed to preserve the 003B report |

The raw BIS bulk download is **not committed**, as required.

Nothing under `live/` or `recorder/` was modified or committed.

---

No strategy profitability is reported and no V2 parameter is recommended in this document.
