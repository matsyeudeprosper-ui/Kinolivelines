"""TP = $1 flat (not brick-scaled), same recovery/cap engine as the real
live bot (recovery trigger = 3 bricks, cap = 4 positions, 0.01 lots).
Same everything else as study/renko_clean.py - only the TP line changes
from brick-scaled ($2.50-ish, drifts with price) to a flat $1.00 (100pts).
"""
import numpy as np
import MetaTrader5 as mt5
from datetime import datetime

PCT, SPCT = 50.0 / 64000.0, 10.0 / 64000.0
REV, SLB, CAP, PT, START = 2, 3, 4, 0.01, 1000.0
FROM = datetime(2022, 1, 1)
TP_USD = 1.0
TP_PTS_FLAT = TP_USD / PT  # 100 points, FLAT - does not scale with brick size

mt5.initialize(path=r"C:\Program Files\MetaTrader 5\terminal64.exe")
r = mt5.copy_rates_from_pos("BTCUSDm", mt5.TIMEFRAME_H1, 0, 80000)
mt5.shutdown()
keep = r["time"] >= FROM.timestamp()
r = r[keep]
o, h, l, c = (r[k].astype(float) for k in ("open", "high", "low", "close"))
tm = r["time"]; N = len(c)
ym = np.array([datetime.utcfromtimestamp(t).strftime("%Y-%m") for t in tm])
yr = np.array([datetime.utcfromtimestamp(t).strftime("%Y") for t in tm])
span = (tm[-1] - tm[0]) / 86400 / 365
print(f"bars {N}   {datetime.utcfromtimestamp(tm[0]):%Y-%m-%d} -> "
      f"{datetime.utcfromtimestamp(tm[-1]):%Y-%m-%d}   ({span:.1f} years)")
print(f"TP flat ${TP_USD:.2f} ({TP_PTS_FLAT:.0f}pts)   recovery trigger {SLB} bricks   cap {CAP}\n")


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


def run(cap=CAP, tp_flat_pts=TP_PTS_FLAT):
    bal = START; cyc = START
    ent = np.empty(0); lng = np.empty(0, dtype=bool); tpp = np.empty(0); slv = np.empty(0)
    rec = False; in_cycle = False; pending = None
    peak = START; mdd = 0.0; mddp = 0.0; lo = START; eq = START
    opened = skipped = pend_at_end = 0
    tpwins = 0; maxbask = 0; basket_bars = 0
    by_exit = {"tp": [], "recovered": [], "forced": []}
    bask_start = None; bask_lens = []
    eq_month = {}; eq_year = {}; dead = None
    for j in range(N):
        B = c[j] * PCT; SP = c[j] * SPCT
        if pending is not None:
            L, a, b = pending
            if len(ent) == 0:
                bask_start = j; in_cycle = True
            ent = np.append(ent, o[j] + SP if L else o[j]); lng = np.append(lng, L)
            tpp = np.append(tpp, a); slv = np.append(slv, b)
            opened += 1; maxbask = max(maxbask, len(ent)); pending = None
        if j in REVS and j + 1 < N:
            if len(ent) == 0 or (rec and len(ent) <= cap):
                pending = ((REVS[j] == 1), tp_flat_pts, B * SLB)
            else:
                skipped += 1
        if len(ent):
            basket_bars += 1
            hit = np.where(lng, h[j] >= ent + tpp, l[j] <= ent - tpp - SP)
            if hit.any():
                bal += float(np.sum(tpp[hit])) * PT
                tpwins += int(hit.sum())
                ent, lng, tpp, slv = ent[~hit], lng[~hit], tpp[~hit], slv[~hit]
        if len(ent) and not rec:
            if np.where(lng, l[j] <= ent - slv, h[j] >= ent + slv + SP).any():
                rec = True
        flo = float(np.sum(np.where(lng, c[j] - ent, ent - c[j] - SP)) * PT) if len(ent) else 0.0
        eq = bal + flo
        closed = None
        if rec and len(ent) and eq >= cyc:
            closed = "recovered"
        elif len(ent) > cap:
            closed = "forced"
        if closed:
            by_exit[closed].append(eq - cyc); in_cycle = False; bal = eq
            ent = np.empty(0); lng = np.empty(0, dtype=bool)
            tpp = np.empty(0); slv = np.empty(0); eq = bal
            if bask_start is not None:
                bask_lens.append(j - bask_start); bask_start = None
        if len(ent) == 0:
            if in_cycle and closed is None:
                by_exit["tp"].append(bal - cyc); in_cycle = False
                if bask_start is not None:
                    bask_lens.append(j - bask_start); bask_start = None
            rec = False
            cyc = bal
        peak = max(peak, eq); mdd = max(mdd, peak - eq)
        mddp = max(mddp, (peak - eq) / peak * 100); lo = min(lo, eq)
        eq_month[ym[j]] = eq; eq_year[yr[j]] = eq
        if eq <= 0:
            dead = j; break
    if pending is not None:
        pend_at_end = 1
    unfillable = sum(1 for q in REVS if q + 1 >= N)
    stuck = len(ent)
    return dict(eq=eq, lo=lo, mdd=mdd, mddp=mddp, dead=dead, opened=opened,
                skipped=skipped, tpwins=tpwins, maxbask=maxbask, by_exit=by_exit,
                bask_lens=bask_lens, basket_bars=basket_bars, eq_month=eq_month,
                eq_year=eq_year, unfillable=unfillable, pend=pend_at_end,
                stuck=stuck, last_j=(dead if dead is not None else N - 1))


z = run()
be = z["by_exit"]
allc = np.array(be["tp"] + be["recovered"] + be["forced"]) if (be["tp"] or be["recovered"] or be["forced"]) else np.array([0.0])
nc = len(allc)

print("BOTTOM LINE")
print(f"  ended with            ${z['eq']:>9,.2f}   ({100*(z['eq']/START-1):+.0f}%)")
print(f"  lowest equity ever    ${z['lo']:>9,.2f}")
print(f"  worst drawdown        ${z['mdd']:>9,.2f}   ({z['mddp']:.1f}% from its peak)")
if z["dead"] is not None:
    print(f"  *** ACCOUNT HIT ZERO {datetime.utcfromtimestamp(tm[z['dead']]):%Y-%m-%d} ***")

print("\nTRADES")
print(f"  reversal signals                  {len(REVS):>6}")
print(f"  positions opened                  {z['opened']:>6}")
print(f"  signals skipped (basket full)     {z['skipped']:>6}   ({100*z['skipped']/len(REVS):.1f}%)")
print(f"  positions that hit take profit    {z['tpwins']:>6}   ({100*z['tpwins']/max(1,z['opened']):.1f}%)")
print(f"  biggest basket                    {z['maxbask']:>6}")

print("\nCYCLES")
print(f"  cycles completed                  {nc:>6}")
for k, nm in (("tp", "ended on take profit"), ("recovered", "ended by recovering"),
              ("forced", "ended at the cap (loss)")):
    v = be[k]
    print(f"  {nm:<32}{len(v):>6}   ({100*len(v)/max(1,nc):>3.0f}%)  "
          f"avg ${np.mean(v) if v else 0:>+7.2f}")
print(f"  average winning cycle             ${allc[allc>0].mean() if (allc>0).any() else 0:>+7.2f}")
print(f"  average losing cycle              ${allc[allc<0].mean() if (allc<0).any() else 0:>+7.2f}")
print(f"  worst single cycle                ${allc.min():>+7.2f}")
print(f"  EXPECTANCY per cycle              ${allc.mean():>+7.2f}")

print("\nCAP SENSITIVITY (same TP=$1 flat)")
for cap in (2, 3, 4, 5, 6, 8, 12):
    y = run(cap)
    if y["dead"] is not None:
        print(f"  cap {cap:<4} DIED {datetime.utcfromtimestamp(tm[y['dead']]):%Y-%m-%d}")
    else:
        print(f"  cap {cap:<4} ${y['eq']:>9,.2f}   lowest ${y['lo']:>8,.2f}   dd ${y['mdd']:>8,.2f}")

print(f"\nFOR COMPARISON: the real live bot (TP $2.50-ish, brick-scaled) ended at $584.10 on this same data/period.")
