"""Tests for compte_controller (ChatGPT review 3): corruption, latch,
recovery, idempotence, determinism, scale tolerance.  python test_compte_controller.py"""
import math, random, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from compte_controller import CompteController, run, check_determinism, VERSION

r = random.Random(7)
P = [r.choice([-1.0, 0.8]) * r.choice([1.0, 2.0, 3.0]) for _ in range(160)]
fails = []
def ok(name, cond):
    print(("PASS " if cond else "FAIL ") + name)
    if not cond: fails.append(name)

# 1 invalid is latched: a later valid row does not clear it, nothing mutates
c = CompteController(); c.feed(1.0, event="e1"); c.feed(0.0, valid=False, event="e2")
snap = (c.n, c.cum, len(c.kept))
s = c.feed(2.0, event="e3")
ok("latched invalid survives a valid row", s["status"] == "invalid" and s["reason"] == "flagged_gap")
ok("no mutation after invalid", (c.n, c.cum, len(c.kept)) == snap and c.invalid["last_valid_event"] == "e1")
# 2 NaN / inf / None / str rejected BEFORE mutation
for bad, why in ((float("nan"), "non_finite_input"), (float("inf"), "non_finite_input"), (None, "missing_or_non_numeric"), ("x", "missing_or_non_numeric"), (True, "missing_or_non_numeric")):
    c = CompteController(); c.feed(1.0); s = c.feed(bad)
    ok("rejects %r before mutation" % (bad,), s["status"] == "invalid" and s["reason"] == why and c.n == 1 and c.cum == 1.0)
# 3 cumulative overflow is caught, last valid state kept
c = CompteController(); c.feed(1e308); s = c.feed(1e308)
ok("non-finite cumulative latched, cum kept finite", s["status"] == "invalid" and s["reason"] == "non_finite_cumulative" and math.isfinite(c.cum))
# 4 recovery only via reset + complete replay
c = CompteController(); c.feed(1.0); c.feed(None); c.reset()
for p in P: c.feed(p)
ok("reset + full replay equals a fresh run", c.state == run(P).state and c.invalid is None)
# 5 determinism (restart safety)
ok("0 determinism violations over 160 prefixes", check_determinism(P) == 0)
# 6 idempotence of the event id: the SAME outcome fed twice is two rows here
#   (dedup is the LEDGER's job, keyed by event id) - documented, not hidden
c = CompteController(); c.feed(1.0, event="a"); c.feed(1.0, event="a")
ok("controller does not dedup (ledger must)", c.n == 2)
# 7 positive-scale tolerance: same trend path at x0.01 .. x1000 (doc: up to TOL)
base = [s["trend"] for s in (lambda cc: [cc.feed(p) and dict(cc.state) for p in P])(CompteController())]
agree = {}
for k in (0.01, 0.1, 10.0, 1000.0):
    cc = CompteController(); seq = [dict(cc.feed(p * k))["trend"] for p in P]
    agree[k] = sum(1 for a, b in zip(base, seq) if a == b) / len(P)
ok("scale x0.1/x10/x1000 give the same trend path", all(agree[k] == 1.0 for k in (0.1, 10.0, 1000.0)))
print("scale agreement:", agree, "(x0.01 may differ: values approach the 1e-9 tolerance)")
# 8 synthetic origin case: pinned controller does not flip at outcome 108
c = run(P)
ok("no no-mark flip in the synthetic case", all(t[4] != "no_mark" for t in c.transitions))
print(VERSION, "transitions", [(t[0], t[1], t[2], t[4]) for t in c.transitions])
print("\nRESULT:", "ALL PASS" if not fails else "FAILED: " + ", ".join(fails))
sys.exit(1 if fails else 0)
