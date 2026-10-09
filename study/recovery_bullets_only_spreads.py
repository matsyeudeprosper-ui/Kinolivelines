import sys
sys.path.insert(0, r"C:\Projects\KinoliveLines\live\lab"); sys.argv = ["x"]
import harness as H
sym, R = H.bars()
for sp in (5.0, 7.0, 10.0):
    H.DEBT_MAIN_MULT = None; a = H.run_cfg(R, sp, {"jar": True})
    H.DEBT_MAIN_MULT = 0.0; e = H.run_cfg(R, sp, {"jar": False}); H.DEBT_MAIN_MULT = None
    print("spread %4.1f | today: net %7.2f h1 %7.2f h2 %7.2f drop %7.2f | E: net %7.2f h1 %7.2f h2 %7.2f drop %7.2f | verdict %s" % (
        sp, a["full"]["net"], a["h1"]["net"], a["h2"]["net"], -a["full"]["worst_debt"],
        e["full"]["net"], e["h1"]["net"], e["h2"]["net"], -e["full"]["worst_debt"], H.verdict(e, a)), flush=True)
