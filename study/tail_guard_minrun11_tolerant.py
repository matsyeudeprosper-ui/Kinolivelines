"""Side test v2: run-length filter with tolerance for one isolated
opposite-color brick within an otherwise same-color swing (a single lone
counter-brick that gets immediately reversed does not break the count -
only 2+ consecutive opposite bricks count as a genuine new swing).
Same TP=$1, SL=1-in-100 percentile (recalibrated for this signal), cap=1.
Multi-anchor validated.
"""
import numpy as np
import MetaTrader5 as mt5
from datetime import datetime
from collections import Counter

PCT, SPCT = 50.0 / 64000.0, 10.0 / 64000.0
REV, PT = 2, 0.01
TP_USD = 1.0
TP_PTS = TP_USD / PT
CALIBRATE_WINDOW = 2000
FROM = datetime(2022, 1, 1)
MIN_RUN = 11


def build_brick_dirs(o, h, l, c, N):
    dirs = []
    bar_idx = []
    ao = ac = float(o[0])
    d = 0
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
            dirs.append(d)
            bar_idx.append(i)
    return dirs, bar_idx


def tolerant_runlengths(dirs):
    n = len(dirs)
    if n == 0:
        return []
    runlen = [0] * n
    color = dirs[0]
    count = 1
    blip_used = False
    runlen[0] = 1
    i = 1
    while i < n:
        if dirs[i] == color:
            count += 1
            runlen[i] = count
            i += 1
        else:
            if (not blip_used) and i + 1 < n and dirs[i + 1] == color:
                blip_used = True
                runlen[i] = count
                i += 1
            else:
                color = dirs[i]
                count = 1
                blip_used = False
                runlen[i] = 1
                i += 1
    return runlen


def signals_with_tolerant_runlength(o, h, l, c, N):
    dirs, bar_idx = build_brick_dirs(o, h, l, c, N)
    rl = tolerant_runlengths(dirs)
    revs = {}
    runlen_at_reversal = {}
    prev_dir = dirs[0] if dirs else None
    for k in range(1, len(dirs)):
        if dirs[k] != prev_dir and rl[k] == 1:
            revs.setdefault(bar_idx[k], dirs[k])
            runlen_at_reversal[bar_idx[k]] = rl[k - 1]
        prev_dir = dirs[k]
    return revs, runlen_at_reversal


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


def run(o, h, l, c, tm, N, sigs, runlen, SL_PTS, min_run):
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
    entry_days = []
    filtered_out = 0
    passed = 0
    for j in range(N):
        if pending is not None:
            L, entry = pending
            in_pos = True
            pos_L = L
            pos_entry = entry
            pending = None
        if j in sigs and j + 1 < N and not in_pos:
            if runlen.get(j, 0) < min_run:
                filtered_out += 1
            else:
                passed += 1
                L = (sigs[j] == 1)
                SP = c[j] * SPCT
                entry = o[j + 1] + SP if L else o[j + 1]
                pending = (L, entry)
                entry_days.append(datetime.utcfromtimestamp(tm[j + 1]).date())
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
            return dict(dead=True, entry_days=entry_days)
    pnl = np.array(pnl_list) if pnl_list else np.array([0.0])
    return dict(dead=False, trades=len(pnl), wins=wins, losses=losses, end=bal, lo=lo, mdd=mdd,
                winrate=100 * wins / max(1, len(pnl)), entry_days=entry_days,
                passed=passed, filtered_out=filtered_out)


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

print("filter: >= " + str(MIN_RUN) + " bricks, tolerant of one isolated opposite brick")
print()
print("anchor  test period               SL($)  trades   win%      ended    lowest   pass%")
results = []
all_entry_days = []
all_span_days = []
for i in range(1, NSEG):
    cal_end = bounds[i]
    test_start, test_end = bounds[i], bounds[i + 1]
    oc, hc, lc, cc = o[:cal_end], h[:cal_end], l[:cal_end], c[:cal_end]
    sigc, runlenc = signals_with_tolerant_runlength(oc, hc, lc, cc, cal_end)
    sigc_f = {j: d for j, d in sigc.items() if runlenc.get(j, 0) >= MIN_RUN}
    dist = worst_adverse_distribution(oc, hc, lc, cc, cal_end, sigc_f)
    SL_USD = np.percentile(dist, 99) * PT
    SL_PTS = SL_USD / PT
    ot, ht, lt, ct, tmt = o[test_start:test_end], h[test_start:test_end], l[test_start:test_end], c[test_start:test_end], tm[test_start:test_end]
    Nt = test_end - test_start
    sigt, runlent = signals_with_tolerant_runlength(ot, ht, lt, ct, Nt)
    z = run(ot, ht, lt, ct, tmt, Nt, sigt, runlent, SL_PTS, MIN_RUN)
    d0 = datetime.utcfromtimestamp(tmt[0]).strftime("%Y-%m-%d")
    d1 = datetime.utcfromtimestamp(tmt[-1]).strftime("%Y-%m-%d")
    results.append(z)
    all_entry_days.extend(z["entry_days"])
    all_span_days.extend([datetime.utcfromtimestamp(t).date() for t in tmt])
    if z["dead"]:
        print("seg " + str(i) + "   " + d0 + " to " + d1 + "   DIED")
    else:
        passrate = 100 * z["passed"] / max(1, z["passed"] + z["filtered_out"])
        print("seg %d   %s to %s  $%7.2f %7d %5.1f%% $%9.2f $%8.2f %6.1f%%" % (
            i, d0, d1, SL_USD, z["trades"], z["winrate"], z["end"], z["lo"], passrate))

n_dead = sum(1 for zz in results if zz["dead"])
n_profit = sum(1 for zz in results if not zz["dead"] and zz["end"] > 1000)
day_counter = Counter(all_entry_days)
total_days = len(set(all_span_days))
print()
print("SUMMARY: died %d/5   profitable %d/5   losing-but-survived %d/5" % (n_dead, n_profit, 5 - n_dead - n_profit))
print("days with >=1 trade: %.1f%%   avg trades/day: %.2f" % (100 * len(day_counter) / total_days, sum(day_counter.values()) / total_days))
print()
print("FOR COMPARISON, original cap=1 (no filter):")
print("seg1 $1031 | seg2 $754 loss | seg3 $1074 | seg4 $1258 | seg5 $1302 | 0/5 died | 17.1% active days | 0.54 trades/day")
print("strict (no-tolerance) >=11 filter from the previous test:")
print("seg1 $1034 | seg2 $790 loss | seg3 $969 loss | seg4 $887 loss | seg5 $1146 | 0/5 died | 24.8% active days | 0.59 trades/day")
