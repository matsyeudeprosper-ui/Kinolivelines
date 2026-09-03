"""Test: use the NARROWEST of the 5 validated SL calibrations ($266.68 at
0.01 lots, from segment 2) as a FIXED SL across all 5 periods, instead of
recalibrating per-anchor. Same TP point distance (100pts). Multi-anchor
validated, same 5 segments as the accepted Tail Guard version. Dollar
figures reported at 0.01 lots AND scaled to 0.05 lots (TP=$5) since that's
what was asked.
"""
import numpy as np
import MetaTrader5 as mt5
from datetime import datetime

PCT, SPCT = 50.0 / 64000.0, 10.0 / 64000.0
REV, PT = 2, 0.01
TP_PTS = 100.0
SL_USD_MIN_FIXED = 266.68
SL_PTS_FIXED = SL_USD_MIN_FIXED / PT
FROM = datetime(2022, 1, 1)


def signals_reversal(o, h, l, c, N):
    revs = {}
    ao = ac = float(o[0])
    d = 0
    pd_ = 0
    for i in range(N):
        B = c[i] * PCT
        while True:
            up = (ao if d == -1 else ac) + B * (REV if d == -1 else 1)
            dn = (ao if d == 1 else ac) - B * (REV if d == 1 else 1)
            if c[i] >= up:
                base = ao if d == -1 else ac
                ao, ac, d = base, base + B, 1
            elif c[i] <= dn:
                base = ao if d == 1 else ac
                ao, ac, d = base, base - B, -1
            else:
                break
            if pd_ and d != pd_:
                revs.setdefault(i, d)
            pd_ = d
    return revs


def run(o, h, l, c, N, sigs, SL_PTS, TP_PTS):
    bal = 1000.0
    peak = bal
    mdd = 0.0
    lo = bal
    wins = losses = 0
    pnl_list = []
    pending = None
    in_pos = False
    pos_L = None
    pos_entry = None
    for j in range(N):
        if pending is not None:
            L, entry = pending
            in_pos = True
            pos_L = L
            pos_entry = entry
            pending = None
        if j in sigs and j + 1 < N and not in_pos:
            L = (sigs[j] == 1)
            SP = c[j] * SPCT
            entry = o[j + 1] + SP if L else o[j + 1]
            pending = (L, entry)
        if in_pos:
            tp_price = pos_entry + TP_PTS if pos_L else pos_entry - TP_PTS
            sl_price = pos_entry - SL_PTS if pos_L else pos_entry + SL_PTS
            hit_tp = (h[j] >= tp_price) if pos_L else (l[j] <= tp_price)
            hit_sl = (l[j] <= sl_price) if pos_L else (h[j] >= sl_price)
            if hit_tp and hit_sl:
                bal -= SL_PTS * PT
                pnl_list.append(-SL_PTS * PT)
                losses += 1
                in_pos = False
            elif hit_tp:
                bal += TP_PTS * PT
                pnl_list.append(TP_PTS * PT)
                wins += 1
                in_pos = False
            elif hit_sl:
                bal -= SL_PTS * PT
                pnl_list.append(-SL_PTS * PT)
                losses += 1
                in_pos = False
        peak = max(peak, bal)
        mdd = max(mdd, peak - bal)
        lo = min(lo, bal)
        if bal <= 0:
            return dict(dead=True)
    pnl = np.array(pnl_list) if pnl_list else np.array([0.0])
    return dict(dead=False, trades=len(pnl), wins=wins, losses=losses, end=bal, lo=lo, mdd=mdd,
                winrate=100 * wins / max(1, len(pnl)))


mt5.initialize(path=r"C:\Program Files\MetaTrader 5\terminal64.exe")
r = mt5.copy_rates_from_pos("BTCUSDm", mt5.TIMEFRAME_H1, 0, 80000)
mt5.shutdown()
keep = r["time"] >= FROM.timestamp()
r = r[keep]
o, h, l, c = (r[k].astype(float) for k in ("open", "high", "low", "close"))
tm = r["time"]
N = len(c)
NSEG = 6
bounds = [int(N * i / NSEG) for i in range(NSEG + 1)]
SCALE_005 = 5.0  # 0.05 lots / 0.01 lots baseline

print("SL FIXED at the minimum validated value: $%.2f (%.0f pts) at 0.01 lots" % (SL_USD_MIN_FIXED, SL_PTS_FIXED))
print("TP fixed at 100pts ($1.00 at 0.01 lots)\n")
print("anchor  test period               trades   win%      ended(0.01L)   lowest(0.01L)")
results = []
for i in range(1, NSEG):
    test_start, test_end = bounds[i], bounds[i + 1]
    ot, ht, lt, ct = o[test_start:test_end], h[test_start:test_end], l[test_start:test_end], c[test_start:test_end]
    Nt = test_end - test_start
    sigt = signals_reversal(ot, ht, lt, ct, Nt)
    z = run(ot, ht, lt, ct, Nt, sigt, SL_PTS_FIXED, TP_PTS)
    d0 = datetime.utcfromtimestamp(tm[test_start]).strftime("%Y-%m-%d")
    d1 = datetime.utcfromtimestamp(tm[test_end - 1]).strftime("%Y-%m-%d")
    results.append(z)
    if z["dead"]:
        print("seg %d   %s to %s   DIED" % (i, d0, d1))
    else:
        print("seg %d   %s to %s  %6d  %5.1f%%   $%9.2f      $%8.2f" % (
            i, d0, d1, z["trades"], z["winrate"], z["end"], z["lo"]))

n_dead = sum(1 for zz in results if zz["dead"])
n_profit = sum(1 for zz in results if not zz["dead"] and zz["end"] > 1000)
print("\nSUMMARY (0.01 lots): died %d/5   profitable %d/5" % (n_dead, n_profit))

print("\n=== same results, SCALED to 0.05 lots (TP=$5.00, SL=$%.2f) ===" % (SL_USD_MIN_FIXED * SCALE_005))
print("anchor   profit at 0.05L   lowest-equity-implied-dd at 0.05L")
for i, z in enumerate(results, start=1):
    if z["dead"]:
        print("seg %d   DIED (would die at any lot size - this is a % loss pattern, not a $ one)" % i)
        continue
    profit_001 = z["end"] - 1000.0
    profit_005 = profit_001 * SCALE_005
    dd_001 = 1000.0 - z["lo"]
    dd_005 = dd_001 * SCALE_005
    print("seg %d   %+9.2f          dd $%8.2f" % (i, profit_005, dd_005))
