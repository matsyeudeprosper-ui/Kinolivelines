"""Filters on ALIGNED internal trades. Every filter reported, not only the
best one, because with this many tests something will look good by luck."""
import bisect, inspect, sys, datetime as dt
sys.path.insert(0, r"C:\Projects\KinoliveLines\live")
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import MetaTrader5 as mt5
import owl_chart_feed as F
SPREAD, RR = 7.0, 0.8
if not F.connect(): sys.exit("pas de connexion")
R = mt5.copy_rates_from_pos(F.SYMBOL, mt5.TIMEFRAME_M1, 0, 60000)
mt5.shutdown()
R = [dict(time=int(r[0]), open=float(r[1]), high=float(r[2]),
          low=float(r[3]), close=float(r[4])) for r in R]
kept = F.build(R)
raw_i = {r["time"]: i for i, r in enumerate(R)}
src = inspect.getsource(F.engine)
src = src.replace("        lo_i, lo_v = i, l\n    # 2026-09-15",
                  "        lo_i, lo_v = i, l\n"
                  "        SNAP.append((t, trend,\n"
                  "                     (prot_lo[1] if (trend==1 and prot_lo)\n"
                  "                      else (prot_hi[1] if (trend==-1 and prot_hi)\n"
                  "                            else None)),\n"
                  "                     (hi_v if trend==1 else\n"
                  "                      (lo_v if trend==-1 else None))))\n"
                  "    # 2026-09-15")
src = src.replace("                    prot_lo = nd",
                  "                    prot_lo = nd; BRK.append((t, 1, nd[1], nd[0]))")
src = src.replace("                    prot_hi = nd",
                  "                    prot_hi = nd; BRK.append((t, -1, nd[1], nd[0]))")
src = src.replace("def engine(kept, snap=None):", "def engine_b(kept, snap=None):", 1)
ns = {"BRK": [], "SNAP": []}
exec(src, F.__dict__ | ns, ns)
ns["BRK"].clear(); ns["SNAP"].clear(); ns["engine_b"](kept)
MAIN, SNAP = list(ns["BRK"]), list(ns["SNAP"])
STT = [t for t, *_ in SNAP]; ST = {t: (a, b, c) for t, a, b, c in SNAP}
def state_at(t):
    i = bisect.bisect_right(STT, t) - 1
    return ST[STT[i]] if i >= 0 else (0, None, None)
def walk(i0, d, entry, sl, tp):
    for r in R[i0 + 1:i0 + 6000]:
        if d == 1:
            if r["low"] <= sl: return -abs(entry - sl)
            if r["high"] >= tp: return abs(tp - entry)
        else:
            if r["high"] >= sl: return -abs(entry - sl)
            if r["low"] <= tp: return abs(tp - entry)
    return None
T = []
for j, (mt_, mdir, mprot, mdot) in enumerate(MAIN):
    seg_end = MAIN[j + 1][0] if j + 1 < len(MAIN) else R[-1]["time"]
    seg = [k for k in kept if mdot < k[0] <= seg_end]
    if len(seg) < 5: continue
    ns["BRK"].clear(); ns["SNAP"].clear(); ns["engine_b"](seg)
    for bt, d, lvl, _ in list(ns["BRK"]):
        mtr, miv, mnx = state_at(bt)
        if not mtr or d != mtr: continue
        i0 = raw_i.get(bt)
        if i0 is None: continue
        e = R[i0]["close"] + (SPREAD if d == 1 else -SPREAD)
        dist = abs(e - lvl)
        if dist <= 10: continue
        p = walk(i0, d, e, lvl, e + d * RR * dist)
        if p is None: continue
        h = dt.datetime.utcfromtimestamp(bt).hour
        wd = dt.datetime.utcfromtimestamp(bt).weekday()
        rng = (abs(miv - mnx) if (miv is not None and mnx is not None)
               else None)
        T.append(dict(t=bt, r=p / dist, h=h, wd=wd, dist=dist, d=d,
                      rng=rng, age=(bt - mt_) / 3600.0))
T.sort(key=lambda x: x["t"])
print(f"{len(T)} trades alignes sur "
      f"{(R[-1]['time']-R[0]['time'])/86400:.0f} jours\n")
def stats(xs, name):
    if len(xs) < 8:
        print(f"  {name:<30s} n {len(xs):4d}  (trop peu)"); return
    n = len(xs); rs = [x["r"] for x in xs]
    w = sum(1 for r in rs if r > 0) / n; e = sum(rs) / n
    se = (sum((r - e) ** 2 for r in rs) / (n - 1)) ** .5 / n ** .5
    h = n // 2
    e1 = sum(x["r"] for x in xs[:h]) / max(h, 1)
    e2 = sum(x["r"] for x in xs[h:]) / max(n - h, 1)
    both = "oui" if (e1 > 0) == (e2 > 0) else "non"
    print(f"  {name:<30s} n {n:4d} | gagn {w:4.0%} | esp {e:+.3f} "
          f"+/-{2*se:.3f} | moities {e1:+.2f}/{e2:+.2f} accord {both}")
stats(T, "REFERENCE tous alignes")
print("\n  seances (UTC)")
for nm, lo, hi in (("Asie 00-07", 0, 7), ("Londres 07-12", 7, 12),
                   ("Chevauchement 12-16", 12, 16), ("NY 16-21", 16, 21),
                   ("Creux 21-24", 21, 24)):
    stats([x for x in T if lo <= x["h"] < hi], "  " + nm)
print("\n  hors Asie (le reste)")
stats([x for x in T if not (0 <= x["h"] < 7)], "  07-24")
print("\n  largeur du stop")
ds = sorted(x["dist"] for x in T); q1, q2, q3 = [ds[int(len(ds)*p)] for p in (.25,.5,.75)]
for nm, a, b in (("le plus serre", 0, q1), ("2e quart", q1, q2),
                 ("3e quart", q2, q3), ("le plus large", q3, 9e9)):
    stats([x for x in T if a <= x["dist"] < b], f"  {nm} ({a:.0f}-{b:.0f} pts)")
print("\n  sens")
stats([x for x in T if x["d"] == 1], "  achats")
stats([x for x in T if x["d"] == -1], "  ventes")
print("\n  jour de la semaine")
for i, nm in enumerate(("lundi","mardi","mercredi","jeudi","vendredi",
                        "samedi","dimanche")):
    stats([x for x in T if x["wd"] == i], "  " + nm)

# ---------- controls ----------
import random
print("\n" + "=" * 62)
drift = (R[-1]["close"] - R[0]["close"]) / R[0]["close"]
print(f"  derive du marche sur la periode : {drift:+.1%} "
      f"({R[0]['close']:.0f} -> {R[-1]['close']:.0f})")
rs = [x["r"] for x in T]
def perm(mask_fn, label, n=4000):
    sel = [x["r"] for x in T if mask_fn(x)]
    if len(sel) < 8: return
    k = len(sel); real = sum(sel) / k
    pool = list(rs); hit = 0
    for _ in range(n):
        random.shuffle(pool)
        if sum(pool[:k]) / k >= real: hit += 1
    print(f"  {label:<34s} esp {real:+.3f} | le hasard fait aussi bien "
          f"{hit/n:5.1%}")
random.seed(31)
print("\n  temoin par permutation (contre le meme jeu de trades)")
perm(lambda x: 7 <= x["h"] < 12, "Londres 07-12")
perm(lambda x: 16 <= x["h"] < 21, "NY 16-21 (mauvais)")
perm(lambda x: x["d"] == 1, "achats")
perm(lambda x: x["wd"] == 3, "jeudi")
perm(lambda x: x["wd"] == 5, "samedi (mauvais)")
# does the buy/sell split survive once drift is removed?
print("\n  apres retrait de la derive du marche")
import statistics
# per-trade drift proxy: market move over the trade's own horizon is not
# recorded, so compare buys vs sells within each week instead
wk = {}
for x in T:
    w = dt.datetime.utcfromtimestamp(x["t"]).isocalendar()[1]
    wk.setdefault(w, []).append(x)
diffs = []
for w, xs in wk.items():
    b = [x["r"] for x in xs if x["d"] == 1]
    s = [x["r"] for x in xs if x["d"] == -1]
    if len(b) >= 5 and len(s) >= 5:
        diffs.append((w, len(b), len(s), sum(b)/len(b) - sum(s)/len(s)))
print(f"  ecart achats - ventes, semaine par semaine :")
for w, nb, nsx, dd in diffs:
    print(f"     semaine {w}: achats {nb:3d} ventes {nsx:3d}  ecart {dd:+.3f}")
pos = sum(1 for *_, dd in diffs if dd > 0)
print(f"  semaines ou les achats font mieux : {pos}/{len(diffs)}")

# ---- decisive control: same entry times and stop widths, RANDOM direction.
# If buys still win, the win belongs to the market's +18.7% drift, not to
# the structure.
print("\n" + "=" * 62)
print("  temoin direction aleatoire (memes instants, memes stops)")
def rand_run(seed):
    random.seed(seed)
    buys, sells = [], []
    for x in T:
        i0 = raw_i.get(x["t"])
        if i0 is None: continue
        d = random.choice((1, -1))
        px = R[i0]["close"]
        e = px + (SPREAD if d == 1 else -SPREAD)
        sl = e - d * x["dist"]
        p = walk(i0, d, e, sl, e + d * RR * x["dist"])
        if p is None: continue
        (buys if d == 1 else sells).append(p / x["dist"])
    return buys, sells
gaps = []
for sd in range(12):
    b, s = rand_run(100 + sd)
    if len(b) > 20 and len(s) > 20:
        gaps.append(sum(b)/len(b) - sum(s)/len(s))
b0 = [x["r"] for x in T if x["d"] == 1]
s0 = [x["r"] for x in T if x["d"] == -1]
real = sum(b0)/len(b0) - sum(s0)/len(s0)
gaps.sort()
print(f"     ecart reel achats - ventes            : {real:+.3f} R")
print(f"     meme ecart avec des directions au hasard : "
      f"median {gaps[len(gaps)//2]:+.3f}, "
      f"min {gaps[0]:+.3f}, max {gaps[-1]:+.3f}")
beat = sum(1 for g in gaps if g >= real)
print(f"     tirages au hasard atteignant l ecart reel : {beat}/{len(gaps)}")
print("     -> " + ("l ecart vient de la DERIVE du marche"
                    if beat >= 2 else
                    "l ecart survit au temoin"))

print("\n" + "=" * 62)
print("  temoin direction aleatoire, par seance")
def rand_session(seed, lo, hi):
    random.seed(seed)
    out = []
    for x in T:
        if not (lo <= x["h"] < hi): continue
        i0 = raw_i.get(x["t"])
        if i0 is None: continue
        d = random.choice((1, -1))
        px = R[i0]["close"]
        e = px + (SPREAD if d == 1 else -SPREAD)
        p = walk(i0, d, e, e - d * x["dist"], e + d * RR * x["dist"])
        if p is not None: out.append(p / x["dist"])
    return out
for nm, lo, hi in (("Londres 07-12", 7, 12), ("NY 16-21", 16, 21),
                   ("Asie 00-07", 0, 7)):
    sel = [x["r"] for x in T if lo <= x["h"] < hi]
    real = sum(sel) / len(sel)
    sims = []
    for sd in range(12):
        o = rand_session(200 + sd, lo, hi)
        if len(o) > 15: sims.append(sum(o) / len(o))
    sims.sort()
    beat = sum(1 for g in sims if g >= real)
    print(f"  {nm:<14s} reel {real:+.3f} | hasard median "
          f"{sims[len(sims)//2]:+.3f} (min {sims[0]:+.3f} max {sims[-1]:+.3f})"
          f" | {beat}/{len(sims)} l atteignent")
    print(f"                 -> " +
          ("vient de la derive / du hasard" if beat >= 2
           else "survit au temoin"))
