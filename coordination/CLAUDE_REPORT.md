FROM: CLAUDE
TASK: 006 — RESEARCH STATE AND LIQUIDATION READINESS

Documentation and data-readiness work only. **No strategy was proposed, optimised,
implemented or tested. No liquidation outcome was inspected. No live process, recorder
setting, trade or configuration was changed.**

Task 005A's report is preserved at `coordination/CLAUDE_REPORT_TASK005A.md`.

---

# The two findings that matter

**1. The documentation contradiction was real and worse than described.** `RESEARCH_MAP.md`
told a reader to *"run this first"* (perp-index basis) and *"Run next"* (DVOL) for families
`HANDOFF.md` records as null. A future model following it would have re-run three dead
studies. Corrected.

**2. The "~85 days to the liquidation gate" figure was wrong by roughly 4×.** It counted the
wrong thing. Under the frozen preregistered definition the honest position is **5 independent
cascades so far, 396 development and 99 holdout still to go** — several hundred days at the
current pace, not 85. Corrected in both `HANDOFF.md` and `RESEARCH_MAP.md`.

## Commit

| | |
|---|---|
| Commit SHA | `PENDING_SHA` |
| Branch | `main` (the existing research branch) |
| Parent | `a5dd74c` |

## Files inspected

`HANDOFF.md`, `FINDINGS.md`, `RESEARCH_MAP.md`, `README.md`,
`PREREGISTRATION_liquidations.md`, `coordination/DECISIONS_NEEDED.md`,
`coordination/CLAUDE_REPORT.md`, `study/data_readiness.py`,
`recorder/data/liquidations_BTC.csv`, `recorder/data/derivs_BTC.csv`, and the four
heartbeat files (read-only).

---

## 1. Documentation contradictions found and corrected

| # | Contradiction | Source of truth | Fix |
|---|---|---|---|
| 1 | `RESEARCH_MAP.md` H1 perp-index basis — *"Status — run this first."* | `HANDOFF.md` §2: **null**, `basis_edge.py` | Moved to CLOSED |
| 2 | `RESEARCH_MAP.md` H6 DVOL — *"the strongest testable-now hypothesis. Run next."* | `HANDOFF.md` §2: **null; Q2 died out-of-sample** | Moved to CLOSED |
| 3 | `RESEARCH_MAP.md` H3 broker feed lag — *"TESTABLE NOW (preliminary)"* | `HANDOFF.md` §2: **null on all 4 preregistered criteria** | Moved to CLOSED |
| 4 | `RESEARCH_MAP.md` title — *"BTC-specific edges still open"*, implying several | Only H4 is open | Retitled; states plainly that exactly one hypothesis is open |
| 5 | `RESEARCH_MAP.md` H4 — *"Liquidations are not currently recorded at all"* | They have been recorded since 2026-07-31 | Replaced with live counts |
| 6 | Neither FX family appeared in any closed list | Tasks 003–005A | Added to both `HANDOFF.md` §2 and `RESEARCH_MAP.md` |
| 7 | `HANDOFF.md` §4 — *"roughly 85 days out … at 42.6 events/hour"* | Frozen definition + this audit | Corrected, with both errors explained |
| 8 | `HANDOFF.md` §4 gate stated as *"400 independent cascades"* | Preregistration requires **400 dev AND 100 holdout** | Both arms now stated |

`README.md` needed no change — it defers to `RESEARCH_MAP.md`, so fixing that fixes the
pointer. `coordination/DECISIONS_NEEDED.md` was already consistent (rewritten last commit).

**Added to `FINDINGS.md`:** a closed section for FX Policy-Rate Differential V2 carrying every
figure requested — baseline −$49.93, validation −$30.39, holdout −$19.55, PF 0.826, p 0.5525,
6/16 plus one N/A, fixed 47-trade credit counterfactual **+$19.87**, recursive credit path
**−$7.32**, actual 2026 snapshot contribution **$0.00**, forming D1 bar removed, permanently
closed.

**Both distinctions preserved verbatim in the docs:**

- a current swap snapshot is **not** historical swap evidence;
- zero carry on V2's selected side does **not** prove that every holding-based strategy on
  every venue is impossible — one venue, one snapshot, one selected side.

All documents now agree that **liquidation cascades are the only open hypothesis** and that no
outcome test may run before the frozen event gate.

### One correction to my own earlier wording

Task 005A said the measured −0.0 h offset showed *"the MT5 server frame IS UTC."* That was
over-stated: the MT5 Python API already returns timestamps in UTC, so the comparison confirms
the timestamps this code receives are UTC-aligned but does not independently establish the
broker's internal server timezone. Only the UTC alignment matters for the completeness rule,
and the forming-bar removal is unaffected. Wording fixed in
`study/fx_policy_differential_v2.py` (docstring and runtime output).

---

## 2. Liquidation readiness audit — read-only

New script: `study/liquidation_readiness_audit.py`. It **never loads the BTCUSDm price
series at all**, which is the simplest guarantee that no outcome was examined — the data
required to compute one is not opened.

### Feed

| | |
|---|---|
| File | `recorder/data/liquidations_BTC.csv` |
| Raw rows | **2,947** |
| First timestamp (UTC) | 2026-07-31 02:02:15 |
| Latest timestamp (UTC) | 2026-08-03 07:15:37 |
| Span | 77.2 hours (3.22 days) |
| Observed rate | 38.2 events/hour |

### Growth

| Window | Events | Note |
|---|---|---|
| Last 24 hours | **655** | full window covered |
| Last 7 days | 2,947 | feed only 77.2 h old |
| Last 30 days | 2,947 | feed only 77.2 h old |

### Integrity

| Check | Result |
|---|---|
| Duplicate rows | **0** — CLEAN |
| Malformed rows | **0** |
| Non-finite / missing `ts_ms`, `sz`, `bkPx` | **0 / 0 / 0** |
| Non-positive sizes | **0** |
| Timestamps in the future | **0** |
| Stored in time order | **No** — writer is newest-first; sorted for this audit |
| Non-empty 5-minute buckets | **166** of 928 slots |
| Empty 5-minute slots | 762 (82.1%) — quiet market, not necessarily loss |
| Inter-event gaps > 1 hour | **22**, longest **4.10 h** (2026-08-01 03:57 → 08:03) |

**One integrity problem worth acting on later:** the OKX endpoint returns at most **100
events per poll**, and four minutes have already carried **≥ 90 events** (busiest: 193).
Cascades are by definition the busiest minutes, so the feed may be **truncating exactly the
episodes the hypothesis is about**. Flagged only — task 006 forbids changing recorder
settings, and I did not.

### Cascade candidates — frozen definition, no outcomes examined

Applied exactly as preregistered: a 5-minute bucket whose **total** liquidated size exceeds
the **95th percentile of the trailing 30-day distribution of non-empty buckets**.

| | |
|---|---|
| Buckets scorable | 146 (rest lack trailing history to rank) |
| **Raw cascade buckets** | **10** |
| First / latest cascade | 2026-07-31 13:40 → 2026-08-03 03:45 |

Independence — the longest preregistered horizon is 4 h, so 4 h is the strictest reading and
is used as primary:

| Separation | Independent cascades |
|---|---|
| 15 min | 7 |
| 1 h | 5 |
| **4 h (primary)** | **5** |

### The gate

| | Development | Holdout | Total |
|---|---|---|---|
| **Have** (75-25 chronological split) | **4** | **1** | 5 |
| Gate | 400 | 100 | — |
| **Remaining** | **396** | **99** | — |
| **Gate open** | **No** | | |

**Rough pace, explicitly not a deadline:** ~1.55 independent cascades/day → satisfying both
arms needs ~533 total, roughly **340 more days** at the current rate. Liquidation activity is
regime-dependent and the trailing threshold moves with it, so this will change. **The trigger
remains the count, never a date.**

**PROVISIONAL:** the feed is 3.22 days old, shorter than the 30-day trailing window, so no
bucket yet has a full trailing distribution and the 5% threshold is set by partial history.
Every cascade count above is provisional and should be recomputed once the feed exceeds 30
days. This does not change the gate rule.

### Does `study/data_readiness.py` agree? — **No, and mine is the stricter one**

| | `data_readiness.py` | This audit |
|---|---|---|
| Independent count | **14** | **5** |
| ETA | +2,129 h (~89 days) | ~340 days |

Three differences, all in the same direction:

1. It counts individual **events** at/above the **90th** percentile of size; the frozen rule
   scores **5-minute buckets** by **total** size at the **95th** percentile.
2. It ranks against the **whole sample**; the frozen rule ranks against a **trailing 30-day**
   window.
3. It counts any 4-hour window containing one such event, and **ignores the holdout arm**
   entirely — it targets 400, where the preregistration needs ~533 across both arms.

`data_readiness.py` is a useful loose proxy but it is **not** the preregistered definition,
and it is the source of the "~85 days" figure that propagated into `HANDOFF.md`. I have left
the script unchanged — it was not in scope — and documented the divergence in both files.

### Recorder health — read-only

| Heartbeat | Age | Limit |
|---|---|---|
| `live/daemon_alive.json` | 24 s | < 90 s |
| `recorder/data/status.json` | 1 s | < 60 s |
| `recorder/data/derivs_alive.json` | 28 s | < 400 s |
| `recorder/data/micro_alive.json` | 0 s | < 30 s |

All four fresh. Checked by reading file modification times only; no process was started,
stopped, restarted or configured.

---

## 3. Confirmations

- **No outcome was examined.** No post-cascade return, direction, volatility outcome,
  profitability or win rate was computed. The audit script never opens a price series.
- **No live or recorder process was changed.** No restart, no configuration edit, no order,
  no trade, no change to the daemon or either recorder. The only commands touching the live
  system were file-modification-time reads.
- **No raw recorder data is committed.** `recorder/data/*` is untouched and unstaged.
- **No strategy was proposed, optimised, implemented or tested.**

## Errors and assumptions

- **Assumption:** independence enforced at 4 h, the longest preregistered horizon. A set
  independent at 4 h is independent at 1 h and 15 min too; the looser counts are reported for
  reference only.
- **Assumption:** with the feed younger than 30 days, the trailing rank uses whatever history
  precedes each bucket. Same rule, shorter effective window, flagged PROVISIONAL throughout.
- **Assumption:** the holdout is the final 25% chronologically, per the preregistration's
  "untouched final 25%".
- Buckets with fewer than 20 prior non-empty buckets are not scored, since a 95th percentile
  cannot be defined from them. 146 of 166 were scorable.

## Files changed

| File | Change |
|---|---|
| `RESEARCH_MAP.md` | rewritten — basis, broker lag and DVOL moved to CLOSED; H4 the only open hypothesis; both FX families added; corrected gate status |
| `HANDOFF.md` | §2 gains both FX families; §4 gate corrected (both arms, real counts, the "85 days" error explained) |
| `FINDINGS.md` | new closed section for FX Policy-Rate Differential V2 |
| `study/liquidation_readiness_audit.py` | **new** — read-only readiness audit |
| `study/results/liquidation_readiness_audit.csv` | **new** |
| `study/results/liquidation_readiness_audit.txt` | **new** |
| `study/fx_policy_differential_v2.py` | wording only — the server-timezone over-claim corrected |
| `coordination/CLAUDE_REPORT.md` | this file (006) |
| `coordination/CLAUDE_REPORT_TASK005A.md` | renamed to preserve the 005A report |

`README.md` and `coordination/DECISIONS_NEEDED.md` inspected, already consistent, unchanged.
Nothing under `live/` or `recorder/` was modified or committed.

---

No strategy is proposed or recommended in this document.
