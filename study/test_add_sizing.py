"""the bench's add count must equal the live bot's formula on the same inputs (structure_bos_bot try-adds, JAR branch)"""
import math, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "live"))
import tick_engine as E
def live_n(chest, debt, dist, rr, max_extra=3, stake=E.JAR_STAKE):
    r001 = max(round(0.5 * dist * 0.01, 2), 0.01); gain = rr * r001
    return max(0, min(max_extra, int((chest * stake) // r001), int(math.ceil(debt / gain)) if gain > 0 else 0))
class P(dict): pass
fails = 0
for chest, debt, dist, rr in ((10.67, 21.34, 347.3, 0.8), (8.76, 27.84, 111.9, 0.8), (14.63, 29.26, 148.2, 0.8), (3.0, 2.0, 400.0, 1.0), (20.0, 50.0, 90.0, 0.8)):
    a = E.Arm.__new__(E.Arm); a.c = {"jar": 1}; a.chest = chest; a.pk = debt; a.run = 0.0; a.streak = 0; a.K = 2; a.NB = 3; a.rr = rr
    a.n = {"adds_triggered": 0}; a.events = []; a.order = None; a.bars = {}
    a.pos = {"dist": dist, "d": 1, "t": 0, "nv": 0.5}
    E.Arm.try_adds(a, 0, [0], [0], [0])
    got = a.order["n"] if a.order else 0
    want = live_n(chest, debt, dist, rr)
    ok = got == want; fails += not ok
    print(("ok  " if ok else "FAIL") + " chest %.2f debt %.2f dist %.1f -> bench %d, live %d" % (chest, debt, dist, got, want))
sys.exit(1 if fails else 0)
