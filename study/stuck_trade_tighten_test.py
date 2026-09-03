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

TRIGGER_DAYS = 30.0
TRIGGER_DEPTH_PCT = 0.45  # of the ORIGINAL sl width (not of price)

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
print(f"M1 bars: {N}  ({span_days:.1f} days)\n")

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

def run(o,h,l,c,tm,N,sigs,tighten_pct):
    """tighten_pct: after TRIGGER_DAYS held AND TRIGGER_DEPTH_PCT of original
    SL width used, move SL to entry_price*tighten_pct (must be < REL_SL_PCT
    to mean anything). tighten_pct=None means no tightening (control)."""
    bal=0.0; wins=losses=0
    pending=None; in_pos=False; pos_L=None; pos_entry=None; pos_sl=None; pos_et=None
    pos_tightened=False
    loss_events=[]; tighten_events=0
    for j in range(N):
        if pending is not None:
            L,entry,et = pending; in_pos=True; pos_L=L; pos_entry=entry; pos_et=et; pending=None
            pos_sl = entry*REL_SL_PCT
            pos_tightened=False
        if j in sigs and j+1<N and not in_pos:
            L=(sigs[j]==1); SP=SPREAD_PTS if L else 0.0
            entry = o[j+1]+SP if L else o[j+1]
            pending=(L,entry,tm[j+1])
        if in_pos:
            if tighten_pct is not None and not pos_tightened:
                days_in = (tm[j]-pos_et)/86400
                if days_in >= TRIGGER_DAYS:
                    adv = (pos_entry-l[j]) if pos_L else (h[j]-pos_entry)
                    depth_pct = adv/pos_sl
                    if depth_pct >= TRIGGER_DEPTH_PCT:
                        new_sl = pos_entry*tighten_pct
                        if new_sl < pos_sl:
                            pos_sl = new_sl
                            pos_tightened = True
                            tighten_events += 1
            tpp = pos_entry+TP_PTS if pos_L else pos_entry-TP_PTS
            slp = pos_entry-pos_sl if pos_L else pos_entry+pos_sl
            htp = (h[j]>=tpp) if pos_L else (l[j]<=tpp)
            hsl = (l[j]<=slp) if pos_L else (h[j]>=slp)
            if htp or hsl:
                usd = (-pos_sl if hsl else TP_PTS)*PT*SCALE
                bal += usd
                if hsl: losses+=1; loss_events.append((pos_L, datetime.utcfromtimestamp(pos_et), datetime.utcfromtimestamp(tm[j]), round(usd,2), pos_tightened))
                else: wins+=1
                in_pos=False
    return dict(trades=wins+losses, wins=wins, losses=losses, net=bal, loss_events=loss_events, tighten_events=tighten_events)

zb = run(o,h,l,c,tm,N,sigs,None)
print(f"CONTROL (no tightening, today's live config): trades {zb['trades']}  losses {zb['losses']}  net ${zb['net']:.2f}")
for L,et,xt,usd,tg in zb['loss_events']:
    print(f"    LOSS: {'BUY' if L else 'SELL'} entered {et}  ${usd}")

print(f"\nTRIGGER: held >={TRIGGER_DAYS:.0f}d AND adverse >= {100*TRIGGER_DEPTH_PCT:.0f}% of original SL width\n")
for tp in [0.10, 0.15, 0.20, 0.25, 0.30, 0.35]:
    z = run(o,h,l,c,tm,N,sigs,tp)
    print(f"tighten-to {100*tp:>4.0f}%:  trades {z['trades']:>4}  losses {z['losses']:>2}  net ${z['net']:>10,.2f}  (triggered {z['tighten_events']}x, diff vs control ${z['net']-zb['net']:+,.2f})")
    for L,et,xt,usd,tg in z['loss_events']:
        tag = "TIGHTENED" if tg else "full SL"
        print(f"      LOSS [{tag}]: {'BUY' if L else 'SELL'} entered {et}  closed {xt}  ${usd}")
