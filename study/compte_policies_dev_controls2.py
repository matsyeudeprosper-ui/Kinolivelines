"""Exposure-matched control, corrected (review 5: "use actual broker lot
steps/minimums and show matching error").

A constant 0.83x multiplier on a 0.02 lot rounds down to 0.01 at the broker's
0.01 step, so the 'constant' control in compte_policies_dev_replay.py ran at
0.5x on every trade (exposure 515 vs the candidate's 862/932). This control
matches planned exposure with a DETERMINISTIC alternating schedule instead:
every k-th entry (by index) is halved, k chosen so the planned risk sum
matches the candidate's; the matching error is printed. Fitted on the same
development data (not an executable holdout control - a diagnostic)."""
import sys, json
sys.path.insert(0, r"C:\Projects\KinoliveLines\live\lab"); sys.argv = ["x"]
import harness as H
sym, R = H.bars()
J = json.load(open(r"C:\Projects\KinoliveLines\study\compte_policies_dev_replay.json"))

def run(cfg, hook, adds):
    H.EQHOOK = hook; H.EQ_ADDS = adds; H.TRACE = []
    f = H.simulate(R, 7.0, cfg); tr = list(H.TRACE); H.TRACE = None; H.EQHOOK = None; H.EQ_ADDS = False
    pn = sorted(x["pnl"] for x in tr if x["pnl"] is not None and x["pnl"] < 0)
    t_last = tr[int(len(tr) * 2 / 3)]["t"] if tr else 0
    return {"net": round(f["net"], 2), "exposure": round(sum(x.get("risk", 0) for x in tr), 2), "worst_drop": round(-f["worst_debt"], 2),
            "tail5": round(sum(pn[:5]), 2), "trades": f["trades"], "later_third": round(sum(x["pnl"] for x in tr if x["t"] >= t_last and x["pnl"] is not None), 2)}

for dkey, res in J.items():
    drag = float(dkey.split("_")[1]); LIVE = {"jar": True, "drag": drag}
    base = res["baseline"]
    print("\n=== %s ===" % dkey, flush=True)
    for lab in ("global half (main+adds PRIMARY)", "directional half (main+adds PRIMARY)"):
        target = res[lab]["exposure"]; best = None
        for k in range(2, 13):                       # halve every k-th entry
            cnt = {"i": 0}
            def hook(_a, k=k, cnt=cnt):
                cnt["i"] += 1; return (0.5 if cnt["i"] % k == 0 else 1.0), False
            m = run(LIVE, hook, True)
            err = abs(m["exposure"] - target) / target
            if best is None or err < best[1]: best = (k, err, m)
        k, err, m = best
        print("%-40s target exposure %8.2f | alternating control: halve every %dth entry -> exposure %8.2f (match error %.1f%%) | net %8.2f | later third %8.2f | drop %7.2f | tail5 %7.2f | candidate: net %8.2f drop %7.2f" % (
            lab, target, k, m["exposure"], 100 * err, m["net"], m["later_third"], m["worst_drop"], m["tail5"], res[lab]["net"], res[lab]["worst_drop"]), flush=True)
