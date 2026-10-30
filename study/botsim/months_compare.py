"""months_compare.py (2026-10-30, owner: "compare those months") - what separates the bot's winning months from its losing ones.

For each month of 2026 replayed by the real bot (botsim months.py, fresh 200 $ each month), the MARKET (from the M1 archive)
and the BOT (from the month's trade journal), then the winning months against the losing ones, and the rank correlation
of each measure with the month's result. Ten months are a small sample: this points at hypotheses, it proves nothing.

    python study/botsim/months_compare.py      -> table + study/botsim/months_compare.json
"""
import csv, json, os, statistics as st
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
STUDY = os.path.dirname(HERE)
S = {r["month"]: r for r in json.load(open(os.path.join(HERE, "months_summary.json"))) if "net" in r}


def market(ym):
    p = os.path.join(STUDY, "ticks_archive_BTCUSD", "bars_%s.npz" % ym)
    if not os.path.exists(p):
        return None
    R = np.load(p)["R"]
    t, o, h, l, c, sp = R["f0"] if "f0" in R.dtype.names else R[R.dtype.names[0]], None, None, None, None, None
    n = R.dtype.names
    t, o, h, l, c, sp = (R[n[0]].astype(np.int64), R[n[1]], R[n[2]], R[n[3]], R[n[4]], R[n[6]])
    day = t // 86400
    rng, eff = [], []
    for d in np.unique(day):
        m = day == d
        if m.sum() < 600:
            continue
        rng.append((h[m].max() - l[m].min()) / o[m][0] * 100)
        hc = c[m][::60]                                   # hourly closes
        r = np.diff(hc)
        if len(r) > 5 and np.abs(r).sum() > 0:
            eff.append(abs(r.sum()) / np.abs(r).sum())   # 1 = a clean trend day, ~0 = pure back-and-forth
    hc = c[::60]
    hr = np.diff(np.log(hc))
    return {"ret_pct": round((c[-1] / o[0] - 1) * 100, 1), "day_range_pct": round(float(np.mean(rng)), 2),
            "h1_vol_pct": round(float(np.std(hr) * 100), 3), "trendiness": round(float(np.mean(eff)), 3),
            "spread": round(float(np.mean(sp)), 1)}


def bot(ym):
    p = os.path.join(HERE, "runs", "month_%s-01" % ym, "bos_journal_valere.csv")
    if not os.path.exists(p):
        return None
    T = [r for r in csv.DictReader(open(p, encoding="utf-8")) if r.get("outcome") in ("WIN", "LOSS")]
    if not T:
        return None
    P = [float(r["profit_usd"] or 0) for r in T]
    W = [x for x in P if x > 0]
    L_ = [x for x in P if x <= 0]
    D = [float(r["duration_min"] or 0) for r in T]
    flips = sum(1 for r in T if "FLIP" in str(r.get("kind")))
    return {"trades": len(T), "win_rate": round(len(W) / len(T) * 100), "avg_win": round(st.mean(W), 2) if W else 0,
            "avg_loss": round(st.mean(L_), 2) if L_ else 0, "dur_min": round(st.median(D), 1),
            "flip_share": round(flips / len(T) * 100), "dist_pts": round(st.median(float(r["dist_pts"] or 0) for r in T))}


def spearman(a, b):
    ra, rb = np.argsort(np.argsort(a)), np.argsort(np.argsort(b))
    return float(np.corrcoef(ra, rb)[0, 1])


rows = []
for ym in sorted(S):
    m, b = market(ym), bot(ym)
    rows.append(dict(month=ym, net=S[ym]["net"], killed=S[ym].get("killed"), **(m or {}), **(b or {})))
out = {"rows": rows}
print("%-8s %8s | %6s %6s %7s %6s %6s | %6s %4s %6s %6s %5s %5s %5s" % (
    "month", "net", "ret%", "range%", "h1vol%", "trend", "spread", "trades", "win%", "avgW", "avgL", "dur", "flip%", "dist"))
for r in rows:
    print("%-8s %8.2f | %6s %6s %7s %6s %6s | %6s %4s %6s %6s %5s %5s %5s" % (
        r["month"], r["net"], r.get("ret_pct", "-"), r.get("day_range_pct", "-"), r.get("h1_vol_pct", "-"), r.get("trendiness", "-"),
        r.get("spread", "-"), r.get("trades", "-"), r.get("win_rate", "-"), r.get("avg_win", "-"), r.get("avg_loss", "-"),
        r.get("dur_min", "-"), r.get("flip_share", "-"), r.get("dist_pts", "-")))
keys = ["ret_pct", "day_range_pct", "h1_vol_pct", "trendiness", "spread", "trades", "win_rate", "avg_win", "avg_loss", "dur_min", "flip_share", "dist_pts"]
print("\nup months vs down months (mean)  |  rank correlation with the month's result (n months)")
cmp = {}
for k in keys:
    R_ = [r for r in rows if r.get(k) is not None]
    up = [r[k] for r in R_ if r["net"] > 0]
    dn = [r[k] for r in R_ if r["net"] <= 0]
    rho = spearman([r[k] for r in R_], [r["net"] for r in R_]) if len(R_) >= 5 else None
    cmp[k] = {"up": round(st.mean(up), 3) if up else None, "down": round(st.mean(dn), 3) if dn else None,
              "rho": None if rho is None else round(rho, 2), "n": len(R_)}
    print("  %-14s up %8s   down %8s   rho %5s  (n=%d)" % (k, cmp[k]["up"], cmp[k]["down"], cmp[k]["rho"], len(R_)))
out["compare"] = cmp
json.dump(out, open(os.path.join(HERE, "months_compare.json"), "w"), indent=1)
