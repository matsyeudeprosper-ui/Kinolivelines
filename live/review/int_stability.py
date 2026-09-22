"""Does the internal structure FLAP - appear, vanish, reappear?

Owner 2026-09-22: "why does the internal structure keep showing and
disappearing, it was there a few minutes ago and now gone."

Suspect: my own 2026-09-21 fix. INT_WINDOWS gained short tails
(120/80/50/30/20) so a stuck window could still find a trend. The loop
takes the FIRST window that finds a direction - so once the long windows
fail, the answer comes from a 20-30 candle tail, and a tail that short
changes content every time a candle arrives. That would buy availability
at the cost of stability.

This walks the recent series one kept candle at a time, recomputes the
internal trend exactly as owl_chart_feed does, and counts how often the
answer CHANGES - with the short tails and without them.

    python review/int_stability.py
"""
import json
import os
import sys

LIVE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, LIVE)

import MetaTrader5 as mt5              # noqa: E402
import owl_chart_feed as F             # noqa: E402

OLD = (200, 300, 400, 550)
NEW = F.INT_WINDOWS


def int_trend(pre, wins):
    """Exactly the feed's internal block, trend only."""
    r = F.engine(pre)
    dots, marks, trend, choch, nxt, inv, nxt_t, inv_t, mdir, mflp, mflp_t, mfdir = r
    t0 = (inv_t if inv_t else (marks[-1][0] if marks
                               else (pre[0][0] if pre else None)))
    if t0 and pre:
        bs = [v for v in (nxt, inv, mflp) if v is not None]
        hi, lo = (max(bs), min(bs)) if bs else (None, None)
        touch = None
        for k in pre:
            if k[0] <= t0:
                continue
            if ((hi is not None and k[4] > hi) or (lo is not None and k[4] < lo)):
                touch = k[0]
        if touch and touch > t0:
            t0 = touch
    pool = [k for k in pre if k[0] > t0] if t0 else []
    for w in wins:
        t = pool[-w:]
        if len(t) < 5:
            continue
        rr = F.engine(t)
        if rr[2] != 0:
            return rr[2], w, len(t)
    return 0, None, len(pool)


def main():
    u = next(x for x in json.load(open(os.path.join(
        LIVE, "owl_nest_users.json"), encoding="utf-8")) if x["id"] == "std")
    assert mt5.initialize(path=u["terminal"]), mt5.last_error()
    sym = "BTCUSD" if mt5.symbol_info("BTCUSD") else "BTCUSDm"
    R = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_M1, 0, 8000)
    mt5.shutdown()
    kept = F.build(R)
    print(f"\n  {sym}  {len(kept)} kept candles  "
          f"(feed reads {len(R)} raw bars)")
    print(f"  old windows {OLD}")
    print(f"  new windows {NEW}\n")

    N = 250          # the last 250 kept candles, one step at a time
    for lab, wins in (("OLD (long only)", OLD), ("NEW (with tails)", NEW)):
        seq = []
        for j in range(len(kept) - N, len(kept)):
            tr, w, n = int_trend(kept[:j + 1], wins)
            seq.append((tr, w))
        on = sum(1 for s in seq if s[0] != 0)
        flips = sum(1 for a, b in zip(seq, seq[1:]) if (a[0] != 0) != (b[0] != 0))
        dirch = sum(1 for a, b in zip(seq, seq[1:])
                    if a[0] != 0 and b[0] != 0 and a[0] != b[0])
        wins_used = {}
        for s in seq:
            if s[1]:
                wins_used[s[1]] = wins_used.get(s[1], 0) + 1
        print(f"  {lab}")
        print(f"    structure present   {on}/{len(seq)} steps "
              f"({100*on/len(seq):.0f}%)")
        print(f"    ON<->OFF switches   {flips}   <- the flapping")
        print(f"    direction reversals {dirch}")
        print(f"    window that answered: "
              f"{dict(sorted(wins_used.items())) or 'none'}")
        print()


if __name__ == "__main__":
    main()
