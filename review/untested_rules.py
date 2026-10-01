"""The two rules nobody has ever tested.

The parity check reports three rules as "no dial, matches assumption". That
phrase is not reassurance - it means the harness silently assumes a value
and nobody has ever checked whether the assumption is the right one. The
movement brake was the third, and measuring it on 2026-10-01 found it worth
43-65% of net. These are the other two.

  debt_mode       the bot has "hwm" (debt is the distance below the peak)
                  and "half" (a ledger: a loss adds 0.5x itself, a win pays
                  it down). Every account runs hwm. The harness could not
                  express half at all until 2026-09-30, so the two have
                  never been compared on this engine.

  max_trades_day  a hard ceiling on entries per UTC day. Set to None on
                  every account, so the live answer is "no cap" and nobody
                  has ever asked whether a cap would help.

PRE-REGISTERED, written before any number was read:
  - four shapes: the two house references plus two real balances.
  - full period and BOTH halves.
  - debt_mode: hwm STAYS unless half beats it on every shape and in both
    halves. It is the deployed rule; the burden is on the challenger.
  - max_trades_day: a cap is only worth proposing if it beats no-cap on
    every shape and in both halves. A rule that refuses trades has to earn
    them back.
  - no tuning after the fact. These doses, this once.

Run:  python review/untested_rules.py
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
SHAPES = [("base", "base", {}),
          ("valere", "valere", {"balance": 252.0}),
          ("Valere", "valere", {"balance": 270.75, "scale_ref": 230.0}),
          ("Depenses", "valere", {"balance": 200.00, "scale_ref": 230.0})]


def show(tag, v, base=None):
    f, h1, h2 = v["full"], v["h1"], v["h2"]
    d = ""
    if base:
        def pc(a, b):
            return f"{(a-b)/abs(b)*100:+6.1f}%" if b else "      -"
        d = (f"   vs base: full {pc(f['net'], base['full']['net'])}"
             f"  h1 {pc(h1['net'], base['h1']['net'])}"
             f"  h2 {pc(h2['net'], base['h2']['net'])}")
    print(f"  {tag:<18} full {f['net']:+8.2f}  h1 {h1['net']:+8.2f}"
          f"  h2 {h2['net']:+8.2f}  tr {f['trades']:4d}"
          f"  DD {f['worst_debt']:6.2f}{d}")
    return v


def beats(cand, base):
    return all(cand[k]["net"] > base[k]["net"] for k in ("full", "h1", "h2"))


def main():
    print("loading bars...")
    sym, R = H.bars_long()
    if R is None or not len(R):
        print("no bars from MT5 - is a terminal running?")
        return 2
    print(f"{sym}: {len(R)} M1 bars, engine {H.ENGINE}")
    out = {"engine": H.ENGINE, "bars": len(R), "debt": {}, "cap": {}}
    half_wins, cap_wins = [], {2: [], 3: [], 5: []}

    for label, pkg, over in SHAPES:
        print("")
        print(f"=== {label} ===")
        base = show("hwm, no cap (live)",
                    H.run_cfg(R, SPREAD, H.package_cfg(pkg, dict(over))))
        half = show("debt_mode half",
                    H.run_cfg(R, SPREAD, H.package_cfg(
                        pkg, dict(over, debt_mode="half"))), base)
        half_wins.append(beats(half, base))
        out["debt"][label] = {
            "hwm": {k: base[k]["net"] for k in ("full", "h1", "h2")},
            "half": {k: half[k]["net"] for k in ("full", "h1", "h2")}}
        out["cap"][label] = {}
        for n in (2, 3, 5):
            c = show(f"max {n} trades/day",
                     H.run_cfg(R, SPREAD, H.package_cfg(
                         pkg, dict(over, max_trades_day=n))), base)
            cap_wins[n].append(beats(c, base))
            out["cap"][label][n] = {k: c[k]["net"] for k in ("full", "h1", "h2")}

    print("")
    print("debt_mode: does 'half' beat 'hwm' everywhere?",
          "YES" if all(half_wins) else "no")
    for n in (2, 3, 5):
        print(f"max {n} trades/day: beats no-cap everywhere?",
              "YES" if all(cap_wins[n]) else "no")
    print("")
    print("VERDICT")
    print("  debt_mode : " + ("half wins everywhere - worth proposing"
                              if all(half_wins) else
                              "hwm STAYS - half does not clear the bar"))
    any_cap = [n for n in (2, 3, 5) if all(cap_wins[n])]
    print("  trade cap : " + (f"doses {any_cap} clear the bar - worth proposing"
                              if any_cap else
                              "no cap STAYS - no dose clears the bar"))
    json.dump(out, open(os.path.join(HERE, "untested_rules.json"), "w"),
              indent=1)
    print("written: review/untested_rules.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
