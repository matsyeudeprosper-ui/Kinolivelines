"""Liquidity-sweep test - PRE-REGISTERED, parameters fixed before any result.

Hypothesis: the tradeable event at a KinoliveLines level is not a touch but a
SWEEP - price penetrates the level (taking resting stops), then reclaims it.

  sell-side sweep : low  < support   - pen, then close > support   -> BUY
  buy-side  sweep : high > resistance + pen, then close < resistance -> SELL

Fixed parameters (chosen from mechanism, not tuned):
  pen        = 0.10 * ATR(H1)     penetration must clearly exceed the $10 spread
  reclaim    = within 15 M1 bars
  stop       = beyond the sweep extreme + 0.10 * ATR(H1)
  target     = 1R / 2R / 3R
  horizon    = 480 M1 bars
  cost       = $10 per round trip

Control: same direction, random entry time, same risk distance and R multiple.
Drift affects control and signal equally, so the difference is the edge.
"""
import MetaTrader5 as mt5, pandas as pd, numpy as np, os

SPREAD = 10.0
PEN_MULT = 0.10
RECLAIM_BARS = 15
BUF_MULT = 0.10
FWD = 480
rng = np.random.default_rng(11)

mt5.initialize()
SYM = "BTCUSDm"
def R(tf, n):
    d = pd.DataFrame(mt5.copy_rates_from_pos(SYM, tf, 0, n))
    d['time'] = pd.to_datetime(d['time'], unit='s'); return d
m1, m15, h1, h4 = R(mt5.TIMEFRAME_M1,50000), R(mt5.TIMEFRAME_M15,20000), R(mt5.TIMEFRAME_H1,20000), R(mt5.TIMEFRAME_H4,20000)
mt5.shutdown()

def atr(d, n=14):
    pc = d['close'].shift(1)
    return pd.concat([d['high']-d['low'],(d['high']-pc).abs(),(d['low']-pc).abs()],axis=1).max(axis=1).rolling(n).mean()
h1['atr'] = atr(h1)

DUR = {'H4': pd.Timedelta(hours=4), 'H1': pd.Timedelta(hours=1), 'M15': pd.Timedelta(minutes=15)}
SRC = {'H4': (h4,3), 'H1': (h1,2), 'M15': (m15,1)}
idx = {n: np.searchsorted((SRC[n][0]['time']+DUR[n]).values, m1['time'].values, side='right')-1 for n in SRC}
arrs = {n: (SRC[n][0]['high'].values, SRC[n][0]['low'].values, SRC[n][1]) for n in SRC}
h1_atr_v = h1['atr'].values
H, L, C = m1['high'].values, m1['low'].values, m1['close'].values
T = m1['time'].values

def build(i):
    raw = []
    for name in ('H4','H1','M15'):
        j = idx[name][i]
        if j < 0: continue
        hi, lo, prio = arrs[name]
        raw.append([hi[j], True, prio, name]); raw.append([lo[j], False, prio, name])
    if not raw: return []
    j1 = idx['H1'][i]
    a = h1_atr_v[j1] if j1 >= 0 and not np.isnan(h1_atr_v[j1]) else SPREAD*10
    tol = max(SPREAD*3.0, a*0.12)
    raw.sort(key=lambda r: r[0]); keep=[True]*len(raw)
    for x in range(len(raw)):
        if not keep[x]: continue
        for y in range(x+1,len(raw)):
            if not keep[y]: continue
            if abs(raw[x][0]-raw[y][0]) <= tol:
                if raw[y][2] > raw[x][2]: raw[x]=raw[y]
                keep[y]=False
    merged=[r for x,r in enumerate(raw) if keep[x]]
    md = merged[0][0]*0.001; out=[]
    for r in merged:
        if not out or r[1]!=out[-1][1] or abs(r[0]-out[-1][0])>=md: out.append(r)
        if len(out)>=6: break
    return out

# ---------- find sweeps ----------
signals = []
active = {}          # key -> bar index where penetration began
for i in range(300, len(m1)-FWD-RECLAIM_BARS):
    j1 = idx['H1'][i]
    a = h1_atr_v[j1] if j1 >= 0 else np.nan
    if not np.isfinite(a) or a <= 0: continue
    pen = PEN_MULT*a
    for price, isHigh, prio, tf in build(i):
        k = (round(price,2), isHigh)
        if isHigh:
            if H[i] > price + pen:
                if k not in active: active[k] = (i, H[i])
                else: active[k] = (active[k][0], max(active[k][1], H[i]))
            elif k in active:
                st, ext = active.pop(k)
                if i - st <= RECLAIM_BARS and C[i] < price:
                    sl = ext + BUF_MULT*a
                    signals.append({'i':i,'dir':'SELL','entry':C[i],'sl':sl,
                                    'risk':sl-C[i],'tf':tf,'level':price,'time':T[i]})
        else:
            if L[i] < price - pen:
                if k not in active: active[k] = (i, L[i])
                else: active[k] = (active[k][0], min(active[k][1], L[i]))
            elif k in active:
                st, ext = active.pop(k)
                if i - st <= RECLAIM_BARS and C[i] > price:
                    sl = ext - BUF_MULT*a
                    signals.append({'i':i,'dir':'BUY','entry':C[i],'sl':sl,
                                    'risk':C[i]-sl,'tf':tf,'level':price,'time':T[i]})

signals = [s for s in signals if s['risk'] > SPREAD]
print(f"sweep signals: {len(signals)}   BUY {sum(1 for s in signals if s['dir']=='BUY')}"
      f"  SELL {sum(1 for s in signals if s['dir']=='SELL')}")
span_days = (m1['time'].iloc[-1]-m1['time'].iloc[0]).days
print(f"period {span_days}d  ->  {len(signals)/span_days*30:.0f} signals/month")
print(f"median risk ${np.median([s['risk'] for s in signals]):.0f}")

def outcome(i, entry, direction, risk, rmult):
    fh, fl = H[i+1:i+1+FWD], L[i+1:i+1+FWD]
    if len(fh) < FWD: return None
    up = np.maximum.accumulate(fh)-entry
    dn = entry-np.minimum.accumulate(fl)
    tp_d = risk*rmult
    if direction=='BUY':
        tpi = np.argmax(up>=tp_d) if (up>=tp_d).any() else 10**9
        sli = np.argmax(dn>=risk) if (dn>=risk).any() else 10**9
    else:
        tpi = np.argmax(dn>=tp_d) if (dn>=tp_d).any() else 10**9
        sli = np.argmax(up>=risk) if (up>=risk).any() else 10**9
    if tpi==sli==10**9: return -SPREAD
    if sli<=tpi: return -risk-SPREAD
    return tp_d-SPREAD

print("\n"+"="*94)
print(f"{'entry':<24}{'side':<6}{'R':>4}{'n':>7}{'win%':>8}{'$/trade':>11}{'total$':>12}{'expectancy(R)':>15}")
print("="*94)
for rmult in (1,2,3):
    for side in ('BUY','SELL','BOTH'):
        subs = signals if side=='BOTH' else [s for s in signals if s['dir']==side]
        if len(subs) < 30: continue
        sig = np.array([x for x in (outcome(s['i'],s['entry'],s['dir'],s['risk'],rmult) for s in subs) if x is not None])
        # control: same direction, same risk, random time
        ctl = []
        for s in subs:
            ri = int(rng.integers(300, len(m1)-FWD-1))
            o = outcome(ri, C[ri], s['dir'], s['risk'], rmult)
            if o is not None: ctl.append(o)
        ctl = np.array(ctl)
        medrisk = np.median([s['risk'] for s in subs])
        print(f"{'SWEEP+RECLAIM':<24}{side:<6}{rmult:>4}{len(sig):>7}{(sig>0).mean()*100:>8.1f}"
              f"{sig.mean():>11.2f}{sig.sum():>12.0f}{sig.mean()/medrisk:>15.3f}")
        print(f"{'  random control':<24}{side:<6}{rmult:>4}{len(ctl):>7}{(ctl>0).mean()*100:>8.1f}"
              f"{ctl.mean():>11.2f}{ctl.sum():>12.0f}{ctl.mean()/medrisk:>15.3f}")
        print(f"{'  >> EDGE':<24}{'':<6}{'':>4}{'':>7}{'':>8}{sig.mean()-ctl.mean():>11.2f}")
        print("-"*94)
