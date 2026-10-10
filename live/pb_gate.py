"""The pullback-chart gate - ONE decision function shared by the live bot
(structure_bos_bot.enter) and the replay (study/tick_engine_pbgate.py), so the
two can never drift apart.

Owner 2026-10-10 (evening), the OFFICIAL rule, trend following:
  * bullish pullback structure  -> filtered-silence BUY BOS signals only, and
    only ABOVE the pullback chart's last BOS;
  * bearish pullback structure  -> SELL BOS signals only, and only BELOW it;
  * price on the wrong side of that last BOS = continuation entries PAUSED
    until price reclaims the level or the pullback structure reverses;
  * unknown pullback trend or missing last BOS = PAUSED too (no permissive
    fallback); entries resume when a valid structure is available.
The gate is stateless: it is asked at every signal with the current state.

Earlier modes kept for the replay (and for the record):
  'choch'  - the 10-10 morning rule: direction of the pullback trend, a
             pending CHoCH in the trade's direction beyond its level excepted
  'strict' - direction of the pullback trend, no exception
  'off'    - no gate (the reference account)
"""


def pb_gate(mode, d, px, trend, choch=0, choch_lvl=None, last_bos=None):
    """-> (ok, code).  d = +1 buy / -1 sell; px = the entry price (ask for a buy,
    bid for a sell); trend / choch / choch_lvl / last_bos = the pullback chart's
    trend, pending CHoCH direction (0 = none), its level, and its last BOS price."""
    if mode in (None, False, "off", "none"):
        return True, "off"
    if trend not in (1, -1):
        # owner 2026-10-10 (evening, via GPT): under the official rule an UNKNOWN
        # pullback trend pauses entries - no permissive fallback; the older
        # modes keep their old behaviour for the replay record
        return (False, "no_structure") if mode == "trend" else (True, "no_structure")
    if d != trend:
        if (mode == "choch" and choch == d and choch_lvl is not None and px is not None
                and d * (px - choch_lvl) > 0):
            return True, "choch_exception"
        return False, "against_structure"
    if mode == "trend":
        if last_bos is None or px is None:
            return False, "no_last_bos"      # missing last BOS (or no quote) = pause, same rule
        if d * (px - last_bos) <= 0:
            return False, "paused_wrong_side"
        return True, "beyond_last_bos"
    return True, "with_structure"
