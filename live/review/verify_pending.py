"""Replay the internal window candle by candle and print what is anticipated
during the minutes when a CHoCH is armed but the confirming BOS has not
fired yet."""
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
_, marks, _, _, _, _, _, inv_t, _ = F.engine(kept)
t0 = inv_t or marks[-1][0]
rows = [[int(r["time"]), float(r["open"]), float(r["high"]), float(r["low"]),
         float(r["close"]), 1 if r["close"] >= r["open"] else -1]
        for r in R[:-1] if int(r["time"]) > t0]
f = lambda t: dt.datetime.utcfromtimestamp(t).strftime("%H:%M")
print(f"{'minute':>6s} | {'tend':>4s} | {'bascule':>7s} | {'sens anticipe':>13s} "
      f"| {'niveau':>9s} | repli")
shown = 0
prev = None
for n in range(40, len(rows)):
    d, m, tr, ch, nx, iv, nx_t, iv_t, dr = F.engine(rows[:n])
    if not ch or ch == tr:        # only the armed-flip minutes matter
        prev = None; continue
    key = (tr, ch, round(nx or 0, 2))
    if key == prev: continue
    prev = key
    opp = -1 if dr == 1 else 1
    rdy = any(r[5] == opp for r in rows[:n] if nx_t and r[0] > nx_t)
    print(f"{f(rows[n-1][0]):>6s} | {tr:+4d} | {ch:+7d} | "
          f"{('haussier' if dr==1 else 'baissier'):>13s} | "
          f"{(f'{nx:.2f}' if nx else '-'):>9s} | {'oui' if rdy else 'non'}")
    shown += 1
    if shown >= 8: break
