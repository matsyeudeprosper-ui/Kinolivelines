"""gold_confirm.py <SYM> <robot> [seeds=40] - re-run the random-entry control on more seeds and, when the fixed
rule still passes (percentile >= 95), lift the hold in live/market_hold.json for that robot@market.

2026-10-16 (owner: "do what you would recommend"): Pekos owl on Gold passed the 20-seed control at exactly 19/20.
A verdict that rests on one random run is confirmed on 40 before real money; the hold comes off by itself when it
holds, and stays (with the reason updated) when it does not.
"""
import sys, os, json, subprocess, time
HERE = os.path.dirname(os.path.abspath(__file__)); LIVE = os.path.join(os.path.dirname(HERE), "live")
sym, rid = sys.argv[1].upper(), sys.argv[2]; seeds = int(sys.argv[3]) if len(sys.argv) > 3 else 40
key = "%s@%s" % (rid, sym); hold_f = os.path.join(LIVE, "market_hold.json")
t0 = time.time()
r = subprocess.run([sys.executable, "-u", os.path.join(HERE, "ctrl_split.py"), sym, rid, str(seeds), "4"], cwd=HERE)
j = json.load(open(os.path.join(HERE, "random_control_%s_%s.json" % (rid, sym)), encoding="utf-8"))
pct, n = float(j["percentile"]), int(j["seeds"])
hold = {}
try:
    hold = json.load(open(hold_f, encoding="utf-8"))
except Exception:
    pass
if r.returncode == 0 and n >= seeds and pct >= 95.0:
    hold.pop(key, None); verdict = "CONFIRMED on %d seeds (%.1f pct) - hold lifted" % (n, pct)
else:
    hold[key] = "contrôle du hasard sur %d tirages : %.1fe percentile, sous la barre des 95 - pas d'argent réel" % (n, pct) if r.returncode == 0 else hold.get(key, "contrôle à refaire")
    verdict = "NOT confirmed on %d seeds (%.1f pct) - hold kept" % (n, pct)
json.dump(hold, open(hold_f, "w", encoding="utf-8"), ensure_ascii=True, indent=1)
line = "%s %s: %s (real %.2f, control median %.2f, %.0f s)" % (time.strftime("%Y-%m-%d %H:%M:%S"), key, verdict, float(j["real"]["net"]), float(j["control"]["median"]), time.time() - t0)
open(os.path.join(LIVE, "robots", "market_runs.log"), "a", encoding="utf-8").write(line + "\n")
print(line)
