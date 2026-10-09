"""Post-run companion of manifest_runner.py (review 10):
 (a) the policy's OWN cut per regime from each decision's ladder (proposed vs
     policy lot) - main and permitted-add parts apart, floor-inert decisions counted;
 (b) the 10% hard cap binding on a regime where it can (Special, lot 0.03).
Writes study/manifest_runner_policy_cut.json."""
import sys, json
sys.argv = ["x"]
src = open(r"C:\Projects\KinoliveLines\study\manifest_runner.py", encoding="utf-8").read().split("REGIMES = [")[0]
ns = {"__file__": r"C:\Projects\KinoliveLines\study\manifest_runner.py"}; exec(src, ns)
H, PR, run, States, reference = ns["H"], ns["man"]["arms"]["baseline"]["package_regimes"], ns["run"], ns["States"], ns["reference"]
hook_directional, effective_cfg = ns["hook_directional"], ns["effective_cfg"]
res = {}
for drag in (0.0, 0.35):
    S = States(reference(drag))
    for uid, bal in (("infinity", 175.70), ("u224016179", 267.42), ("bos", 360.37), ("reference_uncapped", 1000.0)):
        cfg, _ = effective_cfg(PR[uid], bal, drag); f, tr = run(cfg, hook_directional(S), True)
        fired = [x for x in tr if x["lot_pol"] < x["lot_prop"] - 1e-9]
        floor = [x for x in tr if x["lot_prop"] <= 0.01 + 1e-9]
        main_cut = sum((x["lot_prop"] - x["lot_pol"]) * x["dist"] for x in tr)
        # permitted adds: the policy halves the permitted count (int(3*0.5)=1 of 3) -> the
        # unadjusted budget was 3x the recorded one on the decisions where it fired
        add_cut = sum(x["add_permitted_risk"] * 2.0 for x in fired if x.get("add_permitted_risk", 0) > 0)
        # decisions where the main could not move (floor) but the add budget still could
        adds_only = sum(1 for x in floor if x.get("add_permitted_risk", 0) > 0)
        k = "%s|%.2f" % (uid, drag)
        res[k] = {"decisions": len(tr), "policy_halved_main": len(fired), "main_at_floor": len(floor), "floor_with_add_budget": adds_only,
                  "main_cut_usd": round(main_cut, 2), "permitted_add_cut_usd": round(add_cut, 2)}
        print(k, res[k], flush=True)
cfg, _ = effective_cfg(PR["bos"], 360.37, 0.0); fa, ta = run(dict(cfg, hard_cap_pct=0.0)); fb, tb = run(cfg)
would = [(x["t"], x["bal_now"], x["risk"], round(0.1 * x["bal_now"], 2)) for x in ta if x["risk"] > 0.1 * x["bal_now"] + 1e-9]
res["special_hard_cap"] = {"breaking_without": len(would), "trades_with": len(tb), "trades_without": len(ta), "examples": would[:5]}
print("Special hard cap:", res["special_hard_cap"], flush=True)
H.DIRGATE = None
json.dump(res, open(r"C:\Projects\KinoliveLines\study\manifest_runner_policy_cut.json", "w"), indent=1)
