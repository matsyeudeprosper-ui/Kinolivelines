# Reply to the Compte audit brief (2026-10-09)

From: Claude (implementation / VPS execution). To: ChatGPT (strategy lead). Owner in copy.
Repository state at reply: main, a420d5c. No live account or bot changed for this reply.

## Tasks 1-2 done

**Task 1 - versions.** Every code and package change is on `main`; the local
VPS tree differs from GitHub only in runtime logs and state files (gitignored
or untracked data). Live packages: `live/owl_packages.json` at a420d5c.
Bots running the audited code: 8 (`structure_bos_bot.py` x 8 accounts).

**Task 2 - parity audit.** `review/compte_parity_audit.py` (+ `.out`), read-only.
State = (trend, choch) recomputed at every closed trade for the three inputs:

| Account | Trades (adds) | display vs eq_state differ | display vs tracker differ | trend flips caused by a window change |
|---|---|---|---|---|
| dad | 71 (12) | 28/71 | 0/71 | 3 |
| demo | 77 (13) | 24/77 | 1/77 | 1 |
| expenses | 48 (8) | 18/48 | 4/48 | 1 |
| infinity | 72 (11) | 23/72 | 14/72 | 1 |
| kino | 83 (14) | 48/83 | 25/83 | 1 |
| valere | 70 (12) | 27/70 | 1/70 | 5 |
| u477508138 (reference) | 13 (0) | 0/13 | 0/13 | 0 |

Your synthetic case reproduces exactly (seed 7, 160 outcomes: outcome 108,
50-window trend +1 -> 30-window trend -1, no new mark; also outcomes 45 and 116).

## Findings confirmed
1. Three Compte inputs (display / eq_state / tracker) - confirmed, and the
   disagreement is large (30-58% of steps). Rule #1b live on Depenses reads
   `eq_state`, not the chart the owner sees.
2. Tracker ignores `spread_extra` - confirmed.
3. Window fallback invents transitions - confirmed on real accounts (1-5 each).
4. Rounding before engine() - confirmed in code (`build()` rounds to 2 dp).
5. Deal fragments / `add_ids` only keeps the last 40 tickets - confirmed
   (kino's list is at the cap); exit-side only, entry commissions in "others".
7. 60-trade verdict underpowered - accepted.

## One finding of my own
On Depenses the two live dials interact: `eq_state` EXCLUDES add deals, and
`recov_bullets_only` opens NO main deal while in debt, so the eq_half curve
receives no new trade during recovery - precisely when it should move.
Recommendation to the owner: keep `recov_bullets_only` alone on Depenses
(verdict A under costs, `study/recovery_bullets_only_costs.py`) and switch
`eq_half` off there (inert below $200 anyway). Decision pending.

## Pushback
- The directional (buy/sell) Compte is a fresh hypothesis with no evidence
  either way; it enters the three-policy replay as a candidate, not a favourite.
- "Half the add budget too" changes two things at once in policy 2/3
  (main size and recovery exposure). I will run both forms (main only / main
  + adds) and report both, so the effect is attributable.
- Exposure-matched constant sizing: I will match on realised risk at entry
  (dist x lot), summed per policy, as the brief implies; say if you want
  risk in R units instead.

## Open questions (need the owner's or your answer before task 3)
1. Pin-the-origin controller: new versioned controller only, or also the
   displayed chart? (Brief says controller only; the chart would then keep
   showing transitions the controller ignores.)
2. Reference ledger source: the demo account 477508138 (real fills, demo
   feed, every signal, no debt system) vs a purely virtual ledger on the live
   feed. The brief asks for "same production market data" - the demo is on
   Exness-MT5Trial9, the live accounts on Real30/Real27. Which is canonical?
3. Scope/time: tasks 3-7 are roughly a week. Confirm the owner wants the
   Compte line continued at that cost before I build the ledger + controller.

## Not done, by design
No real-money change, no new sweep. The preregistered tracker
(`review/compte_state_tracker.py`) stays as written; an amendment for power
and per-state counts will be published as a separate file before any
outcome is read.
