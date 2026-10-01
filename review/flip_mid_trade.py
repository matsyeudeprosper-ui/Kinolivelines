"""E029 - the trend flips against an open trade. Hold, close, or reverse?

THE OWNER'S QUESTION, 2026-10-01: "What if the trend changes mid trade?
For example I'm in a buy trade taking long to hit tp and then before it
hits tp it's flipped trend and now makes the first BOS on the opposite
direction?"

CAN THAT EVEN HAPPEN with the stop intact? Yes, and it is worth seeing
why. The protected level RATCHETS UP on every continuation break, so the
level whose breach confirms a bearish CHoCH can sit well ABOVE the stop
the long was born with. Price closes below the latest protected low, the
CHoCH confirms, the first bearish BOS follows - and the original stop is
still sitting there untouched below all of it. So the trade is alive and
the structure now points the other way.

WHAT THE BOT DOES TODAY, twice by omission. One line -
`if sig is None or pos: continue` - drops ANY signal that arrives while a
position is open. So the bot (a) keeps the now-wrong-way trade to its
target or stop, and (b) misses the new flip entry entirely. Neither was a
decision; both are the same missing branch.

PRE-REGISTERED, written before any number was read.

  Three arms:
    HOLD     today's behaviour - ride it out to SL or TP, skip the signal.
    CLOSE    close the trade when the opposing flip BOS confirms, then
             stand aside.
    REVERSE  close it and take the reversal, which is what a person
             watching the chart would do.

  REVERSE must be judged against CLOSE, not only against HOLD. If both
  beat HOLD by the same amount then the value is in GETTING OUT and the
  reversal adds nothing - that is a different and much cheaper change.

  Both reference shapes (base, valere), full period and both halves.
  Reported first, because it decides whether the question matters: HOW
  OFTEN the trend actually flips against an open trade.

  Verdict:
    CHANGE IT   the arm beats HOLD on both references AND in both halves;
                and for REVERSE, also beats CLOSE on both references.
    LEAVE IT    anything else. HOLD is deployed, so the burden is on the
                change, and a rule that pays in one half only is weather.

  A flip exit is scored a win when it banks money - that is what the live
  bot does, it reads the closed deal's profit.

  No tuning: the flip is the engine's own flip-confirming BOS, no
  threshold, no "only when the trade is losing" variant added afterwards.

Run:  python review/flip_mid_trade.py
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
ARMS = [(0, "HOLD    (today)"), (1, "CLOSE   (stand aside)"),
        (2, "REVERSE (take it)")]


def pc(a, b):
    return f"{(a-b)/abs(b)*100:+6.1f}%" if b else "      -"


def main():
    print("loading bars...")
    sym, R = H.bars_long()
    if R is None or not len(R):
        print("no bars from MT5 - is a terminal running?")
        return 2
    print(f"{sym}: {len(R)} M1 bars, engine {H.ENGINE}")
    out = {"engine": H.ENGINE, "bars": len(R), "runs": {}}
    fired = 0
    tally = {}

    for label, over in REFS:
        print("")
        print(f"=== {label} ===")
        res = {}
        for arm, name in ARMS:
            o = dict(over)
            o["flip_exit"] = arm
            v = H.run_cfg(R, SPREAD, H.package_cfg(label, o))
            res[arm] = v
            f, b = v["full"], res[0]["full"]
            fired += f.get("flip_exits", 0)
            print(f"  {name:<22} net {f['net']:+8.2f}"
                  f"  h1 {v['h1']['net']:+8.2f}  h2 {v['h2']['net']:+8.2f}"
                  f"  trades {f['trades']:4d}  wr {f['wr']:4.1f}%"
                  f"  DD {f['worst_debt']:6.2f}"
                  + ("" if arm == 0 else
                     f"   vs HOLD {pc(f['net'], b['net'])}"))
            if arm:
                print(f"  {'':<22} flips against an open trade: full"
                      f" {f.get('flip_exits',0)}"
                      f"  h1 {v['h1'].get('flip_exits',0)}"
                      f"  h2 {v['h2'].get('flip_exits',0)}"
                      f"  ({f.get('flip_exits',0)/max(1,f['trades'])*100:.0f}%"
                      f" of trades)")
        tally[label] = res
        out["runs"][label] = {
            str(a): {p: {k: val for k, val in vv.items() if k != "curve"}
                     for p, vv in v.items()} for a, v in res.items()}

    print("")
    print("=" * 70)
    if not fired:
        print("THE TREND NEVER FLIPPED AGAINST AN OPEN TRADE in this window.")
        print("The question is real but this data cannot answer it, and the")
        print("rule would never have fired. LEAVE IT.")
        out["verdict"] = "NO SAMPLE - never fired"
    else:
        out["verdict"] = {}
        for arm, name in ARMS[1:]:
            ok = []
            for label in ("base", "valere"):
                b, v, cl = tally[label][0], tally[label][arm], tally[label][1]
                good = all(v[p]["net"] > b[p]["net"]
                           for p in ("full", "h1", "h2"))
                if arm == 2:
                    good = good and v["full"]["net"] > cl["full"]["net"]
                ok.append(good)
            if all(ok):
                print(f"{name.split('(')[0].strip()}: CHANGE IT - better on"
                      " both references and both halves"
                      + (", and past CLOSE." if arm == 2 else "."))
                out["verdict"][str(arm)] = "CHANGE IT"
            else:
                print(f"{name.split('(')[0].strip()}: LEAVE IT - does not"
                      " clear the bar written before the run.")
                out["verdict"][str(arm)] = "LEAVE IT"
    print("=" * 70)

    with open(os.path.join(HERE, "flip_mid_trade.json"), "w",
              encoding="utf-8") as f:
        json.dump(out, f, indent=1)
    print("written: review/flip_mid_trade.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
