# Canonical reference ledger - schema (draft for review, 2026-10-09)

Purpose: the independent, fixed-size, cost-adjusted record of every eligible
strategy opportunity, produced VIRTUALLY on the control account's own feed.
Never sends an order. Append-only. One file per control feed:
`live/lab/reference_ledger_<control_uid>.jsonl` (one JSON object per line).

## Runner
`live/bos_paper_variant.py` already trades a lab config virtually on a feed
with the same engine, awake window, storm and movement gates, one position at
a time, entries on the closed candle, exits judged on live ticks and swept on
the closed bar. The reference is a twin with the control package's STRATEGY
dials and no recovery (`n_cont` unlimited, no bullets, no jar, no caps, fixed
lot), attached READ-ONLY to the control account's terminal (Real30/Real27), so
the prices are the control's production feed. Proposed id: `reference_<uid>`.

## Row (one per opportunity, written when it CLOSES; blocked ones written at signal time)
| field | type | meaning |
|---|---|---|
| `event_id` | str | `<feed>:<signal_bar_time>:<dir>:<kind>` - stable, causal |
| `strategy_version` | str | git short hash of structure_bos_bot.py at runner start |
| `feed` | str | server + terminal login the prices came from |
| `symbol`, `contract_size`, `volume_step`, `volume_min` | | from symbol_info at runner start, re-read daily |
| `dir` | int | 1 buy / -1 sell |
| `kind` | str | FLIP-BOS / BOS / TOUCH / INT |
| `t_signal` | int | closed-bar time the signal was confirmed on |
| `t_fill_earliest` | float | first tick after the signal bar closed |
| `t_fill`, `t_close` | float | virtual fill / close time (tick clock) |
| `entry`, `sl`, `tp` | float | prices; entry = executable ask (buy) / bid (sell) at fill |
| `lot` | float | fixed reference volume (0.02) |
| `risk_usd` | float | planned stop risk at entry: dist x lot x contract_size |
| `spread_at_fill` | float | ask - bid at fill |
| `cost_usd` | float | explicit cost charged: commission schedule + swap (0 on demo/Pro BTC unless the symbol says otherwise), recorded per row, never a global constant |
| `pnl_usd` | float | net main result, full precision |
| `pnl_r` | float | pnl_usd / risk_usd (diagnostic) |
| `exit_why` | str | sl / tp / sl-bar / tp-bar (bar = swept on the closed bar; ambiguous when both sides hit in one bar -> `ambiguous` with `pnl_lo`/`pnl_hi` bounds) |
| `state_before` | obj | controller state (version, trend, choch, origin) BEFORE entry |
| `eligible` | bool | false + `reason` when blocked (storm, movement, one-position, min-dist) |
| `valid` | bool | false + `reason` on a feed/history error (never an empty neutral row) |

## Conventions
* One reference position at a time: an opportunity arriving while one is
  open is written with `eligible: false, reason: "position_open"`.
* The reference keeps running through real-account pauses, caps, kill lines
  and size changes - it has none of them.
* Costs are what the symbol reports, per row. Demo-vs-live spread
  differences are NOT patched in (that is what makes the Trial9 demo
  account secondary; the control-feed twin needs no spread_extra).
* Buy and sell rows live in the same file; the directional controller
  simply filters by `dir`.

## Open points for the lead
1. TOUCH and INT entries: include as rows with `kind`, or exclude from the
   reference curve (the live packages have INT off)? Proposal: include,
   flagged, and build the primary curve from FLIP-BOS + BOS only.
2. Entry price: executable ask/bid at the first tick after the bar close
   (what the twin does) vs the bar close itself (what the harness does).
   Proposal: tick, and log the gap to the bar close per row.
