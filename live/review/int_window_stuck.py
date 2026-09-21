"""How often does the internal window find nothing, and would a shorter
fallback window fix it?

Owner 2026-09-21: "why no internal structure yet, I can see lower lows and
higher highs now already inside that range."

Diagnosis on the live feed: after a one-way run the engine's references sit
at the two ENDS of that run - lo_v at the window's first candle, hi_v at the
top - so nothing that happens between them can confirm a dot. The window was
56 candles and every INT_WINDOWS entry (200/300/400/550) takes all 56, so
the adaptive search had nothing shorter to fall back to.

This walks history, rebuilds the real internal pool at each sample (anchored
on the main protected dot, same as owl_chart_feed) and compares:
    NOW       INT_WINDOWS as shipped
    FALLBACK  the same list with shorter tails appended

Appending is safe by construction: the loop breaks on the FIRST window that
finds a direction, so an existing success is never altered - a fallback can
only turn "nothing" into "something".

    python review/int_window_stuck.py
"""
import json
import os
import sys

LIVE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, LIVE)

import MetaTrader5 as mt5              # noqa: E402
import owl_chart_feed as F             # noqa: E402

NOW = F.INT_WINDOWS
FALLBACK = tuple(NOW) + (120, 80, 50, 30, 20)


def first_hit(pool, wins):
    for w in wins:
        t = pool[-w:]
        if len(t) < 5:
            continue
        r = F.engine(t)
        if r[2] != 0:
            return w, len(r[0])
    return None, 0


def main():
    u = next(x for x in json.load(open(os.path.join(
        LIVE, "owl_nest_users.json"), encoding="utf-8")) if x["id"] == "std")
    assert mt5.initialize(path=u["terminal"]), mt5.last_error()
    sym = "BTCUSD" if mt5.symbol_info("BTCUSD") else "BTCUSDm"
    R = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_M1, 0, 8000)
    mt5.shutdown()
    kept = F.build(R)
    print(f"\n  {sym}  {len(R)/1440:.1f} days  ->  {len(kept)} kept candles")
    print(f"  now      {NOW}")
    print(f"  fallback {FALLBACK}\n")

    n = both = only_fb = neither = 0
    pools = []
    step = max(1, len(kept) // 400)
    for i in range(300, len(kept), step):
        pre = kept[:i]
        r = F.engine(pre)
        inv_t = r[7]
        if not inv_t:
            continue
        pool = [k for k in pre if k[0] > inv_t]
        if len(pool) < 5:
            continue
        n += 1
        pools.append(len(pool))
        w1, _ = first_hit(pool, NOW)
        w2, d2 = first_hit(pool, FALLBACK)
        if w1:
            both += 1
        elif w2:
            only_fb += 1
        else:
            neither += 1

    print(f"  {n} samples, median pool {sorted(pools)[len(pools)//2]} candles")
    print(f"    structure found today          {both:>4}  "
          f"{100*both/n:5.1f}%")
    print(f"    found ONLY with the fallback   {only_fb:>4}  "
          f"{100*only_fb/n:5.1f}%   <- what this would add")
    print(f"    still nothing either way       {neither:>4}  "
          f"{100*neither/n:5.1f}%")
    print(f"\n  internal structure availability: "
          f"{100*both/n:.1f}%  ->  {100*(both+only_fb)/n:.1f}%\n")


if __name__ == "__main__":
    main()
