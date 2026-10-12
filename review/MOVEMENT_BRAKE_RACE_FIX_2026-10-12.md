# Movement brake race - live fix (owner "do it", 2026-10-12)

## What happened
2026-10-12 04:43:03 UTC, the same FLIP-BOS BUY (price 83 936.62, beyond the pullback chart's last BOS 83 172.12)
reached all seven robots. Six refused "aucun grand mouvement depuis 2 h"; Valère (u224016179, package valere_cap3)
entered (0.02 -> 0.01 lot by the 3 % risk cap, stop 83 388.85, risk $5.48). Every account has the movement brake ON.

Cause: the brake read `moves_2h` from owl_chart_btc.json, which the feed rewrites every few seconds. The six read
the file at 03.45-03.53 s (moves_2h = 0); Valère read it at 03.60 s, after the feed had rewritten it with the new
flip mark counted (the feed's counter uses the forming bar as "now", so the just-closed signal bar falls inside its
window) -> moves_2h = 1 -> allowed. The feed's own comment already noted the brake "losing a race with this file".

## Fix (structure_bos_bot.py, owl_manual_trader.py)
`weather_gate(..., sig_t=None)`: when the signal candle's time is given, big moves are counted from the feed's
`marks` list strictly before it: `sig_t - 7200 <= mark < sig_t`. That is the window the brake was measured with
(replay), and every account now gets the same answer whatever moment it reads the file. The bot's entry path and its
nervosity-shadow counterfactual pass `sig_t=bt`; the manual desk's main-structure gate and its signal publication
pass `sig_t=bt`. Other callers (review scripts) keep the old counter behaviour. The internal-structure half
(`int_brk_1h`) is unchanged.

## Verification
Reproduced 04:43 with the current chart file (calm nervosity forced to isolate the movement half): the only mark in
[02:42, 04:42] is the 04:42 flip itself. Old rule: file seen with the flip -> allowed, before it -> refused (the race).
New rule with sig_t = 04:42: refused for both files. A signal 30 min after a real earlier move: allowed.
Preflight OK; robots restarted, one process per account (8); manual desk restarted (1); no new errors; Valère's open
trade untouched and still managed.

## Not affected
SCANNER-F2 loads its own frozen engine copy (engine_f2), so this live edit does not reach it. The frozen entry study
bundle is unchanged. Valère's trade from 04:43 stays open (no intervention).
