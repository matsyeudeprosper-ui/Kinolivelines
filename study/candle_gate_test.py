# Owner 2026-10-08: use the progression candle chart (one candle per trade,
# silence filter) as a switch. Last SHOWN candle red -> real trading paused,
# the system keeps trading virtually; resume when a green candle shows up.
# The chart is drawn from ALL trades (real + virtual) - the system's own path.
# Compared with: base, yesterday's plain rule (any loss -> wait for 1 win),
# and random skips of the same number of trades.
import sys, glob, random
import pandas as pd
sys.path.insert(0, r"C:\Projects\KinoliveLines\live\lab"); sys.argv = ["x"]

def gate_candles(P):
    real, ref_h, ref_l, col, cum = [], None, None, 1, 0.0
    for p in P:
        real.append(col == 1)                    # decided BEFORE the trade
        o, c = cum, cum + p; cum = c
        h, l = max(o, c), min(o, c)
        if ref_h is None or c > ref_h or c < ref_l:   # shown candle
            ref_h, ref_l = h, l
            col = 1 if c >= o else -1
    return real
def gate_plain(P):
    real, last = [], 1
    for p in P:
        real.append(last >= 0); last = 1 if p > 0 else (-1 if p < 0 else last)
    return real
def stats(P, mask):
    x = [p for p, m in zip(P, mask) if m]
    c = pk = dd = 0
    for p in x: c += p; pk = max(pk, c); dd = min(dd, c - pk)
    return len(x), sum(x), dd
def rand_pct(P, mask, net, reps=2000):
    k = sum(mask); n = len(P); random.seed(3); better = 0
    for _ in range(reps):
        idx = set(random.sample(range(n), k))
        better += sum(P[i] for i in idx) < net
    return 100 * better / reps
def report(name, P):
    h = len(P) // 2
    print(f"\n{name}: {len(P)} trades")
    for lab, g in (("base", lambda P: [True] * len(P)), ("candle gate", gate_candles), ("plain gate", gate_plain)):
        m = g(P); n, net, dd = stats(P, m)
        n1, a, _ = stats(P[:h], m[:h]); n2, b, _ = stats(P[h:], m[h:])
        extra = "" if lab == "base" else f" | random pct {rand_pct(P, m, net):3.0f}"
        print(f"  {lab:12s} real {n:3d}  net {net:8.2f}  worst drop {dd:8.2f} | 1st half {a:7.2f} 2nd half {b:7.2f}{extra}")

import harness as H
sym, R = H.bars()
H.TRACE = []; H.simulate(R, 7.0, {}); tr = [x for x in H.TRACE if x["pnl"] is not None]; H.TRACE = None
report("REPLAY 60000 bars (bot rules)", [x["pnl"] for x in tr])
for f in sorted(glob.glob(r"C:\Projects\KinoliveLines\live\bos_journal*.csv")):
    j = pd.read_csv(f); j = j[j.profit_usd.notna()].copy()
    j["t"] = pd.to_datetime(j.exit_time_utc, utc=True, format="mixed"); j = j.sort_values("t")
    if len(j) >= 30: report("REAL " + f.split("\\")[-1], list(j.profit_usd))
