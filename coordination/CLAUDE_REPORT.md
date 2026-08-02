FROM: CLAUDE
TASK: 002 — CLEAN FX RESEARCH DATASET

Data preparation and audit only. No strategy was tested, no returns are reported, no rule
is recommended, the live bot was not modified and no order was placed or changed.

Task 001's report is preserved at `coordination/CLAUDE_REPORT_TASK001.md`.

---

## ⚠ The 6-year history requirement cannot be met — read first

The universe rule asks for **≥ 6 calendar years of reliable history**. **No symbol on this
account meets it on H1**, and this is a broker limit, not a download or sync problem.

`EURUSDm` H1 bars per calendar year, as served by Exness:

| 2018 | 2019 | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 | 2026 |
|---|---|---|---|---|---|---|---|---|
| 155 | 311 | 312 | 3,055 | 6,235 | 6,216 | 6,240 | 6,216 | 3,624 (to Jul) |

A full FX year is ~6,200 H1 bars. 2018–2020 return 155–312 — sparse remnants, not history.
I verified this is the broker's limit by issuing explicit `copy_rates_range()` calls for 2019
and 2020: they return the same 311 and 312 bars. A longer or different download does not fix it.

- First month with a full complement of H1 bars: **2021-08**
- Usable dense window: **2021-08-02 → 2026-07-31 = 4.99 years**

Applying the rule literally would empty the universe and produce no dataset. So the rule is
applied, **recorded as failed for every symbol** (`meets_6y_requirement=False` in
`fx_universe_audit.csv`), and the dataset is built over the real 4.99-year window. This is
stated in the first section of the integrity report too.

**Relevant fact for whoever sets strategy:** broker **D1** reaches back to 2018-07 (~8 years)
even though H1 does not. A daily panel could therefore span ~8 years — but it could **not** be
cut to the canonical 17:00 New York session boundary, because that construction requires
intraday bars. Stated as a trade-off; no recommendation is made.

---

## Commit

| | |
|---|---|
| Commit SHA | `PENDING_SHA` |
| Branch | `main` |
| Parent | `ad52262` (task 001) |
| Date | 2026-08-02 |

## Commands run

```
python study/build_fx_canonical_data.py     # universe + H1 download + canonical build + audit
```

## Selected symbols — 23

All are true fiat FX pairs, tradeable both sides, from census groups A and B:

```
AUDCADm  AUDCHFm  AUDJPYm  AUDNZDm  AUDUSDm  CADJPYm  CHFJPYm  EURCADm
EURCHFm  EURGBPm  EURJPYm  EURNZDm  EURUSDm  GBPAUDm  GBPCHFm  GBPJPYm
GBPNZDm  GBPUSDm  NZDCADm  NZDJPYm  USDCADm  USDCHFm  USDJPYm
```

12 from group A, 11 from group B — group B majors were included as instructed, not excluded.

## Excluded symbols and reasons

| Reason | Count | Examples |
|---|---|---|
| not in census group A or B | 239 | BTCUSDm, LTCUSDm, XRPUSDm, SOLUSDm … |
| asset_class = Stocks | 68 | NFLXm, WMTm, KOm, XOMm … |
| asset_class = Indices | 5 | AUS200m, HK50m, UK100m, US500m, FR40m |
| asset_class = Crypto | 1 | ETHUSDm |
| non-fiat base hiding in Forex | 5 | XALUSDm, XCUUSDm, XNIUSDm, XPBUSDm, XZNUSDm |
| median spread > 6.00% of D1 ATR | 13 | USDSGDm 24.8%, USDDKKm 19.2%, AUDZARm 18.7%, HKDJPYm 18.5%, EURSGDm 16.2%, AUDMXNm 14.5%, EURMXNm 12.4%, ZARJPYm 11.6%, CHFMXNm 10.8%, USDILSm 10.8%, GBPMXNm 10.5%, USDMXNm 7.0%, **NZDCHFm 6.02%** |
| 2-ATR risk > 2.00% of $979 | 2 | GBPILSm 2.22%, USDZARm 2.44% |

`NZDCHFm` is the only genuinely marginal call — it misses the spread cap by 0.02pp (6.02% vs
6.00%) and was excluded because the threshold is the threshold. Flagging it so the decision is
visible rather than buried.

No energies symbol reached groups A/B, so none needed excluding by that rule.

## Data coverage

Every one of the 23 symbols produced an **identical, balanced panel** — ideal for
cross-sectional work, since no symbol enters or leaves the sample mid-stream:

| | |
|---|---|
| Daily canonical bars | **1,299 per symbol** (29,877 rows total) |
| Weekly canonical bars | **261 per symbol** (6,003 rows total) |
| First / last session | 2021-08-02 → 2026-07-31 |
| Span | 4.99 years |
| Weekday counts | Mon 259, Tue 261, Wed 259, Thu 259, Fri 261 |
| Duplicate timestamps | **0** across all symbols |
| Days with a gap | 4–6 per symbol |
| Total missing H1 bars | 4–6 per symbol (out of ~31,000) |
| Missing weeks | 1 per symbol |
| Abnormally short (<20h) or long (>25h) days | **0** |

H1 download: **13.6 min**, 23 symbols, sequential.

## Time base — the UTC assumption is verified, not assumed

Timestamps treated as UTC and converted to `America/New_York`, as instructed. The data
independently confirms this:

- **Observed Sunday open: exactly 17:00 NY**
- **Observed Friday last bar: exactly 16:00 NY** (the 16:00–17:00 bar)

Had the feed been on a UTC+2/+3 server clock, these would not land on the 17:00 boundary. The
integrity report prints both so the assumption stays checkable.

Canonical session: `session_date = (t_newyork + 7h).date()`, so 17:00 NY shifts to 00:00 the
next day and evening bars belong to the *next* session.

## Sunday-bar findings

- **45,654 raw Sunday H1 bars** across the 23 symbols — all merged into Monday.
- **Zero standalone Sunday canonical candles**, structurally: the +7h shift moves Sunday
  17:00–23:59 NY into Monday, so a Sunday session cannot be emitted by construction.
- **Stray weekend bars**: 3,818 across full history; within the dense window actually used
  only **3 per symbol (69 total)**. I checked what they are — timestamps like
  `2021-08-01 00:00 UTC` = **Saturday 20:00 NY**, carrying roughly *half* the normal tick
  volume (630 vs 1,601). Genuine weekend artefacts, correctly dropped and counted rather than
  folded into a session.

## DST handling

**0 sessions of 25 hours, 1 session of 23 hours** across the whole panel. That is correct, not
a failure to detect: US and EU daylight-saving transitions occur on a Sunday at ~02:00 local,
which falls inside the weekend market closure. A 17:00-NY-to-17:00-NY session therefore almost
never spans a transition. Transitions are handled by `tz_convert`; any 23/25-hour session is
reported rather than normalised, because forcing it to 24 would either invent or discard a real
hour of market data.

## Broker D1 ATR(20) vs canonical 5-day ATR(20)

**The canonical ATR is larger than the broker's D1 ATR for all 23 symbols, without exception.**

| | |
|---|---|
| Ratio range | 1.049 – 1.195 |
| Median ratio | **1.113** |
| Symbols with ratio > 1.0 | **23 of 23** |

This is a boundary effect, not an error: the broker's D1 candle uses its own daily cut, while
the canonical bar spans the true 17:00-NY FX session and therefore captures range the broker's
candle splits across two days. It matters because **task 001 sized every risk figure off the
broker's D1 ATR, which understates the session range by ~11% on average.**

## Revised risk classification

Revised USD risk re-prices the canonical ATR using the USD-per-price-unit implied by the
terminal's own `order_calc_profit()` result from task 001 — so no assumed contract arithmetic
enters, and no new terminal calls were needed.

| Limit | Fits |
|---|---|
| ≤ 1.00% of $979 | **10 of 23** |
| ≤ 1.50% of $979 | **19 of 23** |
| ≤ 2.00% of $979 | **23 of 23** |

Two symbols pass on the broker's ATR but **fail** once measured on canonical sessions:

| Symbol | Census risk | Revised risk |
|---|---|---|
| AUDJPYm | 0.95% | **1.07%** |
| NZDJPYm | 0.90% | **1.03%** |

Both would have been treated as inside a 1% budget on task 001's numbers. They are not.

## Spread audit (spread only — no return series was inspected)

Full table: `study/results/fx_spread_by_hour.csv` (2,760 rows: symbol × weekday × NY hour).

Pooled by New York hour, the rollover is unmistakable:

| NY hour | Median (pts) | p90 (pts) |
|---|---|---|
| 00–15 | 20–21 | 38 |
| 16 | 20 | 43 |
| **17** | **53** | **158** |
| **18** | **46** | **108** |
| 19–23 | 21 | 38–41 |

Spread at the 17:00 NY session rollover is **~2.6× the median hour and its p90 is ~4× normal**.

By weekday: Mon 21, Tue–Thu 20, Fri 20 (medians); the Sunday mini-session is the worst at
median 24 / p90 93.

This table was produced from the spread series alone. No return was examined in building it, so
it cannot have been tuned toward a favourable execution hour.

## Swap

Swap values are carried into `fx_universe_audit.csv` **only as a dated broker snapshot**
(2026-08-02), in columns suffixed `_snapshot`. They are **not** applied across historical years.
**Exness does not publish historical swap rates and none were separately collected**, so any
historical carry figure would be fabricated. Holding cost is known only as of the snapshot date.

## Missing-data problems

- The 6-year history shortfall above is the material one.
- 4–6 missing H1 bars per symbol out of ~31,000, and 1 missing week per symbol.
- 0 duplicate timestamps, 0 abnormally short/long sessions, 0 symbols failed to build.
- **No missing price was forward-filled anywhere in this pipeline.**

## Terminal contention

| | |
|---|---|
| Latency probes | 23 |
| Median / p95 / max | 0 ms / 0 ms / **1 ms** |
| Pauses taken | **0** |
| Aborted | No |

No contention occurred — every probe answered within 1 ms, so no data was read from a strained
terminal. Requests were strictly sequential with a 0.3 s delay between symbols. Market Watch was
restored in a `finally:` block to its exact starting baseline. The bot and both recorders ran
untouched throughout.

## Files changed

| File | Status |
|---|---|
| `study/build_fx_canonical_data.py` | new — universe, download, canonical build, audit |
| `study/data/fx_daily_canonical.csv` | new — 29,877 rows |
| `study/data/fx_weekly_canonical.csv` | new — 6,003 rows |
| `study/results/fx_universe_audit.csv` | new — 356 rows × 61 cols, exclusions included |
| `study/results/fx_spread_by_hour.csv` | new — 2,760 rows |
| `study/results/fx_data_integrity_report.txt` | new — full integrity report |
| `coordination/CLAUDE_REPORT.md` | this file (task 002) |
| `coordination/CLAUDE_REPORT_TASK001.md` | renamed from `CLAUDE_REPORT.md` to preserve task 001 |
| `.gitignore` | added `study/data/raw_h1/` |

Raw H1 downloads live in `study/data/raw_h1/` and are **gitignored, not committed**, as required.

Nothing under `live/` or `recorder/` was modified or committed.

---

No strategy returns are reported and no strategy rule is recommended in this document.
