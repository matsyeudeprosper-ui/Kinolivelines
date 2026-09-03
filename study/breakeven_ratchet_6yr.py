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

def run(o,h,l,c,tm,N,sigs,use_ratchet):
    bal=0.0; wins=losses=0; realized_cum=0.0
    pending=None; in_pos=False; pos_L=None; pos_entry=None; pos_sl=None; pos_et=None
    loss_events=[]; ratchet_active_count=0
    for j in range(N):
        if pending is not None:
            L,entry,et = pending; in_pos=True; pos_L=L; pos_entry=entry; pos_et=et; pending=None
            default_sl_usd = pos_entry*REL_SL_PCT*LOTS
            trigger = pos_entry*REL_SL_PCT*LOTS   # "current relative-SL dollar value"
            if use_ratchet and realized_cum >= trigger:
                sl_usd = realized_cum   # give back at most all banked profit - worst case breakeven
                ratchet_active_count += 1
            else:
                sl_usd = default_sl_usd
            pos_sl = sl_usd/LOTS
        if j in sigs and j+1<N and not in_pos:
            L=(sigs[j]==1); SP=SPREAD_PTS if L else 0.0
            entry = o[j+1]+SP if L else o[j+1]
            pending=(L,entry,tm[j+1])
        if in_pos:
            tpp = pos_entry+TP_PTS if pos_L else pos_entry-TP_PTS
            slp = pos_entry-pos_sl if pos_L else pos_entry+pos_sl
            htp = (h[j]>=tpp) if pos_L else (l[j]<=tpp)
            hsl = (l[j]<=slp) if pos_L else (h[j]>=slp)
            if htp or hsl:
                usd = (-pos_sl if hsl else TP_PTS)*PT*SCALE
                bal += usd; realized_cum += usd
                if hsl: losses+=1; loss_events.append((pos_L, datetime.utcfromtimestamp(pos_et), round(usd,2)))
                else: wins+=1
                in_pos=False
    return dict(trades=wins+losses, wins=wins, losses=losses, net=bal, loss_events=loss_events, ratchet_active_count=ratchet_active_count)

zb = run(o,h,l,c,tm,N,sigs,False)
print(f"BASELINE (current live config): trades {zb['trades']}  losses {zb['losses']}  net ${zb['net']:,.2f}")

zr = run(o,h,l,c,tm,N,sigs,True)
print(f"\nBREAKEVEN RATCHET: trades {zr['trades']}  losses {zr['losses']}  net ${zr['net']:,.2f}  "
      f"(diff ${zr['net']-zb['net']:+,.2f})")
print(f"trades opened while ratchet was active: {zr['ratchet_active_count']}")
print(f"\nlosses under ratchet:")
for L,et,usd in zr['loss_events']:
    print(f"  {'BUY' if L else 'SELL'} entered {et}  ${usd}")

def run_capped(o,h,l,c,tm,N,sigs):
    """Same idea, but SL is capped at the normal default width - never wider
    than the standard relative-40% SL, even if a lot of profit has banked.
    Only ever tightens (protects against giving back more than banked),
    never loosens beyond the normal default."""
    bal=0.0; wins=losses=0; realized_cum=0.0
    pending=None; in_pos=False; pos_L=None; pos_entry=None; pos_sl=None; pos_et=None
    loss_events=[]; ratchet_active_count=0
    for j in range(N):
        if pending is not None:
            L,entry,et = pending; in_pos=True; pos_L=L; pos_entry=entry; pos_et=et; pending=None
            default_sl_usd = pos_entry*REL_SL_PCT*LOTS
            trigger = pos_entry*REL_SL_PCT*LOTS
            if realized_cum >= trigger:
                sl_usd = min(realized_cum, default_sl_usd)
                ratchet_active_count += 1
            else:
                sl_usd = default_sl_usd
            pos_sl = sl_usd/LOTS
        if j in sigs and j+1<N and not in_pos:
            L=(sigs[j]==1); SP=SPREAD_PTS if L else 0.0
            entry = o[j+1]+SP if L else o[j+1]
            pending=(L,entry,tm[j+1])
        if in_pos:
            tpp = pos_entry+TP_PTS if pos_L else pos_entry-TP_PTS
            slp = pos_entry-pos_sl if pos_L else pos_entry+pos_sl
            htp = (h[j]>=tpp) if pos_L else (l[j]<=tpp)
            hsl = (l[j]<=slp) if pos_L else (h[j]>=slp)
            if htp or hsl:
                usd = (-pos_sl if hsl else TP_PTS)*PT*SCALE
                bal += usd; realized_cum += usd
                if hsl: losses+=1; loss_events.append((pos_L, datetime.utcfromtimestamp(pos_et), round(usd,2)))
                else: wins+=1
                in_pos=False
    return dict(trades=wins+losses, wins=wins, losses=losses, net=bal, loss_events=loss_events, ratchet_active_count=ratchet_active_count)

zc = run_capped(o,h,l,c,tm,N,sigs)
print(f"\nCAPPED RATCHET (SL never exceeds normal default): trades {zc['trades']}  losses {zc['losses']}  net ${zc['net']:,.2f}  "
      f"(diff vs baseline ${zc['net']-zb['net']:+,.2f})")
print(f"trades opened while ratchet was tighter-than-default: {zc['ratchet_active_count']}")
print(f"\nlosses under capped ratchet:")
for L,et,usd in zc['loss_events']:
    print(f"  {'BUY' if L else 'SELL'} entered {et}  ${usd}")

def run_capped_v2(o,h,l,c,tm,N,sigs,trigger_frac):
    """Cap stays at the normal default SL width (never wider than normal).
    Trigger is now a FRACTION of that default width, giving the ratchet
    genuine room to operate between trigger and cap."""
    bal=0.0; wins=losses=0; realized_cum=0.0
    pending=None; in_pos=False; pos_L=None; pos_entry=None; pos_sl=None; pos_et=None
    loss_events=[]; ratchet_tighter_count=0
    for j in range(N):
        if pending is not None:
            L,entry,et = pending; in_pos=True; pos_L=L; pos_entry=entry; pos_et=et; pending=None
            default_sl_usd = pos_entry*REL_SL_PCT*LOTS
            trigger = trigger_frac*default_sl_usd
            if realized_cum >= trigger:
                sl_usd = min(max(realized_cum, 0.0), default_sl_usd)
                if sl_usd < default_sl_usd: ratchet_tighter_count += 1
            else:
                sl_usd = default_sl_usd
            pos_sl = sl_usd/LOTS
        if j in sigs and j+1<N and not in_pos:
            L=(sigs[j]==1); SP=SPREAD_PTS if L else 0.0
            entry = o[j+1]+SP if L else o[j+1]
            pending=(L,entry,tm[j+1])
        if in_pos:
            tpp = pos_entry+TP_PTS if pos_L else pos_entry-TP_PTS
            slp = pos_entry-pos_sl if pos_L else pos_entry+pos_sl
            htp = (h[j]>=tpp) if pos_L else (l[j]<=tpp)
            hsl = (l[j]<=slp) if pos_L else (h[j]>=slp)
            if htp or hsl:
                usd = (-pos_sl if hsl else TP_PTS)*PT*SCALE
                bal += usd; realized_cum += usd
                if hsl: losses+=1; loss_events.append((pos_L, datetime.utcfromtimestamp(pos_et), round(usd,2)))
                else: wins+=1
                in_pos=False
    return dict(trades=wins+losses, wins=wins, losses=losses, net=bal, loss_events=loss_events, ratchet_tighter_count=ratchet_tighter_count)

print("\n=== capped ratchet, trigger as fraction of default SL width ===")
for tf in [0.05, 0.1, 0.15, 0.2, 0.3, 0.4, 0.5, 0.6, 0.75, 0.9]:
    z = run_capped_v2(o,h,l,c,tm,N,sigs,tf)
    print(f"trigger={100*tf:>4.0f}% of default SL: trades {z['trades']:>4} losses {z['losses']:>2} "
          f"tighter-count {z['ratchet_tighter_count']:>4}  net ${z['net']:>10,.2f}  diff ${z['net']-zb['net']:>+9,.2f}")

print("\n=== fine sweep 15%-55% ===")
for tf in [0.15,0.18,0.20,0.22,0.25,0.28,0.30,0.32,0.35,0.38,0.40,0.42,0.45,0.48,0.50,0.52,0.55]:
    z = run_capped_v2(o,h,l,c,tm,N,sigs,tf)
    print(f"trigger={100*tf:>5.1f}%: trades {z['trades']:>4} losses {z['losses']:>2}  net ${z['net']:>10,.2f}  diff ${z['net']-zb['net']:>+9,.2f}")

print("\n=== DETAIL at trigger=30% (middle of the stable plateau) ===")
z = run_capped_v2(o,h,l,c,tm,N,sigs,0.30)
print(f"trades {z['trades']}  losses {z['losses']}  net ${z['net']:,.2f}  (baseline: ${zb['net']:,.2f}, diff ${z['net']-zb['net']:+,.2f})")
print(f"tighter-than-default count: {z['ratchet_tighter_count']}")
print()
for L,et,usd in z['loss_events']:
    print(f"  {'BUY' if L else 'SELL'} entered {et}  ${usd}")
