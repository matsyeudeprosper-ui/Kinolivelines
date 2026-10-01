"""E028 - a storm arrives while the trade is open. Cut, or let it run?

THE OWNER'S QUESTION, 2026-10-01: "When I'm in a trade, entered during
calm meteo, then while still in the trade the tres agite meteo arrives
when the bot is not supposed to be trading - what is your best
recommendation: we cut off the trade at the next positive pnl whatever it
is, or we let the trade just complete normally to its SL or TP?"

WHAT THE BOT DOES TODAY: nothing. Nervosity gates ENTRIES only -
weather_gate() is called from enter() and nowhere else - so an open trade
runs to its target or its stop whatever the weather does. Every storm
study on the shelf (post_storm, skip_post_storm, storm_gate,
storm_during_recovery, storm_hedge) is about whether to OPEN. None of them
asks this. So "let it run" is not a considered choice, it is the default
nobody has tested.

"Tres agite" is nervosity >= 1.85 (NERV_STORM), where nervosity is the
31st of the last 60 candle ranges over the 721st of the last 1440 - the
top band on the weather card.

PRE-REGISTERED, written before any number was read.

  Three arms:
    RUN     today's behaviour - the trade goes to SL or TP.
    GREEN   the owner's suggestion - once nervosity >= 1.85, leave at the
            first close that is not negative after costs.
    OUT     leave at the first close after the storm arrives, whatever the
            P&L. This is the CONTROL, and it is why the study can answer
            the question rather than flatter it: if GREEN wins and OUT
            wins too, then the gain is "getting out of storms" and has
            nothing to do with waiting for green. If GREEN wins and OUT
            loses, waiting for green is doing real work.

  Both reference shapes (base, valere), full period and both halves.
  Reported first, because it decides whether the question matters at all:
  HOW OFTEN a storm actually arrives mid-trade.

  Verdict:
    CHANGE IT   the arm beats RUN on both references AND in both halves,
                and beats its own control.
    LEAVE IT    anything else. The burden is on the change: RUN is what
                is deployed, and a rule that only pays in one half or on
                one reference is weather, not an edge.

  A storm exit is scored a win when it banks money, because that is what
  the live bot does - it reads the closed deal's profit, it does not ask
  whether a target was touched.

  No tuning. The 1.85 floor is the deployed one and the only one tested;
  no "what if we used 1.6" afterwards.

Run:  python review/storm_mid_trade.py
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
ARMS = [(0, "RUN   (today)"), (1, "GREEN (next >= 0)"), (2, "OUT   (control)")]


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
    hits = 0
    tally = {}

    for label, over in REFS:
        print("")
        print(f"=== {label} ===")
        res = {}
        for arm, name in ARMS:
            o = dict(over)
            o["storm_exit"] = arm
            v = H.run_cfg(R, SPREAD, H.package_cfg(label, o))
            res[arm] = v
            f = v["full"]
            hits += f.get("storm_exits", 0)
            b = res[0]["full"]
            print(f"  {name:<18} net {f['net']:+8.2f}  h1 {v['h1']['net']:+8.2f}"
                  f"  h2 {v['h2']['net']:+8.2f}  trades {f['trades']:4d}"
                  f"  wr {f['wr']:4.1f}%  DD {f['worst_debt']:6.2f}"
                  + ("" if arm == 0 else
                     f"   vs RUN {pc(f['net'], b['net'])}"))
            if arm:
                print(f"  {'':<18} storm exits: full {f.get('storm_exits',0)}"
                      f"  h1 {v['h1'].get('storm_exits',0)}"
                      f"  h2 {v['h2'].get('storm_exits',0)}"
                      f"  ({f.get('storm_exits',0)/max(1,f['trades'])*100:.0f}%"
                      f" of trades)")
        tally[label] = res
        out["runs"][label] = {
            str(a): {p: {k: val for k, val in vv.items() if k != "curve"}
                     for p, vv in v.items()} for a, v in res.items()}

    print("")
    print("=" * 70)
    if not hits:
        print("A STORM NEVER ARRIVED MID-TRADE in this window, on either")
        print("reference. The question is real but this data cannot answer")
        print("it - and the rule would never have fired. LEAVE IT.")
        out["verdict"] = "NO SAMPLE - never fired"
    else:
        for arm, name in ARMS[1:]:
            betters = []
            for label in ("base", "valere"):
                b, v = tally[label][0], tally[label][arm]
                ctl = tally[label][2]
                betters.append(all(v[p]["net"] > b[p]["net"]
                                   for p in ("full", "h1", "h2")))
                if arm == 1:
                    betters[-1] = betters[-1] and v["full"]["net"] > ctl["full"]["net"]
            if all(betters):
                print(f"{name.strip()}: CHANGE IT - better on both references,"
                      " both halves, and past its control.")
                out.setdefault("verdict", {})[str(arm)] = "CHANGE IT"
            else:
                print(f"{name.strip()}: LEAVE IT - does not clear the bar"
                      " written before the run.")
                out.setdefault("verdict", {})[str(arm)] = "LEAVE IT"
    print("=" * 70)

    with open(os.path.join(HERE, "storm_mid_trade.json"), "w",
              encoding="utf-8") as f:
        json.dump(out, f, indent=1)
    print("written: review/storm_mid_trade.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
