"""OPENING DISPLACEMENT FAILURE V1 — frozen, approved 2026-08-24.
transition -> >=KxATR_pre displacement within 15 min -> failure close back
through the reference price (agreeing body) by minute 45 -> enter against the
displacement at next M1 open. One signal per transition. No continuation-void
rule (removed per approval). Single pass, no rescue.
Configs: PRIMARY 00:00 UTC K=4; diagnostics 00:00 K=3, K=5; 08:00 K=4;
16:00 K=4; pooled all-hours K=4.
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

print("OPENING DISPLACEMENT FAILURE V1 (frozen) — single preregistered pass", flush=True)

tr = h - l
# hour-start indices
hour_starts = [i for i in range(1, N) if tm[i] // 3600 != tm[i - 1] // 3600]
rng = np.random.default_rng(11)
HORIZONS = [1, 2, 5, 10, 15, 30, 60]
COSTS = [0.0, 6.6, 8.25, 9.9]

def run(name, anchor_hour, K):
    # anchor_hour: int 0..23 or 'all'
    trans = [i for i in hour_starts
             if anchor_hour == 'all' or (tm[i] // 3600) % 24 == anchor_hour]
    n_total = 0
    n_qual = 0
    n_up = 0
    n_dn = 0
    n_fail = 0
    signals = []   # (entry_bar, d_trade)
    for j0 in trans:
        if j0 < 15 or j0 + 106 >= N:
            continue
        n_total += 1
        ref = o[j0]
        atr_pre = tr[j0 - 14:j0].mean()
        if atr_pre <= 0:
            continue
        need = max(K * atr_pre, 20.0)
        # displacement: first side to qualify within bars j0..j0+14
        disp = 0
        q_bar = None
        up_ext = 0.0
        dn_ext = 0.0
        for k in range(j0, j0 + 15):
            up_ext = max(up_ext, h[k] - ref)
            dn_ext = max(dn_ext, ref - l[k])
            up_ok = up_ext >= need
            dn_ok = dn_ext >= need
            if up_ok or dn_ok:
                disp = 1 if (up_ok and (not dn_ok or up_ext >= dn_ext)) else -1
                q_bar = k
                break
        if disp == 0:
            continue
        n_qual += 1
        if disp == 1:
            n_up += 1
        else:
            n_dn += 1
        # failure: from bar after qualification until minute 45 after transition
        sig = None
        for k in range(q_bar + 1, j0 + 45):
            if disp == 1 and c[k] < ref and c[k] < o[k]:
                sig = k
                break
            if disp == -1 and c[k] > ref and c[k] > o[k]:
                sig = k
                break
        if sig is None:
            continue
        n_fail += 1
        signals.append((sig + 1, -disp))
    print("")
    print(f"== {name} ==", flush=True)
    print(f"funnel: transitions={n_total}  qualified={n_qual} ({n_qual / max(1, n_total) * 100:.1f}%)  "
          f"UP={n_up} DOWN={n_dn}  failures={n_fail} "
          f"({n_fail / max(1, n_qual) * 100:.1f}% of qualified)  entries={len(signals)}")
    if len(signals) < 20:
        print("  too few entries for inference")
        return
    for k in HORIZONS:
        gross = []
        for e, d in signals:
            entry = o[e]
            gross.append((c[min(e + k, N - 1)] - entry) * d / 100.0)
        gross = np.array(gross)
        bs = np.array([rng.choice(gross, size=len(gross), replace=True).mean() for _ in range(2000)])
        line = (f"  {k:2d}min: n={len(gross)}  gross ${gross.mean():+.4f} "
                f"(med ${np.median(gross):+.4f} hit {(gross > 0).mean() * 100:4.1f}%)")
        for RT in COSTS[1:]:
            lo_ci = np.percentile(bs, 2.5) - RT / 100.0
            hi_ci = np.percentile(bs, 97.5) - RT / 100.0
            if RT == 6.6:
                line += f"  net@6.6 ${gross.mean() - RT / 100.0:+.4f} CI ${lo_ci:+.4f}..${hi_ci:+.4f}"
        print(line, flush=True)
    m = gross  # 60min view left in m; per-cost expectancy summary at 30min:
    g30 = []
    for e, d in signals:
        g30.append((c[min(e + 30, N - 1)] - o[e]) * d / 100.0)
    g30 = np.array(g30)
    row = "  30min expectancy by cost: " + "  ".join(
        f"{RT}pts ${g30.mean() - RT / 100.0:+.4f}" for RT in COSTS)
    print(row, flush=True)

run("PRIMARY: 00:00 UTC, K=4", 0, 4.0)
run("diag: 00:00 UTC, K=3", 0, 3.0)
run("diag: 00:00 UTC, K=5", 0, 5.0)
run("diag: 08:00 UTC, K=4", 8, 4.0)
run("diag: 16:00 UTC, K=4", 16, 4.0)
run("diag: ALL hours pooled, K=4", 'all', 4.0)
