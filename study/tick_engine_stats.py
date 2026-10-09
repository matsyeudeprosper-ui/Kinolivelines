"""Day/block uncertainty for the tick engine arms (review 13: shared history, rows
not independent). Paired exact-horizon block bootstrap on the arms' daily closed
P&L (by exit time): 5-day blocks nominated, 3 / 10 sensitivities, seed 7, 3000
resamples, degenerate (baseline DD = 0) counted. Candidate vs baseline and
half-size control vs baseline, per regime and cost basis.
    python tick_engine_stats.py
"""
import json, random, statistics
res = json.load(open(r"C:\Projects\KinoliveLines\study\tick_engine.json"))
SEED, REPS, BLOCKS = 7, 3000, (5, 3, 10)


def dd_of(seq):
    c = pk = dd = 0.0
    for p in seq:
        c += p; pk = max(pk, c); dd = max(dd, pk - c)
    return dd


def by_day(tr, t0):
    d = {}
    for x in tr: d.setdefault((x["tc"] // 1000 - t0) // 86400, []).append(x["pnl"])
    return d


def boot(trA, trB, t0, n_days, block):
    A, B = by_day(trA, t0), by_day(trB, t0); r = random.Random(SEED); ratios, diffs, degen = [], [], 0
    for _ in range(REPS):
        sa, sb, got = [], [], 0
        while got < n_days:
            s = r.randrange(0, n_days - block + 1); take = min(block, n_days - got)
            for dd in range(s, s + take): sa.extend(A.get(dd, [])); sb.extend(B.get(dd, []))
            got += take
        da, db = dd_of(sa), dd_of(sb)
        if db <= 0: degen += 1; continue
        ratios.append(da / db); diffs.append(sum(sa) - sum(sb))
    ratios.sort(); diffs.sort(); q = lambda xs, p: round(xs[int(p * (len(xs) - 1))], 3) if xs else None
    return {"ratio_ci90": [q(ratios, 0.05), q(ratios, 0.95)], "net_diff_ci90": [q(diffs, 0.05), q(diffs, 0.95)], "degenerate": degen, "resamples": len(ratios)}


out = {}
for key, row in sorted(res["rows"].items()):
    arms = row["arms"]; base = arms["baseline"]["trades_list"]
    all_tc = [x["tc"] for a in arms.values() for x in a["trades_list"]]
    t0 = min(all_tc) // 1000 // 86400 * 86400; n_days = (max(all_tc) // 1000 - t0) // 86400 + 1
    out[key] = {"n_days": n_days}
    for name in ("delayed", "half_main"):
        tr = arms[name]["trades_list"]
        ddb, dda = dd_of([x["pnl"] for x in base]), dd_of([x["pnl"] for x in tr])
        b = {str(bl): boot(tr, base, t0, n_days, bl) for bl in BLOCKS}
        out[key][name] = {"ratio_point": round(dda / ddb, 3) if ddb else None, "net_point_diff": round(arms[name]["net"] - arms["baseline"]["net"], 2), "boot": b}
        print("%-22s %-9s ratio %s CI90 %s (b3 %s b10 %s) | net diff %.2f CI90 %s | degen %d | days %d" % (
            key, name, out[key][name]["ratio_point"], b["5"]["ratio_ci90"], b["3"]["ratio_ci90"], b["10"]["ratio_ci90"], out[key][name]["net_point_diff"], b["5"]["net_diff_ci90"], b["5"]["degenerate"], n_days), flush=True)
json.dump(out, open(r"C:\Projects\KinoliveLines\study\tick_engine_stats.json", "w"), indent=1)
print("DONE")
