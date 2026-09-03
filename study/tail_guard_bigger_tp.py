"""Test: raise TP while keeping the same SL methodology (1-in-100 percentile,
calibrated per-anchor, no lookahead). Does a bigger TP widen the safety
margin above breakeven, or does the win rate drop enough (waiting longer
for a farther target) to cancel the benefit? Multi-anchor validated, same
5 segments as the accepted Tail Guard version.
"""
import numpy as np
import MetaTrader5 as mt5
from datetime import datetime

PCT, SPCT = 50.0 / 64000.0, 10.0 / 64000.0
REV, PT = 2, 0.01
CALIBRATE_WINDOW = 2000
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


def worst_adverse_distribution(o, h, l, c, N, sigs):
    vals = []
    for j, dirn in sigs.items():
        if j + 1 >= N:
            continue
        ent_bar = j + 1
        SP = c[j] * SPCT
        L = (dirn == 1)
        entry = o[ent_bar] + SP if L else o[ent_bar]
        end = min(N, ent_bar + CALIBRATE_WINDOW)
        worst = 0.0
        for k in range(ent_bar, end):
            adv = (entry - l[k]) if L else (h[k] - entry)
            if adv > worst:
                worst = adv
        vals.append(worst)
    return np.array(vals)


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

TP_OPTIONS_USD = [1.0, 2.0, 3.0, 5.0, 7.0, 10.0, 15.0, 20.0]

for tp_usd in TP_OPTIONS_USD:
    TP_PTS = tp_usd / PT
    print("=" * 100)
    print("TP = $%.2f (%d pts)" % (tp_usd, TP_PTS))
    print("anchor  test period               SL($)  breakeven%%  trades   win%%      ended    lowest")
    results = []
    for i in range(1, NSEG):
        cal_end = bounds[i]
        test_start, test_end = bounds[i], bounds[i + 1]
        oc, hc, lc, cc = o[:cal_end], h[:cal_end], l[:cal_end], c[:cal_end]
        sigc = signals_reversal(oc, hc, lc, cc, cal_end)
        dist = worst_adverse_distribution(oc, hc, lc, cc, cal_end, sigc)
        SL_USD = np.percentile(dist, 99) * PT
        SL_PTS = SL_USD / PT
        breakeven_pct = 100 * SL_PTS / (SL_PTS + TP_PTS)

        ot, ht, lt, ct = o[test_start:test_end], h[test_start:test_end], l[test_start:test_end], c[test_start:test_end]
        Nt = test_end - test_start
        sigt = signals_reversal(ot, ht, lt, ct, Nt)
        z = run(ot, ht, lt, ct, Nt, sigt, SL_PTS, TP_PTS)
        d0 = datetime.utcfromtimestamp(tm[test_start]).strftime("%Y-%m-%d")
        d1 = datetime.utcfromtimestamp(tm[test_end - 1]).strftime("%Y-%m-%d")
        results.append(z)
        if z["dead"]:
            print("seg %d   %s to %s   DIED" % (i, d0, d1))
        else:
            print("seg %d   %s to %s  $%6.2f   %6.2f%%  %6d  %5.1f%%  $%9.2f  $%8.2f" % (
                i, d0, d1, SL_USD, breakeven_pct, z["trades"], z["winrate"], z["end"], z["lo"]))
    n_dead = sum(1 for zz in results if zz["dead"])
    n_profit = sum(1 for zz in results if not zz["dead"] and zz["end"] > 1000)
    total_end = sum((zz["end"] if not zz["dead"] else 0) for zz in results)
    print("SUMMARY: died %d/5   profitable %d/5   sum of 5 endings: $%.2f (vs $5000 if all flat)" % (
        n_dead, n_profit, total_end))
    print()
