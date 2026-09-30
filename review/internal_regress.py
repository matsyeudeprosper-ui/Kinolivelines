"""Regression: with internal=0 the patched harness must agree with the
pre-patch one, bar for bar, on the SAME data.

Comparing two separate runs is worthless here - bars_long() loads the latest
candles each time, so the market moves between runs and the nets differ for
reasons that have nothing to do with the patch. Both versions are loaded in
ONE process and given the identical R.
"""
import importlib.util
import os
import sys

LIVE = r"C:\Projects\KinoliveLines\live"
SCR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, LIVE)
sys.path.insert(0, os.path.join(LIVE, "lab"))


def load(name, path):
    sp = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(sp)
    sys.modules[name] = m
    sp.loader.exec_module(m)
    return m


new = load("harness_new", os.path.join(LIVE, "lab", "harness.py"))
old = load("harness_old", os.path.join(LIVE, "lab", "_harness_old_tmp.py"))

print("loading bars once, shared by both...")
sym, R = new.bars_long()
print(sym, len(R), "bars")

CASES = [("valere", {"balance": 270.75, "scale_ref": 230.0}),
         ("valere", {}),
         ("base", {}),
         ("demo", {"balance": 200.0, "scale_ref": 230.0})]

bad = 0
for pkg, over in CASES:
    a = old.simulate(R, 7.0, old.package_cfg(pkg, dict(over)))
    b = new.simulate(R, 7.0, new.package_cfg(pkg, dict(over)))
    same = (a["net"] == b["net"] and a["trades"] == b["trades"]
            and a["worst_debt"] == b["worst_debt"] and a["wr"] == b["wr"])
    if not same:
        bad += 1
    print(f"  {pkg:<8} {str(over)[:34]:<36} "
          f"old net {a['net']:+8.2f}/{a['trades']:4d}tr   "
          f"new net {b['net']:+8.2f}/{b['trades']:4d}tr   "
          f"{'IDENTICAL' if same else '*** DIFFERS ***'}")

print("")
print("regression:", "PASS - internal=0 changes nothing" if not bad
      else f"FAIL on {bad} case(s)")
sys.exit(1 if bad else 0)
