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

files = ['coinbase_m1_2yr_partneg1.json','coinbase_m1_2yr_part0.json','coinbase_m1_2yr_part1.json',
         'coinbase_m1_2yr_part2.json','coinbase_m1_extra_year.json','coinbase_m1_pilot.json']
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

CHECKPOINTS = [5, 10, 20, 30]  # days
pending=None; in_pos=False; pos_L=None; pos_entry=None; pos_sl=None; pos_et=None
checkpoints_hit = None
long_trades = []  # trades that survive past day 5
for j in range(N):
    if pending is not None:
        L,entry,et = pending; in_pos=True; pos_L=L; pos_entry=entry; pos_et=et; pending=None
        pos_sl = pos_entry*REL_SL_PCT
        checkpoints_hit = {}
    if j in sigs and j+1<N and not in_pos:
        L=(sigs[j]==1); SP=SPREAD_PTS if L else 0.0
        entry = o[j+1]+SP if L else o[j+1]
        pending=(L,entry,tm[j+1])
    if in_pos:
        days_in = (tm[j]-pos_et)/86400
        adv = (pos_entry-l[j]) if pos_L else (h[j]-pos_entry)
        depth_pct = adv/pos_sl
        for cp in CHECKPOINTS:
            if days_in>=cp and cp not in checkpoints_hit:
                checkpoints_hit[cp] = depth_pct
        tpp = pos_entry+TP_PTS if pos_L else pos_entry-TP_PTS
        slp = pos_entry-pos_sl if pos_L else pos_entry+pos_sl
        htp = (h[j]>=tpp) if pos_L else (l[j]<=tpp)
        hsl = (l[j]<=slp) if pos_L else (h[j]>=slp)
        if htp or hsl:
            if 5 in checkpoints_hit:  # survived past day 5 - part of the "long trade" population
                long_trades.append(dict(entry_t=datetime.utcfromtimestamp(pos_et), L=pos_L,
                                         won=htp, checkpoints=dict(checkpoints_hit),
                                         final_days=(tm[j]-pos_et)/86400))
            in_pos=False

print(f"total 'long' trades (survived past day 5): {len(long_trades)}")
wins = [t for t in long_trades if t['won']]
losses = [t for t in long_trades if not t['won']]
print(f"  of those: {len(wins)} eventually WON, {len(losses)} eventually LOST")
print(f"  base rate: {100*len(losses)/len(long_trades):.1f}% of long trades become losses")
print()

for cp in CHECKPOINTS:
    print(f"=== at day {cp} checkpoint ===")
    w_depths = [t['checkpoints'][cp] for t in wins if cp in t['checkpoints']]
    l_depths = [t['checkpoints'][cp] for t in losses if cp in t['checkpoints']]
    if not w_depths or not l_depths:
        print("  not enough data at this checkpoint")
        continue
    print(f"  winners (n={len(w_depths)}): depth mean={np.mean(w_depths)*100:.1f}%  median={np.median(w_depths)*100:.1f}%  p75={np.percentile(w_depths,75)*100:.1f}%  p90={np.percentile(w_depths,90)*100:.1f}%  max={max(w_depths)*100:.1f}%")
    print(f"  losers  (n={len(l_depths)}): depth mean={np.mean(l_depths)*100:.1f}%  median={np.median(l_depths)*100:.1f}%  min={min(l_depths)*100:.1f}%  max={max(l_depths)*100:.1f}%")
