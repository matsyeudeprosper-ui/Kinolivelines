# Manual / Auto on the live account 223995441 (2026-09-17)

Owner: "the account ending 441 is in manual trading while the setting says
mettre le bot en pause. Make it right — en pause must mean manual and allow
option to switch it on. When switched on it must resume auto trading
internal and main structure according to all the approved rules. Only this
account is allowed to desactive the autotrading."

## What "pause" meant before
Nothing coherent. The desk (`owl_manual_trader.py bos`) never auto-traded, so
it never read a pause file at all. The switch wrote a file no process on that
account consulted, while the label said "mettre le robot en pause" about a
robot that was not running.

## Now
- **MANUAL** (the switch on) = the desk takes no entry of its own. You trade
  from the chart. This is the state the account was already in, now named
  correctly.
- **AUTO** (the switch off) = the desk enters by itself, on the small
  structure and the main one.
- **The default with no file is MANUAL**, on both the desk and the app,
  because the safe default on a real account is to do nothing.
- **`PAUSE_ALLOWED = ("bos",)`** — only this account can switch, enforced on
  the write route as well as in the UI. Every other account, the master
  included, now sees a padlock.

## What AUTO actually does
On each closed M1 candle, and only if not manual:

1. **Small structure** — the protected level moving means a break just
   confirmed. Requires the direction to match the main trend.
2. **Main structure** — the engine's own signal, as the frozen bot has it.

Both must pass the rules that survived being measured two ways:

| rule | small structure | main structure |
|---|---|---|
| a movement in the last hour | `int_brk_1h >= 1` | `moves_2h >= 1` |
| nervosity at or below its daily norm | ≤ 1.0× | ≤ 1.0× |

And then every existing rail still applies, because the entry goes through
`execute()`: minimum stop distance, the 10% single-trade risk cap, no entry
with a position open or an order armed, the war-chest lot sizing, the kill
line.

## Verified
- `manual_mode()` returns True with `paused:true`, False with `paused:false`,
  and **True with no file at all**.
- `gates()` refuses both routes right now with the correct reasons.
- The AUTO branch was live for 95 seconds with both gates shut and correctly
  did nothing; the branch was then confirmed by direct test rather than by
  its silence.
- Switch state across all eight accounts: only `bos` is usable, and it reads
  MANUEL.

## Stated plainly in the confirmation dialog
Turning AUTO on shows: the robot will enter alone, on both structures, only
when both brakes are green — and that these rules were measured to limit
losses, not to produce gains. That sentence is in the dialog because it is
the honest expectation from `review/RULE_STACK.md`.
