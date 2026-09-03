import json
import numpy as np
import MetaTrader5 as mt5
from datetime import datetime

BRICK, REVERSAL = 50.0, 2
PT = 0.01
TP_PTS = 100.0
SPREAD_PTS = 10.0
LOTS = 0.05; SCALE = LOTS/0.01
REL_SL_PCT = 0.40
N_SEEDS = 30

files = ['coinbase_m1_2yr_part0.json','coinbase_m1_2yr_part1.json','coinbase_m1_2yr_part2.json','coinbase_m1_extra_year.json','coinbase_m1_pilot.json']
rows = {}
for f in files:
    for t, lo, hi, op, cl, vol in json.load(open(f)):
        rows[int(t)] = (op, hi, lo, cl)
ok = mt5.initialize(path=r"C:\Program Files\MetaTrader 5\terminal64.exe")
mt5.symbol_select("BTCUSDm", True)
r = mt5.copy_rates_from_pos("BTCUSDm", mt5.TIMEFRAME_M1, 0, 99000)
mt5.shutdown()
for i in range(len(r)):
    t = int(r["time"][i])
    rows[t] = (float(r["open"][i]), float(r["high"][i]), float(r["low"][i]), float(r["close"][i]))
times = sorted(rows.keys())
N = len(times)
o = np.array([rows[t][0] for t in times]); h = np.array([rows[t][1] for t in times])
l = np.array([rows[t][2] for t in times]); c = np.array([rows[t][3] for t in times])
tm = np.array(times)
span_days = (tm[-1]-tm[0])/86400
print(f"M1 bars: {N}  {datetime.utcfromtimestamp(tm[0])} -> {datetime.utcfromtimestamp(tm[-1])}  ({span_days:.1f} days)\n")

def build_bricks_signals(o,h,l,c,N):
    revs = {}
    ao = ac = float(o[0]); d = 0; pd_ = 0
    for i in range(N):
        while True:
            up = (ao if d==-1 else ac) + BRICK*(REVERSAL if d==-1 else 1)
            dn = (ao if d==1 else ac) - BRICK*(REVERSAL if d==1 else 1)
            if c[i] >= up:
                base = ao if d==-1 else ac; ao,ac,d = base, base+BRICK, 1
            elif c[i] <= dn:
                base = ao if d==1 else ac; ao,ac,d = base, base-BRICK, -1
            else: break
            if pd_ and d != pd_: revs.setdefault(i,d)
            pd_ = d
    return revs

sigs = build_bricks_signals(o,h,l,c,N)
print(f"total A0 signals: {len(sigs)}\n")

def run(o,h,l,c,tm,N,sigs,track_mae=False):
    """relative SL = entry_price * REL_SL_PCT"""
    bal_usd=0.0; wins=losses=0
    pending=None; in_pos=False; pos_L=None; pos_entry=None; pos_sl_pts=None; pos_entry_t=None
    loss_events=[]; mae_trace=[]
    for j in range(N):
        if pending is not None:
            L,entry,et = pending; in_pos=True; pos_L=L; pos_entry=entry; pos_entry_t=et; pending=None
            pos_sl_pts = entry * REL_SL_PCT
            mae_this = 0.0
        if j in sigs and j+1<N and not in_pos:
            L=(sigs[j]==1); SP=SPREAD_PTS if L else 0.0
            entry = o[j+1]+SP if L else o[j+1]
            pending=(L,entry,tm[j+1])
        if in_pos:
            adv = (pos_entry-l[j]) if pos_L else (h[j]-pos_entry)
            if adv > mae_this: mae_this = adv
            tp_price = pos_entry+TP_PTS if pos_L else pos_entry-TP_PTS
            sl_price = pos_entry-pos_sl_pts if pos_L else pos_entry+pos_sl_pts
            hit_tp = (h[j]>=tp_price) if pos_L else (l[j]<=tp_price)
            hit_sl = (l[j]<=sl_price) if pos_L else (h[j]>=sl_price)
            if hit_tp or hit_sl:
                usd = (-pos_sl_pts if hit_sl else TP_PTS)*PT*SCALE
                bal_usd += usd
                if hit_sl:
                    losses+=1; loss_events.append((pos_L, datetime.utcfromtimestamp(pos_entry_t), round(usd,2)))
                else: wins+=1
                if track_mae:
                    mae_trace.append(dict(entry_t=datetime.utcfromtimestamp(pos_entry_t),
                                           exit_t=datetime.utcfromtimestamp(tm[j]),
                                           L=pos_L, won=hit_tp, mae_usd=round(mae_this*PT*SCALE,2)))
                in_pos=False
    return dict(trades=wins+losses, wins=wins, losses=losses, net=bal_usd, loss_events=loss_events, mae_trace=mae_trace)

zA = run(o,h,l,c,tm,N,sigs, track_mae=True)
print(f"A0 (real reversal-brick entry, relative 40% SL): trades {zA['trades']}  win% {100*zA['wins']/zA['trades']:.2f}  "
      f"losses {zA['losses']}  net ${zA['net']:.2f}   ${zA['net']/(span_days/30.44):.2f}/mo")
for L,t,usd in zA['loss_events']:
    print(f"    LOSS: {'BUY' if L else 'SELL'} {t}  ${usd}")

print(f"\nRANDOM entry control - relative 40% SL, same TP, same candidate-signal COUNT ({len(sigs)}), {N_SEEDS} seeds:")
results = []
for seed in range(N_SEEDS):
    rng = np.random.default_rng(seed)
    idx = rng.choice(N-1, size=min(len(sigs), N-1), replace=False)
    dirs = rng.choice([1,-1], size=len(idx))
    rsig = dict(zip(idx.tolist(), dirs.tolist()))
    z = run(o,h,l,c,tm,N,rsig)
    results.append(z)
    wr = 100*z['wins']/z['trades'] if z['trades'] else 0
    print(f"  seed {seed:>2}: trades {z['trades']:>4}  win% {wr:>5.2f}%  losses {z['losses']:>2}  net ${z['net']:>10,.2f}")

ends = [z['net'] for z in results]
print(f"\nA0 (real entry) net: ${zA['net']:,.2f}")
print(f"random average net:  ${np.mean(ends):,.2f}   (min ${min(ends):,.2f}, max ${max(ends):,.2f}, median ${np.median(ends):,.2f})")
print(f"random seeds that beat A0: {sum(1 for e in ends if e > zA['net'])}/{N_SEEDS}")
print(f"A0 percentile rank vs random distribution: {100*sum(1 for e in ends if e < zA['net'])/N_SEEDS:.0f}th percentile")

print(f"\n=== MAE (max adverse excursion) trace, all {len(zA['mae_trace'])} trades, relative 40% SL ===")
mae_sorted = sorted(range(len(zA['mae_trace'])), key=lambda i: -zA['mae_trace'][i]['mae_usd'])
top = mae_sorted[0]
print(f"MAX MAE: trade #{top} entry {zA['mae_trace'][top]['entry_t']} {'BUY' if zA['mae_trace'][top]['L'] else 'SELL'}  "
      f"MAE=${zA['mae_trace'][top]['mae_usd']:.2f}  outcome={'WIN' if zA['mae_trace'][top]['won'] else 'LOSS'}")
if top > 0:
    prev = zA['mae_trace'][top-1]
    print(f"trade JUST BEFORE it (#{top-1}): entry {prev['entry_t']} {'BUY' if prev['L'] else 'SELL'}  "
          f"MAE=${prev['mae_usd']:.2f}  outcome={'WIN' if prev['won'] else 'LOSS'}")
print(f"\ntop 10 MAE trades:")
for i in mae_sorted[:10]:
    t = zA['mae_trace'][i]
    print(f"  #{i:>4}  {t['entry_t']}  {'BUY' if t['L'] else 'SELL'}  MAE=${t['mae_usd']:>9,.2f}  {'WIN' if t['won'] else 'LOSS'}")

print("\n=== MAE FREQUENCY DISTRIBUTION (relative 40% SL, all 1777 trades) - 'which DD does noise hit most' ===")
maes = np.array([t['mae_usd'] for t in zA['mae_trace']])
for p in [10,25,50,75,90,95,99,99.5,100]:
    print(f"  p{p:<5}: ${np.percentile(maes,p):>9,.2f}")

print("\nfrequency table (>= threshold):")
for thr in [1,2,5,10,20,50,100,200,500,1000,2000]:
    n = (maes>=thr).sum()
    print(f"  >=${thr:<6}: {n:>4} trades ({100*n/len(maes):5.2f}%)  1-in-{len(maes)/max(n,1):.0f}" if n else f"  >=${thr:<6}: 0 trades")
