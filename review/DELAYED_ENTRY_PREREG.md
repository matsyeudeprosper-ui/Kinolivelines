# Delayed recovery entry - pre-registered test on untouched data (DRAFT v0.1, 2026-10-10)

**Status: DRAFT - values proposed by Claude for the lead's confirmation; nothing frozen; no live change.**
Executable configuration: `review/entry_study_manifest.json` (sources hashed, data boundaries, quote model,
delays, gap rules, arms, regimes, cost bases). Freezing = a dated FROZEN line here plus the manifest's
`status` set to FROZEN and `frozen_at` filled in the same commit.

## What has NOT been used to choose the candidate
Development used dataset b (closed M1 bars from 2026-08-28 22:54 UTC to the closed-bar cutoff
1791558420 = **2026-10-09 16:07 UTC**) and its ticks. Bars and ticks AFTER that cutoff were not loaded by
any study script; the pinned dataset replaced the harness's sliding window on 2026-10-09 and `bars()` was
not run since. What Claude did see after the cutoff: the live bots' logs, the reference ledger and the
chart (monitoring duties) - not used in any selection step, but stated. The untouched evaluation period
therefore starts at **2026-10-09 16:08 UTC**. There is no earlier untouched period: the second half of
dataset b has been inspected (reported as "later half" in every table) and is development evidence.

## Registered design (to confirm)
* **Horizon:** 42 calendar days from the start (ends **2026-11-20 16:08 UTC**), one evaluation at the end,
  no interim look at arm P&L. Fixed; neither shortened nor extended after inspecting results.
* **Data:** M1 closed bars and bid/ask ticks of BTCUSDm from the std account's terminal, fetched read-only
  by `study/fetch_ticks.py` (daily, appended to `study/ticks_forward/`, per-day hashes in a manifest) and a
  bar pin made at the end with the same `dev_dataset` method. No real orders; the engine is a replay.
* **Arms, regimes, costs, delays, gap rules, pending/exit rules:** exactly the manifest's; package values
  as of the FROZEN line; balances recorded at the FROZEN line.
* **Primary:** Infinity (valere). Supporting: u224016179 (cap3), Special, reference - reported, never a
  replacement for the primary.
* **Nominated cost basis:** $0.35 per 0.02 lot extra drag (bid/ask embedded) - the conservative basis;
  the $0 basis is reported as sensitivity.
* **Adequacy (not a stopping rule):** at least 35 UTC days with ticks and at least 150 baseline trades on
  the primary; otherwise INCONCLUSIVE, no extension.
* **Acceptance on the primary, nominated basis, closed-trade metrics (point values; intervals reported):**
  - PASS: delayed / baseline closed-trade DD ratio <= 0.75 AND delayed net >= baseline net - $5 AND delayed
    net >= half_main net.
  - FAIL: ratio >= 0.90 OR delayed net < baseline net - $15.
  - otherwise INCONCLUSIVE (not a pass).
  The $0 basis must not contradict the PASS (ratio <= 0.90 and net >= baseline - $10) for a PASS to stand.
* **Policy for an inadequate sample:** INCONCLUSIVE; a second, separately registered period may follow;
  no merging of periods after the fact.
* **Reporting:** the full per-arm table (net, closed DD, MTM DD, trades, wins, MAIN/add attribution, risk,
  missed winners, waits, skipped signals, rejects, kills, gap flags), the paired bootstrap as conditional
  uncertainty, event traces, before/after against the development numbers.
* **What a PASS permits:** a proposal for a paper/demo deployment on the reference account's feed - not a
  live sizing change; live deployment needs its own decision.

FROZEN: (not yet)
