"""Stage-1 paired contrasts (revised brief): for every regime / cost basis in
tick_engine_matrix.json, the four questions as PAIRED contrasts with conditional
uncertainty (paired exact-horizon block bootstrap on daily closed P&L by exit
time over the dataset calendar; 5-day blocks nominated, 3 / 10 sensitivities,
seed 7, 3000; degenerate counted). Twelve cells = one research family on one
history; nothing here is an independent confirmation.
  1. always-delay vs recovery-only delay (allowance, cap identical)       4 pairs
  2. all-BOS recovery vs current allowance (entry, cap identical)          6 pairs
  3. cap off vs cap on (entry, allowance identical)                        6 pairs
  4. interactions: the all-BOS effect by entry policy; the cap effect by entry policy
    python tick_engine_matrix_stats.py
"""
import json, random, sys, itertools
sys.argv = ["x"]; sys.path.insert(0, r"C:\Projects\KinoliveLines\study")
import dev_dataset
_s, R, META = dev_dataset.load("b")
T0 = int(R["time"][0]) // 86400 * 86400; N_DAYS = (int(META["closed_bar_cutoff"]) - T0 + 86399) // 86400
res = json.load(open(r"C:\Projects\KinoliveLines\study\tick_engine_matrix.json"))
SEED, REPS, BLOCKS = 7, 3000, (5, 3, 10)
ENTRY = ("immediate", "delay_debt", "delay_always"); ALLOW = ("current", "all_bos"); CAP = ("cap_on", "cap_off")
name = lambda e, a, c: "%s|%s|%s" % (e, a, c)


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


def contrast(arms, a, b, label):
    """arm a vs arm b (b = reference): point net diff, DD ratio, CI90 (5-day) + sensitivities"""
    ta, tb = arms[a]["trades_list"], arms[b]["trades_list"]
    dda, ddb = dd_of([x["pnl"] for x in ta]), dd_of([x["pnl"] for x in tb])
    bt = {str(bl): boot(ta, tb, bl) for bl in BLOCKS}
    out = {"label": label, "a": a, "b": b, "net_a": arms[a]["net"], "net_b": arms[b]["net"], "net_diff": round(arms[a]["net"] - arms[b]["net"], 2),
           "dd_a": round(dda, 2), "dd_b": round(ddb, 2), "dd_ratio": round(dda / ddb, 3) if ddb else None, "boot": bt}
    print("   %-58s net %7.2f vs %7.2f diff %7.2f CI90 %s | DD %6.2f vs %6.2f ratio %s CI90 %s (b3 %s b10 %s)" % (
        label, out["net_a"], out["net_b"], out["net_diff"], bt["5"]["net_diff_ci90"], dda, ddb, out["dd_ratio"], bt["5"]["ratio_ci90"], bt["3"]["ratio_ci90"], bt["10"]["ratio_ci90"]), flush=True)
    return out


out = {"label": "conditional uncertainty of the realised paths (engine not rerun on resampled prices); one history, one research family", "n_days": N_DAYS, "rows": {}}
for key in sorted(res["rows"]):
    arms = res["rows"][key]["arms"]; row = {"q1_always_vs_recovery_delay": [], "q2_allbos_vs_current": [], "q3_capoff_vs_capon": [], "q4_interactions": {}}
    print("== %s (duplicates: %s)" % (key, res["rows"][key].get("duplicates")), flush=True)
    for a_, c_ in itertools.product(ALLOW, CAP):
        row["q1_always_vs_recovery_delay"].append(contrast(arms, name("delay_always", a_, c_), name("delay_debt", a_, c_), "Q1 always vs recovery delay | %s %s" % (a_, c_)))
    for e_, c_ in itertools.product(ENTRY, CAP):
        row["q2_allbos_vs_current"].append(contrast(arms, name(e_, "all_bos", c_), name(e_, "current", c_), "Q2 all_bos vs current | %s %s" % (e_, c_)))
    for e_, a_ in itertools.product(ENTRY, ALLOW):
        row["q3_capoff_vs_capon"].append(contrast(arms, name(e_, a_, "cap_off"), name(e_, a_, "cap_on"), "Q3 cap off vs on | %s %s" % (e_, a_)))
    # interactions: the all-BOS net effect by entry policy (cap on and off), the cap effect by entry policy
    inter = {}
    for e_ in ENTRY:
        inter["allbos_effect_%s" % e_] = {c_: round(arms[name(e_, "all_bos", c_)]["net"] - arms[name(e_, "current", c_)]["net"], 2) for c_ in CAP}
        inter["capoff_effect_%s" % e_] = {a_: round(arms[name(e_, a_, "cap_off")]["net"] - arms[name(e_, a_, "cap_on")]["net"], 2) for a_ in ALLOW}
    row["q4_interactions"] = inter
    print("   Q4 interactions:", json.dumps(inter), flush=True)
    # the old half-MAIN control vs the original recovery-delay candidate (attribution)
    row["half_main_vs_recovery_delay"] = contrast(arms, name("delay_debt", "current", "cap_on"), "half_main", "attribution: recovery delay vs half_main (cap on, current)")
    out["rows"][key] = row
json.dump(out, open(r"C:\Projects\KinoliveLines\study\tick_engine_matrix_stats.json", "w"), indent=1)
print("DONE", flush=True)
