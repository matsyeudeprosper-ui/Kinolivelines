"""Would an INTERNAL weather say anything the main one does not?
Walk the chart hour by hour and count flips in the trailing 2 h for each."""
import sys, datetime as dt
sys.path.insert(0, r"C:\Projects\KinoliveLines\live")
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import MetaTrader5 as mt5
import owl_chart_feed as F
if not F.connect(): sys.exit("pas de connexion")
R = mt5.copy_rates_from_pos(F.SYMBOL, mt5.TIMEFRAME_M1, 0, 6000)
mt5.shutdown()
R = [dict(time=r[0], open=r[1], high=r[2], low=r[3], close=r[4]) for r in R]
kept = F.build(R)
f = lambda t: dt.datetime.utcfromtimestamp(t).strftime("%m-%d %H:%M")
rows = []
end_t = int(R[-1]["time"])
for back in range(0, 60 * 46, 60 * 2):          # every 2 h
    now = end_t - back * 60
    k = [x for x in kept if x[0] <= now]
    if len(k) < 200:
        continue
    # main: flips (BOS marks) in the trailing 2 h
    _, mk, mtr, *rest = F.engine(k)
    inv_t = rest[4]
    mflip = sum(1 for m in mk if m[2] == "bos" and m[0] > now - 7200)
    # internal: its window, its own events in the trailing 2 h
    t0 = inv_t or (mk[-1][0] if mk else 0)
    inner = [x for x in k if x[0] > t0][-F.INT_MAX:]
    iflip = 0; itr = 0
    if len(inner) >= 5:
        _, imk, itr, *_ = F.engine(inner)
        iflip = sum(1 for m in imk if m[2] == "bos" and m[0] > now - 7200)
    rows.append((now, mflip, iflip))
st = lambda n: "endormie" if n == 0 else ("active" if n >= 2 else "calme")
dis = sum(1 for _, a, b in rows if (a == 0) != (b == 0))
print(f"{len(rows)} releves toutes les 2 h\n")
print(f"  {'quand':>11s} | {'principal':>9s} | {'interne':>7s} | accord")
for now, a, b in rows[:14]:
    ok = "" if (a == 0) == (b == 0) else "   <-- DESACCORD"
    print(f"  {f(now):>11s} | {a:2d} {st(a):<6s} | {b:2d} {st(b):<4s} |{ok}")
print(f"\n  la principale dort alors que l'interne bouge (ou l'inverse) : "
      f"{dis}/{len(rows)} ({dis/max(len(rows),1):.0%})")
sleep_main = sum(1 for _, a, _ in rows if a == 0)
both = sum(1 for _, a, b in rows if a == 0 and b > 0)
print(f"  principale endormie : {sleep_main}/{len(rows)}, "
      f"dont {both} ou l'interne avait quand meme de la structure")
