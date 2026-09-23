"""Internal trades: stop at the internal protected dot, or at the extreme
of the whole internal structure?

Owner 2026-09-23. Today the internal stop is the internal protected dot
(int_inv). The proposal is the far edge of the internal window - the
highest high of that structure for a sell, the lowest low for a buy. A
wider stop, so a further target too (TP is RR x distance either way).

Rebuilds the internal structure the way owl_chart_feed does, INCLUDING
the 2026-09-23 guard that rejects a window whose break lands on the same
candle as the main break - without it the "internal" structure is just
the main one relabelled, which is what contaminated the earlier internal
numbers.

    python review/int_sl_extreme_test.py [spread]
"""
import json
import os
import statistics as st
import sys

LIVE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, LIVE)
_A = sys.argv[1:]

import MetaTrader5 as mt5              # noqa: E402
import owl_chart_feed as F             # noqa: E402

SP = float(_A[0]) if _A else 7.0
RR = 0.8
LOT = 0.02
S_MIN = 10.0


def main():
    u = next(x for x in json.load(open(os.path.join(
        LIVE, "owl_nest_users.json"), encoding="utf-8")) if x["id"] == "std")
    assert mt5.initialize(path=u["terminal"]), mt5.last_error()
    sym = "BTCUSD" if mt5.symbol_info("BTCUSD") else "BTCUSDm"
    R = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_M1, 0, 30000)
    mt5.shutdown()
    kept = F.build(R)
    hi = [float(b["high"]) for b in R]
    lo = [float(b["low"]) for b in R]
    tms = [int(b["time"]) for b in R]

    pin = {"t0": None, "start": None}
    last_inv = None
    sigs = []
    for j in range(300, len(kept)):
        pre = kept[:j + 1]
        r = F.engine(pre)
        nxt, inv, nxt_t, inv_t, mflp = r[4], r[5], r[6], r[7], r[9]
        t0 = inv_t if inv_t else (r[1][-1][0] if r[1] else pre[0][0])
        bs = [v for v in (nxt, inv, mflp) if v is not None]
        if bs:
            h_, l_ = max(bs), min(bs)
            tc = None
            for k in pre:
                if k[0] > t0 and (k[4] > h_ or k[4] < l_):
                    tc = k[0]
            if tc and tc > t0:
                t0 = tc
        pool = [k for k in pre if k[0] > t0]
        if pin["t0"] != t0:
            pin["t0"], pin["start"] = t0, None
        itr = iinv = None
        win = []
        if pin["start"] is not None:
            w = [k for k in pool if k[0] >= pin["start"]]
            if len(w) >= 5:
                rr = F.engine(w)
                if rr[2] != 0 and rr[6] != nxt_t:
                    itr, iinv, win = rr[2], rr[5], w
            if itr is None:
                pin["start"] = None
        if itr is None:
            for wl in F.INT_WINDOWS:
                w = pool[-wl:]
                if len(w) < 5:
                    continue
                rr = F.engine(w)
                if rr[2] != 0 and rr[6] == nxt_t:
                    continue                      # the main structure
                if rr[2] != 0:
                    itr, iinv, win = rr[2], rr[5], w
                    pin["start"] = w[0][0]
                    break
        if itr is None or iinv is None or iinv == last_inv:
            continue
        last_inv = iinv
        c = pre[-1][4]
        # A: the internal protected dot.  B: the far edge of the structure
        sl_a = iinv
        sl_b = (min(k[3] for k in win) if itr == 1
                else max(k[2] for k in win))
        sigs.append({"t": pre[-1][0], "d": itr, "e": c,
                     "a": sl_a, "b": sl_b})

    def settle(s, sl):
        d, e = s["d"], s["e"]
        dist = abs(e - sl)
        if dist <= S_MIN:
            return None
        tp = e + d * RR * dist
        i0 = next((i for i, t in enumerate(tms) if t >= s["t"]), None)
        if i0 is None:
            return None
        for i in range(i0 + 1, len(R)):
            hs = (lo[i] <= sl) if d == 1 else (hi[i] >= sl)
            ht = (hi[i] >= tp) if d == 1 else (lo[i] <= tp)
            if hs or ht:
                w = bool(ht and not hs)
                pts = (RR * dist - SP) if w else -(dist + SP)
                return {"R": pts / dist, "win": w, "usd": pts * LOT,
                        "dist": dist}
        return None

    print(f"\n  {sym}  {len(R)/1440:.1f} days, {len(sigs)} internal signals"
          f"  (duplicate-of-main rejected)\n")
    print(f"  {'stop at':<28}{'trades':>7}{'win%':>8}{'R/trade':>10}"
          f"{'median stop':>13}{'$':>9}")
    for lab, key in (("the internal dot (today)", "a"),
                     ("the structure's extreme", "b")):
        out = [settle(s, s[key]) for s in sigs]
        out = [x for x in out if x]
        if not out:
            print(f"  {lab:<28}{'-':>7}   none")
            continue
        r = [x["R"] for x in out]
        print(f"  {lab:<28}{len(out):>7}"
              f"{100*sum(1 for x in out if x['win'])/len(out):>7.1f}%"
              f"{sum(r)/len(r):>+10.3f}"
              f"{st.median(x['dist'] for x in out):>13.0f}"
              f"{sum(x['usd'] for x in out):>9.2f}")
    print()


if __name__ == "__main__":
    main()
