"""FALCON V1 — frozen hypothesis test (2026-08-24).
Breakout of 12-H1 range -> pullback/retest of the broken edge -> failed
return (continuation candle) -> enter WITH the breakout.

Frozen choices (disclosed): touch within <=10 completed M1 bars of the
breakout close; continuation candle within <=10 bars of the touch; range
frozen at breakout-arm time; one open position at a time, no hourly cap.
Costs: full round-trip front-loaded at entry (RT pts), symmetric both sides.
Usage: python kino_falcon_backtest.py [NR=12] [mode=full|quick]
"""
import numpy as np
import datetime as dt
import json as _json
import sys

NR = int(sys.argv[1]) if len(sys.argv) > 1 else 12

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

print(f"FALCON V1 | range = last {NR} completed H1 | breakout->retest->continuation", flush=True)

# rolling completed-H1 range available AT each bar
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
        if len(hist) > NR:
            hist.pop(0)
        cur_hid = hid; chi = h[i]; clo = l[i]
    else:
        chi = max(chi, h[i]); clo = min(clo, l[i])
    if len(hist) == NR:
        range_at[i] = (max(x[0] for x in hist), min(x[1] for x in hist))

# ---- signal state machine ----
# per side: 0 idle -> breakout close arms (freeze range) -> touch within 10
# bars -> continuation candle within 10 bars -> signal
signals = []   # (signal_bar, dir, retest_extreme, armed_level)
state = 0      # 0 idle, 1 armed(up), -1 armed(down), 2 touched(up), -2 touched(down)
lvl = None
cnt = 0
ext = None     # retest extreme (min low since arm for buys / max high for sells)
for i in range(N - 61):
    if range_at[i] is None:
        continue
    rhi, rlo = range_at[i]
    if state == 0:
        if c[i] > rhi:
            state = 1; lvl = rhi; cnt = 0; ext = l[i]
        elif c[i] < rlo:
            state = -1; lvl = rlo; cnt = 0; ext = h[i]
    elif state == 1:
        cnt += 1
        ext = min(ext, l[i])
        if l[i] <= lvl:
            state = 2; cnt = 0
        elif cnt >= 10:
            state = 0
    elif state == -1:
        cnt += 1
        ext = max(ext, h[i])
        if h[i] >= lvl:
            state = -2; cnt = 0
        elif cnt >= 10:
            state = 0
    elif state == 2:
        cnt += 1
        ext = min(ext, l[i])
        if c[i] > lvl and c[i] > o[i] and c[i] > h[i - 1]:
            signals.append((i, 1, ext, lvl))
            state = 0
        elif cnt >= 10:
            state = 0
    elif state == -2:
        cnt += 1
        ext = max(ext, h[i])
        if c[i] < lvl and c[i] < o[i] and c[i] < l[i - 1]:
            signals.append((i, -1, ext, lvl))
            state = 0
        elif cnt >= 10:
            state = 0

months_total = (tm[-1] - tm[0]) / (30.44 * 86400)
print(f"signals: {len(signals)}  ({len(signals) / months_total:.0f}/month)", flush=True)

def era_of(t):
    y = dt.datetime.utcfromtimestamp(int(t)).year
    return 0 if y < 2022 else 1 if y < 2024 else 2

rng = np.random.default_rng(7)

# ---- PART 1: signal forward-move study ----
print("")
print("== PART 1: forward signed movement per horizon ($ per 0.01 lot) ==", flush=True)
HORIZONS = [1, 2, 5, 10, 15, 30, 60]
for RT in (0.0, 6.6):
    print(f"-- cost {RT} pts round trip --")
    for k in HORIZONS:
        mv = []
        for i, d, ext, lvl in signals:
            entry = o[i + 1] + d * RT
            mv.append((c[min(i + 1 + k, N - 1)] - entry) * d / 100.0)
        mv = np.array(mv)
        bs = np.array([rng.choice(mv, size=len(mv), replace=True).mean() for _ in range(2000)])
        print(f"  {k:2d}min: n={len(mv)}  mean ${mv.mean():+.4f}  med ${np.median(mv):+.4f}  "
              f"hit {(mv > 0).mean() * 100:4.1f}%  CI ${np.percentile(bs, 2.5):+.4f}..${np.percentile(bs, 97.5):+.4f}",
              flush=True)

# ---- PART 2: basic trading version ----
print("")
print("== PART 2: trading sim (SL beyond retest extreme, TP 1R, 30min max, one position at a time) ==", flush=True)

def trade_sim(RT, tp_mult):
    trades = []   # (t, pnl$, dir)
    busy_until = -1
    for i, d, ext, lvl in signals:
        j = i + 1
        if j <= busy_until or j >= N:
            continue
        ep = o[j] + d * RT
        sl = ext
        R = (ep - sl) * d
        if R <= 0:
            continue
        tp = ep + d * R * tp_mult
        pnl = None
        end = min(j + 30, N - 1)
        for k in range(j, end):
            if (l[k] <= sl) if d == 1 else (h[k] >= sl):
                pnl = -R * 0.01; kend = k; break
            if (h[k] >= tp) if d == 1 else (l[k] <= tp):
                pnl = R * tp_mult * 0.01; kend = k; break
        if pnl is None:
            pnl = (o[end] - ep) * d * 0.01; kend = end
        busy_until = kend
        trades.append((tm[j], pnl, d))
    return trades

def report(name, trades, dump=None):
    if not trades:
        print(f"{name}: no trades"); return
    p = np.array([t[1] for t in trades])
    wins = p[p > 0]; losses = p[p <= 0]
    eras = [0.0, 0.0, 0.0]
    for t in trades:
        eras[era_of(t[0])] += t[1]
    bal = np.cumsum(p)
    peak = np.maximum.accumulate(bal)
    mdd = (peak - bal).max()
    bs = np.array([rng.choice(p, size=len(p), replace=True).mean() for _ in range(2000)])
    print(f"{name}: n={len(p)} ({len(p) / months_total:.0f}/mo)  total ${p.sum():+.2f} (${p.sum() / months_total:+.2f}/mo)  "
          f"exp ${p.mean():+.4f} CI ${np.percentile(bs, 2.5):+.4f}..${np.percentile(bs, 97.5):+.4f}")
    print(f"   PF {wins.sum() / max(1e-9, -losses.sum()):.3f}  win {(p > 0).mean() * 100:.1f}%  maxDD ${mdd:.2f}  "
          f"eras ${eras[0]:+.0f}/${eras[1]:+.0f}/${eras[2]:+.0f}")
    for dname, dv in (("BUY", 1), ("SELL", -1)):
        gg = np.array([t[1] for t in trades if t[2] == dv])
        if len(gg):
            print(f"   {dname}: n={len(gg)}  total ${gg.sum():+.2f}  exp ${gg.mean():+.4f}")
    yearly = {}
    for t in trades:
        y = dt.datetime.utcfromtimestamp(int(t[0])).year
        yearly[y] = yearly.get(y, 0.0) + t[1]
    print("   yearly: " + "  ".join(f"{y}:${v:+.0f}" for y, v in sorted(yearly.items())))
    mon = {}
    for t in trades:
        mkey = dt.datetime.utcfromtimestamp(int(t[0])).strftime("%Y-%m")
        mon[mkey] = mon.get(mkey, 0.0) + t[1]
    mk = sorted(mon)
    mv2 = np.array([mon[k] for k in mk])
    for w in (3, 6, 12):
        if len(mv2) >= w:
            roll = np.array([mv2[x:x + w].mean() for x in range(len(mv2) - w + 1)])
            print(f"   rolling {w:2d}-mo $/mo: min ${roll.min():+.2f} max ${roll.max():+.2f} "
                  f"neg windows {(roll < 0).mean() * 100:.0f}%")
    if dump:
        days = {}
        for t in trades:
            dkey = dt.datetime.utcfromtimestamp(int(t[0])).strftime("%Y-%m-%d")
            days[dkey] = days.get(dkey, 0.0) + t[1]
        _json.dump(days, open(dump, "w"))
        print(f"   daily pnl dumped -> {dump}")

for RT in (0.0, 6.6, 8.25, 9.9):
    tr = trade_sim(RT, 1.0)
    report(f"TP 1R @ cost {RT}pts", tr, dump=("falcon_daily.json" if abs(RT - 6.6) < 1e-9 else None))
    print("")
print("-- diagnostics only (do not select): --")
for m in (1.5, 2.0):
    report(f"TP {m}R @ cost 6.6pts", trade_sim(6.6, m))
    print("")
