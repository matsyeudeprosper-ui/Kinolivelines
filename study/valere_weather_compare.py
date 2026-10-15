"""Valère fidelity: does the engine measure the market's agitation the way the live bot did?

For every REAL entry in the journal (bot's own nervosity + movement_count at entry), the engine signal of the same
side at the same minute (+/- 2 min): engine nv / mv2 / outcome. Run after study/valere_decision_table.py.
    python study/valere_weather_compare.py
"""
import csv, json, os, statistics as stt
from datetime import datetime
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
D = json.load(open(os.path.join(HERE, "valere_decision_table.json")))
SIG = D["signal_rows"]
rows = []
for r in csv.DictReader(open(os.path.join(ROOT, "live", "bos_journal_valere.csv"), encoding="utf-8", newline="")):
    if r["is_add"] == "True" or r["kind"] == "INT":
        continue
    te = datetime.fromisoformat(r["entry_time_utc"].replace("Z", "+00:00")).timestamp()
    d = 1 if r["direction"] == "BUY" else -1
    c = [s for s in SIG if s["d"] == d and abs(s["t"] + 60 - te) <= 120]
    s = min(c, key=lambda s: abs(s["t"] + 60 - te)) if c else None
    rows.append({"t": r["entry_time_utc"][:16], "kind": r["kind"], "real_nv": float(r["nervosity"] or 0), "real_mv": int(float(r["movement_count"] or 0)),
                 "eng_nv": s["nv"] if s else None, "eng_mv": s["mv2"] if s else None, "eng_awake": s["awake"] if s else None, "eng_out": s["outcome"] if s else "no signal",
                 "pnl": float(r["profit_usd"] or 0)})
M = [x for x in rows if x["eng_nv"] is not None]
print("real entries %d, with an engine signal at the same minute %d" % (len(rows), len(M)))
dn = [x["eng_nv"] - x["real_nv"] for x in M]
print("nervosity  engine - real: median %+.2f, mean %+.2f, |diff|>0.3 on %d of %d" % (stt.median(dn), stt.mean(dn), sum(1 for v in dn if abs(v) > 0.3), len(dn)))
dm = [x for x in M if x["eng_mv"] is not None]
print("movements  equal on %d of %d; engine fewer on %d, more on %d" % (sum(1 for x in dm if x["eng_mv"] == x["real_mv"]), len(dm),
      sum(1 for x in dm if x["eng_mv"] < x["real_mv"]), sum(1 for x in dm if x["eng_mv"] > x["real_mv"])))
print("\nentries the engine REFUSED for weather (real took them):")
for x in rows:
    if x["eng_out"] == "weather":
        why = ("storm (engine nv %.2f >= 1.85)" % x["eng_nv"]) if x["eng_nv"] >= 1.85 else ("asleep (engine moves %s)" % x["eng_mv"])
        print("  %s %-8s real nv %.2f mv %d | engine nv %.2f mv %s -> %-28s pnl %+.2f" % (x["t"], x["kind"], x["real_nv"], x["real_mv"], x["eng_nv"], x["eng_mv"], why, x["pnl"]))
json.dump(rows, open(os.path.join(HERE, "valere_weather_compare.json"), "w"), indent=1)
