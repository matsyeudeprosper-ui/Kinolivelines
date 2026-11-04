"""stress_check.py (2026-11-04, owner list 9 item 4): does Kino take fewer valid entries soon after being corrected?
Entries due = kino_entries hindsight reviews (open_trade excluded); corrections = kino_trust log. First run (11-04 02:5x UTC):
1 correction, 6 entries due, none within 30 min after it - not enough to conclude; rerun when weeks of sessions exist.

    python -X utf8 live/review/stress_check.py [person] [window_min]
"""
import json, os, sys, time

R = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "robots")
person = sys.argv[1] if len(sys.argv) > 1 else "kino"
win = 60 * float(sys.argv[2] if len(sys.argv) > 2 else 30)
E = [r for r in json.load(open(os.path.join(R, "kino_entries.json"), encoding="utf-8")).get(person, []) if r["called_for"] and r["kino"] != "open_trade"]
T = json.load(open(os.path.join(R, "kino_trust.json"), encoding="utf-8")).get(person, {})
corr = sorted(float(x["t"]) for k in (T.get("kinds") or {}).values() for x in k.get("log") or [] if x.get("r") != "approved")
a = [r for r in E if any(0 < r["t"] - c < win for c in corr)]
b = [r for r in E if r not in a]
ok = lambda L: sum(1 for r in L if r["kino"] in ("took", "late"))
print("corrections %d | entries due after a correction: %d taken %d | otherwise: %d taken %d" % (len(corr), len(a), ok(a), len(b), ok(b)))
if min(len(a), len(b)) < 15:
    print("not enough data to conclude (need 15+ on each side)")
