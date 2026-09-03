import json
import numpy as np
import MetaTrader5 as mt5
from datetime import datetime
from collections import defaultdict

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
o_f = np.array([rows[t][0] for t in times]); h_f = np.array([rows[t][1] for t in times])
l_f = np.array([rows[t][2] for t in times]); c_f = np.array([rows[t][3] for t in times])
tm_f = np.array(times)
N = len(times)

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

sigs = build_bricks_signals(o_f,h_f,l_f,c_f,N)

def run_full(o,h,l,c,tm,N,sigs,trig_f,cap_f):
    bal=0.0; realized_cum=0.0
    pending=None; in_pos=False; pos_L=None; pos_entry=None; pos_sl=None
    losses = []
    for j in range(N):
        if pending is not None:
            L,entry = pending; in_pos=True; pos_L=L; pos_entry=entry; pending=None
            if trig_f is None:
                pos_sl = pos_entry*REL_SL_PCT
            else:
                default_sl_usd = pos_entry*REL_SL_PCT*LOTS
                trig = trig_f*default_sl_usd; cap = cap_f*default_sl_usd
                if realized_cum >= trig:
                    sl_usd = min(max(realized_cum,0.0), cap)
                else:
                    sl_usd = default_sl_usd
                pos_sl = sl_usd/LOTS
        if j in sigs and j+1<N and not in_pos:
            L=(sigs[j]==1); SP=SPREAD_PTS if L else 0.0
            entry = o[j+1]+SP if L else o[j+1]
            pending=(L,entry)
        if in_pos:
            tpp = pos_entry+TP_PTS if pos_L else pos_entry-TP_PTS
            slp = pos_entry-pos_sl if pos_L else pos_entry+pos_sl
            htp = (h[j]>=tpp) if pos_L else (l[j]<=tpp)
            hsl = (l[j]<=slp) if pos_L else (h[j]>=slp)
            if htp or hsl:
                usd = (-pos_sl if hsl else TP_PTS)*PT*SCALE
                bal += usd
                if trig_f is not None: realized_cum += usd
                if hsl: losses.append((tm[j], round(usd,2)))
                in_pos=False
    return losses, bal

def report(losses, label):
    print(f"\n=== {label} - {len(losses)} losses total ===")
    by_month = defaultdict(int)
    dates = []
    for epoch, usd in losses:
        dt = datetime.utcfromtimestamp(epoch)
        by_month[(dt.year, dt.month)] += 1
        dates.append(dt)
        print(f"  {dt.strftime('%Y-%m-%d %H:%M')}  {usd:>+10,.2f}")
    print(f"\n  losses per month (only months with >=1 loss):")
    for (y,m), cnt in sorted(by_month.items()):
        print(f"    {y}-{m:02d}: {cnt}")
    if len(dates) > 1:
        gaps = [(dates[i+1]-dates[i]).days for i in range(len(dates)-1)]
        print(f"\n  gap between consecutive losses (days): min={min(gaps)} max={max(gaps)} "
              f"avg={sum(gaps)/len(gaps):.1f} median={sorted(gaps)[len(gaps)//2]}")
        print(f"  all gaps: {gaps}")
    total_span_days = (datetime.utcfromtimestamp(times[-1]) - datetime.utcfromtimestamp(times[0])).days
    print(f"  overall: 1 loss every ~{total_span_days/len(losses):.0f} days on average across the full {total_span_days}-day history")

print("running baseline (no ratchet, the old rule)...")
losses_base, net_base = run_full(o_f,h_f,l_f,c_f,tm_f,N,sigs,None,None)
report(losses_base, "OLD RULE (relative 40% SL only, no ratchet)")

print("\nrunning CURRENT LIVE RULE (ratchet trigger=30%, cap=100%)...")
losses_rat, net_rat = run_full(o_f,h_f,l_f,c_f,tm_f,N,sigs,0.30,1.00)
report(losses_rat, "CURRENT LIVE RULE (Breakeven Ratchet trigger=30%, cap=100%)")
