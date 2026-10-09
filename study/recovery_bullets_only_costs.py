# Owner 2026-10-09: real-cost check for "bullets only in recovery" (E).
# Execution drag charged per lot on EVERY position, bullets included.
import sys
sys.path.insert(0, r"C:\Projects\KinoliveLines\live\lab"); sys.argv = ["x"]
import harness as H
sym, R = H.bars()
for dg in (0.0, 0.35, 0.57, 1.0):
    H.DEBT_MAIN_MULT = None; a = H.run_cfg(R, 7.0, {"jar": True, "drag": dg})
    H.DEBT_MAIN_MULT = 0.0; e = H.run_cfg(R, 7.0, {"jar": False, "drag": dg}); H.DEBT_MAIN_MULT = None
    print("cost $%.2f/0.02 lot | today: net %7.2f h1 %7.2f h2 %7.2f drop %7.2f | E: net %7.2f h1 %7.2f h2 %7.2f drop %7.2f | verdict %s" % (
        dg, a["full"]["net"], a["h1"]["net"], a["h2"]["net"], -a["full"]["worst_debt"],
        e["full"]["net"], e["h1"]["net"], e["h2"]["net"], -e["full"]["worst_debt"], H.verdict(e, a)), flush=True)
