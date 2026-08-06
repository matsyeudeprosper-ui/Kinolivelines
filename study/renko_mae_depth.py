"""How deep does a position go AGAINST you before it resolves?

The harvest bot has no stop loss, so this is the number that decides how bad a
bad trade can get. Measured per position from entry until it closes (or until
the data ends), and per BASKET, which is what the account actually feels.

M5, 278 days - the longest window with full coverage, so the tail is real rather
than a 56-day sample.
"""
import numpy as np
import MetaTrader5 as mt5
from datetime import datetime

SPREAD = 10.0
BRICK, REV = 50.0, 2
import sys
TP, SL, PT, START = 250.0, 150.0, 0.01, 1000.0
CAP = int(sys.argv[1]) if len(sys.argv)>1 else 4

mt5.initialize(path=r"C:\Program Files\MetaTrader 5\terminal64.exe")
R = mt5.copy_rates_from_pos("BTCUSDm", mt5.TIMEFRAME_M5, 0, 80000)
mt5.shutdown()
o, h, l, c = (R[k].astype(float) for k in ("open", "high", "low", "close"))
tm = R["time"]; N = len(c)
print(f"M5, {(tm[-1]-tm[0])/86400:.0f} days\n")

ao = ac = float(o[0]); d = 0; pd_ = 0
bal = START; cyc = START
ent = np.empty(0); lng = np.empty(0, dtype=bool); mae = np.empty(0)
rec = False; pending = None
pos_mae = []            # per position, points against at its worst
bask_mae = []           # per basket, worst dollars underwater
cur_bask = 0.0
for j in range(N):
    if pending is not None:
        L = pending
        ent = np.append(ent, o[j] + SPREAD if L else o[j])
        lng = np.append(lng, L); mae = np.append(mae, 0.0); pending = None
    ci = c[j]
    while True:
        u = (ao if d == -1 else ac) + BRICK * (REV if d == -1 else 1)
        n = (ao if d == 1 else ac) - BRICK * (REV if d == 1 else 1)
        if ci >= u:
            base = ao if d == -1 else ac; ao, ac, d = base, base + BRICK, 1
        elif ci <= n:
            base = ao if d == 1 else ac; ao, ac, d = base, base - BRICK, -1
        else:
            break
        if pd_ and d != pd_ and pending is None:
            if ((len(ent) == 0) or (rec and len(ent) <= CAP)) and j + 1 < N:
                pending = (d == 1)
        pd_ = d
    if len(ent):
        # worst point of this bar for each position
        adv = np.where(lng, ent - l[j], h[j] + SPREAD - ent)
        mae = np.maximum(mae, adv)
        hit = np.where(lng, h[j] >= ent + TP, l[j] <= ent - TP - SPREAD)
        if hit.any():
            bal += float(hit.sum()) * TP * PT
            pos_mae.extend(mae[hit].tolist())
            ent, lng, mae = ent[~hit], lng[~hit], mae[~hit]
    if len(ent) and not rec:
        if np.where(lng, l[j] <= ent - SL, h[j] >= ent + SL + SPREAD).any():
            rec = True
    flo = float(np.sum(np.where(lng, c[j]-ent, ent-c[j]-SPREAD)) * PT) if len(ent) else 0.0
    cur_bask = min(cur_bask, flo)
    eq = bal + flo
    closed = None
    if rec and len(ent) and eq >= cyc:
        closed = 1
    elif len(ent) > CAP:
        closed = 1
    if closed:
        pos_mae.extend(mae.tolist())
        bal = eq; ent = np.empty(0); lng = np.empty(0, dtype=bool); mae = np.empty(0)
        eq = bal
    if len(ent) == 0:
        if cur_bask < 0:
            bask_mae.append(-cur_bask)
        cur_bask = 0.0; rec = False; cyc = bal
    if eq <= 0:
        print('*** ACCOUNT HIT ZERO at', datetime.utcfromtimestamp(tm[j]).strftime('%Y-%m-%d'), '***')
        break
pos_mae.extend(mae.tolist())

p = np.array(pos_mae); b = np.array(bask_mae)
print(f"PER POSITION - points against before it resolved   ({len(p)} positions)")
for q, lab in ((50, "median"), (75, "75th"), (90, "90th"), (95, "95th"),
               (99, "99th"), (99.9, "99.9th")):
    print(f"  {lab:<8} {np.percentile(p, q):>8.0f} pts   = {np.percentile(p,q)*PT:>6.2f} $")
print(f"  WORST    {p.max():>8.0f} pts   = {p.max()*PT:>6.2f} $   "
      f"({p.max()/BRICK:.0f} bricks)")
print(f"  the recovery trigger sits at {SL:.0f} pts; "
      f"{100*(p>SL).mean():.0f}% of positions cross it")

print(f"\nPER BASKET - worst dollars underwater in a cycle   ({len(b)} cycles)")
for q, lab in ((50, "median"), (90, "90th"), (99, "99th")):
    print(f"  {lab:<8} ${np.percentile(b, q):>7.2f}")
print(f"  WORST    ${b.max():>7.2f}   = {100*b.max()/START:.1f}% of a $1,000 account")
print("")
print(f"  baskets deeper than $92 (the capped worst): {int((b>91.97).sum())} of {len(b)} ({100*(b>91.97).mean():.1f}%)")
print(f"  baskets deeper than $17 (the capped 90th) : {int((b>17.06).sum())} of {len(b)} ({100*(b>17.06).mean():.1f}%)")
print(f"  final equity ${eq:,.2f}")
