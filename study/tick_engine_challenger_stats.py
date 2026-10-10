"""Review 16 item 1: the EXACT challenger (delay_always | all_bos | cap_on) versus (a) the old baseline
(immediate | current | cap_on) and (b) the original recovery-delay candidate (delay_debt | current | cap_on),
per live package and cost basis, with conditional net / DD uncertainty (paired exact-horizon block
bootstrap on the dataset calendar; 5-day nominated, 3 / 10 sensitivities, seed 7, 3000) and the full raw
counts and calendar halves of the shortlisted arm. Development data, one history.
    python tick_engine_challenger_stats.py
"""
import json, random, sys
sys.argv = ["x"]; sys.path.insert(0, r"C:\Projects\KinoliveLines\study")
import dev_dataset
_s, R, META = dev_dataset.load("b")
T0 = int(R["time"][0]) // 86400 * 86400; N_DAYS = (int(META["closed_bar_cutoff"]) - T0 + 86399) // 86400
res = json.load(open(r"C:\Projects\KinoliveLines\study\tick_engine_matrix.json"))["rows"]
SEED, REPS, BLOCKS = 7, 3000, (5, 3, 10)
CH, BASE, CAND = "delay_always|all_bos|cap_on", "immediate|current|cap_on", "delay_debt|current|cap_on"


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


out = {"label": "conditional uncertainty of realised paths; one history; the challenger was selected after inspecting the 12 x 4 x 2 family", "n_days": N_DAYS, "rows": {}}
for key in ("infinity|0.00", "infinity|0.35", "u224016179|0.00", "u224016179|0.35", "bos|0.00", "bos|0.35"):
    arms = res[key]["arms"]; ch = arms[CH]
    row = {"challenger_raw": {k: v for k, v in ch.items() if k not in ("trades_list", "events", "admitted")}}
    for name, ref in (("vs_baseline", BASE), ("vs_recovery_delay_candidate", CAND)):
        ta, tb = ch["trades_list"], arms[ref]["trades_list"]; dda, ddb = dd_of([x["pnl"] for x in ta]), dd_of([x["pnl"] for x in tb])
        b = {str(bl): boot(ta, tb, bl) for bl in BLOCKS}
        row[name] = {"ref": ref, "net": [ch["net"], arms[ref]["net"]], "net_diff": round(ch["net"] - arms[ref]["net"], 2), "dd": [round(dda, 2), round(ddb, 2)], "dd_ratio": round(dda / ddb, 3) if ddb else None, "boot": b}
        print("%-18s challenger vs %-28s net %7.2f vs %7.2f diff %7.2f CI90 %s (b3 %s b10 %s) | DD %6.2f vs %6.2f ratio %s CI90 %s | degen %d" % (
            key, ref, ch["net"], arms[ref]["net"], row[name]["net_diff"], b["5"]["net_diff_ci90"], b["3"]["net_diff_ci90"], b["10"]["net_diff_ci90"], dda, ddb, row[name]["dd_ratio"], b["5"]["ratio_ci90"], b["5"]["degenerate"]), flush=True)
    c = ch["counts"]
    print("   challenger raw: trades %d wins %d main %.2f adds %.2f (%d) risk %.0f | H1 %.2f H2 %.2f | setups %d missed %d wait med %s | admitted %d (%s) | skipped open/pending %d/%d not_awake %d weather %d daycap %d debtgate %d dedupe %d | gap flagged %d" % (
        ch["trades"], ch["wins"], ch["pnl_main"], ch["pnl_add"], ch["adds"], ch["risk_main"], ch["first_half"], ch["later_half"], c["setups"], c["missed_win"], ch["wait_s_median"],
        c["admitted_by_allowance"], (ch.get("admitted_money") or {}).get("pnl"), c["skipped_open"], c["skipped_pending"], c["not_awake"], c["weather"], c["day_cap"], c["debt_gate"], c["dedupe"], ch["gap_flagged_trades"]), flush=True)
    out["rows"][key] = row
json.dump(out, open(r"C:\Projects\KinoliveLines\study\tick_engine_challenger_stats.json", "w"), indent=1)
print("DONE", flush=True)
