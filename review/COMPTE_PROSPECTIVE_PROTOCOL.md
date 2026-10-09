# Compte directional sizing - prospective shadow protocol

**Status: DRAFT v0 (2026-10-09). Not frozen.** Freeze = a dated "FROZEN" line
below, after the lead's reply and the power numbers from
`study/compte_policies_dev_replay_v2.*`. Nothing here changes a live bot.

## Candidates (fixed now, never reselected)
| arm | definition | role |
|---|---|---|
| baseline | the account's frozen package, no allocation | control path |
| **directional MAIN+ADDS** | at entry, if the trade's OWN side (buy curve for a buy, sell curve for a sell) of the reference Compte is in a downtrend with no CHoCH up pending: main lot x0.5 (floored at the broker step) and the permitted add budget x0.5 (count-based, achieved cut reported); else x1; never above baseline; multiplier frozen per opportunity at entry | **primary** (as nominated in the brief) |
| directional MAIN-only | same trigger, main lot only | exploratory attribution arm; no priority, no inherited evidence |
| exposure control | a periodic schedule (every k-th eligible entry at x0.5, k fixed from development so planned exposure matches the primary; ALL k phases run) | matched-exposure control |
| global | parked | reported once for the record, not evaluated |

## State source
`lab/reference_ledger_infinity.jsonl` (rec-3): the independent fixed-size
reference on Infinity's live feed. States = compte-ctl-2 (global / buy /
sell) fed with resolved closes STRICTLY before the entry; an unresolved
close latches the state invalid (no sizing change while invalid - the
baseline multiplier applies and the opportunity is tagged `state_invalid`).
Signals arriving while a reference position is open are recorded as
`blocked: position_open` so every path can apply its own eligibility.

## Paths (each complete and independent)
Every arm is simulated as a COMPLETE package path on the same opportunity
stream with its OWN debt, jar, loss streak, eligibility, caps, balance and
position lifecycle (lab/harness simulate() with the package's own config and
the EQHOOK/EQ_ADDS policy). No size-undo on real P&L: real fills of the live
accounts are observations for matched trades only, reported beside the
shadow paths as a fill-realism check, never as the counterfactual.
Capped (valere, valere_cap3, special_10) and uncapped (reference) regimes
are evaluated apart; the shared opportunity stream counts once.

## Data and timing
* Start: the first bar after the FROZEN line's timestamp. Nothing before it
  is prospective; everything inspected before is development.
* Pairing: common calendar time over the complete signal/event stream.
* Horizon: fixed at freeze - [N] eligible opportunities on the reference
  stream (proposed 600) or [D] calendar days, whichever first. ONE
  evaluation at the horizon; no interim PASS checks. Insufficient evidence
  at the horizon = inconclusive (a new, separately registered horizon may
  follow); never "the family is closed".
* Costs: results are gross after spread, before execution drag; the
  reference's commission is unknown -> `net_cost` validity false. Net
  evaluation requires a verified cost model frozen here (currently: NOT
  available - gross-state research only). Drag sensitivity reported at
  $0 and $0.35 per 0.02 lot.
* Curve basis: B (reference rebuilt under the same cost model) is the
  evaluation basis; A (spread-only reference, cost-stressed policy) is a
  sensitivity. Fixed now.

## Metrics (full path, every arm)
net; planned exposure (main + contingent add budget) and committed exposure
(main + fired adds); three drawdowns - daily-sampled realised, close-to-close
realised, marked-to-market bounds (adverse / close); tail (sum of 5 worst,
p95 loss); trade count; the later calendar half of the horizon.

## Decision rule - RISK label only (profit label not resolvable, see power)
PASS if, on the primary vs baseline paired paths at the horizon:
1. candidate maximum drawdown (close-to-close realised, primary metric;
   MTM-adverse reported) / baseline maximum drawdown <= 0.80, with the
   block-bootstrap 90% interval of the ratio entirely <= 0.80... [to be set
   from the power calculation: the interval requirement may be relaxed to
   "point <= 0.80 and interval upper bound <= 1.00" if the detectable ratio
   at the horizon is too wide - decided at freeze, not after];
2. paired net degradation <= 0.05 baseline-risk units per eligible
   opportunity (baseline-risk unit = the baseline's mean planned main stop
   risk), block-bootstrap 90% interval respecting the bound;
3. the primary beats at least 75% of the exposure-control phases and 75% of
   the 20 block-shifted schedules on the drawdown ratio.
Blocks: 5 calendar days nominated (~20 opportunities); 3 and 10 days shown
as sensitivities, never used to pick the result.
Otherwise: inconclusive (interval straddles) or FAIL (point estimate the
wrong way). The exploratory arm gets the same table and no decision.

## Power (filled from replay v2 before freezing)
* per-day paired SD of (candidate - baseline): [sd]
* detectable mean daily difference at 30 / 60 / 120 days (80%, one-sided
  5%): [values]  -> profit label: [resolvable / not]
* drawdown ratio CI90 width on the development paths at block 5 / 3 / 10:
  [values] -> feasibility of gate 1 at the horizon: [assessment]

## Prohibited
Parameter sweeps on multiplier, window, CHoCH definition, k or block length;
reselecting the arm after seeing prospective results; any live rollout.

FROZEN: (not yet)
