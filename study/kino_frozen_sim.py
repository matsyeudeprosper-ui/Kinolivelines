"""Controlled backtest of the FROZEN KINO ruleset (2026-09-03).

Purpose: separate 'chop tax' from 'code effect', and test the base-size
lever. Faithful approximation of the live constitution:
- KINO entry: 2 same-colour bars, 2nd closes beyond 1st's extreme = leg;
  peak/dip made official by a close beyond the last leg-bar's other side;
  enter on a close back beyond that official level (return-to-extreme).
- SL = pullback extreme; TP = dist - discount (near 1:1).
- On SL: two-door chain (flip on close beyond SL line; re-enter on close
  back beyond the failed entry), lot += STEP, wall = recent extreme,
  heal target if deep, risk cap holds, $100 page cap ends it.
- Ratchet: lot>=0.04 lock@40% (SL->entry), bank@70%; <0.04 lock@80%.
- Regime tag per trade: TREND if 60-bar range >= TREND_PTS else CHOP.
- Bar-ordering trap: run opt + pess; trust overlap.
Costs: SPREAD_PTS per round trip. PT_USD scales with lot.
"""
import sys
import numpy as np
import MetaTrader5 as mt5

TERMINAL = r"C:\Projects\MT5-KinoliveTrader\terminal64.exe"
SYMBOL = "BTCUSDm"
SPREAD = 10.0
STEP = 0.01
DEEP = 0.04
MINWALL = 60.0
RISKCAP = 35.0
PAGECAP = 100.0
TREND_PTS = 1100.0     # 60-bar range above this = trending
BARS = int(sys.argv[1]) if len(sys.argv) > 1 else 50000
BASE = float(sys.argv[2]) if len(sys.argv) > 2 else 0.02

mt5.initialize(path=TERMINAL)
r = mt5.copy_rates_from_pos(SYMBOL, mt5.TIMEFRAME_M1, 0, BARS)
mt5.shutdown()
o = np.asarray(r["open"], float); h = np.asarray(r["high"], float)
l = np.asarray(r["low"], float); c = np.asarray(r["close"], float)
n = len(c)


def pt_usd(lot):
    return lot / 0.01 * 0.01   # $0.01 per point per 0.01 lot? BTC=$1/pt/0.01
# BTCUSDm truth: 1 point = $0.01 per 0.01 lot -> per lot L: $ (L/0.01)*0.01 = L
# so per-point $ = lot * 1.0  (0.02 lot -> $0.02/pt). Use that:
def ptusd(lot):
    return lot * 1.0


def simulate(order, base):
    bal = 0.0
    trend_net = chop_net = 0.0
    trades = 0
    # KINO detector state
    up = {}; dn = {}
    i = 2
    # active page: None or dict(dir,entry,sl,tp,lot,loss,rat,deep)
    page = None
    watch = None  # dict(dir, sl, trig, lot, loss) after an SL
    def regime(idx):
        if idx < 60: return "chop"
        rng = h[idx-60:idx].max() - l[idx-60:idx].min()
        return "trend" if rng >= TREND_PTS else "chop"

    def open_page(direction, entry, wall, lot, loss):
        dist = abs(entry - wall)
        if dist < MINWALL: return None
        if dist * lot > RISKCAP: return None
        disc = min(0.75, 0.25*dist*lot)/lot
        tpd = dist - disc
        if lot >= DEEP and loss > 0:
            hd = (loss + 3.0)/lot
            if MINWALL < hd < tpd: tpd = hd
        tp = entry + tpd if direction==1 else entry - tpd
        return {"dir":direction,"entry":entry,"sl":wall,"tp":round(tp,1),
                "lot":lot,"loss":loss,"rat":False}

    for i in range(2, n):
        reg = regime(i)
        # ---- manage open page with bar i ----
        if page is not None:
            d=page["dir"]; prize=abs(page["tp"]-page["entry"])*page["lot"]
            cur=c[i]
            # ratchet checks using bar extreme in favour
            fav = h[i] if d==1 else l[i]
            favprof = (fav-page["entry"])*d*page["lot"]
            if prize>0 and not page["rat"]:
                thr = 0.40 if page["lot"]>=DEEP else 0.80
                if favprof >= thr*prize:
                    page["rat"]=True; page["sl"]=page["entry"]
            # bank at 70% deep
            banked=False
            if page["lot"]>=DEEP and prize>0 and favprof>=0.70*prize:
                pnl=0.70*prize - SPREAD*ptusd(page["lot"])
                bal+=pnl; banked=True
            if banked:
                trades+=1
                if reg=="trend": trend_net+=pnl
                else: chop_net+=pnl
                # win -> page closed, no chain
                page=None; watch=None
                continue
            hit_tp = h[i]>=page["tp"] if d==1 else l[i]<=page["tp"]
            hit_sl = l[i]<=page["sl"] if d==1 else h[i]>=page["sl"]
            done=None
            if hit_tp and hit_sl:
                done="tp" if order=="opt" else "sl"
            elif hit_tp: done="tp"
            elif hit_sl: done="sl"
            if done:
                px=page["tp"] if done=="tp" else page["sl"]
                pnl=(px-page["entry"])*d*page["lot"] - SPREAD*ptusd(page["lot"])
                bal+=pnl; trades+=1
                if reg=="trend": trend_net+=pnl
                else: chop_net+=pnl
                if done=="sl" and not page["rat"]:
                    # arm chain
                    watch={"dir":d,"sl":page["sl"],"trig":page["entry"],
                           "lot":page["lot"],"loss":page["loss"]+abs(pnl)}
                else:
                    watch=None
                page=None
        # ---- chain doors ----
        if page is None and watch is not None:
            d=watch["dir"]; broke = c[i]<watch["sl"] if d==1 else c[i]>watch["sl"]
            reent = (not broke) and (c[i]>watch["trig"] if d==1 else c[i]<watch["trig"])
            if broke or reent:
                nd = d if reent else -d
                nl = round(watch["lot"]+STEP,2)
                if watch["loss"] >= PAGECAP:
                    watch=None
                else:
                    wall = h[max(0,i-90):i].max() if nd==-1 else l[max(0,i-90):i].min()
                    np_ = open_page(nd, c[i], wall, nl, watch["loss"])
                    if np_ is not None:
                        page=np_; watch=None
        # ---- KINO fresh entry (only if flat) ----
        if page is None and watch is None:
            pv=i-1
            # up leg
            if c[pv]>o[pv] and c[i]>o[i] and c[i]>h[pv]:
                up={"leg":True,"peak":h[i],"glow":l[i]}
            elif up.get("leg"):
                up["peak"]=max(up["peak"],h[i])
                if c[i]>o[i]: up["glow"]=l[i]
                elif c[i]<up.get("glow",-1e18):
                    up["pending"]=up["peak"]; up["plow"]=l[i]; up["leg"]=False
            if up.get("pending"):
                up["plow"]=min(up.get("plow",l[i]),l[i])
                if c[i]>up["pending"]:
                    p=open_page(1,c[i],up["plow"],base,0.0)
                    up["pending"]=None
                    if p: page=p
            if page is None:
                if c[pv]<o[pv] and c[i]<o[i] and c[i]<l[pv]:
                    dn={"leg":True,"dip":l[i],"rhigh":h[i]}
                elif dn.get("leg"):
                    dn["dip"]=min(dn["dip"],l[i])
                    if c[i]<o[i]: dn["rhigh"]=h[i]
                    elif c[i]>dn.get("rhigh",1e18):
                        dn["pending"]=dn["dip"]; dn["phigh"]=h[i]; dn["leg"]=False
                if dn.get("pending"):
                    dn["phigh"]=max(dn.get("phigh",h[i]),h[i])
                    if c[i]<dn["pending"]:
                        p=open_page(-1,c[i],dn["phigh"],base,0.0)
                        dn["pending"]=None
                        if p: page=p
    return bal, trend_net, chop_net, trades


print(f"bars {n} (~{n/1440:.0f} days), base {BASE}")
for order in ("opt","pess"):
    bal,tn,cn,tr=simulate(order,BASE)
    print(f"[{order:4}] net ${bal:.2f} ({bal/(n/1440):.2f}/day) | "
          f"trend ${tn:.2f} | chop ${cn:.2f} | trades {tr}")
