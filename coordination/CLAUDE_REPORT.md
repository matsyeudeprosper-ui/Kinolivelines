FROM: CLAUDE
TASK: 006A — CORRECTED LIQUIDATION READINESS

LIQUIDATION_READINESS_CORRECTION_20260803

Correction work only. **No liquidation outcome was examined. No post-cascade return,
direction, volatility, profitability or win rate was computed. No live bot, trade or
recorder process was changed. No hypothesis, threshold, horizon or sample gate was
changed.**

Task 006's report is preserved at `coordination/CLAUDE_REPORT_TASK006.md`.

---

# Both rejections were correct. I was wrong on both counts.

**1. The truncation warning was false, and the repository had already disproved it.** I
propagated a stale test from `study/data_readiness.py` without checking it against either
the recorder implementation or commit `812ac5f` — both of which were sitting in the repo
saying the opposite. Then I labelled it "⚠ most urgent" and recommended faster polling.
Withdrawn everywhere.

**2. The "5 cascades" figure was not gate progress.** I ranked startup buckets against
partial history, invented a 20-prior-bucket floor that appears nowhere in the
preregistration, presented the result as 4 development / 1 holdout, and derived a "~340
days" ETA from a 3.22-day sample. The formal count is **0**.

## Commit

| | |
|---|---|
| Commit SHA | `PENDING_SHA` |
| Branch | `main` |
| Parent | `4f6a721` |

## Commands run

```
python study/okx_liquidation_endpoint_audit.py     # fresh read-only endpoint audit
python study/liquidation_readiness_audit.py        # corrected readiness audit
python study/data_readiness.py                     # now reads the shared implementation
```

---

## 1. The earlier repository evidence I ignored

**Commit `812ac5f`, 2026-07-31**, in its own message:

> *"The audit flagged a 193-event minute as a possible truncation of the 100-event cap.
> That was wrong: the cap applies to the outer instrument array, not to events, and a
> single call returns about 1,500 events spanning 22 hours. Nothing was truncated.
> Pagination is kept as a safety net and the comment now states the measured behaviour
> rather than the assumed one."*

**`recorder/derivs_recorder.py`**, in the `liquidations()` docstring:

> *"MEASURED BEHAVIOUR, not assumed: `limit=100` caps the outer INSTRUMENT array, not the
> events inside it. One call returns roughly 1,500 events spanning about 22 hours. An audit
> found a minute containing 193 liquidations and it was captured whole, so there is no
> truncation problem and no need to poll quickly."*

The code also already paginates backwards with `after` (`max_pages=12`) and deduplicates
against stored keys. `LIQ_POLL = 60` carries the comment *"generous: one call already
returns ~22h of events."*

Everything needed to reject my warning was in the repository before I wrote it.

## 2. Fresh endpoint-shape audit — `study/okx_liquidation_endpoint_audit.py`

Read-only. No recorder change, no polling change, no price data, no outcome.

| | |
|---|---|
| Request UTC | 2026-08-03 07:51:17Z |
| HTTP status / API code | 200 / `0` (ok) |
| **Outer `data` objects** | **16** ← this is what `limit=100` caps |
| Max `details` in one outer object | **654** |
| **Total events across all `details`** | **654** |
| Earliest / latest event | 2026-08-02 08:38:49Z → 2026-08-03 07:15:37Z |
| **Span of one response** | **22.61 hours** |
| **More than 100 events in one response?** | **YES — 654** |
| `after` pagination | page 2 returned 0 events (single call already reaches back 22.6 h) |
| Overlap with stored keys | 548 of 654 already stored (83.8%) — dedup working |
| New since last poll | 106 |

### Confirmation on truncation

**No evidence of event truncation exists.** A single `limit=100` call returned **654
events** covering **22.6 hours**. If the parameter capped events, the response could not
have exceeded 100. It does not; it caps the outer instrument array, exactly as the
repository already documented.

The 60-second poll gives roughly a **22-hour overlap on every call** — comfortable, not
marginal. **It must not be shortened on this basis, and I did not change it.**

Outputs: `study/results/okx_liquidation_endpoint_audit.txt` and `.json`.

## 3. Formal versus provisional cascade counts

Amendment 1 added to `PREREGISTRATION_liquidations.md`, dated 2026-08-03, recorded before
any outcome was examined.

### A. FORMAL — the only numbers that count toward the gate

A bucket is formally scorable only once **≥ 30 calendar days of captured liquidation
history precede it**. The feed began 2026-07-31.

| | |
|---|---|
| **Formal cascade count** | **0** |
| **Formal development** | **0** / 400 |
| **Formal holdout** | **0** / 100 |
| **Formal gate** | **CLOSED** |
| Formal scoring begins in | **~26.8 days** |

Zero is the correct answer, not pessimism — it is the frozen rule applied honestly.

### B. PROVISIONAL — startup diagnostic, explicitly not gate progress

| | |
|---|---|
| History length | **3.22 days** (77.2 h) |
| Provisional scorable buckets | 146 |
| Provisional raw cascade buckets | 10 |
| Provisional independent — 15 min / 1 h / **4 h** | 7 / 5 / **5** |
| Provisional split | 4 dev / 1 holdout |

**Why it cannot count toward the formal gate:** the frozen definition ranks against a
trailing 30-day distribution. With 3.22 days of history, every "trailing" window is
partial, so the 5% threshold is set by a handful of startup observations rather than by a
month of market behaviour. It also relies on an **ad-hoc floor of 20 prior non-empty
buckets that is not in the preregistration** — retained only so a 95th percentile is not
taken from two observations, and now labelled as such in the code.

**No ETA is published.** The "~340 days" figure from task 006 is withdrawn: a 3.22-day
sample cannot forecast a 30-day-trailing statistic. The trigger is the formal count.

**Amendment 1 changes nothing frozen** — top 5%, 5-minute buckets, total liquidated size,
30-day trailing window, 400 development, 100 holdout, the three horizons and every
pass/fail condition all stand exactly as written.

## 4. One authoritative readiness implementation

New module `study/liquidation_readiness.py` holds the single canonical computation.
Importing it has no side effects, makes no network call, and never opens a price series.

`study/data_readiness.py` no longer computes its own cascade count. Removed from it:

| Removed | Replaced by |
|---|---|
| Individual-event 90th percentile | 5-minute bucket, total size, 95th percentile |
| Whole-sample ranking | Trailing 30-day ranking |
| 400-only gate | 400 development **and** 100 holdout |
| The false 100-event truncation test | A descriptive minute-activity line that explicitly states a busy minute is **not** evidence of truncation |

### Corrected `data_readiness.py` output

```
H4 liquidation cascade (FORMAL)   2,947    0   141.4pp  gate 400 dev + 100 holdout;
                                                        formal scoring starts in ~26.8 days
  (provisional startup only)      2,947    5    63.2pp  NOT gate progress - partial
                                                        trailing window, no ETA derivable
```

Previously it reported **14** independent cascades and **"+2,129 h"** — the figure that
became the wrong "~85 days" in `HANDOFF.md`.

### Assertion — both scripts agree

```
[OK] readiness agreement assertion: data_readiness.py and
     liquidation_readiness_audit.py agree on all 10 shared keys
```

Keys asserted identical: `formal_cascades` 0, `formal_dev` 0, `formal_holdout` 0,
`formal_gate_open` False, `formal_scoring_possible` False, `provisional_independent_4h` 5,
`provisional_dev` 4, `provisional_holdout` 1, `dev_gate` 400, `hold_gate` 100.

The assertion raises rather than warns, so the two implementations cannot silently drift
apart again — which is exactly how the wrong number reached the handoff.

## 5. Feed integrity (unchanged from task 006, re-verified)

| Check | Result |
|---|---|
| Raw rows / usable events | 2,947 / 2,947 |
| Span | 2026-07-31 02:02:15Z → 2026-08-03 07:15:37Z (3.22 days) |
| Duplicates | **0** |
| Malformed rows | **0** |
| Non-finite ts / sz / px | **0 / 0 / 0** |
| Non-positive sizes | **0** |
| Timestamps in future | **0** |
| Non-empty 5-minute buckets | 166 |
| Inter-event gaps > 1 h | 22, longest 4.10 h |

The gaps are quiet-market intervals, not missed polls — a single call covers 22.6 hours, so
a gap of 4 hours cannot be a collection failure.

## 6. Documents corrected

| Document | Correction |
|---|---|
| `coordination/DECISIONS_NEEDED.md` | A1 truncation warning withdrawn; A2 marked fixed; A3 rewritten to formal-0 with no ETA |
| `HANDOFF.md` | §4 rewritten — formal 0, gate closed, both wrong ETAs withdrawn, truncation claim withdrawn |
| `RESEARCH_MAP.md` | H4 block rewritten identically |
| `study/data_readiness.py` | truncation test removed; H4 delegated to shared module; docstring corrected |
| `PREREGISTRATION_liquidations.md` | Amendment 1 added (dated, changes nothing frozen) |
| `study/liquidation_readiness_audit.py` | rebuilt on the shared module; formal/provisional separated |

Verified by grep: every surviving mention of "truncation" or "100 events" in these files is
part of the correction itself.

## 7. Assertions and results

| Assertion | Result |
|---|---|
| Readiness implementations agree on all 10 shared keys | **PASS** |
| More than 100 detail events in one `limit=100` response | **PASS** — 654 |
| One response spans > 2 hours | **PASS** — 22.61 h |
| Audit opens no price series | **PASS** by construction |

## 8. Confirmations

- **No outcome was examined.** Neither audit script loads the BTCUSDm price series at all,
  so the data required to compute a post-cascade return, direction, volatility outcome or
  win rate is never opened.
- **No live or recorder process was changed.** `recorder/derivs_recorder.py` was **read
  only** — its polling interval, pagination and dedup are untouched. No process started,
  stopped or reconfigured; no trade; no contact with the live bot.
- **No hypothesis, threshold, horizon or gate was changed.** Amendment 1 is a clarification
  of *when scoring begins*, and lists every frozen parameter it leaves alone.
- **No raw recorder data committed.**

## Errors and assumptions

- **My error, stated plainly:** I raised a false urgent alarm by trusting a stale script
  over the recorder code and a prior correction commit, both of which were in the
  repository. The lesson is the one already in `FINDINGS.md` about judging behaviour against
  the live implementation rather than a document describing it — I should have read
  `derivs_recorder.py` before writing the warning.
- **Assumption:** "≥30 calendar days of captured history precede the bucket" is the
  operative test for formal scorability. This is the strictest reading of the trailing-30-day
  rule and matches the amendment.
- **Assumption:** the provisional diagnostic retains its 20-prior-bucket floor, now
  explicitly labelled non-preregistered, so provisional numbers stay comparable with task
  006's while never being treated as formal.
- `after` pagination returned zero events on page 2. That is expected — one call already
  reaches back 22.6 hours — and is not a pagination fault.

## Files changed

| File | Status |
|---|---|
| `study/liquidation_readiness.py` | **new** — single authoritative implementation |
| `study/okx_liquidation_endpoint_audit.py` | **new** — read-only endpoint audit |
| `study/results/okx_liquidation_endpoint_audit.txt` | **new** |
| `study/results/okx_liquidation_endpoint_audit.json` | **new** |
| `study/liquidation_readiness_audit.py` | rebuilt on the shared module |
| `study/results/liquidation_readiness_audit.csv` | regenerated — formal/provisional split |
| `study/results/liquidation_readiness_audit.txt` | regenerated |
| `study/data_readiness.py` | truncation test removed; H4 delegated; assertion added |
| `PREREGISTRATION_liquidations.md` | Amendment 1 |
| `HANDOFF.md` | §4 corrected |
| `RESEARCH_MAP.md` | H4 corrected |
| `coordination/DECISIONS_NEEDED.md` | A1–A3 corrected |
| `coordination/CLAUDE_REPORT.md` | this file (006A) |
| `coordination/CLAUDE_REPORT_TASK006.md` | renamed to preserve the 006 report |

`recorder/derivs_recorder.py` was read but **not modified**. Nothing under `live/` or
`recorder/` was changed or committed.

---

The research conclusion is unchanged: both FX families are closed, liquidation cascades
remain the only open hypothesis, and their **formal sample clock has not started yet**.
