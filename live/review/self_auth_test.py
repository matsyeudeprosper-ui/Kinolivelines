"""How often does a signal authorise ITSELF through the movement gate?

Owner-visible symptom 2026-09-22 13:59: the three bots refused a flip
("aucun grand mouvement depuis 2 h") and the 441 desk took it 3.5 s later,
because by then the feed had published the flip's OWN break and moves_2h
had gone 0 -> 1.

  live feed   sum(1 for m in marks if m[0] >= now - 7200)   INCLUSIVE of now
  replay      bisect(marks,t) - bisect(marks,t-7200)        EXCLUSIVE of t

So the rule that was measured (12/12 anchors, +0.033 R/trade) is the
STRICT one, and the bots are running the permissive one. This counts the
signals where the two disagree: the break is the only movement in 2 h, so
it passes the gate only by counting itself.

    python review/self_auth_test.py
"""
import bisect
import json
import os
import sys

LIVE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, LIVE)

import MetaTrader5 as mt5              # noqa: E402
import owl_chart_feed as F             # noqa: E402


def main():
    u = next(x for x in json.load(open(os.path.join(
        LIVE, "owl_nest_users.json"), encoding="utf-8")) if x["id"] == "std")
    assert mt5.initialize(path=u["terminal"]), mt5.last_error()
    sym = "BTCUSD" if mt5.symbol_info("BTCUSD") else "BTCUSDm"
    R = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_M1, 0, 60000)
    mt5.shutdown()
    kept = F.build(R)
    marks = sorted(m[0] for m in F.engine(kept)[1])
    print(f"\n  {sym}  {len(R)/1440:.1f} days  {len(marks)} confirmed breaks\n")

    strict_pass = loose_pass = self_auth = 0
    for t in marks:
        lo = bisect.bisect_left(marks, t - 7200)
        strict = bisect.bisect_left(marks, t) - lo      # [t-7200, t)
        loose = bisect.bisect_right(marks, t) - lo      # [t-7200, t]
        if strict >= 1:
            strict_pass += 1
        if loose >= 1:
            loose_pass += 1
        if strict < 1 <= loose:
            self_auth += 1
    n = len(marks)
    print(f"  gate passes, STRICT  (measured rule) {strict_pass:>4}  "
          f"{100*strict_pass/n:5.1f}%")
    print(f"  gate passes, LIVE    (feed today)    {loose_pass:>4}  "
          f"{100*loose_pass/n:5.1f}%")
    print(f"  SELF-AUTHORISING - the break is the only movement in 2 h:"
          f"  {self_auth}  ({100*self_auth/n:.1f}% of all breaks)")
    print(f"\n  Those {self_auth} signals pass the live gate ONLY because the")
    print("  break counts itself. Whether an account actually takes one")
    print("  depends on whether its poll lands before or after the feed")
    print("  update - which is why 441 traded and the three bots did not.\n")


if __name__ == "__main__":
    main()
