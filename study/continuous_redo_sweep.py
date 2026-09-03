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
o_f = np.array([rows[t][0] for t in times]); h_f = np.array([rows[t][1] for t in times])
l_f = np.array([rows[t][2] for t in times]); c_f = np.array([rows[t][3] for t in times])
tm_f = np.array(times)
N = len(times)
print(f"loaded {N} M1 bars, {datetime.utcfromtimestamp(times[0])} -> {datetime.utcfromtimestamp(times[-1])}")

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

print("building signals once, continuously, over the full 6-year history (this is the fix)...")
sigs = build_bricks_signals(o_f,h_f,l_f,c_f,N)
print(f"signals built: {len(sigs)} reversal points")

def run_net(o,h,l,c,tm,N,sigs,trig_f,cap_f):
    """trig_f=None means plain baseline (no ratchet at all). Otherwise dual-cap
    ratchet with the given trigger/cap fractions, realized_cum accumulating
    CONTINUOUSLY across the whole run - never reset, matching the real live bot."""
    bal=0.0; losses=0; realized_cum=0.0
    pending=None; in_pos=False; pos_L=None; pos_entry=None; pos_sl=None
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
                if hsl: losses += 1
                in_pos=False
    return bal, losses

zb, lb = run_net(o_f,h_f,l_f,c_f,tm_f,N,sigs,None,None)
print(f"\nBASELINE (continuous, correct): net ${zb:,.2f}  losses={lb}")

print("\n=== coarse sweep: trigger 10-50%, cap 50-100% (continuous, no resets) ===")
print("trig\cap   50%      60%      70%      80%      90%     100%")
for trig_f in [0.10,0.15,0.20,0.25,0.30,0.35,0.40,0.45,0.50]:
    row = []
    for cap_f in [0.50,0.60,0.70,0.80,0.90,1.00]:
        z,l = run_net(o_f,h_f,l_f,c_f,tm_f,N,sigs,trig_f,cap_f)
        row.append(z-zb)
    print(f"{100*trig_f:>5.0f}%   " + "  ".join(f"{v:>+8.0f}" for v in row))

print("\n\n=== fine sweep: cap fixed at 100% (the simple single-cap ratchet), trigger 5-50% in 1% steps ===")
print("trig    diff")
for i in range(5, 51):
    trig_f = i/100.0
    z,l = run_net(o_f,h_f,l_f,c_f,tm_f,N,sigs,trig_f,1.00)
    print(f"{i:>4d}%  {z-zb:>+9.0f}   losses={l}")
