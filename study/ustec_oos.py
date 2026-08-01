"""Out-of-sample test of the ONE hypothesis that popped.

Hypothesis (pre-specified, no variants): on USTECm, a sweep-and-reclaim of a
prior-day / prior-week high or low is tradeable at 1R.

Design:
  IS-M1   last 50d on M1   -> the window the result was FOUND in (t=3.39)
  IS-M5   last 50d on M5   -> does the M5 pipeline reproduce it? sanity check
  OOS-M5  everything older -> the real test. This data was never looked at.

Rules held constant in TIME, not bars, so M1 and M5 are comparable:
  penetrate >= 0.10*ATR(H1); reclaim within 15 minutes; stop beyond sweep
  extreme + 0.10*ATR(H1); target 1R; horizon 8h; spread charged once.

Also reports hour-of-day of every signal. If the opening-range story is real
the signals cluster near the cash open; if they are scattered, the story was
invented after the fact and the result is noise.
"""
import MetaTrader5 as mt5, pandas as pd, numpy as np

SYM = "USTECm"
PEN_MULT = BUF_MULT = 0.10
RECLAIM_MIN = 15
HORIZON_H   = 8

mt5.initialize()
mt5.symbol_select(SYM, True)
tk = mt5.symbol_info_tick(SYM)
SPREAD = tk.ask - tk.bid

def R(tf, n):
    """The server refuses oversized requests by returning nothing rather than
    truncating, so step down until a request actually lands."""
    for want in (n, 100000, 50000, 20000, 10000, 5000, 2000):
        if want > n: continue
        r = mt5.copy_rates_from_pos(SYM, tf, 0, want)
        if r is not None and len(r):
            d = pd.DataFrame(r)
            d['time'] = pd.to_datetime(d['time'], unit='s')
            return d
    raise RuntimeError(f"no data for tf={tf}")

m1 = R(mt5.TIMEFRAME_M1, 50000)
m5 = R(mt5.TIMEFRAME_M5, 100000)
h1 = R(mt5.TIMEFRAME_H1, 50000)
d1 = R(mt5.TIMEFRAME_D1, 5000)
mt5.shutdown()

def atr(d, n=14):
    pc = d['close'].shift(1)
    return pd.concat([d['high']-d['low'],(d['high']-pc).abs(),(d['low']-pc).abs()],
                     axis=1).max(axis=1).rolling(n).mean()
h1['atr'] = atr(h1)

print(f"{SYM}  spread {SPREAD}")
print(f"  M1 : {len(m1)} bars  {m1['time'].iloc[0]} -> {m1['time'].iloc[-1]}")
print(f"  M5 : {len(m5)} bars  {m5['time'].iloc[0]} -> {m5['time'].iloc[-1]}")
print(f"  D1 : {len(d1)} bars  {d1['time'].iloc[0]} -> {d1['time'].iloc[-1]}")

IS_START = m1['time'].iloc[0]          # boundary: M1 window = in-sample
print(f"\n  IS window starts {IS_START}   (OOS = everything before this)")

def build_pools(bars):
    """PD/PW pools only - the pre-specified hypothesis."""
    T = bars['time'].values
    def at(ts): return int(np.searchsorted(T, np.datetime64(ts), side='left'))
    pools = []
    for i in range(1, len(d1)):
        k = at(d1['time'].values[i])
        if k >= len(bars): continue
        pools.append({'price': d1['high'].values[i-1], 'isHigh': True,  'i': k, 'kind':'PDH'})
        pools.append({'price': d1['low' ].values[i-1], 'isHigh': False, 'i': k, 'kind':'PDL'})
    wk = d1.set_index('time').resample('W-MON', label='left', closed='left').agg(
        {'high':'max','low':'min'}).dropna().reset_index()
    for i in range(1, len(wk)):
        k = at(wk['time'].values[i])
        if k >= len(bars): continue
        pools.append({'price': wk['high'].values[i-1], 'isHigh': True,  'i': k, 'kind':'PWH'})
        pools.append({'price': wk['low' ].values[i-1], 'isHigh': False, 'i': k, 'kind':'PWL'})
    return pools

def scan(bars, tf_min, label, t_lo=None, t_hi=None):
    T, H, L, C = bars['time'].values, bars['high'].values, bars['low'].values, bars['close'].values
    N = len(bars)
    FWD     = int(HORIZON_H * 60 / tf_min)
    RECLAIM = max(1, int(RECLAIM_MIN / tf_min))
    GAP     = tf_min * 60 * 1.5
    gapf = np.zeros(N, bool)
    gapf[1:] = np.diff(T).astype('timedelta64[s]').astype(int) > GAP

    ih = np.searchsorted((h1['time']+pd.Timedelta(hours=1)).values, T, side='right') - 1
    av = h1['atr'].values
    def A(i):
        j = ih[i]
        return av[j] if j >= 0 else np.nan

    sig = []
    for p in build_pools(bars):
        s = p['i']
        if s < 50 or s >= N - FWD - RECLAIM: continue
        a = A(s)
        if not np.isfinite(a) or a <= 0: continue
        pen, lvl = PEN_MULT*a, p['price']
        e = min(s + int(3*24*60/tf_min), N - FWD - 1)
        if e <= s: continue
        b = np.flatnonzero(H[s:e] > lvl+pen) if p['isHigh'] else np.flatnonzero(L[s:e] < lvl-pen)
        if len(b) == 0: continue
        b0 = s + b[0]
        if gapf[b0]: continue
        w = min(b0+RECLAIM+1, N)
        rec = np.flatnonzero(C[b0:w] < lvl) if p['isHigh'] else np.flatnonzero(C[b0:w] > lvl)
        if len(rec) == 0: continue
        ri = b0 + rec[0]
        if ri >= N - FWD - 1: continue
        if p['isHigh']:
            ext = H[b0:ri+1].max(); sl = ext + BUF_MULT*a; entry = C[ri]; risk = sl-entry; dr='SELL'
        else:
            ext = L[b0:ri+1].min(); sl = ext - BUF_MULT*a; entry = C[ri]; risk = entry-sl; dr='BUY'
        if risk <= SPREAD: continue
        ts = pd.Timestamp(T[ri])
        if t_lo is not None and ts <  t_lo: continue
        if t_hi is not None and ts >= t_hi: continue

        fh, fl = H[ri+1:ri+1+FWD], L[ri+1:ri+1+FWD]
        if len(fh) < FWD: continue
        up = np.maximum.accumulate(fh)-entry; dn = entry-np.minimum.accumulate(fl)
        if dr=='BUY':
            ti = np.argmax(up>=risk) if (up>=risk).any() else 10**9
            si = np.argmax(dn>=risk) if (dn>=risk).any() else 10**9
        else:
            ti = np.argmax(dn>=risk) if (dn>=risk).any() else 10**9
            si = np.argmax(up>=risk) if (up>=risk).any() else 10**9
        pnl = -SPREAD if ti==si==10**9 else ((-risk-SPREAD) if si<=ti else (risk-SPREAD))
        sig.append({'t': ts, 'dir': dr, 'risk': risk, 'pnl': pnl, 'hour': ts.hour})

    if len(sig) < 10:
        print(f"  {label:<10} only {len(sig)} signals"); return None
    p = np.array([s['pnl'] for s in sig])
    se = p.std(ddof=1)/np.sqrt(len(p))
    mr = np.median([s['risk'] for s in sig])
    days = (bars['time'].iloc[-1]-bars['time'].iloc[0]).days
    print(f"  {label:<10} n={len(p):<5} win {(p>0).mean()*100:>5.1f}%   "
          f"{p.mean():>8.3f}/trade   SE {se:>7.3f}   t={p.mean()/se:>6.2f}   "
          f"exp {p.mean()/mr:>6.3f}R   total {p.sum():>9.1f}")
    return sig

print("\n" + "="*100)
print("PRIMARY TEST - USTECm prior-day/prior-week sweep+reclaim, 1R")
print("="*100)
s_is_m1  = scan(m1, 1, "IS  M1")
s_is_m5  = scan(m5, 5, "IS  M5", t_lo=IS_START)
s_oos_m5 = scan(m5, 5, "OOS M5", t_hi=IS_START)

print("\n" + "="*100)
print("SIGNAL TIMING (server-time hour) - does the opening-range story hold?")
print("="*100)
for nm, s in (("IS  M1", s_is_m1), ("IS  M5", s_is_m5), ("OOS M5", s_oos_m5)):
    if not s: continue
    c = pd.Series([x['hour'] for x in s]).value_counts().sort_index()
    bars_ = " ".join(f"{h:02d}:{v}" for h, v in c.items())
    print(f"  {nm}  n={len(s)}")
    print(f"    {bars_}")
    top = c.sort_values(ascending=False).head(3)
    print(f"    busiest hours: {list(top.index)}  ({top.sum()}/{len(s)} = {top.sum()/len(s)*100:.0f}%)")
