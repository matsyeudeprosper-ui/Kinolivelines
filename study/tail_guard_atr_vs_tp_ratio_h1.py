"""User's idea, tested properly: filter/bucket trades by
ratio = ATR14(H1) / TP_PTS(100) - 'is ATR big enough relative to the TP
distance that we're easily ready to reach it' - as opposed to the
already-killed 'ATR vs its own history percentile' filter. Multi-anchor,
causal SL calibration per anchor (99th pctile of prior worst-adverse),
same methodology as every other filter tested today.
"""
import numpy as np
import MetaTrader5 as mt5
from datetime import datetime

PCT, SPCT = 50.0 / 64000.0, 10.0 / 64000.0
REV, PT = 2, 0.01
TP_PTS = 100.0
FROM = datetime(2022, 1, 1)


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


def worst_adverse_distribution(o, h, l, c, N, sigs, window=2000):
    vals = []
    for j, dirn in sigs.items():
        if j + 1 >= N:
            continue
        ent_bar = j + 1; SP = c[j] * SPCT; L = (dirn == 1)
        entry = o[ent_bar] + SP if L else o[ent_bar]
        end = min(N, ent_bar + window)
        worst = 0.0
        for k in range(ent_bar, end):
            adv = (entry - l[k]) if L else (h[k] - entry)
            if adv > worst:
                worst = adv
        vals.append(worst)
    return np.array(vals)


def run(o, h, l, c, tm, atr, offset, N, sigs, SL_PTS, ratio_thr):
    bal = 1000.0; peak = bal; mdd = 0.0; lo = bal
    wins = losses = 0; durs = []
    pending = None; in_pos = False; pos_L = None; pos_entry = None; pos_entry_t = None
    filtered_out = 0
    for j in range(N):
        if pending is not None:
            L, entry, et = pending
            in_pos = True; pos_L = L; pos_entry = entry; pos_entry_t = et; pending = None
        if j in sigs and j + 1 < N and not in_pos:
            ratio = atr[offset + j] / TP_PTS
            if ratio < ratio_thr:
                filtered_out += 1
            else:
                L = (sigs[j] == 1); SP = c[j] * SPCT
                entry = o[j + 1] + SP if L else o[j + 1]
                pending = (L, entry, tm[j + 1])
        if in_pos:
            tp_price = pos_entry + TP_PTS if pos_L else pos_entry - TP_PTS
            sl_price = pos_entry - SL_PTS if pos_L else pos_entry + SL_PTS
            hit_tp = (h[j] >= tp_price) if pos_L else (l[j] <= tp_price)
            hit_sl = (l[j] <= sl_price) if pos_L else (h[j] >= sl_price)
            if hit_tp and hit_sl:
                bal -= SL_PTS * PT; losses += 1; in_pos = False
                durs.append((tm[j] - pos_entry_t) / 3600)
            elif hit_tp:
                bal += TP_PTS * PT; wins += 1; in_pos = False
                durs.append((tm[j] - pos_entry_t) / 3600)
            elif hit_sl:
                bal -= SL_PTS * PT; losses += 1; in_pos = False
                durs.append((tm[j] - pos_entry_t) / 3600)
        peak = max(peak, bal); mdd = max(mdd, peak - bal); lo = min(lo, bal)
        if bal <= 0:
            return dict(dead=True, filtered_out=filtered_out)
    durs = np.array(durs) if durs else np.array([0.0])
    trades = wins + losses
    return dict(dead=False, trades=trades, wins=wins, losses=losses, end=bal, lo=lo, mdd=mdd,
                winrate=100 * wins / max(1, trades), median_dur=np.median(durs),
                filtered_out=filtered_out)


mt5.initialize(path=r"C:\Program Files\MetaTrader 5\terminal64.exe")
r = mt5.copy_rates_from_pos("BTCUSDm", mt5.TIMEFRAME_H1, 0, 80000)
mt5.shutdown()
keep = r["time"] >= FROM.timestamp()
r = r[keep]
o, h, l, c = (r[k].astype(float) for k in ("open", "high", "low", "close"))
tm = r["time"]; N = len(c)

tr = np.zeros(N)
for i in range(1, N):
    tr[i] = max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1]))
atr14 = np.zeros(N)
for i in range(14, N):
    atr14[i] = tr[i - 13:i + 1].mean()

NSEG = 6
bounds = [int(N * i / NSEG) for i in range(NSEG + 1)]

for RATIO_THR in (0.0, 0.5, 1.0, 1.5, 2.0):
    print(f"\n=== ratio_thr = {RATIO_THR}  (skip signal if ATR14/TP_PTS < {RATIO_THR}) ===")
    print(f"{'anchor':>7} {'test period':>23} {'SL($)':>8} {'trades':>7} {'filtered':>9} {'win%':>6} {'medDur':>8} {'ended':>10} {'lowest':>9}")
    results = []
    for i in range(1, NSEG):
        cal_end = bounds[i]
        test_start, test_end = bounds[i], bounds[i + 1]
        oc, hc, lc, cc = o[:cal_end], h[:cal_end], l[:cal_end], c[:cal_end]
        sigc = signals_reversal(oc, hc, lc, cc, cal_end)
        dist = worst_adverse_distribution(oc, hc, lc, cc, cal_end, sigc)
        SL_USD = np.percentile(dist, 99) * PT
        SL_PTS = SL_USD / PT

        ot, ht, lt, ct, tmt = o[test_start:test_end], h[test_start:test_end], l[test_start:test_end], c[test_start:test_end], tm[test_start:test_end]
        Nt = test_end - test_start
        sigt = signals_reversal(ot, ht, lt, ct, Nt)
        z = run(ot, ht, lt, ct, tmt, atr14, test_start, Nt, sigt, SL_PTS, RATIO_THR)
        d0 = datetime.utcfromtimestamp(tmt[0]).strftime("%Y-%m-%d")
        d1 = datetime.utcfromtimestamp(tmt[-1]).strftime("%Y-%m-%d")
        results.append(z)
        if z["dead"]:
            print(f"seg {i:>3}   {d0} to {d1}   *** DIED ***  (filtered {z['filtered_out']})")
        else:
            print(f"seg {i:>3}   {d0} to {d1}  ${SL_USD:>7.2f} {z['trades']:>7} {z['filtered_out']:>9} "
                  f"{z['winrate']:>5.1f}% {z['median_dur']:>7.1f}h ${z['end']:>9,.2f} ${z['lo']:>8,.2f}")
    n_dead = sum(1 for z in results if z["dead"])
    n_profit = sum(1 for z in results if not z["dead"] and z["end"] > 1000)
    print(f"SUMMARY: died {n_dead}/{len(results)}   profitable {n_profit}/{len(results)}")

print(f"\n=== FOR COMPARISON: cap=1, NO filter (from before) ===")
print(f"seg1 $1031 | seg2 $754 (real loss) | seg3 $1074 | seg4 $1258 | seg5 $1302 | 0/5 died")
