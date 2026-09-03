import json
import numpy as np
import MetaTrader5 as mt5
from datetime import datetime, timezone

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

def day_of(ts):
    return datetime.utcfromtimestamp(ts).date()

def run(o,h,l,c,tm,N,sigs,target,giveback):
    """target/giveback in USD, or target=None for baseline (no daily trail)."""
    bal=0.0; wins=losses=0
    pending=None; in_pos=False; pos_L=None; pos_entry=None; pos_sl=None; pos_et=None
    cur_day=None; day_realized=0.0; day_armed=False; day_peak=0.0
    blocked_today=False
    forced_closes=0
    loss_events=[]
    for j in range(N):
        d = day_of(tm[j])
        if d != cur_day:
            cur_day = d; day_realized = 0.0; day_armed=False; day_peak=0.0; blocked_today=False
        if pending is not None:
            L,entry,et = pending; in_pos=True; pos_L=L; pos_entry=entry; pos_et=et; pending=None
            pos_sl = pos_entry*REL_SL_PCT
        if target is not None and in_pos and not blocked_today:
            floating = ((c[j]-pos_entry) if pos_L else (pos_entry-c[j]))*PT*SCALE
            day_pnl = day_realized + floating
            if not day_armed and day_pnl >= target:
                day_armed = True; day_peak = day_pnl
            if day_armed:
                day_peak = max(day_peak, day_pnl)
                if day_peak - day_pnl >= giveback:
                    usd = floating
                    bal += usd
                    if usd < 0: losses+=1; loss_events.append((pos_L, datetime.utcfromtimestamp(pos_et), round(usd,2)))
                    else: wins+=1
                    day_realized += usd
                    forced_closes += 1
                    in_pos=False; blocked_today=True
                    continue
        if not in_pos and not blocked_today and j in sigs and j+1<N:
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
                bal += usd; day_realized += usd
                if hsl: losses+=1; loss_events.append((pos_L, datetime.utcfromtimestamp(pos_et), round(usd,2)))
                else: wins+=1
                in_pos=False
    return dict(trades=wins+losses, wins=wins, losses=losses, net=bal, loss_events=loss_events, forced_closes=forced_closes)

zb = run(o,h,l,c,tm,N,sigs,None,None)
print(f"BASELINE: trades {zb['trades']}  losses {zb['losses']}  net ${zb['net']:,.2f}\n")

print("=== sweep target/giveback ===")
for target in [10, 15, 20, 30, 50]:
    for giveback in [5, 10, 15, 20]:
        z = run(o,h,l,c,tm,N,sigs,target,giveback)
        print(f"target=${target:>3} giveback=${giveback:>3}: trades {z['trades']:>4} losses {z['losses']:>3} "
              f"forced_closes {z['forced_closes']:>4}  net ${z['net']:>10,.2f}  diff ${z['net']-zb['net']:>+9,.2f}")

def run_realized_only(o,h,l,c,tm,N,sigs,target,giveback):
    """Same idea, but arm/track using ONLY realized (closed-trade) PnL today -
    never the open position's floating value. Giveback measured on realized
    total; if triggered, force-close whatever is currently open at market."""
    bal=0.0; wins=losses=0
    pending=None; in_pos=False; pos_L=None; pos_entry=None; pos_sl=None; pos_et=None
    cur_day=None; day_realized=0.0; day_armed=False; day_peak=0.0; blocked_today=False
    forced_closes=0
    loss_events=[]
    for j in range(N):
        d = day_of(tm[j])
        if d != cur_day:
            cur_day = d; day_realized = 0.0; day_armed=False; day_peak=0.0; blocked_today=False
        if pending is not None:
            L,entry,et = pending; in_pos=True; pos_L=L; pos_entry=entry; pos_et=et; pending=None
            pos_sl = pos_entry*REL_SL_PCT
        if not day_armed and day_realized >= target:
            day_armed = True; day_peak = day_realized
        if day_armed:
            day_peak = max(day_peak, day_realized)
            if day_peak - day_realized >= giveback and in_pos and not blocked_today:
                floating = ((c[j]-pos_entry) if pos_L else (pos_entry-c[j]))*PT*SCALE
                bal += floating; day_realized += floating
                if floating < 0: losses+=1; loss_events.append((pos_L, datetime.utcfromtimestamp(pos_et), round(floating,2)))
                else: wins+=1
                forced_closes += 1
                in_pos=False; blocked_today=True
                continue
        if not in_pos and not blocked_today and j in sigs and j+1<N:
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
                bal += usd; day_realized += usd
                if hsl: losses+=1; loss_events.append((pos_L, datetime.utcfromtimestamp(pos_et), round(usd,2)))
                else: wins+=1
                in_pos=False
    return dict(trades=wins+losses, wins=wins, losses=losses, net=bal, loss_events=loss_events, forced_closes=forced_closes)

print("\n=== REALIZED-ONLY variant (arm off banked profit today, not floating) ===")
for target in [10, 15, 20, 30]:
    for giveback in [5, 10, 15]:
        z = run_realized_only(o,h,l,c,tm,N,sigs,target,giveback)
        print(f"target=${target:>3} giveback=${giveback:>3}: trades {z['trades']:>4} losses {z['losses']:>3} "
              f"forced_closes {z['forced_closes']:>4}  net ${z['net']:>10,.2f}  diff ${z['net']-zb['net']:>+9,.2f}")

def run_hybrid(o,h,l,c,tm,N,sigs,target,giveback):
    """Arm off REALIZED profit reaching target (requires actual banked same-day
    wins, not floating noise). Once armed, track giveback off TOTAL
    (realized+floating) from its peak-since-arming; force-close if breached."""
    bal=0.0; wins=losses=0
    pending=None; in_pos=False; pos_L=None; pos_entry=None; pos_sl=None; pos_et=None
    cur_day=None; day_realized=0.0; day_armed=False; total_peak=0.0; blocked_today=False
    forced_closes=0
    loss_events=[]
    for j in range(N):
        d = day_of(tm[j])
        if d != cur_day:
            cur_day = d; day_realized = 0.0; day_armed=False; total_peak=0.0; blocked_today=False
        if pending is not None:
            L,entry,et = pending; in_pos=True; pos_L=L; pos_entry=entry; pos_et=et; pending=None
            pos_sl = pos_entry*REL_SL_PCT
        if not day_armed and day_realized >= target:
            day_armed = True
            total_peak = day_realized + (((c[j]-pos_entry) if pos_L else (pos_entry-c[j]))*PT*SCALE if in_pos else 0.0)
        if day_armed and in_pos and not blocked_today:
            floating = ((c[j]-pos_entry) if pos_L else (pos_entry-c[j]))*PT*SCALE
            total_now = day_realized + floating
            total_peak = max(total_peak, total_now)
            if total_peak - total_now >= giveback:
                bal += floating; day_realized += floating
                if floating < 0: losses+=1; loss_events.append((pos_L, datetime.utcfromtimestamp(pos_et), round(floating,2)))
                else: wins+=1
                forced_closes += 1
                in_pos=False; blocked_today=True
                continue
        if not in_pos and not blocked_today and j in sigs and j+1<N:
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
                bal += usd; day_realized += usd
                if hsl: losses+=1; loss_events.append((pos_L, datetime.utcfromtimestamp(pos_et), round(usd,2)))
                else: wins+=1
                in_pos=False
    return dict(trades=wins+losses, wins=wins, losses=losses, net=bal, loss_events=loss_events, forced_closes=forced_closes)

print("\n=== HYBRID: arm off realized, trail off total ===")
for target in [10, 15, 20, 30]:
    for giveback in [5, 10, 15, 20]:
        z = run_hybrid(o,h,l,c,tm,N,sigs,target,giveback)
        print(f"target=${target:>3} giveback=${giveback:>3}: trades {z['trades']:>4} losses {z['losses']:>3} "
              f"forced_closes {z['forced_closes']:>4}  net ${z['net']:>10,.2f}  diff ${z['net']-zb['net']:>+9,.2f}")
