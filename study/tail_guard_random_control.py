"""Random-entry control: same TP=$1 / SL=$311.48 (1-in-100), same second
half (out-of-sample) period, same NUMBER of candidate signals as A0's
actual reversal-brick signals - but placed at random bars with random
direction instead. If random does about as well as A0, the entry timing
isn't adding anything; the result would just be the TP:SL shape + market
drift. Averaged over 5 seeds.
"""
import numpy as np
import MetaTrader5 as mt5
from datetime import datetime

PCT, SPCT = 50.0 / 64000.0, 10.0 / 64000.0
REV, PT = 2, 0.01
FROM = datetime(2022, 1, 1)
TP_USD = 1.0
TP_PTS = TP_USD / PT
SL_USD = 311.48
SL_PTS = SL_USD / PT

mt5.initialize(path=r"C:\Program Files\MetaTrader 5\terminal64.exe")
r = mt5.copy_rates_from_pos("BTCUSDm", mt5.TIMEFRAME_H1, 0, 80000)
mt5.shutdown()
keep = r["time"] >= FROM.timestamp()
r = r[keep]
o, h, l, c = (r[k].astype(float) for k in ("open", "high", "low", "close"))
N = len(c)
HALF = N // 2
o2,h2,l2,c2 = o[HALF:],h[HALF:],l[HALF:],c[HALF:]
N2 = N - HALF


def signals_reversal(o, h, l, c, N):
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


def run(o,h,l,c,N,sigs):
    bal = 1000.0; peak = bal; mdd = 0.0; lo = bal
    wins = losses = 0; pnl_list = []
    pending = None; in_pos = False; pos_L = None; pos_entry = None
    for j in range(N):
        if pending is not None:
            L, entry = pending
            in_pos = True; pos_L = L; pos_entry = entry; pending = None
        if j in sigs and j + 1 < N and not in_pos:
            L = (sigs[j] == 1); SP = c[j] * SPCT
            entry = o[j+1] + SP if L else o[j+1]
            pending = (L, entry)
        if in_pos:
            tp_price = pos_entry + TP_PTS if pos_L else pos_entry - TP_PTS
            sl_price = pos_entry - SL_PTS if pos_L else pos_entry + SL_PTS
            hit_tp = (h[j] >= tp_price) if pos_L else (l[j] <= tp_price)
            hit_sl = (l[j] <= sl_price) if pos_L else (h[j] >= sl_price)
            if hit_tp and hit_sl:
                bal -= SL_PTS*PT; pnl_list.append(-SL_PTS*PT); losses += 1; in_pos = False
            elif hit_tp:
                bal += TP_PTS*PT; pnl_list.append(TP_PTS*PT); wins += 1; in_pos = False
            elif hit_sl:
                bal -= SL_PTS*PT; pnl_list.append(-SL_PTS*PT); losses += 1; in_pos = False
        peak = max(peak, bal); mdd = max(mdd, peak-bal); lo = min(lo, bal)
        if bal <= 0:
            return dict(dead=True, end=0.0)
    pnl = np.array(pnl_list) if pnl_list else np.array([0.0])
    return dict(dead=False, trades=len(pnl), wins=wins, losses=losses, end=bal, lo=lo,
                mdd=mdd, mddp=100*mdd/peak if peak else 0, winrate=100*wins/max(1,len(pnl)))


sig2 = signals_reversal(o2,h2,l2,c2,N2)
print(f"A0 (real entry) second half: {len(sig2)} candidate signals")
zA = run(o2,h2,l2,c2,N2,sig2)
print(f"  A0 result: trades {zA['trades']}  win% {zA['winrate']:.1f}%  losses {zA['losses']}  "
      f"ended ${zA['end']:,.2f}  lowest ${zA['lo']:,.2f}\n")

print(f"RANDOM entry control - same candidate-signal COUNT ({len(sig2)}), 5 seeds:")
results = []
for seed in range(5):
    rng = np.random.default_rng(seed)
    idx = rng.choice(N2 - 1, size=min(len(sig2), N2-1), replace=False)
    dirs = rng.choice([1,-1], size=len(idx))
    rsig = dict(zip(idx.tolist(), dirs.tolist()))
    z = run(o2,h2,l2,c2,N2,rsig)
    results.append(z)
    if z["dead"]:
        print(f"  seed {seed}: *** DIED ***")
    else:
        print(f"  seed {seed}: trades {z['trades']:>4}  win% {z['winrate']:>5.1f}%  losses {z['losses']:>2}  "
              f"ended ${z['end']:>9,.2f}  lowest ${z['lo']:>8,.2f}  dd ${z['mdd']:>8,.2f}")

ends = [z['end'] for z in results]
print(f"\nrandom average ended: ${np.mean(ends):,.2f}   (A0 real entry: ${zA['end']:,.2f})")
