"""Live bot vs bench: the same rule pieces must make the same decisions (owner 2026-10-13, step 4).
    python live/robots/test_robot_live.py
Builds bench arms without running a backtest (DslArm methods called on a bare object) and compares them with
robot_live on hand-made cases: every entry event x signal kind, every filter at its edges, every stop kind,
every exit condition."""
import sys, os, itertools
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, r"C:\Projects\KinoliveLines\study"); sys.path.insert(0, r"C:\Projects\KinoliveLines\live"); sys.path.insert(0, r"C:\Projects\KinoliveLines\live\lab")
_argv = sys.argv; sys.argv = ["x"]
import robot_live as L
import robot_dsl as DSL
import tick_engine as E
import tick_engine_matrix as M
from robot_dsl_arm import DslArm
sys.argv = _argv
fails = 0


def check(name, a, b):
    global fails
    if a != b:
        fails += 1
        print("  FAIL", name, "bench", a, "live", b)


def bare(dsl):
    x = DslArm.__new__(DslArm)
    x.dsl = dsl
    x.n = {"dsl_filter": 0}
    return x


# entry
for ev, flip in itertools.product(("any", "bos", "choch"), (True, False)):
    ok, r = DSL.validate("entry", {"event": ev})
    b = bare({"entry": r})._entry_ok({"flip": flip})
    l, _ = L.entry_ok({"entry": r}, "FLIP-BOS" if flip else "BOS")
    check("entry %s flip=%s" % (ev, flip), b, l)
# filters (the bench's late_gates with the ordinary gates switched off)
_orig = M.PolicyArm.late_gates
M.PolicyArm.late_gates = lambda self, o, debt: False
cases = [({"kind": "hours", "from": 8, "to": 20}, {"hour": h}) for h in (7, 8, 19, 20)] + \
        [({"kind": "weekdays", "days": [0, 2, 4]}, {"weekday": w}) for w in range(7)] + \
        [({"kind": "pace", "min": 0.8, "max": 1.3}, {"nv": v}) for v in (0.7, 0.8, 1.0, 1.3, 1.4)] + \
        [({"kind": "pace", "min": None, "max": 1.2}, {"nv": v}) for v in (1.1, 1.25)] + \
        [({"kind": "moves", "min": 2}, {"mv2": m}) for m in (0, 1, 2, 3)]
for rule, o0 in cases:
    ok, r = DSL.validate("filter", rule)
    assert ok, rule
    o = {"hour": 12, "weekday": 1, "nv": 1.0, "mv2": 3}; o.update(o0)
    b = not bare({"filters": [r]}).late_gates(o, 0.0)
    l, _ = L.filters_ok({"filters": [r]}, o["hour"], o["weekday"], o["nv"], o["mv2"])
    check("filter %s %s" % (rule, o0), b, l)
M.PolicyArm.late_gates = _orig
# stops: the bench reads the break candle from the dataset - use a real bar
i = 5000
lo, hi, cl = float(E.R["low"][i]), float(E.R["high"][i]), float(E.R["close"][i])
for rule in ({"kind": "protected", "buffer": 0}, {"kind": "protected", "buffer": 25}, {"kind": "break_candle", "buffer": 10}, {"kind": "fixed", "points": 300}):
    ok, r = DSL.validate("stop", rule)
    for d in (1, -1):
        slp = cl - d * 200
        b = bare({"stop": r})._with_stop({"d": d, "slp": slp, "i": i, "cl": cl})["slp"]
        l = L.stop_for({"stop": r}, d, slp, cl, lo, hi)
        check("stop %s d=%d" % (rule, d), round(b, 6), round(l, 6))
# targets
for rule in ({"target": 1.5, "choch": False}, {"target": None, "choch": True}, {"target": 0.8, "choch": True, "time_min": 30}):
    ok, r = DSL.validate("exit", rule)
    for d in (1, -1):
        e, dist = 80000.0, 150.0
        bench_tp = (e + d * r["target"] * dist) if r["target"] is not None else 0.0
        check("tp %s d=%d" % (rule, d), round(bench_tp, 6), round(L.tp_for({"exit": r}, d, e, dist, 0.8), 6))
# open trade: the bench closes on time >= limit, breakeven when gain >= be x risk, CHoCH against
ok, r = DSL.validate("exit", {"target": 2.0, "choch": True, "time_min": 30, "breakeven_at": 0.5})
for d in (1, -1):
    e, sl = 80000.0, 80000.0 - d * 100
    check("time 29 min", None, L.manage({"exit": r}, d, e, sl, 0, 29 * 60, e, False, False))
    check("time 30 min", "close", (L.manage({"exit": r}, d, e, sl, 0, 30 * 60, e, False, False) or [None])[0])
    check("be at 0.49R", None, L.manage({"exit": r}, d, e, sl, 0, 60, e + d * 49, False, False))
    check("be at 0.5R", ("sl", e), L.manage({"exit": r}, d, e, sl, 0, 60, e + d * 50, False, False))
    check("be once", None, L.manage({"exit": r}, d, e, e, 0, 60, e + d * 80, False, True))
    check("choch against", "close", (L.manage({"exit": r}, d, e, sl, 0, 60, e, True, False) or [None])[0])
# no rules = no change, anywhere
check("no rules entry", True, L.entry_ok({}, "BOS")[0])
check("no rules filters", True, L.filters_ok({}, 3, 6, 9.9, 0)[0])
check("no rules stop", 123.0, L.stop_for({}, 1, 123.0, 1, 1, 1))
check("no rules tp", 80000 + 0.8 * 150, L.tp_for({}, 1, 80000, 150, 0.8))
check("no rules manage", None, L.manage({}, 1, 1, 1, 0, 10 ** 9, 5, True, False))
print("ROBOT LIVE vs BENCH:", "OK" if not fails else "%d FAILED" % fails)
sys.exit(1 if fails else 0)
