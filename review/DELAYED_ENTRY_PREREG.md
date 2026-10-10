# Delayed recovery entry - pre-registered prospective replication (DRAFT v0.2, 2026-10-10, after review 15)

**Status: DRAFT - for the lead's confirmation; nothing frozen; no live change.** Executable configuration:
`review/entry_study_manifest.json`. Freezing = a dated FROZEN line here, the manifest's `status` FROZEN and
`frozen_at` filled, the scored start/end epochs and the accounts' balances recorded, all in ONE commit.
All human-readable dates below are derived from epochs (`study/entry_study_manifest.py` prints them);
UTC first, Paris in brackets.

## Prior exposure, stated honestly (replaces v0.1's "never loaded")
Development used dataset b: closed M1 bars from epoch 1787957640 (2026-08-28 22:54 UTC) to the closed-bar
cutoff epoch **1791558420 = 2026-10-09 15:07 UTC** (17:07 Paris), and ticks of the same days. The first
per-setup tick diagnostic (`delayed_entry_ticks.py` as of commit 654222c) loaded whole daily files and could
resolve trades with quotes AFTER the cutoff (up to 1791576353017 ms = 2026-10-09 20:05 UTC); review 13 flagged
it and the corrected version clips to the cutoff. The engine and every later script clip to the cutoff. So:
quotes between 15:07 and 20:05 UTC on 2026-10-09 were loaded by one development script; nothing after
2026-10-09 20:05 UTC has been loaded by any study script. Monitoring (live logs, ledger, chart) continues
and is not used for selection. **No pre-freeze period is a holdout.** The scored period starts strictly
AFTER the dated freeze.

## Scored period
* **Start:** the first closed-bar boundary (next full UTC minute) after the FROZEN commit's timestamp -
  recorded as an epoch in the manifest at freeze (`scored_start`).
* **End:** `scored_start + 42 x 86400` seconds, recorded in the same commit (`scored_end`). One evaluation at
  the end; the window is neither shortened nor extended after inspecting anything.
* Data: BTCUSDm M1 closed bars and bid/ask ticks from the std account's terminal, collected read-only daily
  (`fetch_ticks.py --forward`, per-day hashes); bars pinned at the end with the `dev_dataset` method over
  [scored_start - warm-up, scored_end]. No real orders; the engine is a replay.

## Initialization (same convention for every arm)
* Cold-flat at `scored_start`: realised run 0, debt 0, jar 0, streak 0, no continuation allowance, no pending
  setup, no position; balance = each account's balance read at the FROZEN commit (recorded in the manifest);
  day roll / scaling as the package says, first roll at the first scored quote.
* Structural warm-up: the harness engine is fed bars from `scored_start - 7 days` (structure, flips, nervosity
  windows need history); signals before `scored_start` are NOT traded; the first tradeable signal is the first
  bar closing at or after `scored_start`.
* First scored quote = first valid tick >= `scored_start` x 1000 ms; last = last valid tick < `scored_end` x 1000.
  The incoming gap of the first scored quote is measured from `scored_start`.

## Coverage and resolution rules (certification, not a trade-excluded subset)
* Valid-quote coverage per UTC day = share of 1-minute buckets inside the broker's trading session with at
  least one valid tick (bid > 0, ask >= bid, finite). A day is COVERED when that share is >= 0.97 and its
  largest gap is <= 120 s. Adequacy: >= 36 of the 42 days covered, else INCONCLUSIVE.
* Gaps > 30 s on a pending / open path flag the trade (count, largest gap). Policy: the account path is
  never reconstructed from a subset; if flagged trades exceed 3% of the primary's trades, or any flagged
  trade contributes to the primary's maximum drawdown, the drawdown metrics are reported as UNCERTIFIED and
  the decision is INCONCLUSIVE.
* Open / pending exposure at `scored_end` is marked at the last scored quote and reported; unresolved outcomes
  are counted, never dropped.

## Arms, regimes, costs
Exactly the manifest's: baseline / delayed / half_main; primary Infinity; supporting u224016179, Special,
reference (reported, never replacements); quote model, 1 s + 1 s delays, gap rules, pending/exit rules frozen;
nominated cost basis $0.35 per 0.02 lot extra drag (bid/ask embedded); $0 reported as sensitivity.

## Two separate checkpoints (declared before any scored data are read)
1. **Risk-improvement replication checkpoint** (the development pattern repeats?): on the primary, nominated
   basis, closed-trade metrics: delayed / baseline DD ratio <= 0.75 AND delayed net >= baseline net - $5
   AND delayed net >= half_main net. Meeting it permits a proposal of a PAPER/DEMO comparison only. Failing
   it (ratio >= 0.90 OR delayed net < baseline - $15) closes the candidate. Otherwise inconclusive.
2. **Profitable-edge checkpoint** (is it a trading edge?): candidate ABSOLUTE net after the nominated costs
   > 0 on the primary AND the paired block-bootstrap 90% interval of (delayed - baseline) net excludes zero
   AND the DD-ratio 90% interval lies entirely below 1.0. This is the only checkpoint that may be called
   "edge"; it is not expected to be reachable in 42 days and an inconclusive result is NOT a pass.
Reported apart: absolute and relative net, closed and MTM drawdown, coverage, conditional uncertainty
(block bootstrap, labelled), per-arm counts, event traces. Neither checkpoint changes anything live.

## Isolation and drift
The replication runs the frozen copy under `study/frozen_entry_study/` (engine, stats, package mapping,
dataset pin, harness, bot engine) whose hashes are in the manifest; the runner asserts them and aborts on
drift. Development work on the entry matrix and Compte experiments continues in the live `study/` files and
cannot touch the frozen copy.

FROZEN: (not yet)

## FROZEN - 2026-10-10 17:13:44 UTC (commit 7702c19)
Scored window 2026-10-10 17:20:00 -> 2026-11-21 17:20:00 UTC (42 days). Balances at the freeze: infinity 171.65,
u224016179 258.44, bos 350.11, reference_uncapped 993.00. Arms: baseline (earlier package snapshot, NOT the live
configuration), recovery-only delayed, half_main, and the selected challenger delay_always | all_bos | cap_on (review 17),
plus the engine-identity cell. Rules above unchanged; the verification of the bundle is in
review/RESEARCH_REPLY_17_2026-10-10.md and study/frozen_entry_study/frozen_fixture_verify.json.
