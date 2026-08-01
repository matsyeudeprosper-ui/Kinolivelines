"""What actually happens when price touches a KinoliveLines level?

Reconstructs the exact level set for every M1 bar over all available history,
finds every touch, then measures forward outcomes. Answers three questions
with data instead of opinion:

  1. At a support touch, is BUY (bounce) or SELL (break) the right side?
     Same for resistance.
  2. What SL/TP, expressed in ATR, actually survives the $10 spread?
  3. Does the source timeframe (H4 / H1 / M15) change the answer?

No strategy is assumed. Both directions are tested at every touch.
"""
import MetaTrader5 as mt5
import pandas as pd
import numpy as np
import os, pickle

SPREAD_COST   = 10.0      # $ round trip, confirmed live on BTCUSDm
ATR_MERGE_MULT = 0.12
MIN_SPACING_PCT = 0.10
MAXLV = 6
FWD   = 480               # M1 bars of forward path kept per touch (8h)
OUT   = os.path.dirname(os.path.abspath(__file__))

mt5.initialize()
SYM = "BTCUSDm"

def rates(tf, n):
    r = mt5.copy_rates_from_pos(SYM, tf, 0, n)
    d = pd.DataFrame(r)
    d['time'] = pd.to_datetime(d['time'], unit='s')
    return d

m1  = rates(mt5.TIMEFRAME_M1, 50000)
m15 = rates(mt5.TIMEFRAME_M15, 20000)
h1  = rates(mt5.TIMEFRAME_H1, 20000)
h4  = rates(mt5.TIMEFRAME_H4, 20000)
mt5.shutdown()
print(f"M1 {len(m1)} bars: {m1['time'].iloc[0]} -> {m1['time'].iloc[-1]}")

def atr(d, n=14):
    pc = d['close'].shift(1)
    tr = pd.concat([d['high'] - d['low'], (d['high'] - pc).abs(), (d['low'] - pc).abs()], axis=1).max(axis=1)
    return tr.rolling(n).mean()

for d in (m1, m15, h1, h4):
    d['atr'] = atr(d)

DUR = {'H4': pd.Timedelta(hours=4), 'H1': pd.Timedelta(hours=1), 'M15': pd.Timedelta(minutes=15)}
SRC = {'H4': (h4, 3), 'H1': (h1, 2), 'M15': (m15, 1)}

# For each M1 bar, index of the last FULLY CLOSED bar of each source TF.
idx = {}
for name, (d, _) in SRC.items():
    close_times = (d['time'] + DUR[name]).values
    idx[name] = np.searchsorted(close_times, m1['time'].values, side='right') - 1

m1_t   = m1['time'].values
m1_h   = m1['high'].values
m1_l   = m1['low'].values
m1_c   = m1['close'].values
m1_atr = m1['atr'].values

arrs = {n: (SRC[n][0]['high'].values, SRC[n][0]['low'].values, SRC[n][1]) for n in SRC}
h1_atr_v = h1['atr'].values

def build(i):
    """Exact port of CollectLevels() for M1 bar i."""
    raw = []
    for name in ('H4', 'H1', 'M15'):
        j = idx[name][i]
        if j < 0:
            continue
        hi, lo, prio = arrs[name]
        raw.append([hi[j], True,  prio, name])
        raw.append([lo[j], False, prio, name])
    if not raw:
        return []
    j1 = idx['H1'][i]
    a = h1_atr_v[j1] if j1 >= 0 and not np.isnan(h1_atr_v[j1]) else SPREAD_COST * 10
    tol = max(SPREAD_COST * 3.0, a * ATR_MERGE_MULT)

    raw.sort(key=lambda r: r[0])
    keep = [True] * len(raw)
    for x in range(len(raw)):
        if not keep[x]:
            continue
        for y in range(x + 1, len(raw)):
            if not keep[y]:
                continue
            if abs(raw[x][0] - raw[y][0]) <= tol:
                if raw[y][2] > raw[x][2]:
                    raw[x] = raw[y]
                keep[y] = False
    merged = [r for x, r in enumerate(raw) if keep[x]]

    md = merged[0][0] * (MIN_SPACING_PCT / 100.0)
    out = []
    for r in merged:
        if not out or r[1] != out[-1][1] or abs(r[0] - out[-1][0]) >= md:
            out.append(r)
        if len(out) >= MAXLV:
            break
    return out

# ---- walk history, collect touch events ----
start = 300                      # let ATRs warm up
prev_inside = {}
events = []
for i in range(start, len(m1) - FWD):
    lv = build(i)
    ns = {}
    lo, hi = m1_l[i], m1_h[i]
    for price, isHigh, prio, tf in lv:
        k = (round(price, 2), isHigh)
        inside = lo <= price <= hi
        ns[k] = inside
        if inside and not prev_inside.get(k, False):
            events.append((i, price, isHigh, tf))
    prev_inside = ns

print(f"touch events: {len(events)}")

# ---- forward paths ----
rows = []
for i, price, isHigh, tf in events:
    fh = m1_h[i + 1:i + 1 + FWD]
    fl = m1_l[i + 1:i + 1 + FWD]
    if len(fh) < FWD:
        continue
    j1 = idx['H1'][i]
    a_h1 = h1_atr_v[j1] if j1 >= 0 else np.nan
    rows.append({
        'i': i, 'time': m1_t[i], 'level': price, 'isHigh': isHigh, 'tf': tf,
        'atr_m1': m1_atr[i], 'atr_h1': a_h1,
        'up_max': np.maximum.accumulate(fh) - price,      # running best above the line
        'dn_max': price - np.minimum.accumulate(fl),      # running best below the line
    })

print(f"usable touches: {len(rows)}")
with open(os.path.join(OUT, "touches.pkl"), "wb") as f:
    pickle.dump({'rows': rows, 'spread': SPREAD_COST}, f)

# ---- evaluate a (direction, SL, TP) grid in ATR(H1) units ----
def evaluate(rows, direction, sl_mult, tp_mult, tf_filter=None):
    """direction 'BUY'/'SELL'. Returns per-trade PnL in $, net of spread."""
    pnl = []
    for r in rows:
        if tf_filter and r['tf'] != tf_filter:
            continue
        a = r['atr_h1']
        if not np.isfinite(a) or a <= 0:
            continue
        sl_d, tp_d = sl_mult * a, tp_mult * a
        if direction == 'BUY':
            tp_first = np.argmax(r['up_max'] >= tp_d) if (r['up_max'] >= tp_d).any() else 10**9
            sl_first = np.argmax(r['dn_max'] >= sl_d) if (r['dn_max'] >= sl_d).any() else 10**9
        else:
            tp_first = np.argmax(r['dn_max'] >= tp_d) if (r['dn_max'] >= tp_d).any() else 10**9
            sl_first = np.argmax(r['up_max'] >= sl_d) if (r['up_max'] >= sl_d).any() else 10**9
        if tp_first == sl_first == 10**9:
            pnl.append(-SPREAD_COST)                       # timed out flat-ish
        elif sl_first <= tp_first:                          # tie -> loss (conservative)
            pnl.append(-sl_d - SPREAD_COST)
        else:
            pnl.append(tp_d - SPREAD_COST)
    return np.array(pnl)

sup = [r for r in rows if not r['isHigh']]
res = [r for r in rows if r['isHigh']]
print(f"\nsupport touches {len(sup)} | resistance touches {len(res)}")

print("\n" + "=" * 104)
print(f"{'touch':<12}{'side':<6}{'SL(atr)':>8}{'TP(atr)':>8}{'n':>7}{'win%':>7}{'avg$':>9}{'total$':>11}{'exp/trade':>11}")
print("=" * 104)
best = []
for label, subset in (('SUPPORT', sup), ('RESISTANCE', res)):
    for direction in ('BUY', 'SELL'):
        for sl_m in (0.5, 1.0, 1.5):
            for tp_m in (0.5, 1.0, 1.5, 2.0):
                p = evaluate(subset, direction, sl_m, tp_m)
                if len(p) < 50:
                    continue
                win = (p > 0).mean() * 100
                print(f"{label:<12}{direction:<6}{sl_m:>8.1f}{tp_m:>8.1f}{len(p):>7}{win:>7.1f}"
                      f"{p.mean():>9.2f}{p.sum():>11.0f}{p.mean():>11.2f}")
                best.append((p.mean(), label, direction, sl_m, tp_m, len(p), win, p.sum()))

print("\n" + "=" * 104)
print("TOP 8 BY EXPECTANCY PER TRADE")
for e in sorted(best, reverse=True)[:8]:
    print(f"  {e[1]:<11} {e[2]:<5} SL {e[3]}atr TP {e[4]}atr | n={e[5]:<5} win {e[6]:.1f}% "
          f"| ${e[0]:+.2f}/trade | total ${e[7]:+,.0f}")
