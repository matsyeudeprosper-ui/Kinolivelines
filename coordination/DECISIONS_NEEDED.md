FROM: CLAUDE
RE: TASK 003 — duplicate spec received, and what needs deciding before any V2

Supersedes the task-002 version of this file. Those five items were all answered by the
task-003 spec (history: both panels; risk cap: 1.50%; ATR: canonical supersedes; NZDCHFm:
stays excluded; execution: first Monday 20:00 New York).

---

## 1. The task-003 spec arrived twice, identical

The second copy was byte-identical to the first. **It was not re-run.** TASK 003 was already
complete and pushed:

- commit `2ddf7a2` (SHA recorded in `b25e959`)
- all 7 required outputs on `origin/main`, report begins with the required two lines
- **verdict: V1 FAILED, 5 of 13 conditions**

If the duplicate was intentional — a re-verification request, or a different task number that
got pasted wrong — say so and I will act on it. Results are deterministic (permutation seed
fixed at 20260802), so a re-run reproduces the same numbers; it costs ~15 minutes and would
confirm nothing new unless the spec actually changed.

**No answer needed if it was just a duplicate.** Proceed to section 2.

---

## 2. Three structural findings that will repeat in any V2 unless the spec changes

These are properties of the account and the schedule, not of the momentum idea. A V2 that
keeps the same geometry inherits all three.

### 2a. Condition 9 (≥40 trades) was close to unreachable by construction

**33 of 55 rebalances were skipped**, every one of them by the 1.50% risk rule. Nothing else
skipped a single trade — 0 for exposure, 0 for conversion.

The arithmetic: a 2-ATR stop at minimum lot on the JPY crosses costs roughly **$14**, against a
budget of **$14.69** (1.50% of $979). The rule sits almost exactly on top of the cheapest
position the broker will let this account open. As equity fell the budget shrank and the skip
rate rose.

So on a $979 account, **2-ATR stop + minimum lot + monthly rebalancing cannot produce 40 trades
in 5 years** — 60 months is the ceiling before any skipping, and skipping removed 60% of what
remained. This is the frozen rule behaving exactly as written; it is not a defect. But the
trade-count condition and the risk rule are in direct tension and one of them has to give.

**Decision needed:** which. Options are yours — a wider risk budget, a tighter stop, a higher
rebalance frequency, a longer test window, or a lower trade-count bar. I am not recommending
one.

### 2b. The canonical panel has no development period

It begins **2021-08-02**; development ends **2021-07-31**. Zero months exist. Development on
the executable panel was therefore empty in task 003, and will be empty in any V2 using the same
split. Only the long-D1 panel has a development period (140 months, signal-only).

**Decision needed:** whether V2 splits the canonical panel differently, or accepts that
development is D1-only.

### 2c. Two pass conditions can be satisfied without meaning anything

- **Condition 5** ("same return sign") passed because **both** panels were negative. It cannot
  distinguish agreement-on-profit from agreement-on-loss.
- **Condition 12** ("no trade > 25% of net profit") passed **vacuously** — with net profit
  negative there is no profit to concentrate.

Both were correctly reported as PASS because that is what the written conditions say. Flagging
that neither carried information in a failing run, so a V2 that fails the same way would again
score 2 free passes.

**Decision needed:** whether to restate either condition. Purely a specification question.

---

## 3. Standing constraint, unchanged

The executable panel spans **4.99 years**, not 6. Exness serves no dense H1 before 2021-08 —
verified in task 002 with explicit `copy_rates_range()` calls. Broker D1 reaches ~8 years but
cannot be cut to the 17:00 New York session boundary.

---

## Not asked

No V2, no parameter change, no replacement strategy and no repair of V1 is proposed here or
anywhere in the task-003 report. V1 is reported FAILED and left alone, as instructed. This file
raises only the specification-level questions whose answers change what I build next.
