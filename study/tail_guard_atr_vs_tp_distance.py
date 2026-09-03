"""User's idea: 'when ATR is good according to TP distance, we're easily
ready to [hit TP]' - i.e. filter/bucket by ratio = ATR14(M1) / TP_PTS(100),
not by ATR's own percentile history (already tested, killed). Faithful to
the LIVE bot: M1 bricks, 50pt/2-brick reversal, TP=100pts, SL=44439pts fixed
(today's live values), 10pt flat spread (matches journaled spread_at_entry).
"""
import numpy as np
import MetaTrader5 as mt5
from datetime import datetime

BRICK, REVERSAL = 50.0, 2
PT = 0.01
TP_PTS = 100.0
SL_PTS = 44439.0
SPREAD_PTS = 10.0
FROM = datetime(2022, 1, 1)


def build_bricks_signals(o, h, l, c, N):
    revs = {}
    ao = ac = float(o[0]); d = 0; pd_ = 0
    for i in range(N):
        while True:
            up = (ao if d == -1 else ac) + BRICK * (REVERSAL if d == -1 else 1)
            dn = (ao if d == 1 else ac) - BRICK * (REVERSAL if d == 1 else 1)
            if c[i] >= up:
                base = ao if d == -1 else ac; ao, ac, d = base, base + BRICK, 1
            elif c[i] <= dn:
                base = ao if d == 1 else ac; ao, ac, d = base, base - BRICK, -1
            else:
                break
            if pd_ and d != pd_:
                revs.setdefault(i, d)
            pd_ = d
    return revs


ok = mt5.initialize(path=r"C:\Program Files\MetaTrader 5\terminal64.exe")
if not ok:
    raise SystemExit(f"initialize failed: {mt5.last_error()}")
mt5.symbol_select("BTCUSDm", True)
r = mt5.copy_rates_from_pos("BTCUSDm", mt5.TIMEFRAME_M1, 0, 99000)  # terminal maxbars=100000
mt5.shutdown()
if r is None:
    raise SystemExit(f"copy_rates_from_pos failed: {mt5.last_error()}")
o, h, l, c = (r[k].astype(float) for k in ("open", "high", "low", "close"))
tm = r["time"]
N = len(c)
print(f"M1 bars loaded: {N}  ({datetime.utcfromtimestamp(tm[0])} to {datetime.utcfromtimestamp(tm[-1])})")

tr = np.zeros(N)
for i in range(1, N):
    tr[i] = max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1]))
atr14 = np.zeros(N)
cs = np.cumsum(tr)
for i in range(14, N):
    atr14[i] = (cs[i] - cs[i - 14]) / 14.0

sigs = build_bricks_signals(o, h, l, c, N)
print(f"total signals: {len(sigs)}")

rows = []  # (ratio, win, duration_bars)
for j, dirn in sigs.items():
    if j + 1 >= N:
        continue
    ent_bar = j + 1
    L = (dirn == 1)
    entry = o[ent_bar] + SPREAD_PTS if L else o[ent_bar]
    ratio = atr14[j] / TP_PTS
    outcome = None
    dur = None
    for k in range(ent_bar, N):
        tp_price = entry + TP_PTS if L else entry - TP_PTS
        sl_price = entry - SL_PTS if L else entry + SL_PTS
        hit_tp = (h[k] >= tp_price) if L else (l[k] <= tp_price)
        hit_sl = (l[k] <= sl_price) if L else (h[k] >= sl_price)
        if hit_tp and hit_sl:
            outcome, dur = 0, k - ent_bar
            break
        if hit_tp:
            outcome, dur = 1, k - ent_bar
            break
        if hit_sl:
            outcome, dur = 0, k - ent_bar
            break
    if outcome is not None:
        rows.append((ratio, outcome, dur))

ratios = np.array([x[0] for x in rows])
wins = np.array([x[1] for x in rows])
durs = np.array([x[2] for x in rows], dtype=float)  # in minutes (M1 bars)
print(f"resolved trades: {len(rows)}   overall win% {100*wins.mean():.1f}   overall median duration {np.median(durs)/60:.1f}h")

print(f"\ncorrelation ratio vs win (point-biserial): {np.corrcoef(ratios, wins)[0,1]:.3f}")
print(f"correlation ratio vs duration:              {np.corrcoef(ratios, durs)[0,1]:.3f}")

print(f"\nBY RATIO BUCKET (ratio = ATR14-M1 / TP_PTS):")
edges = [0, 0.25, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0, np.inf]
for lo_, hi_ in zip(edges[:-1], edges[1:]):
    mask = (ratios >= lo_) & (ratios < hi_)
    n = mask.sum()
    if n == 0:
        continue
    wr = 100 * wins[mask].mean()
    med_h = np.median(durs[mask]) / 60
    print(f"  [{lo_:>4.2f}, {hi_:>5.2f})  n={n:>4}  win%={wr:5.1f}  median_dur={med_h:7.1f}h")

print(f"\nAS A HARD FILTER (skip signal if ratio < threshold) - full-history, single pass:")
for thr in (0.0, 0.25, 0.5, 0.75, 1.0, 1.5, 2.0):
    mask = ratios >= thr
    n = mask.sum()
    if n == 0:
        continue
    wr = 100 * wins[mask].mean()
    net_pts = wins[mask].sum() * TP_PTS - (n - wins[mask].sum()) * SL_PTS
    print(f"  thr={thr:>4.2f}  kept {n:>4}/{len(rows)} ({100*n/len(rows):5.1f}%)  win%={wr:5.1f}  net_$={net_pts*PT:>10.2f}")
