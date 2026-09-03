"""VALIDATION 1: signal forward-move study for pure Croc.
Loads the identical data pipeline by exec'ing the frozen panel script's
data-loading prefix, then measures signed forward moves after three signal
types: raw touch-fade, sweep-without-reclaim, sweep+reclaim (Croc).
Cost: 10 pts round trip applied to every signal type equally.
"""
import numpy as np

panel = open('kino_rangesweep_panel.py', encoding='utf-8').read()
anchor = "tm = np.array(times); N = len(times)"
head = panel[:panel.index(anchor) + len(anchor)]
head = head.replace("START_BAL = float(_sys.argv[1]) if len(_sys.argv) > 1 else 157.0", "START_BAL = 500.0")
head = head.replace("NMIN = int(_sys.argv[2]) if len(_sys.argv) > 2 else 30", "NMIN = 30")
head = head.replace("NRANGE = int(_sys.argv[3]) if len(_sys.argv) > 3 else 12", "NRANGE = 12")
head = head.replace("TRENDF = (_sys.argv[4] if len(_sys.argv) > 4 else 'on') == 'on'   # 3-same-color filter", "TRENDF = False")
head = head.replace("D1F = (_sys.argv[5] if len(_sys.argv) > 5 else 'on') == 'on'      # inside-yesterday filter", "D1F = False")
head = head.replace("print(f'RANGE SWEEP V1: 12-H1 range, M1 sweep+reclaim, ranging-only filters | {NMIN}min | START {START_BAL}', flush=True)", "pass")
g = {}
exec(head, g)
o, h, l, c, tm, N = g['o'], g['h'], g['l'], g['c'], g['tm'], g['N']
NRANGE = 12
COST = 10.0
HORIZONS = [1, 2, 5, 10, 15, 30]

print("VALIDATION 1: signal forward-move study (10 pts round-trip cost on ALL types)", flush=True)

range_at = [None] * N
cur_hid = None
chi = clo = None
hist = []
for i in range(N):
    hid = tm[i] // 3600
    if cur_hid is None:
        cur_hid = hid; chi = h[i]; clo = l[i]
    elif hid != cur_hid:
        hist.append((chi, clo))
        if len(hist) > NRANGE:
            hist.pop(0)
        cur_hid = hid; chi = h[i]; clo = l[i]
    else:
        chi = max(chi, h[i]); clo = min(clo, l[i])
    if len(hist) == NRANGE:
        range_at[i] = (max(x[0] for x in hist), min(x[1] for x in hist))

sigs = {"touch": [], "sweep_noreclaim": [], "croc": []}
hour_done = {k: -1 for k in sigs}
swl = swh = False
last_hour = -1
for i in range(N - 31):
    if range_at[i] is None:
        continue
    rhi, rlo = range_at[i]
    if rhi - rlo <= 50:
        continue
    hid = tm[i] // 3600
    if hid != last_hour:
        last_hour = hid
        swl = swh = False
    if hour_done["touch"] != hid:
        if l[i] <= rlo:
            sigs["touch"].append((i, 1)); hour_done["touch"] = hid
        elif h[i] >= rhi:
            sigs["touch"].append((i, -1)); hour_done["touch"] = hid
    if hour_done["sweep_noreclaim"] != hid:
        if c[i] < rlo:
            sigs["sweep_noreclaim"].append((i, 1)); hour_done["sweep_noreclaim"] = hid
        elif c[i] > rhi:
            sigs["sweep_noreclaim"].append((i, -1)); hour_done["sweep_noreclaim"] = hid
    if l[i] < rlo:
        swl = True
    if h[i] > rhi:
        swh = True
    if hour_done["croc"] != hid:
        if swl and c[i] > rlo and c[i] > o[i]:
            sigs["croc"].append((i, 1)); hour_done["croc"] = hid; swl = swh = False
        elif swh and c[i] < rhi and c[i] < o[i]:
            sigs["croc"].append((i, -1)); hour_done["croc"] = hid; swl = swh = False

import datetime as dt

def era_of(t):
    y = dt.datetime.utcfromtimestamp(int(t)).year
    return 0 if y < 2022 else 1 if y < 2024 else 2

for name, lst in sigs.items():
    print("")
    print(f"== {name}: {len(lst)} signals ==", flush=True)
    for k in HORIZONS:
        mv = []
        for i, d in lst:
            entry = o[i + 1]
            mv.append(((c[min(i + 1 + k, N - 1)] - entry) * d - COST) / 100.0)
        mv = np.array(mv)
        mean = mv.mean(); med = np.median(mv); hit = (mv > 0).mean() * 100
        ci = 1.96 * mv.std() / np.sqrt(len(mv))
        line = f"  {k:2d}min: mean ${mean:+.4f} +/- {ci:.4f}  median ${med:+.4f}  hit {hit:4.1f}%"
        if k == 10:
            eras = [[], [], []]
            for (i, d), v in zip(lst, mv):
                eras[era_of(tm[i])].append(v)
            parts = []
            for e in eras:
                parts.append(f"${np.mean(e):+.4f}" if e else "n/a")
            line += "  | era means: " + " ".join(parts)
        print(line, flush=True)
