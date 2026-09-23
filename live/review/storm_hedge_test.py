import bisect, json, os, statistics as st, sys
HERE = os.path.dirname(os.path.abspath(__file__))
LIVE = os.path.dirname(HERE)
sys.path.insert(0, LIVE)
_A = sys.argv[1:]
sys.argv = ["storm_hedge_test"]
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

def run(R, spread):
    eng = B.Struct(); eng.quiet = True
    rng = [float(r["high"]) - float(r["low"]) for r in R]
    flips, marks = [], []
    prev = 0
    used_hi = used_lo = None
    primary = None
    hedge = None
    cur_ev = None          # the event dict tied to the CURRENT primary, if
                            # a hedge was ever opened alongside it - never
                            # index events[-1] blindly, a primary that never
                            # got a hedge has no event to write into
    events = []
    for i, bar in enumerate(R):
        t = int(bar["time"])
        o, h, l, c = (float(bar["open"]), float(bar["high"]), float(bar["low"]), float(bar["close"]))
        if primary:
            d, e, sl, tp, dist = primary
            hs = (l <= sl) if d == 1 else (h >= sl)
            ht = (h >= tp) if d == 1 else (l <= tp)
            if hs or ht:
                w = bool(ht and not hs)
                pts = (B.RR * dist - SP) if w else -(dist + SP)
                if cur_ev is not None:
                    cur_ev["primary_close"] = {"t": t, "R": pts / dist, "usd": pts * LOT, "win": w}
                primary = None
        if hedge:
            d, e, sl, tp, dist = hedge
            hs = (l <= sl) if d == 1 else (h >= sl)
            ht = (h >= tp) if d == 1 else (l <= tp)
            if hs or ht:
                w = bool(ht and not hs)
                pts = (B.RR * dist - SP) if w else -(dist + SP)
                if cur_ev is not None:
                    cur_ev["hedge_close"] = {"t": t, "R": pts / dist, "usd": pts * LOT, "win": w}
                hedge = None
                if primary is None:
                    cur_ev = None
        sig = eng.step(t, o, h, l, c)
        was_flip = False
        if eng.trend != prev and eng.trend != 0:
            flips.append(t); prev = eng.trend; was_flip = True
        if sig is not None:
            marks.append(t)
        nv = None
        if i >= 1440:
            nv = sorted(rng[i-60:i])[30] / max(sorted(rng[i-1440:i])[720], 1e-9)
        # the hedge opportunity: a >=1.85x flip while a primary is open
        if was_flip and primary and nv is not None and nv >= B.NERV_STORM and sig is not None:
            d, slp = sig
            dist = abs(c - slp)
            if dist > B.S_MIN_DIST and dist * LOT <= B.MAX_RISK_PCT * 230.0:
                tp = c + d * B.RR * dist
                hedge = (d, c, float(slp), tp, dist)
                cur_ev = {"t": t, "nv": nv, "primary_dir": primary[0],
                         "hedge_dir": d, "hedge_dist": dist,
                         "primary_dist": primary[4]}
                events.append(cur_ev)
        if sig is None or primary:
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
        primary = (d, c, float(slp), tp, dist)
    return events

def main():
    sym, R = bars()
    ev = run(R, SP)
    days = len(R) / 1440
    print(f"\n  {sym}  {days:.1f} days, spread {SP:.0f}")
    print(f"  hedge opportunities (storm flip while a primary trade is open): {len(ev)}\n")
    if not ev:
        print("  none in this window - too rare to test here.\n")
        return
    for x in ev:
        pc = x.get("primary_close", {})
        hc = x.get("hedge_close", {})
        print(f"  nv={x['nv']:.2f}x  primary {('BUY' if x['primary_dir']==1 else 'SELL')} "
              f"-> {pc.get('R', 0):+.2f}R ${pc.get('usd', 0):+.2f}   "
              f"hedge {('BUY' if x['hedge_dir']==1 else 'SELL')} "
              f"-> {hc.get('R', 0):+.2f}R ${hc.get('usd', 0):+.2f}   "
              f"combined ${pc.get('usd', 0) + hc.get('usd', 0):+.2f}")
    tot_p = sum(x.get("primary_close", {}).get("usd", 0) for x in ev)
    tot_h = sum(x.get("hedge_close", {}).get("usd", 0) for x in ev)
    print(f"\n  totals across {len(ev)} events:")
    print(f"    primary alone (no hedge)     ${tot_p:+.2f}")
    print(f"    hedge leg alone              ${tot_h:+.2f}")
    print(f"    combined (with hedge)        ${tot_p+tot_h:+.2f}")
    combined = [x.get("primary_close", {}).get("usd", 0) + x.get("hedge_close", {}).get("usd", 0) for x in ev]
    prim = [x.get("primary_close", {}).get("usd", 0) for x in ev]
    if len(ev) > 1:
        print(f"    variance WITHOUT hedge (primary only): {st.pstdev(prim):.2f}")
        print(f"    variance WITH hedge (combined):        {st.pstdev(combined):.2f}")
    print()

if __name__ == "__main__":
    main()
