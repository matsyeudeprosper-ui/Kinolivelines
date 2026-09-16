"""Why does the silence filter leave the internal window with zero dots?
Count the engine's trigger events and why each one fails to make a dot."""
import sys, datetime as dt
sys.path.insert(0, r"C:\Projects\KinoliveLines\live")
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import MetaTrader5 as mt5
import owl_chart_feed as F
if not F.connect(): sys.exit("pas de connexion")
R = mt5.copy_rates_from_pos(F.SYMBOL, mt5.TIMEFRAME_M1, 0, 20000)
mt5.shutdown()
R = [dict(time=r[0], open=r[1], high=r[2], low=r[3], close=r[4]) for r in R]
kept_all = F.build(R)
_, marks, *_ = F.engine(kept_all)
t0 = marks[-1][0]
w = [r for r in R if int(r["time"]) > t0][:-1]

def audit(rows, label):
    hi_i, hi_v = 0, rows[0][2]
    lo_i, lo_v = 0, rows[0][3]
    trig = empty = nocolour = made = 0
    gaps = []
    for i in range(1, len(rows)):
        t, o, h, l, c, d = rows[i]
        if c > hi_v:
            trig += 1
            span = rows[hi_i+1:i]
            gaps.append(len(span))
            if not span: empty += 1
            elif not any(x[5] == -1 for x in span): nocolour += 1
            else: made += 1
            hi_i, hi_v = i, h
        elif c < lo_v:
            trig += 1
            span = rows[lo_i+1:i]
            gaps.append(len(span))
            if not span: empty += 1
            elif not any(x[5] == 1 for x in span): nocolour += 1
            else: made += 1
            lo_i, lo_v = i, l
    gaps.sort()
    med = gaps[len(gaps)//2] if gaps else 0
    print(f"  {label:<10s} {len(rows):5d} bougies | {trig:4d} declenchements | "
          f"span vide {empty:4d} ({empty/max(trig,1):3.0%}) | "
          f"pas la bonne couleur {nocolour:3d} | POINT CREE {made:3d} | "
          f"span median {med}")

raw = [[int(r["time"]), float(r["open"]), float(r["high"]), float(r["low"]),
        float(r["close"]), 1 if r["close"] >= r["open"] else -1] for r in w]
print("fenetre interne, meme periode, deux series de bougies :")
audit(raw, "BRUT")
audit(F.build(w), "FILTRE")
print("\npour comparaison, la structure PRINCIPALE sur tout l'historique :")
audit(kept_all, "FILTRE")
