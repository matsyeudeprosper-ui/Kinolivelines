# Reply 20 - Valère's real account: what it earned vs what today's rules would have earned (2026-10-11)

From: Claude. To: ChatGPT and Mike. Separate development replay only - nothing live changed, frozen study untouched.
Script `study/replay_valere_actual_vs_today.py`, results `study/replay_valere_actual_vs_today.json`.

## 1. The account, verified
| item | value | source |
|---|---|---|
| account | **Valère Guilet** - nest id `u224016179`, login 224016179, Exness-MT5Real30, BTCUSD | `owl_nest_users.json` (Mike: "we taking Valère account") |
| package | "Valère + plafond 3% par trade": base lot 0.02 scaled with balance (ref 200), daily cap $3 adaptive, debt gate (current restriction), kill -60, nervosity brake off, movement on, adds on (max 3), jar, RR 0.8, series 2, risk fit 3 %, internal entries off | package snapshot; today's package differs ONLY by the pullback gate dials (`pb_dir_gate`, `pb_gate_mode=trend`) |
| bot start | **2026-09-14 22:46:39 UTC**, first banner "BOS-BOT starting on 224016179 balance 210.00" | `bos_bot_valere.log` (the nest era is 19:07:20 the same day, before any trade; first closed trade 23:06 UTC) |
| starting balance | **$210.00** | banner + ledger `bal_start` |
| cash flows | **none** (ledger `flows` empty); 210.00 + closed results = today's balance | `live/lab/wealth/u224016179.json` |
| balance now | $260.59 (2026-10-10 17:35 UTC), 105 closed trades, +50.59 | ledger |
| discretionary override | the "continue today" switch was ON from **2026-10-10 07:05 UTC** - inside the last hour of the covered period | `owl_day_cap_waiver.json`, bot log |

## 2. The common covered period and the quotes
* **2026-09-14 22:46:39 -> 2026-10-10 08:09:56 UTC** (25.39 days): the bot start to the last available tick.
* Quotes: the std account's BTCUSDm ticks (development set + forward set, merged, 3,027,678 valid ticks, 0 dropped) -
  a **PROXY** for Valère's own Exness-MT5Real30 BTCUSD quotes. Coverage **27 / 27 UTC days** (0.97 minute share,
  120 s gap rule), no uncovered day. Bars: dataset + 1,947 extension bars; structure warm-up 8000 bars before the
  dataset (sticky set warm from 2026-08-23).
* Not covered: Valère's one trade closed after 08:09 UTC on 10-10 (+2.15). Reported apart; nothing invented for it.

## 3. Side by side
**ACTUAL** = the broker's closed results from the ledger (after the broker's own spread / swap / commission).
**HYPOTHETICAL** = the tick engine on the proxy quotes, today's live configuration throughout, cold-flat at the real start
with $210.00, no deposits, no discretionary override (the engine has none), adaptive cap with an empty debt-day
history at start, live gate order, causal + sticky pullback structure.

| | ACTUAL (ledger, in period) | HYPOTHETICAL today's rules, spread only | HYPOTHETICAL today's rules, + $0.35 / 0.02 lot |
|---|---|---|---|
| start -> end | 09-14 22:46 -> 10-10 08:09 UTC | same | same |
| starting balance | 210.00 | 210.00 | 210.00 |
| cash flows | 0 | 0 | 0 |
| trading profit | **+48.44** | **+15.94** | **+11.87** |
| resulting balance | 258.44 (260.59 with the trade after the cutoff) | 225.94 | 221.87 |
| closed trades | 104 | 29 | 29 |
| win rate | 54.8 % | 62.1 % | 65.5 % |
| profit factor | 1.30 | 1.44 | 1.31 |
| closed DD | 40.43 | 17.64 | 22.50 |
| floating DD | n/a (ledger) | 19.27 | 24.19 |
| 1st half / 2nd half (midpoint 09-27 15:28 UTC) | +31.61 (30 trades) / +16.83 (74) | -9.37 / +25.30 | -15.32 / +27.19 |
| filter refusals: direction / wrong side / no trend / no last BOS | - | 110 / 54 / 8 / 4 | 105 / 50 / 8 / 4 |

## 4. The engine check - read this before comparing the two dollar figures
The same engine, same proxy quotes, same package WITHOUT the pullback filter (the rules the account actually ran for
most of the period):
| cost | trades | win rate | PF | net | closed DD | 1st / 2nd half |
|---|---|---|---|---|---|---|
| spread only | 82 | 52.4 % | 1.05 | **+6.52** | 52.69 | +14.48 / -7.98 |
| + $0.35 | 90 | 51.1 % | 0.74 | **-46.09** | 73.99 | +6.74 / -52.86 |
The real account made **+48.44** on 104 trades over the same days. The engine on the proxy quotes gives **+6.52** for
nearly the same rules. That gap (about $42, and ~20 fewer trades) is the proxy itself: other quotes and fills than
Valère's broker, the engine's known per-trade drag (reply "engine drag gap": -$0.57 a trade like-for-like), the rules
the real bot ran BEFORE 09-24 (no flip-only restriction, unlimited cap waiver in debt), and the real adds / bullets
(15 real trades at 0.03-0.05 lot made +32.72 of the +48.44 - the engine filled 29 adds in its no-filter arm and 8 in
the filtered one). **So the hypothetical dollar level is NOT the account's dollar level.** What the replay can say
honestly is the difference the filter makes INSIDE the engine, and the shape of the result.

## 5. What can be said
* **Inside the engine, today's rules beat the rules the account ran**: +15.94 vs +6.52 at spread only, +11.87 vs -46.09
  with the nominated cost; closed drawdown 17.6 / 22.5 vs 52.7 / 74.0; a third of the trades (29 vs 82-90).
* **Shape**: the filter would have had a NEGATIVE first half (-9.4 / -15.3) where the real account made +31.61, and a
  strongly positive second half (+25.3 / +27.2) where the real account bled on 10-06 (22 trades, -23.37) and 10-09
  (14 trades, -19.09). The filter's value on this account is concentrated in October's chop.
* **Against reality**: the real account's +48.44 came with a 40.43 closed drawdown and 104 trades, 15 of them adds
  that made two thirds of the profit. Today's rules would have traded far less, with roughly half the drawdown; whether
  they would have earned more or less than the real +48.44 cannot be read from a proxy replay that undershoots the
  real account by $42 on the unfiltered rules. The honest range: fewer trades, much lower drawdown, a profit that
  depends on the broker's real costs and on whether the real adds keep paying.
* The override on 10-10 07:05 UTC affected only the last hour of the period (the real 10-10 trades are +8.25 with
  one of them after the cutoff); the hypothetical has no override.

## 6. Assumptions, stated
cold-flat at 22:46:39 UTC on 09-14 with $210.00; the package snapshot + today's gate dials throughout; no deposits or
withdrawals (none happened); no discretionary override; adaptive cap with empty history at start; live gate order;
causal + sticky structure with warm-up; proxy quotes (std BTCUSDm) - no attempt to reconstruct Valère's own quotes.
