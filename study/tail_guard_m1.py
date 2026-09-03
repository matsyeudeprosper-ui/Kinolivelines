"""Tail Guard on M1 data. M1 broker history is short (~55 days per prior
project notes) so this is a much smaller, noisier sample than the H1 test -
using it only for minute-level timing precision, not as a replacement for
the H1 result. SL reused from the H1 calibration ($311.48, 1-in-100) since
55 days is nowhere near enough to recalibrate a rare-event percentile.
"""
import numpy as np
import MetaTrader5 as mt5
from datetime import datetime

PCT, SPCT = 50.0 / 64000.0, 10.0 / 64000.0
REV, PT = 2, 0.01
TP_USD = 1.0
TP_PTS = TP_USD / PT
SL_USD = 311.48  # reused from the H1 1-in-100 calibration
SL_PTS = SL_USD / PT

mt5.initialize(path=r"C:\Program Files\MetaTrader 5\terminal64.exe")
r = mt5.copy_rates_from_pos("BTCUSDm", mt5.TIMEFRAME_M1, 0, 80000)
mt5.shutdown()
o, h, l, c = (r[k].astype(float) for k in ("open", "high", "low", "close"))
tm = r["time"]
N = len(c)
print(f"M1 bars {N}   {datetime.utcfromtimestamp(tm[0])} -> {datetime.utcfromtimestamp(tm[-1])}   "
      f"({(tm[-1]-tm[0])/86400:.1f} days of history)\n")
print(f"TP ${TP_USD:.2f}   SL ${SL_USD:.2f} (reused from H1 1-in-100 calibration)\n")


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


sigs = signals_reversal(o, h, l, c, N)

trades = []
pending = None; in_pos = False; pos_L = None; pos_entry = None; pos_entry_t = None
for j in range(N):
    if pending is not None:
        L, entry, et = pending
        in_pos = True; pos_L = L; pos_entry = entry; pos_entry_t = et; pending = None
    if j in sigs and j + 1 < N and not in_pos:
        L = (sigs[j] == 1); SP = c[j] * SPCT
        entry = o[j+1] + SP if L else o[j+1]
        pending = (L, entry, tm[j+1])
    if in_pos:
        tp_price = pos_entry + TP_PTS if pos_L else pos_entry - TP_PTS
        sl_price = pos_entry - SL_PTS if pos_L else pos_entry + SL_PTS
        hit_tp = (h[j] >= tp_price) if pos_L else (l[j] <= tp_price)
        hit_sl = (l[j] <= sl_price) if pos_L else (h[j] >= sl_price)
        if hit_tp and hit_sl:
            trades.append((pos_entry_t, tm[j], -SL_PTS*PT)); in_pos = False
        elif hit_tp:
            trades.append((pos_entry_t, tm[j], TP_PTS*PT)); in_pos = False
        elif hit_sl:
            trades.append((pos_entry_t, tm[j], -SL_PTS*PT)); in_pos = False

if not trades:
    print("No completed trades in this M1 window.")
else:
    et_arr = np.array([t[0] for t in trades])
    pnl = np.array([t[2] for t in trades])
    dates = np.array([datetime.utcfromtimestamp(t) for t in et_arr])
    span_days = (et_arr[-1]-et_arr[0])/86400 if len(et_arr) > 1 else 1
    print(f"signals: {len(sigs)}   trades opened: {len(trades)}   wins: {(pnl>0).sum()}   losses: {(pnl<0).sum()}")
    print(f"win rate: {100*np.mean(pnl>0):.1f}%")
    print(f"total P&L: ${pnl.sum():+.2f}   span {span_days:.1f} days")
    if span_days > 0:
        print(f"per day: trades {len(trades)/span_days:.2f}   $ {pnl.sum()/span_days:+.3f}")
    print(f"\nstill open at end of data: {'yes' if in_pos else 'no'}")
    if in_pos:
        floating = (c[-1]-pos_entry) if pos_L else (pos_entry-c[-1])
        print(f"  open since {datetime.utcfromtimestamp(pos_entry_t)} UTC, {'BUY' if pos_L else 'SELL'}, "
              f"floating ${floating*PT:+.2f}")

    losses = [t for t in trades if t[2] < 0]
    print(f"\nLOSSES (hour:minute precision, M1):")
    for et_, xt_, p_ in losses:
        print(f"  entry {datetime.utcfromtimestamp(et_)} UTC   exit {datetime.utcfromtimestamp(xt_)} UTC   pnl ${p_:+.2f}")

    print(f"\nWINS by hour (UTC, M1 entries):")
    hours = np.array([d.hour for d in dates])
    for hr in range(24):
        m = hours == hr
        n = m.sum()
        if n == 0: continue
        print(f"  {hr:02d}:00  trades {n:>4}  win% {100*np.mean(pnl[m]>0):5.1f}%  total ${pnl[m].sum():>+7.2f}")
