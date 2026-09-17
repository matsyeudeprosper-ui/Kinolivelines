"""How often did the OLD rule show an anticipated break that the owner's
rule forbids? Replay the internal window minute by minute."""
import sys, datetime as dt
sys.path.insert(0, r"C:\Projects\KinoliveLines\live")
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import MetaTrader5 as mt5
import owl_chart_feed as F
if not F.connect(): sys.exit("pas de connexion")
R = mt5.copy_rates_from_pos(F.SYMBOL, mt5.TIMEFRAME_M1, 0, 3000)
mt5.shutdown()
R = [dict(time=r[0], open=r[1], high=r[2], low=r[3], close=r[4]) for r in R]
kept_all = F.build(R)
out = F.engine(kept_all)
t0 = out[7] or out[1][-1][0]
raw = [[int(r["time"]), float(r["open"]), float(r["high"]), float(r["low"]),
        float(r["close"]), 1 if r["close"] >= r["open"] else -1]
       for r in R[:-1] if int(r["time"]) > t0]
same = old_only = new_only = neither = 0
for n in range(30, len(raw), 3):
    sub = raw[:n]
    d, m, tr, ch, nx, iv, nx_t, iv_t, dr, *_ = F.engine(sub)
    if not nx or not nx_t or not dr:
        continue
    kept_sub = [k for k in kept_all if k[0] <= sub[-1][0]]
    o = any(k[5] == (-1 if dr == 1 else 1) for k in sub if k[0] > nx_t)
    nw = F.pullback_since(kept_sub, nx_t, dr)
    if o and nw: same += 1
    elif o and not nw: old_only += 1
    elif nw and not o: new_only += 1
    else: neither += 1
tot = same + old_only + new_only + neither
print(f"{tot} instants examines dans la fenetre interne\n")
print(f"  les deux regles affichent le niveau      : {same:4d}")
print(f"  ANCIENNE affiche, la tienne INTERDIT     : {old_only:4d}"
      f"  ({old_only/max(tot,1):.0%})  <- les faux niveaux")
print(f"  la tienne affiche, ancienne non          : {new_only:4d}")
print(f"  les deux masquent                        : {neither:4d}")
