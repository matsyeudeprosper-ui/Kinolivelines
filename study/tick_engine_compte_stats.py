"""Stage-2 paired contrasts: global / directional pause vs no pause, and each vs the
outcome-independent thinning control (k from the global pause rate, all phases).
Conditional uncertainty (paired exact-horizon block bootstrap on daily closed P&L,
dataset calendar, 5-day nominated, 3 / 10 sensitivities, seed 7, 3000).
    python tick_engine_compte_stats.py [demo_feed|std_feed]
"""
import json, random, sys
SRC = sys.argv[1] if len(sys.argv) > 1 else "demo_feed"; sys.argv = ["x"]
sys.path.insert(0, r"C:\Projects\KinoliveLines\study")
import dev_dataset
_s, R, META = dev_dataset.load("b")
T0 = int(R["time"][0]) // 86400 * 86400; N_DAYS = (int(META["closed_bar_cutoff"]) - T0 + 86399) // 86400
res = json.load(open(r"C:\Projects\KinoliveLines\study\tick_engine_compte_%s.json" % SRC))
SEED, REPS, BLOCKS = 7, 3000, (5, 3, 10)


def dd_of(seq):
    c = pk = dd = 0.0
    for p in seq:
        c += p; pk = max(pk, c); dd = max(dd, pk - c)
    return dd


def by_day(tr):
    d = {}
    for x in tr: d.setdefault((x["tc"] // 1000 - T0) // 86400, []).append(x["pnl"])
    return d


def boot(trA, trB, block):
    A, B = by_day(trA), by_day(trB); r = random.Random(SEED); ratios, diffs, degen = [], [], 0
    for _ in range(REPS):
        sa, sb, got = [], [], 0
        while got < N_DAYS:
            s = r.randrange(0, N_DAYS - block + 1); take = min(block, N_DAYS - got)
            for dd in range(s, s + take): sa.extend(A.get(dd, [])); sb.extend(B.get(dd, []))
            got += take
        da, db = dd_of(sa), dd_of(sb)
        if db <= 0: degen += 1; continue
        ratios.append(da / db); diffs.append(sum(sa) - sum(sb))
    ratios.sort(); diffs.sort(); q = lambda xs, p: round(xs[int(p * (len(xs) - 1))], 3) if xs else None
    return {"ratio_ci90": [q(ratios, 0.05), q(ratios, 0.95)], "net_diff_ci90": [q(diffs, 0.05), q(diffs, 0.95)], "degenerate": degen}


def contrast(arms, a, b):
    ta, tb = arms[a]["trades_list"], arms[b]["trades_list"]; dda, ddb = dd_of([x["pnl"] for x in ta]), dd_of([x["pnl"] for x in tb])
    bt = {str(bl): boot(ta, tb, bl) for bl in BLOCKS}
    out = {"a": a, "b": b, "net_a": arms[a]["net"], "net_b": arms[b]["net"], "net_diff": round(arms[a]["net"] - arms[b]["net"], 2), "dd_a": round(dda, 2), "dd_b": round(ddb, 2), "dd_ratio": round(dda / ddb, 3) if ddb else None, "boot": bt}
    print("   %-28s vs %-14s net %7.2f vs %7.2f diff %7.2f CI90 %s | DD %6.2f vs %6.2f ratio %s CI90 %s" % (a, b, out["net_a"], out["net_b"], out["net_diff"], bt["5"]["net_diff_ci90"], dda, ddb, out["dd_ratio"], bt["5"]["ratio_ci90"]), flush=True)
    return out


out = {"source": SRC, "label": "conditional uncertainty of realised paths; one history", "n_days": N_DAYS, "rows": {}}
for key in sorted(res["rows"]):
    row = res["rows"][key]; arms = row["arms"]; thin = [n for n in arms if n.startswith("thin_")]
    print("== %s | global pause rate %.3f, k=%s" % (key, row.get("global_pause_rate", 0), row.get("thin_k")), flush=True)
    r = {"global_vs_none": contrast(arms, "global_pause", "no_pause"), "dir_vs_none": contrast(arms, "dir_pause", "no_pause"),
         "global_vs_thin": [contrast(arms, "global_pause", t) for t in thin], "dir_vs_thin": [contrast(arms, "dir_pause", t) for t in thin],
         "counts": {n: {k: v for k, v in arms[n]["counts"].items() if k in ("eligible_for_gate", "paused", "paused_invalid", "no_state", "thinned", "fills", "setups", "missed_win")} for n in arms}}
    out["rows"][key] = r
json.dump(out, open(r"C:\Projects\KinoliveLines\study\tick_engine_compte_stats_%s.json" % SRC, "w"), indent=1)
print("DONE", flush=True)
