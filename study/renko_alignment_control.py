"""Is the reversal caused by the alignment fix, or by a new bug I just wrote?

Runs the SAME recovery code twice, changing one thing: whether a signal on bar j
is tested against bar j (the old code, which prices the fill at bar j+1's open
and then tests it against the bar BEFORE it existed) or filled and tested from
bar j+1 onward (correct).

Also runs the plain strategy under all three tie conventions, because a bar can
span both barriers and trap #2 in FINDINGS.md says a result that changes sign
between them is not a result.

And it checks an invariant the first version never checked: entries opened plus
signals skipped should account for every signal.
"""
import numpy as np
import MetaTrader5 as mt5
from datetime import datetime

PCT, SPCT = 50.0 / 64000.0, 10.0 / 64000.0
REV, TPB, SLB, PT, START = 2, 5, 3, 0.01, 1000.0

mt5.initialize(path=r"C:\Program Files\MetaTrader 5\terminal64.exe")
r = mt5.copy_rates_from_pos("BTCUSDm", mt5.TIMEFRAME_H1, 0, 80000)
mt5.shutdown()
o, h, l, c = (r[k].astype(float) for k in ("open", "high", "low", "close"))
N = len(c); tm = r["time"]


def signals():
    revs = {}; ao = ac = float(o[0]); d = 0; pd_ = 0
    for i in range(N):
        B = c[i] * PCT
        while True:
            up = (ao if d == -1 else ac) + B * (REV if d == -1 else 1)
            dn = (ao if d == 1 else ac) - B * (REV if d == 1 else 1)
            if c[i] >= up:
                base = ao if d == -1 else ac; ao, ac, d = base, base + B, 1
            elif c[i] <= dn:
                base = ao if d == 1 else ac; ao, ac, d = base, base - B, -1
            else:
                break
            if pd_ and d != pd_:
                revs.setdefault(i, d)
            pd_ = d
    return revs


REVS = signals()


def recovery(cap=4, aligned=True):
    bal = START; cyc = START
    ent = np.empty(0); lng = np.empty(0, dtype=bool); tpp = np.empty(0); slv = np.empty(0)
    rec = False; peak = START; mdd = 0.0; lo = START; eq = START
    opened = skipped = forced = done = 0
    pending = None
    for j in range(N):
        B = c[j] * PCT; SP = c[j] * SPCT
        if aligned and pending is not None:
            L, a, b = pending
            ent = np.append(ent, o[j] + SP if L else o[j]); lng = np.append(lng, L)
            tpp = np.append(tpp, a); slv = np.append(slv, b); opened += 1; pending = None
        if j in REVS and j + 1 < N:
            if len(ent) == 0 or (rec and len(ent) <= cap):
                if aligned:
                    pending = ((REVS[j] == 1), B * TPB, B * SLB)
                else:                       # ORIGINAL: fill now, at j+1's open
                    L = (REVS[j] == 1)
                    ent = np.append(ent, o[j + 1] + SP if L else o[j + 1])
                    lng = np.append(lng, L)
                    tpp = np.append(tpp, B * TPB); slv = np.append(slv, B * SLB)
                    opened += 1
            else:
                skipped += 1
        if len(ent):
            hit = np.where(lng, h[j] >= ent + tpp, l[j] <= ent - tpp - SP)
            if hit.any():
                bal += float(np.sum(tpp[hit])) * PT
                ent, lng, tpp, slv = ent[~hit], lng[~hit], tpp[~hit], slv[~hit]
        if len(ent) and not rec:
            if np.where(lng, l[j] <= ent - slv, h[j] >= ent + slv + SP).any():
                rec = True
        flo = float(np.sum(np.where(lng, c[j] - ent, ent - c[j] - SP)) * PT) if len(ent) else 0.0
        eq = bal + flo
        if rec and len(ent) and eq >= cyc:
            bal = eq; done += 1
            ent = np.empty(0); lng = np.empty(0, dtype=bool)
            tpp = np.empty(0); slv = np.empty(0); eq = bal; rec = False
        elif len(ent) > cap:
            bal = eq; forced += 1
            ent = np.empty(0); lng = np.empty(0, dtype=bool)
            tpp = np.empty(0); slv = np.empty(0); eq = bal; rec = False
        if not rec and len(ent) == 0:
            cyc = bal
        peak = max(peak, eq); mdd = max(mdd, peak - eq); lo = min(lo, eq)
        if eq <= 0:
            return dict(dead=j, eq=0.0, mdd=mdd, lo=0.0, opened=opened,
                        skipped=skipped, forced=forced, done=done)
    return dict(dead=None, eq=eq, mdd=mdd, lo=lo, opened=opened,
                skipped=skipped, forced=forced, done=done)


def plain(tie="loss"):
    bal = START; peak = START; mdd = 0.0
    w = ls = 0; ent = None; lng = False; tp = sl = 0.0; pending = None
    opened = 0
    for j in range(N):
        if pending is not None:
            lng, tp, sl = pending
            ent = o[j] + c[j] * SPCT if lng else o[j]
            pending = None; opened += 1
        if ent is not None:
            SP = c[j] * SPCT
            s = (l[j] <= ent - sl) if lng else (h[j] >= ent + sl + SP)
            t = (h[j] >= ent + tp) if lng else (l[j] <= ent - tp - SP)
            if s and t:                       # the bar spans BOTH barriers
                if tie == "loss":   bal -= sl * PT; ls += 1
                elif tie == "win":  bal += tp * PT; w += 1
                else:               bal += (tp - sl) / 2 * PT * 0  # split = scratch
                ent = None
            elif s:
                bal -= sl * PT; ls += 1; ent = None
            elif t:
                bal += tp * PT; w += 1; ent = None
        if ent is None and pending is None and j in REVS and j + 1 < N:
            B = c[j] * PCT
            pending = ((REVS[j] == 1), B * TPB, B * SLB)
        peak = max(peak, bal); mdd = max(mdd, peak - bal)
        if bal <= 0:
            return dict(dead=j, eq=0.0, w=w, l=ls, mdd=mdd, opened=opened)
    return dict(dead=None, eq=bal, w=w, l=ls, mdd=mdd, opened=opened)


print(f"signals in history: {len(REVS)}\n")
print("RECOVERY, cap 4 - one variable changed: barrier alignment")
print("=" * 70)
for aligned, tag in ((False, "ORIGINAL (test on the bar before entry)"),
                     (True,  "FIXED    (fill and test from the next bar)")):
    z = recovery(4, aligned)
    end = f"DIED {(tm[z['dead']]-tm[0])/86400/365:.1f}y" if z["dead"] is not None else f"${z['eq']:,.0f}"
    print(f"  {tag}")
    print(f"     final {end}   worst dd ${z['mdd']:,.0f}   lowest equity ${z['lo']:,.0f}")
    print(f"     opened {z['opened']}  skipped {z['skipped']}  "
          f"sum {z['opened']+z['skipped']} vs {len(REVS)} signals  "
          f"{'OK' if z['opened']+z['skipped']==len(REVS) else 'MISMATCH'}")
    print(f"     recoveries completed {z['done']}  forced at cap {z['forced']}")

print("\nPLAIN 5:3 - all three tie conventions (trap #2)")
print("=" * 70)
for tie in ("loss", "split", "win"):
    p = plain(tie)
    end = f"DIED {(tm[p['dead']]-tm[0])/86400/365:.1f}y" if p["dead"] is not None else f"${p['eq']:,.0f}"
    n = p["w"] + p["l"]
    print(f"  tie->{tie:<5}  {end:>12}   wins {p['w']:>5}/{n:<5} "
          f"({100*p['w']/max(1,n):>4.1f}%)   worst dd ${p['mdd']:,.0f}")
print("\n  For reference: a driftless random walk with TP 5 / SL 3 wins")
print("  3/(5+3) = 37.5% of the time. That is the number to beat.")
