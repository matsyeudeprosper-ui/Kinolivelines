"""Identify every losing trade across the original 5 validated multi-anchor
segments (TP=$1 @0.01 lots, SL=99th pctile calibrated per-anchor, no safety
floor - the CANDIDATE_TAIL_GUARD.md validated shape), then rerun the same
multi-anchor backtest with the entry-hour(s) of those losses excluded.
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


def run(o, h, l, c, tm, N, sigs, SL_PTS, excl_hours=frozenset()):
    bal = 1000.0; peak = bal; lo = bal
    wins = losses = 0
    pending = None; in_pos = False; pos_L = None; pos_entry = None; pos_entry_t = None
    trade_log = []
    for j in range(N):
        if pending is not None:
            L, entry, et = pending
            in_pos = True; pos_L = L; pos_entry = entry; pos_entry_t = et; pending = None
        if j in sigs and j + 1 < N and not in_pos:
            ent_hour = datetime.utcfromtimestamp(tm[j + 1]).hour
            if ent_hour not in excl_hours:
                L = (sigs[j] == 1); SP = c[j] * SPCT
                entry = o[j + 1] + SP if L else o[j + 1]
                pending = (L, entry, tm[j + 1])
        if in_pos:
            tp_price = pos_entry + TP_PTS if pos_L else pos_entry - TP_PTS
            sl_price = pos_entry - SL_PTS if pos_L else pos_entry + SL_PTS
            hit_tp = (h[j] >= tp_price) if pos_L else (l[j] <= tp_price)
            hit_sl = (l[j] <= sl_price) if pos_L else (h[j] >= sl_price)
            if hit_tp or hit_sl:
                outcome = "LOSS" if hit_sl else "WIN"
                pnl = -SL_PTS * PT if hit_sl else TP_PTS * PT
                bal += pnl
                if hit_sl: losses += 1
                else: wins += 1
                trade_log.append(dict(entry_t=pos_entry_t, exit_t=tm[j], outcome=outcome, pnl=pnl,
                                       entry_hour=datetime.utcfromtimestamp(pos_entry_t).hour))
                in_pos = False
        peak = max(peak, bal); lo = min(lo, bal)
        if bal <= 0:
            return dict(dead=True, trade_log=trade_log)
    return dict(dead=False, trades=wins + losses, wins=wins, losses=losses, end=bal, lo=lo,
                trade_log=trade_log)


mt5.initialize(path=r"C:\Program Files\MetaTrader 5\terminal64.exe")
r = mt5.copy_rates_from_pos("BTCUSDm", mt5.TIMEFRAME_H1, 0, 80000)
mt5.shutdown()
keep = r["time"] >= FROM.timestamp()
r = r[keep]
o, h, l, c = (r[k].astype(float) for k in ("open", "high", "low", "close"))
tm = r["time"]; N = len(c)
NSEG = 6
bounds = [int(N * i / NSEG) for i in range(NSEG + 1)]

print("=== PASS 1: baseline (no hour exclusion) - find every loss ===")
all_losses = []
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
    z = run(ot, ht, lt, ct, tmt, Nt, sigt, SL_PTS)
    d0 = datetime.utcfromtimestamp(tmt[0]).strftime("%Y-%m-%d")
    d1 = datetime.utcfromtimestamp(tmt[-1]).strftime("%Y-%m-%d")
    losses_here = [t for t in z["trade_log"] if t["outcome"] == "LOSS"]
    for t in losses_here:
        et = datetime.utcfromtimestamp(t["entry_t"])
        all_losses.append((i, et, t["entry_hour"], t["pnl"]))
    print(f"seg {i}  {d0} to {d1}  SL ${SL_USD:.2f}  trades {z['trades']}  losses {len(losses_here)}  ended ${z['end']:.2f}")

print(f"\nALL LOSSES FOUND ACROSS 5 SEGMENTS:")
for seg, et, eh, pnl in all_losses:
    print(f"  seg {seg}  entered {et}  hour={eh:02d}:00 UTC  pnl=${pnl:.2f}")

loss_hours = set(eh for _, _, eh, _ in all_losses)
print(f"\nhour(s) to exclude: {sorted(loss_hours)}")

print(f"\n=== PASS 2: rerun with those exact entry hour(s) excluded from ALL segments ===")
results2 = []
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
    z = run(ot, ht, lt, ct, tmt, Nt, sigt, SL_PTS, excl_hours=loss_hours)
    d0 = datetime.utcfromtimestamp(tmt[0]).strftime("%Y-%m-%d")
    d1 = datetime.utcfromtimestamp(tmt[-1]).strftime("%Y-%m-%d")
    losses_here = [t for t in z["trade_log"] if t["outcome"] == "LOSS"]
    results2.append(z)
    if z["dead"]:
        print(f"seg {i}  {d0} to {d1}  *** DIED ***")
    else:
        print(f"seg {i}  {d0} to {d1}  SL ${SL_USD:.2f}  trades {z['trades']}  losses {len(losses_here)}  ended ${z['end']:.2f}  lowest ${z['lo']:.2f}")

print(f"\n=== COMPARISON ===")
print(f"BEFORE (no exclusion):  seg1 $1031 | seg2 $754 (real loss) | seg3 $1074 | seg4 $1258 | seg5 $1302 | 0/5 died")
ends = [z['end'] for z in results2]
print(f"AFTER (excl hour {sorted(loss_hours)}): " + " | ".join(f"seg{k+1} ${e:.0f}" for k, e in enumerate(ends)))
