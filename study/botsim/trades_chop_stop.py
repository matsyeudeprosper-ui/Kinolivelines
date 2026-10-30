"""trades_chop_stop.py (2026-10-30, owner: "yes run it") - do the month-level hints hold trade by trade?

Hints from months_compare.py (n=9-10 months): the bot does better in choppy markets than in clean trends, and with tighter
stops. Here, every closed trade of the 2026 month replays (botsim, fresh 200 $ each month, the real bot):
  chop   trendiness of the 12 hours BEFORE the entry (H1 closes from the M1 archive): |net move| / sum |hourly moves|,
         0 = back-and-forth, 1 = one clean trend (only Jan-Sep: October has no archive file)
  stop   dist_pts from the journal (entry to stop, points)
Outcome: WIN / LOSS and profit_usd. Each measure in thirds; the gap between the best and worst third is checked against
2000 shuffles of the outcomes (how often chance makes a gap that big), and in both halves of the year (Jan-May, Jun-Oct).

    python study/botsim/trades_chop_stop.py   -> table + study/botsim/trades_chop_stop.json
"""
import calendar, csv, glob, json, os, random, time
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
STUDY = os.path.dirname(HERE)
H1 = {}                                                 # hour start (s) -> close


def load_h1(ym):
    p = os.path.join(STUDY, "ticks_archive_BTCUSD", "bars_%s.npz" % ym)
    if not os.path.exists(p):
        return
    R = np.load(p)["R"]
    n = R.dtype.names
    t, c = R[n[0]].astype(np.int64), R[n[4]]
    for tt, cc in zip(t, c):
        if tt % 3600 == 3540:                           # the last minute of each hour = that hour's close
            H1[int(tt - 3540)] = float(cc)


def chop(t_entry, hours=12):
    h0 = int(t_entry // 3600 * 3600)
    cl = [H1.get(h0 - 3600 * k) for k in range(hours, 0, -1)]
    if any(x is None for x in cl):
        return None
    r = np.diff(cl)
    s = np.abs(r).sum()
    return float(abs(r.sum()) / s) if s > 0 else None


for ym in ["2025-12"] + ["2026-%02d" % m for m in range(1, 11)]:
    load_h1(ym)

T = []
for p in sorted(glob.glob(os.path.join(HERE, "runs", "month_2026-*-01", "bos_journal_valere.csv"))):
    ym = p.split("month_")[1][:7]
    for r in csv.DictReader(open(p, encoding="utf-8")):
        if r.get("outcome") not in ("WIN", "LOSS"):
            continue
        try:
            te = calendar.timegm(time.strptime(r["entry_time_utc"][:19], "%Y-%m-%dT%H:%M:%S"))
        except Exception:
            continue
        T.append({"ym": ym, "t": te, "win": r["outcome"] == "WIN", "pl": float(r["profit_usd"] or 0),
                  "stop": float(r["dist_pts"] or 0), "chop": chop(te)})
print("trades: %d (with a chop reading: %d)" % (len(T), sum(1 for x in T if x["chop"] is not None)))


def thirds(rows, key):
    R = sorted([x for x in rows if x[key] is not None], key=lambda x: x[key])
    n = len(R)
    G = [R[:n // 3], R[n // 3:2 * n // 3], R[2 * n // 3:]]
    return [{"lo": round(g[0][key], 3), "hi": round(g[-1][key], 3), "n": len(g), "win_pct": round(100 * sum(x["win"] for x in g) / len(g), 1),
             "avg_pl": round(sum(x["pl"] for x in g) / len(g), 3)} for g in G], G


def shuffle_p(G, iters=2000, seed=7):
    """how often random outcomes give a win-rate gap (low third vs high third) at least this big"""
    allw = [x["win"] for g in G for x in g]
    obs = abs(np.mean([x["win"] for x in G[0]]) - np.mean([x["win"] for x in G[2]]))
    n0, n2 = len(G[0]), len(G[2])
    rnd = random.Random(seed)
    k = 0
    for _ in range(iters):
        s = allw[:]
        rnd.shuffle(s)
        if abs(np.mean(s[:n0]) - np.mean(s[-n2:])) >= obs:
            k += 1
    return round(obs * 100, 1), round(k / iters, 3)


out = {}
for key, label in (("chop", "how trendy the last 12 h were (0 = back-and-forth, 1 = clean trend)"), ("stop", "stop distance (points)")):
    print("\n== %s" % label)
    res = {}
    for name, rows in (("all", T), ("Jan-May", [x for x in T if x["ym"] <= "2026-05"]), ("Jun-Oct", [x for x in T if x["ym"] >= "2026-06"])):
        tb, G = thirds(rows, key)
        if min(len(g) for g in G) < 10:
            continue
        gap, p = shuffle_p(G)
        res[name] = {"thirds": tb, "gap_pts": gap, "p_shuffle": p}
        print("  %-8s " % name + " | ".join("%s..%s: n=%d win %s%% avg %+.2f$" % (b["lo"], b["hi"], b["n"], b["win_pct"], b["avg_pl"]) for b in tb) +
              "   gap %s pts, chance %s" % (gap, p))
    out[key] = res
json.dump(out, open(os.path.join(HERE, "trades_chop_stop.json"), "w"), indent=1)
