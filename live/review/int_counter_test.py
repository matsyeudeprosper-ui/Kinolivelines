"""Internal-structure signals: WITH the main trend vs AGAINST it.

Owner 2026-09-22: "taking a counter trend is good idea according to data
and your analysis?" The bot has never taken one - the loop requires
int_trend == eng.trend - so there is no live record and no existing
replay covers it. This builds one.

It walks the kept series one candle at a time and rebuilds, at every step,
exactly what owl_chart_feed publishes: the main structure, the anchored
internal window WITH the 2026-09-22 pin, and the internal protected level.
A change in that level is an internal signal. Each signal is then traded
on raw M1 bars to its stop or target.

Both arms are simulated INDEPENDENTLY - no one-position-at-a-time - so
neither can steal the other's slot. The question is signal quality, not
scheduling. Weather gates are left off in both arms for the same reason.

Slow on purpose (the main engine is re-run per candle); a few minutes.

    python review/int_counter_test.py [spread]
"""
import json
import os
import statistics as st
import sys

LIVE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, LIVE)

import MetaTrader5 as mt5              # noqa: E402
import owl_chart_feed as F             # noqa: E402

SPREAD = float(sys.argv[1]) if len(sys.argv) > 1 else 7.0
RR = 0.8
S_MIN = 10.0


def anchor(pre, r):
    nxt, inv, inv_t, mflp = r[4], r[5], r[7], r[9]
    marks = r[1]
    t0 = inv_t if inv_t else (marks[-1][0] if marks else pre[0][0])
    bs = [v for v in (nxt, inv, mflp) if v is not None]
    if bs and t0:
        hi, lo = max(bs), min(bs)
        touch = None
        for k in pre:
            if k[0] <= t0:
                continue
            if k[4] > hi or k[4] < lo:
                touch = k[0]
        if touch and touch > t0:
            t0 = touch
    return t0


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
    print(f"\n  {sym}  {len(R)/1440:.1f} days  {len(kept)} kept  "
          f"spread {SPREAD:.0f}\n", flush=True)

    pin = {"t0": None, "start": None}
    last_inv = None
    sigs = []
    for j in range(300, len(kept)):
        pre = kept[:j + 1]
        r = F.engine(pre)
        mtrend = r[2]
        t0 = anchor(pre, r)
        pool = [k for k in pre if k[0] > t0]
        if pin["t0"] != t0:
            pin["t0"], pin["start"] = t0, None
        itr = iinv = None
        if pin["start"] is not None:
            t = [k for k in pool if k[0] >= pin["start"]]
            if len(t) >= 5:
                rr = F.engine(t)
                if rr[2] != 0:
                    itr, iinv = rr[2], rr[5]
            if itr is None:
                pin["start"] = None
        if itr is None:
            for w in F.INT_WINDOWS:
                t = pool[-w:]
                if len(t) < 5:
                    continue
                rr = F.engine(t)
                if rr[2] != 0:
                    itr, iinv = rr[2], rr[5]
                    pin["start"] = t[0][0]
                    break
        if itr is None or iinv is None:
            continue
        if iinv == last_inv:
            continue
        last_inv = iinv
        c = pre[-1][4]
        dist = abs(c - iinv)
        if dist <= S_MIN:
            continue
        sigs.append({"t": pre[-1][0], "d": itr, "e": c, "sl": iinv,
                     "tp": c + itr * RR * dist, "dist": dist,
                     "aligned": itr == mtrend})

    print(f"  {len(sigs)} internal signals rebuilt", flush=True)
    # settle each on raw bars
    out = []
    for s in sigs:
        i0 = next((i for i, t in enumerate(tms) if t >= s["t"]), None)
        if i0 is None:
            continue
        for i in range(i0 + 1, len(R)):
            hit_sl = (lo[i] <= s["sl"]) if s["d"] == 1 else (hi[i] >= s["sl"])
            hit_tp = (hi[i] >= s["tp"]) if s["d"] == 1 else (lo[i] <= s["tp"])
            if hit_sl or hit_tp:
                win = bool(hit_tp and not hit_sl)
                pts = (RR * s["dist"] - SPREAD) if win else -(s["dist"] + SPREAD)
                out.append({"R": pts / s["dist"], "win": win,
                            "usd": pts * 0.02, "aligned": s["aligned"],
                            "t": s["t"]})
                break

    def show(lab, tr):
        if not tr:
            print(f"  {lab:<26}{'-':>7}   none")
            return
        r = [x["R"] for x in tr]
        per = sum(r) / len(r)
        se = st.pstdev(r) / len(r) ** 0.5 if len(r) > 1 else 0
        print(f"  {lab:<26}{len(tr):>7}"
              f"{100*sum(1 for x in tr if x['win'])/len(tr):>7.1f}%"
              f"{per:>+10.3f}   [{per-1.96*se:+.3f},{per+1.96*se:+.3f}]"
              f"{sum(x['usd'] for x in tr):>9.2f}")

    print(f"\n  {'arm':<26}{'trades':>7}{'win%':>8}{'R/trade':>10}"
          f"{'95% interval':>20}{'$':>9}")
    al = [x for x in out if x["aligned"]]
    ct = [x for x in out if not x["aligned"]]
    show("WITH the main trend", al)
    show("AGAINST (counter)", ct)
    show("all internal", out)
    if al and ct:
        mid = sorted(x["t"] for x in out)[len(out) // 2]
        print("\n  THE TWO HALVES")
        for lab, sel in (("WITH", al), ("AGAINST", ct)):
            h1 = [x for x in sel if x["t"] < mid]
            h2 = [x for x in sel if x["t"] >= mid]
            if h1 and h2:
                a = sum(x["R"] for x in h1) / len(h1)
                b = sum(x["R"] for x in h2) / len(h2)
                ag = "agree" if (a > 0) == (b > 0) else "DISAGREE"
                print(f"  {lab:<10} 1st {a:+.3f} ({len(h1):>3})   "
                      f"2nd {b:+.3f} ({len(h2):>3})   {ag}")
    print()


if __name__ == "__main__":
    main()
