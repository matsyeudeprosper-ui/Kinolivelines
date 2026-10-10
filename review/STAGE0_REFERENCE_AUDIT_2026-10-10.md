# Stage 0 - the dedicated demo reference: identity, effective rules, reconciliation (2026-10-10)

From: Claude. To: ChatGPT and Mike. Read-only audit; nothing changed on the demo or elsewhere. No credentials.

## Identity (verified on the VPS, not assumed)
| item | value | how verified |
|---|---|---|
| nest id / login | `u477508138` / 477508138 | `owl_nest_users.json` record: `reference: true`, `dedicated: structure_bos_bot.py u477508138`, `bot_only`, `mode auto`, `trade true`, era start 2026-10-08 15:30 UTC |
| server / type | Exness-MT5Trial9, demo (`trade_mode 0`), balance 989.06 at audit time (started 1000.00) | read-only `account_info()` on its own terminal `C:\NestTerminals\u477508138\terminal64.exe` |
| symbol | BTCUSD (demo), `volume_min 0.01`, `stops_level 0`. Spread: the single quote at audit time read 4.48; the MEASURED distribution over the 43 development days is demo BTCUSD median 7.00 (p90 7.00) versus std BTCUSDm median 10.00 (p90 10.00) - the demo feed is the TIGHTER one over the period; the nest's display `spread_extra 2.5` assumes the opposite (review 16 correction: a spot quote is not a period statistic) | `symbol_info` at audit; `study/ticks_u477508138/` vs `study/ticks/` (5.0M ticks each) |
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
Differences A vs C to carry: feed and spread (measured: demo median 7 vs std median 10 points - the earlier "demo ~2x std" line was a spot quote and is withdrawn), TOUCH entries (enabled on A, absent in C and in C'),
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

## TOUCH reconciliation plan (review 16)
The demo's actual rules include TOUCH continuation entries (tick-level: while flat, awake, bid crosses the last
swing high in an uptrend / low in a downtrend, level unused -> enter with the stop at the swing's opposite
extreme). No TOUCH has fired on the demo in 2 days; that does not bound its effect over 42 days. Plan, in order:
1. Count TOUCH events in the demo's own log going forward (every "TOUCH ENTRY" line) and in the nest ledger
   (entry kind is not in the wealth rows - the bot log is the source); report the share of TOUCH trades weekly.
2. Add TOUCH to the tick engine: at each bar close the harness BARHOOK will also emit the two touch levels and
   stops (hi_v with the span's lowest low; lo_v with the span's highest high, span = kept candles after the
   level's candle with at least one opposite-colour candle - the bot's exact rule); between bar closes the
   engine checks the tick bid against those levels for arms whose package has `touch_entries` true (the
   reference), with the same dedupe (`used_hi/used_lo`), awake, one-position and geometry rules, SNIPER off.
3. Validate: replay the demo package on its own quotes with TOUCH on and compare the engine's entries against
   the demo's actual ledger over the forward period (entry times / directions / stops) before any claim of
   "exact dedicated-demo replication"; until then every demo-based result stays labelled "proxy, no TOUCH".
4. Never change the running demo to make the replay match.
