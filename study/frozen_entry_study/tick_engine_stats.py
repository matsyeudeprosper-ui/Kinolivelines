"""Conditional uncertainty of the tick engine arms (reviews 13-14). Paired exact-horizon
block bootstrap on the arms' daily closed P&L (by exit time) over the FROZEN dataset
calendar (dataset start/end, flat boundary days retained): 5-day blocks nominated,
3 / 10 sensitivities, seed 7, 3000 resamples, degenerate (reference DD = 0) counted.
Pairs: delayed vs baseline, half_main vs baseline, and DIRECTLY delayed vs half_main.
LABEL: conditional uncertainty of these realised paths (resampled trade sequences; the
balance-dependent engine is NOT rerun on resampled prices) - not a distribution of
future account outcomes; rows share one history.
    python tick_engine_stats.py
"""
import json, random, sys
sys.argv = ["x"]
sys.path.insert(0, r"C:\Projects\KinoliveLines\study\frozen_entry_study"); import dev_dataset
_sym, R, META = dev_dataset.load("b")
T0 = int(R["time"][0]) // 86400 * 86400; N_DAYS = (int(META["closed_bar_cutoff"]) - T0 + 86399) // 86400
res = json.load(open(r"C:\Projects\KinoliveLines\study\frozen_entry_study\tick_engine.json"))
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
    return {"ratio_ci90": [q(ratios, 0.05), q(ratios, 0.95)], "net_diff_ci90": [q(diffs, 0.05), q(diffs, 0.95)], "degenerate": degen, "resamples": len(ratios)}


out = {"label": "conditional uncertainty of the realised paths (resampled trade sequences, engine not rerun); rows share one history", "calendar": {"t0": T0, "n_days": N_DAYS, "source": "dataset b start / closed-bar cutoff"}, "rows": {}}
print("calendar: %d days from the dataset start (flat days retained)" % N_DAYS, flush=True)
for key, row in sorted(res["rows"].items()):
    arms = row["arms"]; out["rows"][key] = {}
    for name, ref in (("delayed", "baseline"), ("half_main", "baseline"), ("delayed", "half_main")):
        tr, trr = arms[name]["trades_list"], arms[ref]["trades_list"]
        ddr, dda = dd_of([x["pnl"] for x in trr]), dd_of([x["pnl"] for x in tr])
        b = {str(bl): boot(tr, trr, bl) for bl in BLOCKS}
        pair = "%s_vs_%s" % (name, ref)
        out["rows"][key][pair] = {"ratio_point": round(dda / ddr, 3) if ddr else None, "net_point_diff": round(arms[name]["net"] - arms[ref]["net"], 2), "boot": b}
        print("%-22s %-22s ratio %s CI90 %s (b3 %s b10 %s) | net diff %.2f CI90 %s | degen %d" % (
            key, pair, out["rows"][key][pair]["ratio_point"], b["5"]["ratio_ci90"], b["3"]["ratio_ci90"], b["10"]["ratio_ci90"], out["rows"][key][pair]["net_point_diff"], b["5"]["net_diff_ci90"], b["5"]["degenerate"]), flush=True)
json.dump(out, open(r"C:\Projects\KinoliveLines\study\frozen_entry_study\tick_engine_stats.json", "w"), indent=1)
print("DONE")
