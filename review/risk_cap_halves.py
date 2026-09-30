"""The halves check for the risk cap.

review/risk_cap.py measured the full period. A number chosen on the full
period and never checked in both halves is a fit, not a finding - the house
rule here. This runs the two candidates that actually bind on the two
bigger accounts, on the full period and on each half.

A candidate is only recommendable if the cost is of the same order in both
halves. A cap that is free in one half and expensive in the other has been
fitted to whichever half held the big losses.

Run:  python review/risk_cap_halves.py
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
LIVE = os.path.join(os.path.dirname(HERE), "live")
sys.path.insert(0, LIVE)
sys.path.insert(0, os.path.join(LIVE, "lab"))

import harness as H            # noqa: E402

SPREAD = 7.0
ACCOUNTS = [("Valere", 270.75), ("Dad 441", 378.29),
            ("Depenses", 200.00), ("Infinity", 175.99)]
CANDS = [("no cap", {}),
         ("FIT 3%", {"risk_fit": 3.0}),
         ("FIT 5%", {"risk_fit": 5.0})]


def worst_trade(R, cfg):
    H.TRACE = []
    H.simulate(R, SPREAD, cfg)
    tr = H.TRACE
    H.TRACE = None
    ls = [t["pnl"] for t in tr if t.get("pnl") is not None and t["pnl"] < 0]
    return round(min(ls), 2) if ls else 0.0


def main():
    print("loading bars...")
    sym, R = H.bars_long()
    if R is None or not len(R):
        print("no bars from MT5 - is a terminal running?")
        return 2
    mid = len(R) // 2
    print(f"{sym}: {len(R)} M1 bars, engine {H.ENGINE}")
    out = {"engine": H.ENGINE, "bars": len(R), "accounts": {}}

    for name, bal in ACCOUNTS:
        print("")
        print(f"=== {name}  (balance ${bal:.2f}) ===")
        base = None
        rows = {}
        for tag, over in CANDS:
            cfg = H.package_cfg("valere",
                                dict({"balance": bal, "scale_ref": 230.0},
                                     **over))
            r = H.run_cfg(R, SPREAD, cfg)
            wt = worst_trade(R, cfg)
            f, h1, h2 = r["full"], r["h1"], r["h2"]
            if base is None:
                base = (f["net"], h1["net"], h2["net"])
                d = ""
            else:
                def pc(a, b):
                    return f"{(a-b)/abs(b)*100:+5.1f}%" if b else "    -"
                d = (f"   cost full {pc(f['net'], base[0])}"
                     f"  h1 {pc(h1['net'], base[1])}"
                     f"  h2 {pc(h2['net'], base[2])}")
            print(f"  {tag:<9} full {f['net']:+8.2f}  h1 {h1['net']:+8.2f}"
                  f"  h2 {h2['net']:+8.2f}  worst trade {wt:7.2f}{d}")
            rows[tag] = {"full": f["net"], "h1": h1["net"], "h2": h2["net"],
                         "worst_trade": wt, "dd": f["worst_debt"],
                         "trades": f["trades"]}
        out["accounts"][name] = rows

    with open(os.path.join(HERE, "risk_cap_halves.json"), "w") as f:
        json.dump(out, f, indent=1)
    print("")
    print("written: review/risk_cap_halves.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
