# Stage 0 - the dedicated demo reference: identity, effective rules, reconciliation (2026-10-10)

From: Claude. To: ChatGPT and Mike. Read-only audit; nothing changed on the demo or elsewhere. No credentials.

## Identity (verified on the VPS, not assumed)
| item | value | how verified |
|---|---|---|
| nest id / login | `u477508138` / 477508138 | `owl_nest_users.json` record: `reference: true`, `dedicated: structure_bos_bot.py u477508138`, `bot_only`, `mode auto`, `trade true`, era start 2026-10-08 15:30 UTC |
| server / type | Exness-MT5Trial9, demo (`trade_mode 0`), balance 989.06 at audit time (started 1000.00) | read-only `account_info()` on its own terminal `C:\NestTerminals\u477508138\terminal64.exe` |
| symbol | BTCUSD (demo), `volume_min 0.01`, `stops_level 0`; quoted spread at audit 4.48 (wider than the real accounts - the nest charges a display `spread_extra 2.5` on its P&L) | `symbol_info` |
| process | PID 17980, started 2026-10-08 11:11:09 local = 16:11 UTC; log banner at 16:11:10 UTC: "BOS-BOT starting on 477508138 balance 1000.00 base 0.02 RR 0.8 serie 2 kill -100000.0 \| paquet reference \| sans frein nervosite \| sans systeme de dette" | process list + `live/bos_bot_u477508138.log` |
| deployed code version | the running process loaded `structure_bos_bot.py` as of commits 17dc925/6702027 (2026-10-08 11:10-11:11 local: the `debt_gate` dial); two later commits (da34ba9 eq_half, dd12461 recov_bullets_only, both 2026-10-09) are NOT in the running process. Both dials are false for the reference package, so behaviour is unaffected; the running binary is nevertheless one revision behind HEAD. | git log vs process start time |
| tick history on its own terminal | available back to the development window start (3.7-5.9k ticks/hour sampled on 2026-08-28, 09-18, 10-08, 10-09); M1 bars current | read-only `copy_ticks_range` probe |

## Effective rules (package `reference` resolved by `owl_package.for_account`)
base_lot 0.02 fixed (`scale_with_balance false`), rr 0.8, k_streak 2, kill_net -100000 (never binds), day_cap none,
`debt_gate false` (no recovery continuation restriction), `adds_on false` / max_extra 0, `jar false`, `nervosity false`,
`movement true`, `internal_entries false`, `risk_fit_pct 0`, `max_risk_pct 0.10` (of the current balance),
`min_balance 20`, `eq_half false`, `recov_bullets_only false`, `touch_entries` - see below.

## "All trades, nervosity brake only"? - the precise list of SELECTION gates still active on the demo
| gate | active on the demo | evidence |
|---|---|---|
| awake window (a trend flip within the last 7200 s) | YES | code constant `AWAKE_WIN`; harness mirror |
| extreme-storm wait (`nervosity >= 1.85x`: "marche tres rapide - exception, personne ne trade") | YES | 4 refusals in the demo log (1.94x, 2.20x, 2.06x, ...) |
| ordinary nervosity brake (`nervosity > 1.0`) | NO ("sans frein nervosite") | package `nervosity false`, banner |
| movement gate (no structure mark in 2 h = asleep) | YES | package `movement true` |
| used-level deduplication (one entry per broken level) | YES | code; harness mirror |
| one open position at a time | YES | code (`not my_positions()`) |
| debt continuation restriction (FLIP + 1 continuation while in debt) | NO | `debt_gate false`, banner "sans systeme de dette" |
| internal-structure entries | NO (notes logged "pas pris: entrees internes desactivees") | package, log |
| daily profit cap / kill line / recovery adds / jar | NO / never / NO / NO | package |
| **TOUCH continuation entries** (`TOUCH_ENTRIES = True` by default; only the `labo` and `kino` variants switch it off) | **YES, enabled** - a tick-level entry when the bid crosses the last swing high/low while a position is flat and the level is unused; none has fired on the demo in its 2 days (0 "TOUCH" lines, 16 FLIP-BOS/BOS entries) | code lines 104/1596-1636, log count |
| execution constraints (not selection): min balance $20, 10% ceiling on the final lot, `S_MIN_DIST` 10 pts, broker geometry, market orders | YES | code |
So "nervosity brake only" is not accurate: the demo keeps the awake, extreme-storm, movement, dedupe and
one-position gates and has TOUCH entries enabled. The ordinary nervosity brake and every account-money brake are off.

## Reconciliation of the two reference definitions
| source | what it is | status |
|---|---|---|
| **A. dedicated demo ledger** `live/lab/wealth/u477508138.json` (nest worker; closed deals `[t, pnl, lot, dir, minutes]`) | the demo's ACTUAL closed trades: 18 closed from 2026-10-08 19:23 to 2026-10-09 22:38 UTC, sum -$10.94 at $0.02 lot; the nest's `spread_extra 2.5` is a DISPLAY charge in the chart, the ledger P&L is the broker's | **authority for forward Compte observations** (Stage 2 forward) |
| B. Infinity virtual recorder `live/lab/reference_ledger_infinity.jsonl` (rec-3) | an independent virtual strategy on Infinity's Real27 BTCUSD quotes, fixed 0.02, no account-money brakes, awake/storm/movement kept, NO touch entries, tick-level barrier certification | separate research source, labelled; never spliced with A |
| C. harness / engine "reference_uncapped" regime | the demo's PACKAGE replayed on the std account's BTCUSDm bars/ticks (development) | historical PROXY: different feed (std BTCUSDm vs demo BTCUSD), different spread, no TOUCH path, bar-close signal cadence |
Differences A vs C to carry: feed and spread (demo spread ~2x the std's), TOUCH entries (enabled on A, absent in C),
the demo's `max_risk_pct 0.10` of its $1000 (never binds). For historical Stage-2 experiments the demo's OWN tick
history is being fetched now (`fetch_ticks.py --uid u477508138` -> `study/ticks_u477508138/`, read-only) so the
reference strategy can be replayed on the demo's quotes - still a labelled proxy for TOUCH (not modelled) and for
the bar-cadence signals; the feed/cost difference between the std replay and the demo replay will be quantified.
No follower's own Compte curve replaces A; the recorder never creates orders; the demo keeps trading during any
follower pause (it has no pause logic at all).

## Stage-2 source table (to be filled with every Compte result)
| result | reference source used | notes |
|---|---|---|
| historical Stage 2 | C' = the demo package replayed on the demo's own quotes (proxy; TOUCH not modelled) | plus C on the std feed as a transfer check |
| forward Stage 2 | A (demo ledger, closed outcomes strictly before signal eligibility) | B reported apart |
