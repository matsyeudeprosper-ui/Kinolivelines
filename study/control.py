"""Control test: do the LEVELS do anything, or is this just long bias?

Compares touch-triggered entries against random entries at the same times of
day with identical SL/TP rules. If random does as well, the lines are noise.
"""
import MetaTrader5 as mt5, pandas as pd, numpy as np, pickle, os

SPREAD = 10.0
FWD = 480
OUT = os.path.dirname(os.path.abspath(__file__))
rng = np.random.default_rng(7)

mt5.initialize()
m1 = pd.DataFrame(mt5.copy_rates_from_pos("BTCUSDm", mt5.TIMEFRAME_M1, 0, 50000))
h1 = pd.DataFrame(mt5.copy_rates_from_pos("BTCUSDm", mt5.TIMEFRAME_H1, 0, 20000))
mt5.shutdown()
for d in (m1, h1):
    d['time'] = pd.to_datetime(d['time'], unit='s')

print("=== SAMPLE PERIOD DIRECTIONAL BIAS ===")
print(f"M1 window : {m1['time'].iloc[0]}  ->  {m1['time'].iloc[-1]}")
first, last = m1['close'].iloc[0], m1['close'].iloc[-1]
print(f"BTC moved : {first:.2f} -> {last:.2f}   = {last-first:+.2f}  ({(last/first-1)*100:+.2f}%)")
print(f"low {m1['low'].min():.2f}  high {m1['high'].max():.2f}")

def atr(d, n=14):
    pc = d['close'].shift(1)
    return pd.concat([d['high']-d['low'], (d['high']-pc).abs(), (d['low']-pc).abs()],
                     axis=1).max(axis=1).rolling(n).mean()
h1['atr'] = atr(h1)
print(f"median ATR(H1): ${h1['atr'].median():.2f}")

d = pickle.load(open(os.path.join(OUT, "touches.pkl"), "rb"))
rows = d['rows']
print(f"\ntouches loaded: {len(rows)}")

m1_h, m1_l = m1['high'].values, m1['low'].values
h1_close = (h1['time'] + pd.Timedelta(hours=1)).values
h1_atr_v = h1['atr'].values
m1_t = m1['time'].values

def outcome(i, entry, direction, sl_d, tp_d):
    fh = m1_h[i+1:i+1+FWD]; fl = m1_l[i+1:i+1+FWD]
    if len(fh) < FWD: return None
    up = np.maximum.accumulate(fh) - entry
    dn = entry - np.minimum.accumulate(fl)
    if direction == 'BUY':
        tp_i = np.argmax(up >= tp_d) if (up >= tp_d).any() else 10**9
        sl_i = np.argmax(dn >= sl_d) if (dn >= sl_d).any() else 10**9
    else:
        tp_i = np.argmax(dn >= tp_d) if (dn >= tp_d).any() else 10**9
        sl_i = np.argmax(up >= sl_d) if (up >= sl_d).any() else 10**9
    if tp_i == sl_i == 10**9: return -SPREAD
    if sl_i <= tp_i: return -sl_d - SPREAD
    return tp_d - SPREAD

# --- random control: same count, random bars, same SL/TP in ATR(H1) ---
idx_h1 = np.searchsorted(h1_close, m1_t, side='right') - 1
n = len(rows)
cands = rng.integers(300, len(m1) - FWD - 1, size=n)

print("\n" + "="*88)
print(f"{'entry':<22}{'side':<6}{'SL':>5}{'TP':>5}{'n':>7}{'win%':>8}{'$/trade':>10}{'total$':>12}")
print("="*88)

def report(name, pnl, side, sl, tp):
    p = np.array([x for x in pnl if x is not None])
    print(f"{name:<22}{side:<6}{sl:>5.1f}{tp:>5.1f}{len(p):>7}{(p>0).mean()*100:>8.1f}"
          f"{p.mean():>10.2f}{p.sum():>12.0f}")
    return p.mean()

results = {}
for sl_m, tp_m in ((1.5, 1.0), (1.0, 1.0), (1.5, 0.5)):
    for side in ('BUY', 'SELL'):
        # touches
        tp_pnl = []
        for r in rows:
            a = r['atr_h1']
            if not np.isfinite(a) or a <= 0: continue
            tp_pnl.append(outcome(r['i'], r['level'], side, sl_m*a, tp_m*a))
        mt_ = report("TOUCH (support+res)", tp_pnl, side, sl_m, tp_m)

        # random
        rd_pnl = []
        for i in cands:
            j = idx_h1[i]
            a = h1_atr_v[j] if j >= 0 else np.nan
            if not np.isfinite(a) or a <= 0: continue
            rd_pnl.append(outcome(i, m1['close'].values[i], side, sl_m*a, tp_m*a))
        mr = report("RANDOM (control)", rd_pnl, side, sl_m, tp_m)
        print(f"{'  -> edge from levels':<34}{'':>10}{'':>7}{'':>8}{mt_-mr:>10.2f}")
        print("-"*88)
        results[(sl_m, tp_m, side)] = (mt_, mr)
