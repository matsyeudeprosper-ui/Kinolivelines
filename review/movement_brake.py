"""Does the movement brake still earn its place?

The brake: no entry unless the market made at least one big move in the last
two hours (`moves_2h >= 1`). It has been on since before this harness could
switch it off, so it has never actually been measured on this engine - it
was hard-coded into the simulation, which means every backtest ever run here
ASSUMED it was right.

That changed yesterday when `movement` became a dial. The owner asked
whether the indicator still holds after the harness work. This answers it.

PRE-REGISTERED, written before the numbers were read:
  - compare brake ON (today's live rule) against brake OFF.
  - both of the house reference shapes, because an account with a daily cap
    and one without are different animals.
  - full period and both halves. A brake that only pays in one half is a
    coincidence.
  - the brake STAYS unless turning it off is better on both references AND
    in both halves. A brake that blocks trades has to prove it is worth the
    trades it costs; the burden is on removing it, not on keeping it.
  - no second cut, no tuning of the threshold. One question.

Run:  python review/movement_brake.py
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
REFS = [("base", {}), ("valere", {"balance": 252.0})]
ACCTS = [("Valere", 270.75), ("Depenses", 200.00)]


def row(tag, v, base=None):
    f, h1, h2 = v["full"], v["h1"], v["h2"]
    d = ""
    if base:
        def pc(a, b):
            return f"{(a-b)/abs(b)*100:+6.1f}%" if b else "      -"
        d = (f"   vs ON: full {pc(f['net'], base['full']['net'])}"
             f"  h1 {pc(h1['net'], base['h1']['net'])}"
             f"  h2 {pc(h2['net'], base['h2']['net'])}")
    print(f"  {tag:<14} full {f['net']:+8.2f}  h1 {h1['net']:+8.2f}"
          f"  h2 {h2['net']:+8.2f}  trades {f['trades']:4d}"
          f"  DD {f['worst_debt']:6.2f}{d}")


def main():
    print("loading bars...")
    sym, R = H.bars_long()
    if R is None or not len(R):
        print("no bars from MT5 - is a terminal running?")
        return 2
    print(f"{sym}: {len(R)} M1 bars, engine {H.ENGINE}")
    out = {"engine": H.ENGINE, "bars": len(R), "runs": {}}
    better = []

    for label, over in REFS + [(n, {"balance": b, "scale_ref": 230.0})
                               for n, b in ACCTS]:
        pkg = label if label in ("base", "valere") else "valere"
        print("")
        print(f"=== {label} ===")
        on = H.run_cfg(R, SPREAD, H.package_cfg(pkg, dict(over)))
        off = H.run_cfg(R, SPREAD, H.package_cfg(pkg, dict(over, movement=0)))
        row("brake ON", on)
        row("brake OFF", off, on)
        out["runs"][label] = {
            "on": {k: on[k]["net"] for k in ("full", "h1", "h2")},
            "off": {k: off[k]["net"] for k in ("full", "h1", "h2")},
            "on_trades": on["full"]["trades"],
            "off_trades": off["full"]["trades"],
            "on_dd": on["full"]["worst_debt"],
            "off_dd": off["full"]["worst_debt"]}
        wins = all(off[k]["net"] > on[k]["net"] for k in ("full", "h1", "h2"))
        better.append(wins)

    print("")
    print("Removing the brake is better on every split, everywhere:",
          "YES" if all(better) else "no")
    print("")
    if all(better):
        print("VERDICT: the brake costs money on every shape and both halves.")
        print("That is a real result and worth acting on.")
    else:
        print("VERDICT: the brake STAYS. Turning it off does not beat it on")
        print("every reference and both halves, which is the bar a brake has")
        print("to clear before it is removed.")
    json.dump(out, open(os.path.join(HERE, "movement_brake.json"), "w"),
              indent=1)
    print("written: review/movement_brake.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
