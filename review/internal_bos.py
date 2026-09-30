"""Internal-structure entries: the first backtest that includes them.

Until 2026-09-30 `lab/harness.py` did not model internal-structure trades at
all, while the live bot takes them. Every backtest number, including the
proof page, therefore excluded a trade type that really trades. The harness
now carries an `internal` dial:

    0  off - the old behaviour, unchanged
    1  the LIVE rule: enter only when the internal trend agrees with the
       main one
    2  also counter-trend, which the bot logs and refuses today

CALIBRATION, before trusting any of it. The simulated rule fires 8.1 aligned
internal signals a day. The live bots log 4.1/day (Valere) and 8.6/day
(demo) - they differ from each other because each bot runs its own main
structure, so "aligned" is account-specific. The simulation sits inside the
live range, which is the most that can be asked of it.

Reported on the full period and on each half, because a result that only
holds on one half is not a result.

Run:  python review/internal_bos.py
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
ACCOUNTS = [("Valere", 270.75), ("Depenses", 200.00)]
MODES = [("main only", 0), ("+ internal aligned", 1), ("+ internal both", 2)]


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
        rows = {}
        base = None
        for tag, mode in MODES:
            cfg = H.package_cfg("valere", {"balance": bal,
                                           "scale_ref": 230.0,
                                           "internal": mode})
            f = H.simulate(R, SPREAD, cfg)
            h1 = H.simulate(R[:mid], SPREAD, cfg)
            h2 = H.simulate(R[mid:], SPREAD, cfg)
            if base is None:
                base = (f["net"], h1["net"], h2["net"])
                d = ""
            else:
                def pc(a, b):
                    return f"{(a-b)/abs(b)*100:+6.1f}%" if b else "      -"
                d = (f"  vs main: full {pc(f['net'], base[0])}"
                     f"  h1 {pc(h1['net'], base[1])}"
                     f"  h2 {pc(h2['net'], base[2])}")
            print(f"  {tag:<20} full {f['net']:+8.2f}  h1 {h1['net']:+8.2f}"
                  f"  h2 {h2['net']:+8.2f}  trades {f['trades']:4d}"
                  f"  int {f.get('internal', 0):4d}  wr {f['wr']:5.1f}%"
                  f"  DD {f['worst_debt']:6.2f}{d}")
            rows[tag] = {k: v for k, v in f.items()
                         if k not in ("curve", "pnls")}
            rows[tag]["h1_net"] = h1["net"]
            rows[tag]["h2_net"] = h2["net"]
        out["accounts"][name] = rows

    with open(os.path.join(HERE, "internal_bos.json"), "w") as f:
        json.dump(out, f, indent=1)
    print("")
    print("written: review/internal_bos.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
