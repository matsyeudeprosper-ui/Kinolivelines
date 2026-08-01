"""Same pre-registered liquidity-sweep test, any symbol.

Usage: python pool_test.py XAUUSDm US500m USTECm BTCUSDm

Rules are FIXED and identical to the BTCUSDm run - nothing is retuned per
instrument, so results are directly comparable:
  pool kinds : EQH/EQL (clustered M15 swings), PDH/PDL, PWH/PWL, session H/L
  pool life  : consumed on first penetration (liquidity taken is gone)
  sweep      : penetrate >= 0.10*ATR(H1), reclaim within 15 M1 bars
  stop       : beyond sweep extreme + 0.10*ATR(H1);  targets 1R / 2R
  cost       : the symbol's live spread, charged once per round trip
  control    : same direction, same risk, random entry time

Indices are not 24/7, so any penetration occurring on the first bar after a
session/weekend gap is discarded - that is a gap, not a stop hunt.
"""
import MetaTrader5 as mt5, pandas as pd, numpy as np, sys

PEN_MULT, RECLAIM_BARS, BUF_MULT = 0.10, 15, 0.10
FWD, SWING_K, EQ_TOL_MULT = 480, 2, 0.05
GAP_SEC = 300          # >5 min between M1 bars = market was shut

def run(SYM, rng):
    if not mt5.symbol_select(SYM, True):
        print(f"{SYM}: cannot select"); return
    tick = mt5.symbol_info_tick(SYM)
    SPREAD = tick.ask - tick.bid

    def R(tf, n):
        r = mt5.copy_rates_from_pos(SYM, tf, 0, n)
        if r is None or len(r) == 0: return None
        d = pd.DataFrame(r); d['time'] = pd.to_datetime(d['time'], unit='s'); return d

    m1, m15, h1, d1 = R(mt5.TIMEFRAME_M1,50000), R(mt5.TIMEFRAME_M15,20000), R(mt5.TIMEFRAME_H1,20000), R(mt5.TIMEFRAME_D1,2000)
    if m1 is None or len(m1) < 5000 or m15 is None or h1 is None or d1 is None:
        print(f"{SYM}: insufficient history"); return

    def atr(d, n=14):
        pc = d['close'].shift(1)
        return pd.concat([d['high']-d['low'],(d['high']-pc).abs(),(d['low']-pc).abs()],
                         axis=1).max(axis=1).rolling(n).mean()
    h1['atr'] = atr(h1)

    T,Hh,Ll,Cc = m1['time'].values, m1['high'].values, m1['low'].values, m1['close'].values
    N = len(m1)
    gap = np.zeros(N, bool)
    dt = np.diff(T).astype('timedelta64[s]').astype(int)
    gap[1:] = dt > GAP_SEC

    idx_h1 = np.searchsorted((h1['time']+pd.Timedelta(hours=1)).values, T, side='right') - 1
    h1_atr_v = h1['atr'].values
    def atr_at(i):
        j = idx_h1[i]
        return h1_atr_v[j] if j >= 0 else np.nan
    def m1_at(ts): return int(np.searchsorted(T, np.datetime64(ts), side='left'))

    days = (m1['time'].iloc[-1]-m1['time'].iloc[0]).days
    med_atr = np.nanmedian(h1['atr'].values)
    print(f"\n{'='*104}\n{SYM}   spread {SPREAD:.5g}   median ATR(H1) {med_atr:.5g}   "
          f"cost {SPREAD/med_atr*100:.2f}% of ATR   M1 history {days}d ({N} bars)")

    # ---------- pools ----------
    pools = []
    mh, ml, mt_ = m15['high'].values, m15['low'].values, m15['time'].values
    sw = {True: [], False: []}
    for i in range(SWING_K, len(m15)-SWING_K):
        if mh[i] == mh[i-SWING_K:i+SWING_K+1].max(): sw[True].append((i, mh[i]))
        if ml[i] == ml[i-SWING_K:i+SWING_K+1].min(): sw[False].append((i, ml[i]))
    for isHigh, lst in sw.items():
        clusters = []
        for si, price in lst:
            ci = si + SWING_K
            if ci >= len(m15): continue
            i1 = m1_at(mt_[ci])
            if i1 >= N: continue
            a = atr_at(i1)
            if not np.isfinite(a) or a <= 0: continue
            tol = max(SPREAD*2.0, a*EQ_TOL_MULT)
            hit = next((c for c in clusters if abs(c[0]-price) <= tol), None)
            if hit is None: clusters.append([price, 1])
            else:
                hit[1] += 1
                if hit[1] == 2:
                    pools.append({'price':hit[0],'isHigh':isHigh,'from_i':i1,
                                  'kind':'EQH' if isHigh else 'EQL'})
            if len(clusters) > 400: clusters = clusters[-200:]

    for i in range(1, len(d1)):
        i1 = m1_at(d1['time'].values[i])
        if i1 >= N: continue
        pools.append({'price':d1['high'].values[i-1],'isHigh':True, 'from_i':i1,'kind':'PDH'})
        pools.append({'price':d1['low' ].values[i-1],'isHigh':False,'from_i':i1,'kind':'PDL'})

    wk = d1.set_index('time').resample('W-MON',label='left',closed='left').agg({'high':'max','low':'min'}).dropna().reset_index()
    for i in range(1, len(wk)):
        i1 = m1_at(wk['time'].values[i])
        if i1 >= N: continue
        pools.append({'price':wk['high'].values[i-1],'isHigh':True, 'from_i':i1,'kind':'PWH'})
        pools.append({'price':wk['low' ].values[i-1],'isHigh':False,'from_i':i1,'kind':'PWL'})

    mi = m1.set_index('time')
    for name,hf,ht in [('ASIA',0,8),('LON',8,16),('NY',13,21)]:
        sel = mi[(mi.index.hour>=hf)&(mi.index.hour<ht)]
        if len(sel)==0: continue
        g = sel.groupby(sel.index.normalize()).agg({'high':'max','low':'min'})
        ds = list(g.index)
        for k in range(1,len(ds)):
            i1 = m1_at(ds[k-1]+pd.Timedelta(hours=ht))
            if i1>=N: continue
            pools.append({'price':g['high'].iloc[k-1],'isHigh':True, 'from_i':i1,'kind':f'SES_{name}_H'})
            pools.append({'price':g['low' ].iloc[k-1],'isHigh':False,'from_i':i1,'kind':f'SES_{name}_L'})

    pools = [p for p in pools if 300 <= p['from_i'] < N-FWD-RECLAIM_BARS]

    # ---------- sweeps ----------
    sig = []
    for p in pools:
        a = atr_at(p['from_i'])
        if not np.isfinite(a) or a <= 0: continue
        pen, lvl = PEN_MULT*a, p['price']
        s, e = p['from_i'], min(p['from_i']+5000, N-FWD-1)
        if e <= s: continue
        beyond = np.flatnonzero(Hh[s:e] > lvl+pen) if p['isHigh'] else np.flatnonzero(Ll[s:e] < lvl-pen)
        if len(beyond)==0: continue
        b0 = s+beyond[0]
        if gap[b0]: continue                       # gap, not a stop hunt
        w = min(b0+RECLAIM_BARS+1, N)
        rec = np.flatnonzero(Cc[b0:w] < lvl) if p['isHigh'] else np.flatnonzero(Cc[b0:w] > lvl)
        if len(rec)==0: continue
        ri = b0+rec[0]
        if p['isHigh']:
            ext = Hh[b0:ri+1].max(); sl = ext+BUF_MULT*a; entry = Cc[ri]; risk = sl-entry; dr='SELL'
        else:
            ext = Ll[b0:ri+1].min(); sl = ext-BUF_MULT*a; entry = Cc[ri]; risk = entry-sl; dr='BUY'
        if risk <= SPREAD or ri >= N-FWD-1: continue
        sig.append({'i':ri,'dir':dr,'entry':entry,'risk':risk,'kind':p['kind']})

    if len(sig) < 30:
        print(f"  only {len(sig)} signals - not enough to judge"); return
    print(f"  pools {len(pools)}  ->  signals {len(sig)}  ({len(sig)/days*30:.0f}/month)   "
          f"BUY {sum(1 for s in sig if s['dir']=='BUY')} SELL {sum(1 for s in sig if s['dir']=='SELL')}   "
          f"median risk {np.median([s['risk'] for s in sig]):.4g}")

    def outcome(i, entry, dr, risk, rm):
        fh, fl = Hh[i+1:i+1+FWD], Ll[i+1:i+1+FWD]
        if len(fh) < FWD: return None
        up = np.maximum.accumulate(fh)-entry; dn = entry-np.minimum.accumulate(fl)
        tp = risk*rm
        if dr=='BUY':
            ti = np.argmax(up>=tp) if (up>=tp).any() else 10**9
            si = np.argmax(dn>=risk) if (dn>=risk).any() else 10**9
        else:
            ti = np.argmax(dn>=tp) if (dn>=tp).any() else 10**9
            si = np.argmax(up>=risk) if (up>=risk).any() else 10**9
        if ti==si==10**9: return -SPREAD
        return (-risk-SPREAD) if si<=ti else (tp-SPREAD)

    print(f"  {'group':<14}{'R':>3}{'n':>6}{'win%':>7}{'/trade':>11}{'SE':>10}{'t':>7}{'exp(R)':>9}{'ctrl':>11}{'edge':>10}")
    for rm in (1,2):
        for gname, subs in [('ALL',sig), ('EQH+EQL',[s for s in sig if s['kind'].startswith('EQ')]),
                            ('PD+PW',[s for s in sig if s['kind'][:2] in ('PD','PW')]),
                            ('SESSIONS',[s for s in sig if s['kind'].startswith('SES')])]:
            if len(subs) < 30: continue
            a_ = np.array([x for x in (outcome(s['i'],s['entry'],s['dir'],s['risk'],rm) for s in subs) if x is not None])
            c_ = np.array([x for x in (outcome(int(rng.integers(300,N-FWD-1)), Cc[int(rng.integers(300,N-FWD-1))], s['dir'], s['risk'], rm) for s in subs) if x is not None])
            if len(a_) < 30: continue
            se = a_.std(ddof=1)/np.sqrt(len(a_)); mr = np.median([s['risk'] for s in subs])
            print(f"  {gname:<14}{rm:>3}{len(a_):>6}{(a_>0).mean()*100:>7.1f}{a_.mean():>11.4g}"
                  f"{se:>10.4g}{a_.mean()/se:>7.2f}{a_.mean()/mr:>9.3f}{c_.mean():>11.4g}{a_.mean()-c_.mean():>10.4g}")

mt5.initialize()
rng = np.random.default_rng(31)
for s in (sys.argv[1:] or ["XAUUSDm","US500m","USTECm"]):
    try: run(s, rng)
    except Exception as ex: print(f"{s}: {type(ex).__name__}: {ex}")
mt5.shutdown()
print("\nBar: t > 2 AND positive /trade. Anything else is noise.")
