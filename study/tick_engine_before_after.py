"""Before/after of the review-14 fixes: tick_engine_v1.json (commit eed519e) vs tick_engine.json.
Prints per regime / cost / arm the net, closed DD, MTM DD, trades, adds, and the new counters
(pending cancelled on a breached trigger quote, adds rejected by geometry, triggers after an earlier
stop print, same-tick double barriers)."""
import json
v1 = json.load(open(r"C:\Projects\KinoliveLines\study\tick_engine_v1.json"))["rows"]
v2 = json.load(open(r"C:\Projects\KinoliveLines\study\tick_engine.json"))["rows"]
out = {}
print("| regime | drag | arm | net v1 -> v2 | cc DD v1 -> v2 | MTM DD v1 -> v2 | trades v1 -> v2 | adds filled v1 -> v2 | cancel@trigger | adds rej geom | trig after print | same-tick both |")
print("|---|---|---|---|---|---|---|---|---|---|---|---|")
for key in sorted(v2):
    uid, drag = key.split("|")
    for arm in ("baseline", "delayed", "half_main"):
        a, b = v1.get(key, {}).get("arms", {}).get(arm), v2[key]["arms"][arm]
        c = b["counts"]
        row = {"net": [a["net"] if a else None, b["net"]], "cc_dd": [a["cc_dd"] if a else None, b["cc_dd"]], "mtm_dd": [a["mtm_dd"] if a else None, b["mtm_dd"]],
               "trades": [a["trades"] if a else None, b["trades"]], "adds": [a["adds"] if a else None, b["adds"]],
               "cancel_stop_before_submission": c.get("cancel_stop_before_submission", 0), "adds_rejected_geom": c.get("adds_rejected_geom", 0),
               "trigger_after_earlier_stop_print": c.get("trigger_after_earlier_stop_print", 0), "same_tick_both_barriers": c.get("same_tick_both_barriers", 0)}
        out.setdefault(key, {})[arm] = row
        f = lambda v: ("%.2f" % v) if isinstance(v, (int, float)) and v is not None else "-"
        print("| %s | %s | %s | %s -> %s | %s -> %s | %s -> %s | %s -> %s | %s -> %s | %d | %d | %d | %d |" % (
            uid, drag, arm, f(row["net"][0]), f(row["net"][1]), f(row["cc_dd"][0]), f(row["cc_dd"][1]), f(row["mtm_dd"][0]), f(row["mtm_dd"][1]),
            row["trades"][0], row["trades"][1], row["adds"][0], row["adds"][1], row["cancel_stop_before_submission"], row["adds_rejected_geom"],
            row["trigger_after_earlier_stop_print"], row["same_tick_both_barriers"]))
json.dump(out, open(r"C:\Projects\KinoliveLines\study\tick_engine_before_after.json", "w"), indent=1)
