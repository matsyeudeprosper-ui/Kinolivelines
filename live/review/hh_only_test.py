"""Owner 2026-10-24: "Test this. On owl. Same everything. Now we just take trades at last highest high.
Mirror the same for sell."

Reading 1: the Owl keeps every rule, but a BUY is only taken when the swing high it breaks is the HIGHEST high of the
recent past (no higher high behind it), and a SELL only when the swing low it breaks is the LOWEST low. "Recent past"
is not defined by the owner, so it is run for several windows (4 h, 12 h, 24 h, 48 h of M1 candles before the breaking
candle). A change-of-direction entry (FLIP-BOS) breaks a LOWER high by construction, so long windows remove most flips.

Same harness as every other what-if (lab/harness.py: same engine as the live bot, costs, jar, 42 days of the std
terminal's M1). The broken level is read from the structure engine BEFORE the breaking candle moves it.
Control (standing rule): a random gate that passes the same share of signals, 12 seeds, full period.

    python review/hh_only_test.py [spread]

RESULT 2026-10-24 (BTCUSDm, 41.7 days to 24/10, spread 7, generic account):
  owl as is   256 trades, 49% won, net -171.31, worst dip 179.58 (h1 -4.30, h2 -188.12)
  HH 4 h       27 trades, net -22.41 | HH 12 h 10 trades, -22.90 | HH 24 h 7 trades, -9.19 | HH 48 h 3 trades, -11.40
  the gate passes 1-7 % of signals; 12 random gates at the same pass rate: 5 of 12 did as well -> noise, verdict C.
  It "loses less" only because it almost never trades. (The owner's second reading - enter AT the level - is in
  review/hh_entry_at_level_test.py and review/hh_stop_order_test.py.)
"""
import bisect, os, random, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
LIVE = os.path.dirname(HERE)
sys.path.insert(0, LIVE)
sys.path.insert(0, os.path.join(LIVE, "lab"))
_ARGS = sys.argv[1:]
sys.argv = ["hh_only_test"]
import harness as H                       # noqa: E402
import structure_bos_bot as B             # noqa: E402

SPREAD = float(_ARGS[0]) if _ARGS else 7.0
PRE = {"hi": None, "lo": None, "trend0": 0, "trend1": 0, "t0": None}
_step0, _init0 = B.Struct.step, B.Struct.__init__


def _init(self):
    _init0(self)
    PRE["t0"] = None


def _step(self, t, o, h, l, c):
    PRE["hi"], PRE["lo"], PRE["trend0"] = self.hi_v, self.lo_v, self.trend
    if PRE["t0"] is None:
        PRE["t0"] = t
    r = _step0(self, t, o, h, l, c)
    PRE["trend1"] = self.trend
    return r


B.Struct.__init__, B.Struct.step = _init, _step

sym, R = H.bars()
TIMES = [int(r["time"]) for r in R]
HI = [float(r["high"]) for r in R]
LO = [float(r["low"]) for r in R]
days = (TIMES[-1] - TIMES[0]) / 86400.0
print("%s  %d M1 candles = %.1f days  spread %.0f  engine %s" % (sym, len(R), days, SPREAD, H.ENGINE))
STAT = {"n": 0, "ok": 0, "flip": 0, "flip_ok": 0}


def gate_for(W):
    def gate(t, d):
        STAT["n"] += 1
        flip = PRE["trend1"] != PRE["trend0"] and PRE["trend1"] != 0
        STAT["flip"] += flip
        i = bisect.bisect_left(TIMES, t)
        j = max(0, i - W, bisect.bisect_left(TIMES, PRE["t0"] or 0))
        lvl = PRE["hi"] if d == 1 else PRE["lo"]
        if lvl is None or j >= i:
            ok = True
        elif d == 1:
            ok = lvl >= max(HI[j:i]) - 1e-9
        else:
            ok = lvl <= min(LO[j:i]) + 1e-9
        STAT["ok"] += ok
        STAT["flip_ok"] += ok and flip
        return ok
    return gate


def rnd_gate(p, seed):
    rng = random.Random(seed)
    return lambda t, d: rng.random() < p


def line(name, v, extra=""):
    f = v["full"]
    print("  %-14s trades %4d  win %5.1f%%  net %+8.2f  worst dip %7.2f  cc_dd %7.2f | h1 %+7.2f  h2 %+7.2f  %s" % (
        name, f["trades"], f["wr"], f["net"], f["worst_debt"], f["cc_dd"], v["h1"]["net"], v["h2"]["net"], extra))


cfg = H.cfg_of({})
t0 = time.time()
H.DIRGATE = None
base = H.run_cfg(R, SPREAD, cfg)
print("base run %.0f s" % (time.time() - t0))
line("owl as is", base)
out = {}
for W, nm in ((240, "HH 4 h"), (720, "HH 12 h"), (1440, "HH 24 h"), (2880, "HH 48 h")):
    STAT.update(n=0, ok=0, flip=0, flip_ok=0)
    H.DIRGATE = gate_for(W)
    v = H.run_cfg(R, SPREAD, cfg)
    p = STAT["ok"] / max(1, STAT["n"])
    out[W] = (v, p)
    line(nm, v, "verdict %s | gate passes %.0f%% of signals, flips kept %d/%d" % (H.verdict(v, base), 100 * p, STAT["flip_ok"], STAT["flip"]))
# control on the window that made the most money
Wb = max(out, key=lambda w: out[w][0]["full"]["net"])
vb, pb = out[Wb]
nets = []
for s in range(12):
    H.DIRGATE = rnd_gate(pb, 100 + s)
    nets.append(H.simulate(R, SPREAD, cfg)["net"])
H.DIRGATE = None
nets.sort()
beat = sum(1 for x in nets if x >= vb["full"]["net"])
print("\ncontrol for HH %d min (passes %.0f%%): 12 random gates at the same pass rate -> nets %s" % (Wb, 100 * pb, ", ".join("%+.0f" % x for x in nets)))
print("  %d of 12 random gates did as well or better than the HH rule (%+.2f)" % (beat, vb["full"]["net"]))
print("done in %.0f s" % (time.time() - t0))
