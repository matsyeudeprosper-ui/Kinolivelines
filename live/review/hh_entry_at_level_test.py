"""Owner 2026-10-24, second reading of "we just take trades at last highest high": the Owl enters AT the swing high it
breaks (a stop order sitting on the last higher high), mirrored for sells on the last lower low, instead of at the close
of the breaking candle. Same everything else.

Caveat (optimistic): the engine still needs the candle to CLOSE beyond the level to call a break, so the wick-only
touches that a real stop order would also fill (and mostly lose) are not simulated. The gain shown is an upper bound.

Also prints Valere's own package replayed on the same window, to set the generic base against the real account.

    python review/hh_entry_at_level_test.py [spread]

RESULT 2026-10-24 (41.7 days to 24/10, spread 7) - the OPTIMISTIC bound (confirmed breaks only, filled at the level):
  generic as is -171.31 (256 tr) -> entry at level -27.67 (275 tr, 64% won), verdict A
  valere pkg as is -63.02 (232 tr) -> +18.63 (279 tr, 65% won), verdict A
  NOT a result: the wick-only fills a real stop order also takes are missing. With them (hh_stop_order_test.py) the
  gain vanishes: generic -223.76, valere -62.96 (killed at -60). Verdict C. Better price, paid back by false breaks.
"""
import os, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
LIVE = os.path.dirname(HERE)
sys.path.insert(0, LIVE)
sys.path.insert(0, os.path.join(LIVE, "lab"))
_ARGS = sys.argv[1:]
sys.argv = ["hh_entry_at_level_test"]
import harness as H                       # noqa: E402
import structure_bos_bot as B             # noqa: E402

SPREAD = float(_ARGS[0]) if _ARGS else 7.0
MODE = {"on": False}
_step0 = B.Struct.step


def _step(self, t, o, h, l, c):
    hi, lo = self.hi_v, self.lo_v
    sig = _step0(self, t, o, h, l, c)
    if sig is not None and MODE["on"] and len(sig) == 2:
        lvl = hi if sig[0] == 1 else lo
        if lvl is not None:
            sig = (sig[0], sig[1], float(lvl))
    return sig


B.Struct.step = _step
sym, R = H.bars()
print("%s  %d M1 candles = %.1f days  spread %.0f" % (sym, len(R), (int(R[-1]["time"]) - int(R[0]["time"])) / 86400.0, SPREAD))


def line(name, v, extra=""):
    f = v["full"]
    print("  %-22s trades %4d  win %5.1f%%  net %+8.2f  worst dip %7.2f | h1 %+7.2f  h2 %+7.2f  %s" % (
        name, f["trades"], f["wr"], f["net"], f["worst_debt"], v["h1"]["net"], v["h2"]["net"], extra))


t0 = time.time()
for label, cfg in (("generic", H.cfg_of({})), ("valere package", H.package_cfg("valere", {"balance": 210.0}))):
    MODE["on"] = False
    base = H.run_cfg(R, SPREAD, cfg)
    line(label + " as is", base)
    MODE["on"] = True
    v = H.run_cfg(R, SPREAD, cfg)
    line(label + " entry at level", v, "verdict %s" % H.verdict(v, base))
MODE["on"] = False
print("done in %.0f s" % (time.time() - t0))
