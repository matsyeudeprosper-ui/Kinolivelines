"""One-shot state briefing for a live decision wake-up.

Prints everything needed to make a call in a single compact block: price,
volatility, the exact KinoliveLines level set, structure, open positions and
resting orders. Read-only.
"""
import MetaTrader5 as mt5, pandas as pd, numpy as np, os, json

TERMINAL = r"C:\Program Files\MetaTrader 5\terminal64.exe"
LOGIN    = 436771046
SYM      = "BTCUSDm"
LOG      = os.path.join(os.path.dirname(os.path.abspath(__file__)), "decisions.csv")

if not mt5.initialize(path=TERMINAL):
    raise SystemExit(f"initialize failed: {mt5.last_error()}")
acc = mt5.account_info()
if acc.login != LOGIN:
    mt5.shutdown(); raise SystemExit(f"WRONG ACCOUNT {acc.login}")

def R(tf, n):
    d = pd.DataFrame(mt5.copy_rates_from_pos(SYM, tf, 0, n))
    d['time'] = pd.to_datetime(d['time'], unit='s'); return d

m5, m15, h1, h4 = R(mt5.TIMEFRAME_M5,120), R(mt5.TIMEFRAME_M15,60), R(mt5.TIMEFRAME_H1,60), R(mt5.TIMEFRAME_H4,30)
tick = mt5.symbol_info_tick(SYM)
si   = mt5.symbol_info(SYM)

def atr(d, n=14):
    pc = d['close'].shift(1)
    return pd.concat([d['high']-d['low'],(d['high']-pc).abs(),(d['low']-pc).abs()],
                     axis=1).max(axis=1).rolling(n).mean().iloc[-1]

a_m15, a_h1, a_h4 = atr(m15), atr(h1), atr(h4)
spread = tick.ask - tick.bid
mid = (tick.bid + tick.ask) / 2

print("="*78)
print(f"BRIEFING  {SYM}   server {pd.to_datetime(tick.time, unit='s')}")
print("="*78)
print(f"bid {tick.bid}  ask {tick.ask}  spread ${spread:.2f}")
print(f"ATR  M15 ${a_m15:,.0f}   H1 ${a_h1:,.0f}   H4 ${a_h4:,.0f}")
print(f"account equity ${acc.equity:,.2f}  balance ${acc.balance:,.2f}  free ${acc.margin_free:,.2f}")

# ---- KinoliveLines level set (same rule as the EA) ----
raw = []
for name, d, prio in (('H4',h4,3), ('H1',h1,2), ('M15',m15,1)):
    raw.append([d['high'].iloc[-2], True,  prio, name])
    raw.append([d['low' ].iloc[-2], False, prio, name])
tol = max(spread*3.0, a_h1*0.12)
raw.sort(key=lambda r: r[0]); keep=[True]*len(raw)
for i in range(len(raw)):
    if not keep[i]: continue
    for j in range(i+1, len(raw)):
        if not keep[j]: continue
        if abs(raw[i][0]-raw[j][0]) <= tol:
            if raw[j][2] > raw[i][2]: raw[i]=raw[j]
            keep[j]=False
merged=[r for i,r in enumerate(raw) if keep[i]]
md = merged[0][0]*0.001; levels=[]
for r in merged:
    if not levels or r[1]!=levels[-1][1] or abs(r[0]-levels[-1][0])>=md: levels.append(r)
    if len(levels)>=6: break

print(f"\n--- LEVELS (merge tol ${tol:,.0f}) ---")
for price, isHigh, prio, name in sorted(levels, key=lambda x: -x[0]):
    d_px = price - mid
    print(f"  {name:<4} {'RESIST ' if isHigh else 'SUPPORT'} {price:>10,.2f}   "
          f"{d_px:>+9,.2f}  ({abs(d_px)/spread:>5.1f}x spread, {abs(d_px)/a_h1:>4.2f} ATR-H1)")

# ---- structure ----
print(f"\n--- M5 STRUCTURE (last 12) ---")
for _, b in m5.tail(12).iterrows():
    print(f"  {b['time']:%H:%M}  O {b['open']:>9,.2f}  H {b['high']:>9,.2f}  "
          f"L {b['low']:>9,.2f}  C {b['close']:>9,.2f}")
w = m5.tail(48)
print(f"  4h range: low {w['low'].min():,.2f}  high {w['high'].max():,.2f}  "
      f"(${w['high'].max()-w['low'].min():,.0f} wide)")

# swing pivots for trend read
h, l = m5['high'].values, m5['low'].values
piv=[]
for i in range(3, len(m5)-3):
    if h[i]==max(h[i-3:i+4]): piv.append((m5['time'].iloc[i],'H',h[i]))
    if l[i]==min(l[i-3:i+4]): piv.append((m5['time'].iloc[i],'L',l[i]))
keep2=[]
for p in piv:
    if not keep2 or abs(p[2]-keep2[-1][2])>a_m15*0.8: keep2.append(p)
print("  recent swings: " + "  ".join(f"{t:%H:%M}{k}{v:,.0f}" for t,k,v in keep2[-8:]))

# ---- positions / orders ----
print(f"\n--- OPEN POSITIONS ({mt5.positions_total()}) ---")
for p in (mt5.positions_get(symbol=SYM) or []):
    side = 'BUY' if p.type==0 else 'SELL'
    risk = (p.price_open-p.sl) if (p.sl and p.type==0) else ((p.sl-p.price_open) if p.sl else None)
    rew  = (p.tp-p.price_open) if (p.tp and p.type==0) else ((p.price_open-p.tp) if p.tp else None)
    print(f"  #{p.ticket} {side} {p.volume} @ {p.price_open:,.2f}  SL {p.sl or 'NONE'}  TP {p.tp or 'NONE'}")
    print(f"     P&L {p.profit:+.2f}  opened {pd.to_datetime(p.time,unit='s'):%H:%M}"
          + (f"  R:R {rew/risk:.2f}:1  to TP {p.tp-tick.bid:+,.0f}  to SL {tick.bid-p.sl:+,.0f}" if risk and rew else ""))

print(f"\n--- PENDING ORDERS ({mt5.orders_total()}) ---")
TYPES={2:'BUY_LIMIT',3:'SELL_LIMIT',4:'BUY_STOP',5:'SELL_STOP'}
for o in (mt5.orders_get(symbol=SYM) or []):
    # Rule 8 is about the entry's distance from CURRENT price, so print that
    # multiple rather than making the model derive it. An order whose entry has
    # drifted past 1.5x ATR(M15) fills less than 40% of the time inside the hold
    # window and is holding the only slot rule 1 allows. Left implicit, this got
    # ignored for 2h45m at 5.3x while the R:R still looked attractive.
    away = abs(o.price_open - mid) / a_m15 if a_m15 else 0
    verdict = "" if away <= 1.5 else (
        f"  *** UNREACHABLE {away:.1f}x ATR15 - RULE 8 SAYS CANCEL "
        f"(~{'6' if away >= 5 else '15' if away >= 3 else '28'}% fill odds, blocking the only slot) ***")
    print(f"  #{o.ticket} {TYPES.get(o.type,o.type)} {o.volume_current} @ {o.price_open:,.2f}  "
          f"SL {o.sl or 'NONE'} TP {o.tp or 'NONE'}  ({o.price_open-mid:+,.0f} from mid, "
          f"{away:.2f}x ATR15){verdict}")

# The decider's own standing conditions. Without this it only ever sees the note
# on the level that happened to fire, so a condition it set on a DIFFERENT level
# ("cancel rather than chase if price runs away") is invisible at the moment it
# matters. These notes are its only memory between wakes - it must be able to
# read the whole set before overwriting them.
CFG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "watch_config.json")
if os.path.exists(CFG):
    try:
        cfg = json.load(open(CFG, encoding="utf-8"))
        wl = cfg.get("watch_levels", [])
        print(f"\n--- MY STANDING WATCH LEVELS ({len(wl)}) — conditions I set myself ---")
        for l in sorted(wl, key=lambda x: -float(x["price"])):
            price_l, side_l = float(l["price"]), l.get("dir", "below")
            d = price_l - mid
            # A "below" level already under price - or an "above" level already
            # over it - has been passed. The daemon marks such a level broken and
            # then stays SILENT until price reclaims it, so it will not wake you
            # about further movement in that direction. Say so here, because
            # otherwise the only signal is an absence of alerts.
            through = (mid < price_l) if side_l == "below" else (mid > price_l)
            flag = "  *** ALREADY THROUGH - will NOT alert until reclaimed ***" if through else ""
            print(f"  {price_l:>10,.2f} {side_l:<5} ({d:+,.0f} from mid){flag}")
            print(f"      {l.get('note','')}")
        print(f"  max hold: {cfg.get('max_hold_minutes', 120)} min")
    except Exception as e:
        print(f"\n--- watch levels unreadable: {e} ---")

if os.path.exists(LOG):
    dl = pd.read_csv(LOG)
    print(f"\n--- MY DECISION LOG: {len(dl)} entries ---")
    for _, r in dl.tail(3).iterrows():
        print(f"  {r['time']}  {r['action']}  {str(r['reason'])[:70]}")
mt5.shutdown()
