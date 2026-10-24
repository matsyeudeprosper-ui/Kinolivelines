"""Owner 2026-10-24: "we just take trades at last highest high, mirror for sell" - the REALISTIC version of
review/hh_entry_at_level_test.py: a stop order resting on the last higher high (lower low). It fills on the first TOUCH of
the level, whether or not the candle then closes beyond it. Same engine, same gates, same money.

How the wick-only fills are found: on a candle whose high reaches the level but whose close stays under it, a copy of the
structure engine is fed the same candle with a close just beyond the level; if the engine would have called that a break
(trend, CHoCH and silence rules included), the stop order is filled at the level, stop at the protected low, target rr x
the distance - and the real engine keeps its own view (no break registered). A confirmed break fills at the level too.
Still a little kind to the idea: a fill and a stop-out inside the same candle count as an open trade.

    python review/hh_stop_order_test.py [spread]

RESULT 2026-10-24 (41.7 days to 24/10, spread 7): 1094 wick-only fills for 1539 confirmed breaks (42 % of the orders fill
on a wick that never closes through).
  generic as is -167.20 (254 tr, 50% won) -> stop order at level -223.76 (288 tr, 58% won, worst dip 219), verdict C
  valere pkg as is -61.17 (230 tr) -> -62.96 and the -60 kill line hit after 60 trades (h1 alone -62.96), verdict C
  The better entry price is real (+9 points of win rate) and the false breaks take it all back. Closed.
"""
import os, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
LIVE = os.path.dirname(HERE)
sys.path.insert(0, LIVE)
sys.path.insert(0, os.path.join(LIVE, "lab"))
_ARGS = sys.argv[1:]
sys.argv = ["hh_stop_order_test"]
import harness as H                       # noqa: E402
import structure_bos_bot as B             # noqa: E402

SPREAD = float(_ARGS[0]) if _ARGS else 7.0
MODE = {"on": False, "wick": 0, "conf": 0}
_step0 = B.Struct.step


def _step(self, t, o, h, l, c):
    hi, lo = self.hi_v, self.lo_v
    probe = None
    if MODE["on"] and hi is not None and lo is not None:
        up, dn = (h >= hi > c), (l <= lo < c)
        if up or dn:
            cl = B.Struct.__new__(B.Struct)
            cl.__dict__.update(self.__dict__)
            cl.kept = list(self.kept)
            r = _step0(cl, t, o, h, l, (hi + 0.01) if up else (lo - 0.01))
            if r is not None and ((up and r[0] == 1) or (dn and r[0] == -1)):
                probe = (r[0], r[1], float(hi if r[0] == 1 else lo))
    sig = _step0(self, t, o, h, l, c)
    if MODE["on"]:
        if sig is not None and len(sig) == 2:
            lvl = hi if sig[0] == 1 else lo
            if lvl is not None:
                sig = (sig[0], sig[1], float(lvl))
                MODE["conf"] += 1
        elif probe is not None:
            sig = probe
            MODE["wick"] += 1
    return sig


B.Struct.step = _step
sym, R = H.bars()
print("%s  %d M1 candles = %.1f days  spread %.0f" % (sym, len(R), (int(R[-1]["time"]) - int(R[0]["time"])) / 86400.0, SPREAD))


def line(name, v, extra=""):
    f = v["full"]
    print("  %-26s trades %4d  win %5.1f%%  net %+8.2f  worst dip %7.2f  cc_dd %7.2f | h1 %+7.2f  h2 %+7.2f  %s" % (
        name, f["trades"], f["wr"], f["net"], f["worst_debt"], f["cc_dd"], v["h1"]["net"], v["h2"]["net"], extra))


t0 = time.time()
for label, cfg in (("generic", H.cfg_of({})), ("valere package", H.package_cfg("valere", {"balance": 210.0}))):
    MODE["on"] = False
    base = H.run_cfg(R, SPREAD, cfg)
    line(label + " as is", base)
    MODE.update(on=True, wick=0, conf=0)
    v = H.run_cfg(R, SPREAD, cfg)
    line(label + " stop order at level", v, "verdict %s | signals: %d wick-only fills, %d confirmed (3 runs)" % (H.verdict(v, base), MODE["wick"], MODE["conf"]))
MODE["on"] = False
print("done in %.0f s" % (time.time() - t0))
