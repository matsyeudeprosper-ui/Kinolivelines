"""Move the stop to each new glowing dot while the trade runs. Worth it?

Owner 2026-09-23: "when there's a trade running I'd like to move the SL as
the structure updates its last glowing dot."

Definition used: while a position is open, every time the engine confirms a
NEW signal in the SAME direction, that signal carries a fresh protected dot.
The stop moves there - but only when it moves TOWARD price (a trail never
loosens). Target is untouched.

Why it might work: RR is 0.8, so targets are nearer than stops and the
losses are the expensive half. Why it might not: the same trail tightens
into ordinary pullbacks and turns winners into small losses.

Arms are paired inside one replay - identical bars, identical signals,
identical entries - so only the stop rule differs.

    python review/trail_dot_test.py [spread]
"""
import bisect
import json
import os
import statistics as st
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
LIVE = os.path.dirname(HERE)
sys.path.insert(0, LIVE)
_A = sys.argv[1:]
sys.argv = ["trail_dot_test"]

import MetaTrader5 as mt5              # noqa: E402
import structure_bos_bot as B          # noqa: E402
B.say = lambda *a, **k: None

SPREAD = float(_A[0]) if _A else 7.0


def bars(n=60000):
    u = next(x for x in json.load(open(os.path.join(
        LIVE, "owl_nest_users.json"), encoding="utf-8")) if x["id"] == "std")
    if not mt5.initialize(path=u["terminal"]):
        raise SystemExit(f"MT5: {mt5.last_error()}")
    sym = "BTCUSD" if mt5.symbol_info("BTCUSD") else "BTCUSDm"
    R = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_M1, 0, n)
    mt5.shutdown()
    return sym, R


def replay(R, trail, spread, lot=0.02, balance=230.0):
    eng = B.Struct()
    eng.quiet = True
    rng = [float(r["high"]) - float(r["low"]) for r in R]
    flips, marks, trades = [], [], []
    prev_trend = 0
    used_hi = used_lo = None
    pos = None
    for i, bar in enumerate(R):
        t = int(bar["time"])
        o, h, l, c = (float(bar["open"]), float(bar["high"]),
                      float(bar["low"]), float(bar["close"]))
        if pos:
            d, e, sl, tp, risk0, moved, te = pos
            hit_sl = (l <= sl) if d == 1 else (h >= sl)
            hit_tp = (h >= tp) if d == 1 else (l <= tp)
            if hit_sl or hit_tp:
                win = bool(hit_tp and not hit_sl)
                if win:
                    pts = B.RR * risk0 - spread
                else:
                    # the stop may have moved: the loss is to WHERE it sits
                    pts = (sl - e) * d - spread
                trades.append({"t": t, "te": te, "R": pts / risk0,
                               "win": win, "usd": pts * lot,
                               "moved": moved, "risk0": risk0})
                pos = None
        sig = eng.step(t, o, h, l, c)
        if eng.trend != prev_trend and eng.trend != 0:
            flips.append(t)
            prev_trend = eng.trend
        if sig is not None:
            marks.append(t)
        if sig is None:
            continue
        d, slp = sig
        if pos:
            # THE TRAIL: same direction, and only ever toward price
            if trail and d == pos[0]:
                nsl = float(slp)
                if (d == 1 and nsl > pos[2]) or (d == -1 and nsl < pos[2]):
                    pos = (pos[0], pos[1], nsl, pos[3], pos[4],
                           pos[5] + 1, pos[6])
            continue
        if not any(f > t - B.AWAKE_WIN for f in flips):
            continue
        flip = bool(flips) and flips[-1] == t
        if not flip:
            lvl = eng.hi_v if d == 1 else eng.lo_v
            if (d == 1 and used_hi == lvl) or (d == -1 and used_lo == lvl):
                continue
            if d == 1:
                used_hi = lvl
            else:
                used_lo = lvl
        if i >= 1440:
            nv = (sorted(rng[i - 60:i])[30]
                  / max(sorted(rng[i - 1440:i])[720], 1e-9))
            mv2 = (bisect.bisect_left(marks, t)
                   - bisect.bisect_left(marks, t - 7200))
            if nv >= B.NERV_STORM or mv2 < 1:
                continue
        risk = abs(c - slp)
        if risk <= B.S_MIN_DIST or risk * lot > B.MAX_RISK_PCT * balance:
            continue
        pos = (d, c, float(slp), c + d * B.RR * risk, risk, 0, t)
    return trades


def summ(tr):
    if not tr:
        return None
    r = [x["R"] for x in tr]
    per = sum(r) / len(r)
    se = st.pstdev(r) / len(r) ** 0.5 if len(r) > 1 else 0.0
    return dict(n=len(tr), per=per, se=se,
                wr=100 * sum(1 for x in tr if x["win"]) / len(tr),
                usd=sum(x["usd"] for x in tr),
                worst=min(r))


def main():
    sym, R = bars()
    print(f"\n  {sym}  {len(R)/1440:.1f} days  spread {SPREAD:.0f}  "
          f"RR {B.RR}\n")
    print(f"  {'arm':<22}{'trades':>7}{'win%':>8}{'R/trade':>10}"
          f"{'95% interval':>20}{'$':>9}{'worst':>8}{'anch+':>7}")
    ANCH, step = 6, 600
    for lab, tr_on in (("fixed stop (today)", False),
                       ("trail to each dot", True)):
        rows = []
        for a in range(ANCH):
            sub = R[a * step:]
            if len(sub) < 20000:
                break
            rows.append(summ(replay(sub, tr_on, SPREAD)))
        b = rows[0]
        pa = sum(1 for r in rows if r and r["per"] > 0)
        lo, hi = b["per"] - 1.96 * b["se"], b["per"] + 1.96 * b["se"]
        print(f"  {lab:<22}{b['n']:>7}{b['wr']:>7.1f}%{b['per']:>+10.3f}"
              f"   [{lo:+.3f},{hi:+.3f}]{b['usd']:>9.2f}{b['worst']:>8.2f}"
              f"{pa:>4}/{len(rows)}")

    base = replay(R, False, SPREAD)
    trl = replay(R, True, SPREAD)
    mid = sorted(x["t"] for x in base)[len(base) // 2]
    print("\n  THE TWO HALVES")
    for lab, tr in (("fixed", base), ("trail", trl)):
        h1 = summ([x for x in tr if x["t"] < mid])
        h2 = summ([x for x in tr if x["t"] >= mid])
        ag = "agree" if (h1["per"] > 0) == (h2["per"] > 0) else "DISAGREE"
        print(f"  {lab:<8} 1st {h1['per']:+.3f} ({h1['n']:>3})   "
              f"2nd {h2['per']:+.3f} ({h2['n']:>3})   {ag}")

    moved = [x for x in trl if x["moved"] > 0]
    print(f"\n  HOW OFTEN THE STOP ACTUALLY MOVED")
    print(f"    {len(moved)} of {len(trl)} trades "
          f"({100*len(moved)/len(trl):.0f}%)")
    if moved:
        m = summ(moved)
        print(f"    those trades: {m['wr']:.1f}% win  {m['per']:+.3f} R  "
              f"${m['usd']:+.2f}")
        still = [x for x in trl if x["moved"] == 0]
        s2 = summ(still)
        print(f"    never moved : {s2['wr']:.1f}% win  {s2['per']:+.3f} R  "
              f"${s2['usd']:+.2f}")
    print()
    print("  MATCHED PAIRS - only the trades BOTH arms opened")
    bi = {x["te"]: x for x in base}
    ti = {x["te"]: x for x in trl}
    both = sorted(set(bi) & set(ti))
    bb = summ([bi[k] for k in both])
    tt = summ([ti[k] for k in both])
    print(f"    {len(both)} shared entries of {len(base)} fixed"
          f" / {len(trl)} trail")
    print(f"    fixed  {bb['wr']:.1f}% win  {bb['per']:+.3f} R"
          f"  ${bb['usd']:+.2f}")
    print(f"    trail  {tt['wr']:.1f}% win  {tt['per']:+.3f} R"
          f"  ${tt['usd']:+.2f}")
    print(f"    SAME trades, difference: {tt['per']-bb['per']:+.3f} R"
          f"   ${tt['usd']-bb['usd']:+.2f}")
    chg = [k for k in both if ti[k]["moved"] > 0]
    if chg:
        cb = summ([bi[k] for k in chg])
        ct = summ([ti[k] for k in chg])
        print(f"    of those, {len(chg)} had the stop MOVED:")
        print(f"      fixed {cb['wr']:.1f}% win {cb['per']:+.3f} R"
              f" ${cb['usd']:+.2f}")
        print(f"      trail {ct['wr']:.1f}% win {ct['per']:+.3f} R"
              f" ${ct['usd']:+.2f}")
    print("\n  SPREAD")
    for sp in (0.0, 7.0, 15.0):
        a, b2 = summ(replay(R, False, sp)), summ(replay(R, True, sp))
        print(f"    spread {sp:>4.0f}   fixed {a['per']:+.3f}  "
              f"trail {b2['per']:+.3f}   diff {b2['per']-a['per']:+.3f}"
              f"   (${a['usd']:+.2f} vs ${b2['usd']:+.2f})")
    print()


if __name__ == "__main__":
    main()
