"""Is the internal rule bad, or only its wide-stop half?

An internal-structure entry is supposed to be the SMALL structure inside the
big one. The internal trade that cost real money on 2026-09-25 carried a
594 pt stop against a 214 pt median for main-structure trades - nearly three
times wider. A "small structure" with a huge invalidation level is a
contradiction, and it is where the money went.

So: does the internal rule become worth keeping once the wide ones are
thrown away? Two guards, both measured against plain internal and against
main-only:

  tighter    refuse an internal entry whose stop is wider than the MAIN
             structure's own stop right now. This is the guard that follows
             from the definition: an inner structure cannot be looser than
             the one containing it.
  max N x    refuse an internal entry whose stop is wider than N times the
             median 60-minute candle range.

Full period and both halves, two accounts. A guard only counts if it holds
in both halves - the house rule.

Run:  python review/internal_widestop.py
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
MODES = [
    ("main only", {}),
    ("internal, no guard", {"internal": 1}),
    ("internal, tighter than main", {"internal": 1, "int_tighter": 1}),
    ("internal, stop < 3x median", {"internal": 1, "int_max_stop": 3.0}),
    ("internal, stop < 2x median", {"internal": 1, "int_max_stop": 2.0}),
]


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
        for tag, over in MODES:
            cfg = H.package_cfg("valere", dict({"balance": bal,
                                                "scale_ref": 230.0}, **over))
            f = H.simulate(R, SPREAD, cfg)
            h1 = H.simulate(R[:mid], SPREAD, cfg)
            h2 = H.simulate(R[mid:], SPREAD, cfg)
            if base is None:
                base = (f["net"], h1["net"], h2["net"])
                d = ""
            else:
                def pc(a, b):
                    return f"{(a-b)/abs(b)*100:+6.1f}%" if b else "      -"
                d = (f"  vs main: {pc(f['net'], base[0])}"
                     f" | h1 {pc(h1['net'], base[1])}"
                     f" | h2 {pc(h2['net'], base[2])}")
            print(f"  {tag:<28} full {f['net']:+8.2f}  h1 {h1['net']:+8.2f}"
                  f"  h2 {h2['net']:+8.2f}  int {f.get('internal', 0):4d}"
                  f"  tr {f['trades']:4d}  DD {f['worst_debt']:6.2f}{d}")
            rows[tag] = {k: v for k, v in f.items()
                         if k not in ("curve", "pnls")}
            rows[tag]["h1_net"] = h1["net"]
            rows[tag]["h2_net"] = h2["net"]
        out["accounts"][name] = rows

    with open(os.path.join(HERE, "internal_widestop.json"), "w") as f:
        json.dump(out, f, indent=1)
    print("")
    print("written: review/internal_widestop.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
