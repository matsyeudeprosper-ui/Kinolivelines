import sys, datetime as dt
sys.path.insert(0, r"C:\Projects\KinoliveLines\live")
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import MetaTrader5 as mt5
import owl_chart_feed as F
if not F.connect(): sys.exit("pas de connexion")
R = mt5.copy_rates_from_pos(F.SYMBOL, mt5.TIMEFRAME_M1, 0, 3000)
mt5.shutdown()
R = [dict(time=r[0], open=r[1], high=r[2], low=r[3], close=r[4]) for r in R]
kept = F.build(R)
out = F.engine(kept)
t0 = out[7] or out[1][-1][0]
inner = [k for k in kept if k[0] > t0]
f = lambda t: dt.datetime.utcfromtimestamp(t).strftime("%m-%d %H:%M")
print(f"fenetre interne : {f(t0)} -> maintenant")
print(f"  bougies du chart dans la fenetre : {len(inner)}")
print(f"  (bougies M1 brutes sur la meme periode : "
      f"{sum(1 for r in R if int(r['time']) > t0)})")
# replay the trigger machinery to see where dots die
hi_i, hi_v = 0, inner[0][2]
lo_i, lo_v = 0, inner[0][3]
trig = empty = nocol = made = 0
for i in range(1, len(inner)):
    t, o, h, l, c, dd = inner[i]
    if c > hi_v:
        trig += 1; span = inner[hi_i+1:i]
        if not span: empty += 1
        elif not any(x[5] == -1 for x in span): nocol += 1
        else: made += 1
        hi_i, hi_v = i, h
    elif c < lo_v:
        trig += 1; span = inner[lo_i+1:i]
        if not span: empty += 1
        elif not any(x[5] == 1 for x in span): nocol += 1
        else: made += 1
        lo_i, lo_v = i, l
print(f"\n  {trig} cassures de reference")
print(f"     span vide (2 cassures d affilee)      : {empty}")
print(f"     span sans bougie opposee              : {nocol}")
print(f"     VALLEE valide -> point                : {made}")
d, m, tr, *_ = F.engine(inner)
print(f"\n  moteur complet sur cette serie : {len(d)} points, "
      f"{len(m)} evenements, tendance {tr:+d}")
