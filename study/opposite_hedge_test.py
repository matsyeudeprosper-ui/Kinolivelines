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
print(f"total signals: {len(sigs)}  window {span_days:.1f} days\n")

def run_baseline(o,h,l,c,tm,N,sigs):
    bal=0.0; wins=losses=0; pending=None; in_pos=False; pos_L=None; pos_entry=None; pos_sl=None
    for j in range(N):
        if pending is not None:
            L,entry = pending; in_pos=True; pos_L=L; pos_entry=entry; pending=None
            pos_sl = entry*REL_SL_PCT
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
                if hsl: losses+=1
                else: wins+=1
                in_pos=False
    return dict(trades=wins+losses, wins=wins, losses=losses, net=bal)

def run_with_hedge(o,h,l,c,tm,N,sigs):
    """primary position: same rule as baseline. While primary is open, if an
    OPPOSITE-direction signal fires and no hedge is currently open, open a
    second (hedge) position, independent TP/SL, running alongside. Same-
    direction signals while primary is open are still skipped (no pyramiding
    - that's the already-tested-and-rejected failure mode)."""
    bal=0.0; wins=losses=0; hedge_trades=0; hedge_wins=0; hedge_losses=0
    pending=None; in_pos=False; pos_L=None; pos_entry=None; pos_sl=None
    hpending=None; h_in_pos=False; h_L=None; h_entry=None; h_sl=None
    loss_events=[]
    for j in range(N):
        if pending is not None:
            L,entry = pending; in_pos=True; pos_L=L; pos_entry=entry; pending=None
            pos_sl = entry*REL_SL_PCT
        if hpending is not None:
            L,entry = hpending; h_in_pos=True; h_L=L; h_entry=entry; hpending=None
            h_sl = entry*REL_SL_PCT

        if j in sigs and j+1<N:
            sig_L = (sigs[j]==1)
            if not in_pos:
                SP=SPREAD_PTS if sig_L else 0.0
                entry = o[j+1]+SP if sig_L else o[j+1]
                pending=(sig_L, entry)
            elif in_pos and (sig_L != pos_L) and not h_in_pos:
                SP=SPREAD_PTS if sig_L else 0.0
                entry = o[j+1]+SP if sig_L else o[j+1]
                hpending=(sig_L, entry)
            # same-direction signal while primary open, or hedge already open: skip (unchanged)

        if in_pos:
            tpp = pos_entry+TP_PTS if pos_L else pos_entry-TP_PTS
            slp = pos_entry-pos_sl if pos_L else pos_entry+pos_sl
            htp = (h[j]>=tpp) if pos_L else (l[j]<=tpp)
            hsl = (l[j]<=slp) if pos_L else (h[j]>=slp)
            if htp or hsl:
                usd = (-pos_sl if hsl else TP_PTS)*PT*SCALE
                bal += usd
                if hsl: losses+=1; loss_events.append(('PRIMARY', pos_L, datetime.utcfromtimestamp(tm[j]), round(usd,2)))
                else: wins+=1
                in_pos=False
        if h_in_pos:
            tpp = h_entry+TP_PTS if h_L else h_entry-TP_PTS
            slp = h_entry-h_sl if h_L else h_entry+h_sl
            htp = (h[j]>=tpp) if h_L else (l[j]<=tpp)
            hsl2 = (l[j]<=slp) if h_L else (h[j]>=slp)
            if htp or hsl2:
                usd = (-h_sl if hsl2 else TP_PTS)*PT*SCALE
                bal += usd; hedge_trades+=1
                if hsl2: hedge_losses+=1; loss_events.append(('HEDGE', h_L, datetime.utcfromtimestamp(tm[j]), round(usd,2)))
                else: hedge_wins+=1
                h_in_pos=False
    return dict(trades=wins+losses, wins=wins, losses=losses, net=bal,
                hedge_trades=hedge_trades, hedge_wins=hedge_wins, hedge_losses=hedge_losses,
                loss_events=loss_events)

zb = run_baseline(o,h,l,c,tm,N,sigs)
print(f"BASELINE (single position, current live rule): trades {zb['trades']}  win% {100*zb['wins']/zb['trades']:.2f}  losses {zb['losses']}  net ${zb['net']:.2f}")

zh = run_with_hedge(o,h,l,c,tm,N,sigs)
print(f"\nWITH OPPOSITE HEDGE: primary trades {zh['trades']}  win% {100*zh['wins']/zh['trades']:.2f}  primary losses {zh['losses']}")
print(f"  hedge trades: {zh['hedge_trades']}  hedge wins {zh['hedge_wins']}  hedge losses {zh['hedge_losses']}")
print(f"  TOTAL net (primary+hedge): ${zh['net']:.2f}")
print(f"\nDIFFERENCE vs baseline: ${zh['net']-zb['net']:.2f}")
print("\nall loss events (primary + hedge):")
for kind,L,t,usd in zh['loss_events']:
    print(f"  [{kind}] {'BUY' if L else 'SELL'}  {t}  ${usd}")
