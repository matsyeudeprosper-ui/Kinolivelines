"""COIL V1 — frozen & approved 2026-08-25.
Compression (6-H1 box, CR = W / trailing-30d median, CR<=0.5, W>=66pts scale
filter) -> decisive M1 close >=0.1W beyond the FROZEN box edge -> enter next
M1 open, continuation direction. 12h max armed. One entry per event.
Baseline median uses ONLY completed data before the arming hour.
Single preregistered pass. No exits built. No rescue.
"""
import numpy as np
import datetime as dt

panel = open('kino_rangesweep_panel.py', encoding='utf-8').read()
anchor = "tm = np.array(times); N = len(times)"
head = panel[:panel.index(anchor) + len(anchor)]
for a, b in (("START_BAL = float(_sys.argv[1]) if len(_sys.argv) > 1 else 157.0", "START_BAL = 500.0"),
             ("NMIN = int(_sys.argv[2]) if len(_sys.argv) > 2 else 30", "NMIN = 30"),
             ("NRANGE = int(_sys.argv[3]) if len(_sys.argv) > 3 else 12", "NRANGE = 12"),
             ("TRENDF = (_sys.argv[4] if len(_sys.argv) > 4 else 'on') == 'on'   # 3-same-color filter", "TRENDF = False"),
             ("D1F = (_sys.argv[5] if len(_sys.argv) > 5 else 'on') == 'on'      # inside-yesterday filter", "D1F = False"),
             ("print(f'RANGE SWEEP V1: 12-H1 range, M1 sweep+reclaim, ranging-only filters | {NMIN}min | START {START_BAL}', flush=True)", "pass")):
    head = head.replace(a, b)
g = {}
exec(head, g)
o, h, l, c, tm, N = g['o'], g['h'], g['l'], g['c'], g['tm'], g['N']

print("COIL V1 (frozen) - compression -> decisive breakout -> continuation", flush=True)

# completed H1 candles: (end_bar_index_exclusive, hi, lo) in order
h1_list = []          # (first_bar_of_hour, hi, lo)
starts = []
cur = None
for i in range(N):
    hid = tm[i] // 3600
    if cur is None or hid != cur[0]:
        if cur is not None:
            h1_list.append((cur[1], cur[2], cur[3]))
        cur = [hid, i, h[i], l[i]]
        starts.append(i)
    else:
        cur[2] = max(cur[2], h[i])
        cur[3] = min(cur[3], l[i])
# note: last (incomplete) hour intentionally dropped from h1_list

n_hours = len(h1_list)
his = np.array([x[1] for x in h1_list])
los = np.array([x[2] for x in h1_list])
firsts = [x[0] for x in h1_list]

rng = np.random.default_rng(21)
HORIZONS = [15, 30, 60, 120, 240]
COSTS = [0.0, 6.6, 8.25, 9.9]
months_total = (tm[-1] - tm[0]) / (30.44 * 86400)

def era_of(t):
    y = dt.datetime.utcfromtimestamp(int(t)).year
    return 0 if y < 2022 else 1 if y < 2024 else 2

def run(name, NB, CRMAX):
    # box widths per hour index k: box over completed hours [k-NB, k)
    W_at = np.full(n_hours, np.nan)
    for k in range(NB, n_hours):
        W_at[k] = his[k - NB:k].max() - los[k - NB:k].min()
    entries = []   # (entry_bar, dir, W)
    n_armed = 0
    n_timeout = 0
    k = 720 + NB   # need 30 days of baseline
    while k < n_hours - 1:
        base = W_at[k - 720:k]
        base = base[~np.isnan(base)]
        Wk = W_at[k]
        if np.isnan(Wk) or len(base) < 600:
            k += 1
            continue
        med = np.median(base)
        if med <= 0 or Wk / med > CRMAX or Wk < 66.0:
            k += 1
            continue
        # ARMED at hour k: frozen box from completed hours [k-NB, k)
        n_armed += 1
        bhi = his[k - NB:k].max()
        blo = los[k - NB:k].min()
        Wf = bhi - blo
        j0 = firsts[k] if k < len(firsts) else None
        if j0 is None:
            break
        entered = False
        end_bar = min(j0 + 720, N - 245)
        for i in range(j0, end_bar):
            if c[i] > bhi + 0.1 * Wf:
                entries.append((i + 1, 1, Wf)); entered = True; break
            if c[i] < blo - 0.1 * Wf:
                entries.append((i + 1, -1, Wf)); entered = True; break
        if not entered:
            n_timeout += 1
            k += 12
        else:
            # resume arming checks from the hour after the entry bar
            ebar = entries[-1][0]
            ehour_id = tm[ebar] // 3600
            while k < n_hours and (tm[firsts[k]] // 3600 if k < len(firsts) else 1 << 60) <= ehour_id:
                k += 1
    print("")
    print(f"== {name} ==", flush=True)
    era_n = [0, 0, 0]
    for e, d, W in entries:
        era_n[era_of(tm[e])] += 1
    print(f"funnel: armed={n_armed}  entries={len(entries)}  timeouts={n_timeout}  "
          f"({len(entries) / months_total:.1f}/mo overall; per era "
          f"{era_n[0] / 24:.1f} / {era_n[1] / 24:.1f} / {era_n[2] / 25:.1f} per mo)")
    if len(entries) < 20:
        print("  too few entries for inference")
        return
    for hz in HORIZONS:
        mv = []
        ratios = []
        maes = []
        mfes = []
        for e, d, W in entries:
            ep = o[e]
            k2 = min(e + hz, N - 1)
            move = (c[k2] - ep) * d
            mv.append(move)
            ratios.append(move / W)
            if d == 1:
                mfes.append((h[e:k2 + 1].max() - ep) / W)
                maes.append((l[e:k2 + 1].min() - ep) / W)
            else:
                mfes.append((ep - l[e:k2 + 1].min()) / W)
                maes.append((ep - h[e:k2 + 1].max()) / W)
        mv = np.array(mv)
        ratios = np.array(ratios)
        net66 = mv / 100.0 - 0.066
        bs = np.array([rng.choice(net66, size=len(net66), replace=True).mean() for _ in range(2000)])
        print(f"  {hz:3d}min: n={len(mv)}  mean {mv.mean():+7.1f}pts  med {np.median(mv):+7.1f}pts  "
              f"hit {(mv > 0).mean() * 100:4.1f}%  move/W mean {ratios.mean():+.3f} med {np.median(ratios):+.3f}  "
              f"MFE/W {np.mean(mfes):+.3f}  MAE/W {np.mean(maes):+.3f}")
        costs_line = "        net $/0.01: " + "  ".join(
            f"{RT}pts {mv.mean() / 100.0 - RT / 100.0:+.4f}" for RT in COSTS)
        print(costs_line)
        print(f"        net@6.6 bootstrap CI: {np.percentile(bs, 2.5):+.4f}..{np.percentile(bs, 97.5):+.4f}",
              flush=True)

run("PRIMARY: 6-H1 box, CR<=0.5", 6, 0.5)
run("diag: CR<=0.4", 6, 0.4)
run("diag: CR<=0.6", 6, 0.6)
run("diag: 4-H1 box, CR<=0.5", 4, 0.5)
run("diag: 8-H1 box, CR<=0.5", 8, 0.5)
