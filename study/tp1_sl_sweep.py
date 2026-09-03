"""Sweep of fixed SL sizes (no lookahead - round numbers picked upfront,
not derived from the backtest's own worst case) against TP=$1, same live
bot entry (A0), single position per signal, no daily limit."""
import numpy as np
import MetaTrader5 as mt5
from datetime import datetime

PCT, SPCT = 50.0 / 64000.0, 10.0 / 64000.0
REV, PT = 2, 0.01
FROM = datetime(2022, 1, 1)
TP_USD = 1.0
TP_PTS = TP_USD / PT

mt5.initialize(path=r"C:\Program Files\MetaTrader 5\terminal64.exe")
r = mt5.copy_rates_from_pos("BTCUSDm", mt5.TIMEFRAME_H1, 0, 80000)
mt5.shutdown()
keep = r["time"] >= FROM.timestamp()
r = r[keep]
o, h, l, c = (r[k].astype(float) for k in ("open", "high", "low", "close"))
N = len(c)


def signals_reversal():
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


sigs = signals_reversal()


def run(SL_USD):
    SL_PTS = SL_USD / PT
    bal = 1000.0; peak = bal; mdd = 0.0; lo = bal
    wins = losses = 0
    pnl_list = []
    pending = None; in_pos = False; pos_L = None; pos_entry = None
    for j in range(N):
        if pending is not None:
            L, entry = pending
            in_pos = True; pos_L = L; pos_entry = entry; pending = None
        if j in sigs and j + 1 < N and not in_pos:
            L = (sigs[j] == 1)
            SP = c[j] * SPCT
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
            return dict(dead=True, SL=SL_USD)
    pnl = np.array(pnl_list) if pnl_list else np.array([0.0])
    return dict(dead=False, SL=SL_USD, trades=len(pnl), wins=wins, losses=losses,
                end=bal, lo=lo, mdd=mdd, mddp=100*mdd/peak, exp=pnl.mean(),
                worst=pnl.min(), winrate=100*wins/max(1,len(pnl)),
                be_winrate=100*SL_PTS/(SL_PTS+TP_PTS))


print(f"TP fixed at $1.00, single position, no daily limit, same live-bot entry\n")
print(f"{'SL':>8} {'trades':>7} {'win%':>6} {'need%':>6} {'ended':>10} {'lowest':>9} {'worstDD':>9} {'worst trade':>12} {'exp/trade':>10}")
for SL_USD in (1.0, 2.0, 3.0, 5.0, 7.5, 10.0, 15.0, 20.0, 30.0, 50.0, 75.0, 100.0, 150.0, 200.0):
    z = run(SL_USD)
    if z["dead"]:
        print(f"{SL_USD:>7.2f}$  *** ACCOUNT HIT ZERO ***")
        continue
    print(f"{SL_USD:>7.2f}$ {z['trades']:>7} {z['winrate']:>5.1f}% {z['be_winrate']:>5.1f}% "
          f"${z['end']:>9,.2f} ${z['lo']:>8,.2f} ${z['mdd']:>8,.2f} ${z['worst']:>11,.2f} ${z['exp']:>+9.3f}")
