"""Liquidity-pool detector + pre-registered sweep test.

A pool is a price where stop orders genuinely cluster, not an arbitrary
candle extreme. Five kinds, all built from mechanism rather than fitting:

  EQH / EQL   two or more confirmed swing highs (lows) at the same price.
              The densest pool that exists - everyone sees the double top
              and parks their stop just beyond it.
  PDH / PDL   prior day high / low
  PWH / PWL   prior week high / low
  SESH/ SESL  prior session high / low (Asia / London / NY, server time)

Rules that make this a liquidity model rather than a line-drawing exercise:
  * A pool only becomes active once CONFIRMED (a swing needs k bars to its
    right before anyone can see it) - no lookahead.
  * A pool is CONSUMED the first time price penetrates it. Liquidity taken
    is liquidity gone, so each pool yields at most one event, ever.

Sweep test is byte-identical to the pre-registered one already run on the
KinoliveLines levels, so the two results are directly comparable:
  penetrate by >= 0.10*ATR(H1); reclaim within 15 M1 bars; stop beyond the
  sweep extreme + 0.10*ATR(H1); targets 1R/2R/3R; $10 cost; direction- and
  risk-matched random control.
"""
import MetaTrader5 as mt5, pandas as pd, numpy as np, os, pickle

SPREAD       = 10.0
PEN_MULT     = 0.10
RECLAIM_BARS = 15
BUF_MULT     = 0.10
FWD          = 480
SWING_K      = 2          # M15 fractal half-width
EQ_TOL_MULT  = 0.05       # equal-highs cluster tolerance, in ATR(H1)
OUT = os.path.dirname(os.path.abspath(__file__))
rng = np.random.default_rng(23)

mt5.initialize()
SYM = "BTCUSDm"
def R(tf, n):
    d = pd.DataFrame(mt5.copy_rates_from_pos(SYM, tf, 0, n))
    d['time'] = pd.to_datetime(d['time'], unit='s'); return d
m1  = R(mt5.TIMEFRAME_M1, 50000)
m15 = R(mt5.TIMEFRAME_M15, 20000)
h1  = R(mt5.TIMEFRAME_H1, 20000)
d1  = R(mt5.TIMEFRAME_D1, 2000)
mt5.shutdown()

def atr(d, n=14):
    pc = d['close'].shift(1)
    return pd.concat([d['high']-d['low'],(d['high']-pc).abs(),(d['low']-pc).abs()],
                     axis=1).max(axis=1).rolling(n).mean()
h1['atr'] = atr(h1)

T, H, L, C = m1['time'].values, m1['high'].values, m1['low'].values, m1['close'].values
N = len(m1)
h1_close_t = (h1['time'] + pd.Timedelta(hours=1)).values
h1_atr_v   = h1['atr'].values
idx_h1     = np.searchsorted(h1_close_t, T, side='right') - 1

def atr_at(i):
    j = idx_h1[i]
    if j < 0: return np.nan
    return h1_atr_v[j]

def m1_index_at(ts):
    """First M1 bar at or after ts."""
    return int(np.searchsorted(T, np.datetime64(ts), side='left'))

# ================= POOL CONSTRUCTION =================
# pool = dict(price, isHigh, from_i, kind, strength)
pools = []

# ---- EQH / EQL: clustered confirmed M15 swings ----
mh, ml = m15['high'].values, m15['low'].values
mt_ = m15['time'].values
sw_h, sw_l = [], []
for i in range(SWING_K, len(m15) - SWING_K):
    if mh[i] == mh[i-SWING_K:i+SWING_K+1].max():
        sw_h.append((i, mh[i]))
    if ml[i] == ml[i-SWING_K:i+SWING_K+1].min():
        sw_l.append((i, ml[i]))

def cluster_swings(swings, isHigh):
    """A pool forms when a 2nd swing lands at the same price as an earlier one.
    Activation time = confirmation bar of that 2nd swing (index + SWING_K)."""
    out = []
    open_clusters = []          # [price, [indices]]
    for si, price in swings:
        conf_i = si + SWING_K
        if conf_i >= len(m15): continue
        ts = mt_[conf_i]
        i1 = m1_index_at(ts)
        if i1 >= N: continue
        a = atr_at(i1)
        if not np.isfinite(a) or a <= 0: continue
        tol = max(SPREAD * 2.0, a * EQ_TOL_MULT)

        hit = None
        for c in open_clusters:
            if abs(c[0] - price) <= tol:
                hit = c; break
        if hit is None:
            open_clusters.append([price, [si], ts])
        else:
            hit[1].append(si)
            if len(hit[1]) == 2:                 # pool is born on the 2nd touch
                out.append({'price': hit[0], 'isHigh': isHigh, 'from_i': i1,
                            'kind': 'EQH' if isHigh else 'EQL', 'strength': 2})
        # forget clusters that are far in the past
        if len(open_clusters) > 400:
            open_clusters = open_clusters[-200:]
    return out

pools += cluster_swings(sw_h, True)
pools += cluster_swings(sw_l, False)

# ---- PDH / PDL from D1 ----
for i in range(1, len(d1)):
    ts = d1['time'].values[i]
    i1 = m1_index_at(ts)
    if i1 >= N: continue
    pools.append({'price': d1['high'].values[i-1], 'isHigh': True,  'from_i': i1, 'kind': 'PDH', 'strength': 1})
    pools.append({'price': d1['low'].values[i-1],  'isHigh': False, 'from_i': i1, 'kind': 'PDL', 'strength': 1})

# ---- PWH / PWL ----
d1w = d1.set_index('time').resample('W-MON', label='left', closed='left').agg(
    {'high':'max','low':'min'}).dropna().reset_index()
for i in range(1, len(d1w)):
    i1 = m1_index_at(d1w['time'].values[i])
    if i1 >= N: continue
    pools.append({'price': d1w['high'].values[i-1], 'isHigh': True,  'from_i': i1, 'kind': 'PWH', 'strength': 1})
    pools.append({'price': d1w['low'].values[i-1],  'isHigh': False, 'from_i': i1, 'kind': 'PWL', 'strength': 1})

# ---- session highs/lows (server time assumed) ----
SESSIONS = [('ASIA', 0, 8), ('LON', 8, 16), ('NY', 13, 21)]
m1i = m1.set_index('time')
for name, h_from, h_to in SESSIONS:
    hrs = m1i.index.hour
    mask = (hrs >= h_from) & (hrs < h_to)
    sess = m1i[mask].copy()
    sess['day'] = sess.index.normalize()
    g = sess.groupby('day').agg({'high':'max','low':'min'})
    days = list(g.index)
    for k in range(1, len(days)):
        end_ts = days[k-1] + pd.Timedelta(hours=h_to)
        i1 = m1_index_at(end_ts)
        if i1 >= N: continue
        pools.append({'price': g['high'].iloc[k-1], 'isHigh': True,  'from_i': i1, 'kind': f'SESH_{name}', 'strength': 1})
        pools.append({'price': g['low'].iloc[k-1],  'isHigh': False, 'from_i': i1, 'kind': f'SESL_{name}', 'strength': 1})

pools = [p for p in pools if 300 <= p['from_i'] < N - FWD - RECLAIM_BARS]
print(f"pools built: {len(pools)}")
for k in sorted(set(p['kind'] for p in pools)):
    print(f"   {k:<12} {sum(1 for p in pools if p['kind']==k)}")

# ================= SWEEP DETECTION (one event per pool) =================
signals = []
for p in pools:
    a = atr_at(p['from_i'])
    if not np.isfinite(a) or a <= 0: continue
    pen = PEN_MULT * a
    lvl = p['price']
    s, e = p['from_i'], min(p['from_i'] + 5000, N - FWD - 1)
    if e <= s: continue

    if p['isHigh']:
        beyond = np.flatnonzero(H[s:e] > lvl + pen)
    else:
        beyond = np.flatnonzero(L[s:e] < lvl - pen)
    if len(beyond) == 0:
        continue                                  # pool never taken
    b0 = s + beyond[0]                            # penetration = pool consumed

    w_end = min(b0 + RECLAIM_BARS + 1, N)
    if p['isHigh']:
        ext = H[b0:w_end].max()
        rec = np.flatnonzero(C[b0:w_end] < lvl)
        if len(rec) == 0: continue                # broke and held -> no trade
        ri = b0 + rec[0]
        ext = H[b0:ri+1].max()
        sl = ext + BUF_MULT * a
        entry = C[ri]; risk = sl - entry; direction = 'SELL'
    else:
        rec = np.flatnonzero(C[b0:w_end] > lvl)
        if len(rec) == 0: continue
        ri = b0 + rec[0]
        ext = L[b0:ri+1].min()
        sl = ext - BUF_MULT * a
        entry = C[ri]; risk = entry - sl; direction = 'BUY'

    if risk <= SPREAD or ri >= N - FWD - 1: continue
    signals.append({'i': ri, 'dir': direction, 'entry': entry, 'risk': risk,
                    'kind': p['kind'], 'time': T[ri], 'level': lvl})

span_days = (m1['time'].iloc[-1] - m1['time'].iloc[0]).days
print(f"\nsweep signals: {len(signals)}  ->  {len(signals)/span_days*30:.0f}/month")
print(f"   BUY {sum(1 for s in signals if s['dir']=='BUY')}  SELL {sum(1 for s in signals if s['dir']=='SELL')}")
print(f"   median risk ${np.median([s['risk'] for s in signals]):.0f}")
pickle.dump(signals, open(os.path.join(OUT, 'pool_signals.pkl'), 'wb'))

def outcome(i, entry, direction, risk, rmult):
    fh, fl = H[i+1:i+1+FWD], L[i+1:i+1+FWD]
    if len(fh) < FWD: return None
    up = np.maximum.accumulate(fh) - entry
    dn = entry - np.minimum.accumulate(fl)
    tp_d = risk * rmult
    if direction == 'BUY':
        tpi = np.argmax(up >= tp_d) if (up >= tp_d).any() else 10**9
        sli = np.argmax(dn >= risk)  if (dn >= risk).any()  else 10**9
    else:
        tpi = np.argmax(dn >= tp_d) if (dn >= tp_d).any() else 10**9
        sli = np.argmax(up >= risk)  if (up >= risk).any()  else 10**9
    if tpi == sli == 10**9: return -SPREAD
    if sli <= tpi: return -risk - SPREAD
    return tp_d - SPREAD

def stats(arr):
    a = np.asarray(arr, dtype=float)
    se = a.std(ddof=1) / np.sqrt(len(a)) if len(a) > 1 else np.nan
    return a.mean(), se, (a.mean()/se if se and se > 0 else np.nan)

def block(name, subs, rmult):
    if len(subs) < 30: return
    sig = np.array([x for x in (outcome(s['i'], s['entry'], s['dir'], s['risk'], rmult) for s in subs) if x is not None])
    ctl = []
    for s in subs:
        ri = int(rng.integers(300, N - FWD - 1))
        o = outcome(ri, C[ri], s['dir'], s['risk'], rmult)
        if o is not None: ctl.append(o)
    ctl = np.array(ctl)
    if len(sig) < 30: return
    ms, ses, ts_ = stats(sig)
    mc, _, _     = stats(ctl)
    medrisk = np.median([s['risk'] for s in subs])
    print(f"{name:<20}{rmult:>3}{len(sig):>7}{(sig>0).mean()*100:>7.1f}"
          f"{ms:>10.2f}{ses:>8.2f}{ts_:>8.2f}{ms/medrisk:>9.3f}{mc:>10.2f}{ms-mc:>9.2f}")

print("\n" + "="*104)
print(f"{'pool kind':<20}{'R':>3}{'n':>7}{'win%':>7}{'$/trd':>10}{'SE':>8}{'t':>8}{'exp(R)':>9}{'ctrl$':>10}{'edge':>9}")
print("="*104)
groups = [('ALL POOLS', signals),
          ('EQH+EQL', [s for s in signals if s['kind'].startswith('EQ')]),
          ('PDH+PDL', [s for s in signals if s['kind'].startswith('PD')]),
          ('PWH+PWL', [s for s in signals if s['kind'].startswith('PW')]),
          ('SESSIONS', [s for s in signals if s['kind'].startswith('SES')])]
for rmult in (1, 2):
    for gname, subs in groups:
        block(gname, subs, rmult)
    print("-"*104)
print("\nt > 2.0 is the bar for 'not noise'. Absolute $/trd must also be positive.")
