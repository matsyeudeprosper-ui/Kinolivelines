import bisect, json, os, statistics as st, sys
HERE = os.path.dirname(os.path.abspath(__file__))
LIVE = os.path.dirname(HERE)
sys.path.insert(0, LIVE)
_A = sys.argv[1:]
sys.argv = ["post_storm_test"]
import MetaTrader5 as mt5
import structure_bos_bot as B
B.say = lambda *a, **k: None
SP = float(_A[0]) if _A else 7.0
LOT = B.BASE_LOT

def bars(n=60000):
    u = next(x for x in json.load(open(os.path.join(LIVE, "owl_nest_users.json"), encoding="utf-8")) if x["id"] == "std")
    if not mt5.initialize(path=u["terminal"]):
        raise SystemExit(f"MT5: {mt5.last_error()}")
    sym = "BTCUSD" if mt5.symbol_info("BTCUSD") else "BTCUSDm"
    R = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_M1, 0, n)
    mt5.shutdown()
    return sym, R

def replay(R, spread):
    eng = B.Struct(); eng.quiet = True
    rng = [float(r["high"]) - float(r["low"]) for r in R]
    flips, marks, trades = [], [], []
    prev = 0
    used_hi = used_lo = None
    pos = None
    storm_seen = False       # nv hit >=1.85 since the last trade
    for i, bar in enumerate(R):
        t = int(bar["time"])
        o, h, l, c = (float(bar["open"]), float(bar["high"]), float(bar["low"]), float(bar["close"]))
        if pos:
            d, e, sl, tp, dist, tag = pos
            hs = (l <= sl) if d == 1 else (h >= sl)
            ht = (h >= tp) if d == 1 else (l <= tp)
            if hs or ht:
                w = bool(ht and not hs)
                pts = (B.RR * dist - spread) if w else -(dist + spread)
                trades.append({"t": t, "R": pts / dist, "win": w,
                               "usd": pts * LOT, "post_storm": tag})
                pos = None
        sig = eng.step(t, o, h, l, c)
        if eng.trend != prev and eng.trend != 0:
            flips.append(t); prev = eng.trend
        if sig is not None:
            marks.append(t)
        nv = None
        if i >= 1440:
            nv = sorted(rng[i-60:i])[30] / max(sorted(rng[i-1440:i])[720], 1e-9)
            if nv >= B.NERV_STORM:
                storm_seen = True
        if sig is None or pos:
            continue
        if not any(f > t - B.AWAKE_WIN for f in flips):
            continue
        d, slp = sig
        flip = bool(flips) and flips[-1] == t
        if not flip:
            lvl = eng.hi_v if d == 1 else eng.lo_v
            if (d == 1 and used_hi == lvl) or (d == -1 and used_lo == lvl):
                continue
            if d == 1: used_hi = lvl
            else: used_lo = lvl
        if nv is not None:
            mv2 = bisect.bisect_left(marks, t) - bisect.bisect_left(marks, t - 7200)
            if nv >= B.NERV_STORM or mv2 < 1:
                continue
        dist = abs(c - slp)
        if dist <= B.S_MIN_DIST or dist * LOT > B.MAX_RISK_PCT * 230.0:
            continue
        tp = c + d * B.RR * dist
        pos = (d, c, float(slp), tp, dist, storm_seen)
        storm_seen = False    # this trade "used up" the storm episode
    return trades

def summ(tr):
    if not tr:
        return None
    r = [x["R"] for x in tr]
    se = st.pstdev(r) / len(r) ** 0.5 if len(r) > 1 else 0.0
    return dict(n=len(tr), per=sum(r)/len(r), se=se,
               wr=100*sum(1 for x in tr if x["win"])/len(tr),
               usd=sum(x["usd"] for x in tr))

def main():
    sym, R = bars()
    days = len(R)/1440
    print(f"\n  {sym}  {days:.1f} days, spread {SP:.0f}\n")
    ANCH, step = 6, 600
    print(f"  {'group':<20}{'trades':>7}{'win%':>8}{'R/trade':>10}{'95% CI':>20}{'$':>9}{'anch+':>7}")
    rows = {"first after storm ends": [], "every other trade": []}
    base0 = None
    for a in range(ANCH):
        sub = R[a*step:]
        if len(sub) < 20000: break
        tr = replay(sub, SP)
        if a == 0: base0 = tr
        rows["first after storm ends"].append(summ([x for x in tr if x["post_storm"]]))
        rows["every other trade"].append(summ([x for x in tr if not x["post_storm"]]))
    for lab in rows:
        b = rows[lab][0]
        if not b:
            print(f"  {lab:<20}{'-':>7}   none")
            continue
        pos = sum(1 for r in rows[lab] if r and r["per"] > 0)
        cnt = sum(1 for r in rows[lab] if r)
        lo, hi = b["per"]-1.96*b["se"], b["per"]+1.96*b["se"]
        print(f"  {lab:<20}{b['n']:>7}{b['wr']:>7.1f}%{b['per']:>+10.3f}   "
              f"[{lo:+.3f},{hi:+.3f}]{b['usd']:>9.2f}{pos:>4}/{cnt}")
    mid = sorted(x["t"] for x in base0)[len(base0)//2]
    print("\n  THE TWO HALVES")
    for lab, key in (("first after storm", True), ("every other", False)):
        sel = [x for x in base0 if x["post_storm"] == key]
        h1 = summ([x for x in sel if x["t"] < mid])
        h2 = summ([x for x in sel if x["t"] >= mid])
        if not h1 or not h2:
            print(f"  {lab:<18} too few to split"); continue
        ag = "agree" if (h1["per"]>0)==(h2["per"]>0) else "DISAGREE"
        print(f"  {lab:<18} 1st {h1['per']:+.3f} ({h1['n']:>3})   2nd {h2['per']:+.3f} ({h2['n']:>3})   {ag}")
    print()

if __name__ == "__main__":
    main()
