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
_, marks, *_ = F.engine(kept)
t0 = marks[-1][0]
f = lambda t: dt.datetime.utcfromtimestamp(t).strftime("%m-%d %H:%M")
rows = [[int(r["time"]), float(r["open"]), float(r["high"]), float(r["low"]),
         float(r["close"]), 1 if r["close"] >= r["open"] else -1]
        for r in R[:-1] if int(r["time"]) > t0]
d, m, tr, ch, nx, iv, nxt_t, iv_t, _dir, _f, _ft, _fd = F.engine(rows)
print(f"fenetre interne depuis {f(t0)} : {len(rows)} bougies")
print(f"resultat : tendance {tr:+d}, choch en attente {ch:+d}, "
      f"BOS {nx and round(nx,2)}, CHoCH {iv and round(iv,2)}")
print(f"{len(m)} evenements internes au total")
print("\nles 15 derniers evenements internes :")
for t, v, kind, dd in m[-15:]:
    print(f"   {f(t)}  {kind.upper():<6s} {('haussier' if dd==1 else 'baissier'):<9s} {v:.2f}")
print(f"\nprix actuel {R[-1]['close']:.2f}")
# how the trend was established the last time it changed
flips = [x for x in m if x[2] == "bos"]
print(f"\ndernier BOS interne : "
      + (f"{f(flips[-1][0])} {('haussier' if flips[-1][3]==1 else 'baissier')} "
         f"a {flips[-1][1]:.2f}" if flips else "AUCUN - la tendance vient de "
         "l'amorcage (2 creux plus hauts), pas d'un BOS"))
