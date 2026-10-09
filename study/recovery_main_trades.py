# Owner 2026-10-09: "check the recovery main trades, should we remove them?"
# Bullets ride on the main trades (they enter at a main trade's midpoint),
# so "removing" them has several meanings - each tested, live settings (jar
# on), with and without the measured real-execution drag.
import sys
sys.path.insert(0, r"C:\Projects\KinoliveLines\live\lab"); sys.argv = ["x"]
import harness as H
sym, R = H.bars()
def pf(p):
    w = sum(x for x in p if x > 0); l = -sum(x for x in p if x < 0)
    return w / l if l else float("nan")
for drag in (0.0, "auto"):
    print("\n=== execution drag: %s ===" % ("none (replay prices)" if drag == 0.0 else "measured real drag"))
    LIVE = {"jar": True, "drag": drag}
    V = [("A today", LIVE, None, None),
         ("B no trades at all in recovery", LIVE, lambda t, d: False, None),
         ("C bullets only (main at size 0)", LIVE, None, 0.0),
         ("D half-size main in recovery", LIVE, None, 0.5),
         ("E bullets only, jar off", dict(LIVE, jar=False), None, 0.0),
         ("   (today with jar off, for E)", dict(LIVE, jar=False), None, None)]
    base = None
    for name, cfg, gate, mult in V:
        H.DEBTGATE, H.DEBT_MAIN_MULT = gate, mult
        v = H.run_cfg(R, 7.0, cfg); f = v["full"]
        H.DEBTGATE = H.DEBT_MAIN_MULT = None
        if base is None: base = v
        print("%-34s trades %3d | PF %.2f | net %8.2f | 1st half %8.2f | 2nd half %8.2f | worst drop %7.2f | %s" % (
            name, f["trades"], pf(f["pnls"]), f["net"], v["h1"]["net"], v["h2"]["net"], -f["worst_debt"],
            "-" if v is base else "verdict vs A " + H.verdict(v, base)), flush=True)
