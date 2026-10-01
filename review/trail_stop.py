"""Does moving the stop to each new protected level make the losses small?

THE OWNER'S WORDS, 2026-10-01:
  "The SL on Valere currently for example is just too much, it's more than
   the daily profit of many days. So I want this, let's move the SL to the
   Next glowing protected level that Will come (if it comes)."

He is right about the complaint. Valere's 17 closed trades: 9 losses
averaging -$5.02 against 8 wins averaging +$3.45, and the worst single loss
was -$11.95 - about three wins. The question is what the cure costs.

WHAT IS BEING TESTED. The glowing dot is already the stop convention: the
bot enters with the stop exactly at the protected level, no buffer. So the
trail puts the stop where a fresh entry would put it, each time a new level
forms.
  variant 1  every new level, including ones past the entry, so the stop
             can carry the trade into profit
  variant 2  only once the level is past the entry - never protects early,
             never closes for less than the trade risked

WHAT IT CANNOT DO, and the owner should hear this plainly: it does nothing
about the stop at the MOMENT OF ENTRY. Until the market builds a new level
the first stop is the only stop, so the worst case on a trade that goes
straight against us is unchanged. The dollar size of that worst case is
already governed by risk_fit (shrink the lot to a share of the balance),
which is a separate, already-measured control.

PRE-REGISTERED - written before any number was read.

  Measures. The owner's complaint is the SIZE OF A LOSS, so:
    primary    the worst single losing trade, and the average loss
    constraint net, because smaller losses bought by losing the profit is
               not a cure
    reported   how many trades the level actually came for - a trail that
               fires on 5% of trades cannot matter either way

  References: base and valere (an account with a daily cap and one without
  are different animals), plus the two live account shapes.
  Periods: full, first half, second half. A result in one half is weather.
  Views: the synthetic engine AND the bot's real entries.

  Verdict, decided in advance:
    ADOPT    on both references and in both halves: the worst loss shrinks
             by 25% or more AND net is within 5% of leaving it alone.
    A PRICE  the worst loss shrinks by 25% or more everywhere, but net
             costs between 5% and 25%. Then it is not my call: it is the
             owner choosing calmer losses over some expectancy, and I
             report the exchange rate and let him decide.
    REJECT   net costs more than 25% in either half or either reference,
             or the worst loss does not shrink.

  No tuning after the fact. Two variants, both named here, and if one lands
  in A PRICE I do not go looking for a third.

Run:  python review/trail_stop.py
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
VARIANTS = [(1, "every new level"), (2, "only past the entry")]

SHRINK = 25.0      # % the worst loss must shrink by
FREE = 5.0         # % of net it may cost and still be free
PRICEY = 25.0      # % of net above which it is rejected


def losses(v):
    """worst single loss and average loss, in money."""
    neg = [p for p in v["pnls"] if p < 0]
    if not neg:
        return 0.0, 0.0, 0
    return min(neg), sum(neg) / len(neg), len(neg)


def pc(a, b):
    return ((a - b) / abs(b) * 100.0) if b else 0.0


def row(tag, v, base=None):
    w, avg, n = losses(v)
    bw = bavg = None
    if base:
        bw, bavg, _ = losses(base)
    print(f"  {tag:<22} net {v['net']:+8.2f}  worst loss {w:+7.2f}"
          f"{'' if bw is None else f' ({pc(abs(w), abs(bw)):+6.1f}%)'}"
          f"  avg loss {avg:+6.2f}"
          f"{'' if bavg is None else f' ({pc(abs(avg), abs(bavg)):+6.1f}%)'}"
          f"  trades {v['trades']:4d}  DD {v['worst_debt']:6.2f}")
    if v.get("trailed"):
        print(f"  {'':<22} the level came for {v['trailed']} of "
              f"{v['trades']} trades; {v['trail_exits']} were closed by the "
              f"moved stop, worth {v['trail_gain_pts']:+.0f} pts in total")


def main():
    print(__doc__.split("Run:")[0].strip()[:0] or "", end="")
    print("loading bars...")
    sym, R = H.bars_long()
    if R is None or not len(R):
        print("no bars from MT5 - is a terminal running?")
        return 2
    print(f"{sym}: {len(R)} M1 bars, engine {H.ENGINE}")
    T = H.real_entries()
    print(f"real entries loaded: {len(T) if T else 0}")

    out = {"engine": H.ENGINE, "bars": len(R), "runs": {}}
    fired = 0
    tally = {}

    for label, over in REFS + [(n, {"balance": b, "scale_ref": 230.0})
                               for n, b in ACCTS]:
        pkg = label if label in ("base", "valere") else "valere"
        print("")
        print(f"=== {label} ===")
        off = H.run_cfg(R, SPREAD, H.package_cfg(pkg, dict(over)))
        print("  -- full period --")
        row("stop never moves", off["full"])
        res = {"off": off}
        for tv, tname in VARIANTS:
            o = dict(over)
            o["trail_prot"] = tv
            v = H.run_cfg(R, SPREAD, H.package_cfg(pkg, o))
            row(f"trail {tv}: {tname}", v["full"], off["full"])
            fired += v["full"].get("trailed", 0)
            res[f"trail{tv}"] = v
        for part, pname in (("h1", "first half"), ("h2", "second half")):
            print(f"  -- {pname} --")
            row("stop never moves", off[part])
            for tv, tname in VARIANTS:
                row(f"trail {tv}", res[f"trail{tv}"][part], off[part])
        if T:
            print("  -- the bot's real entries --")
            r0 = H.simulate_real(T, R, SPREAD, H.package_cfg(pkg, dict(over)))
            print(f"  {'stop never moves':<22} net {r0['net']:+8.2f}"
                  f"  trades {r0['trades']:4d}")
            for tv, tname in VARIANTS:
                o = dict(over)
                o["trail_prot"] = tv
                rv = H.simulate_real(T, R, SPREAD, H.package_cfg(pkg, o))
                print(f"  {'trail ' + str(tv):<22} net {rv['net']:+8.2f}"
                      f"  trades {rv['trades']:4d}"
                      f"  ({pc(rv['net'], r0['net']):+6.1f}%)")
                res[f"trail{tv}"]["real"] = rv
            res["off"]["real"] = r0
        out["runs"][label] = {
            k: {p: {kk: vv for kk, vv in val.items() if kk != "curve"}
                for p, val in v.items()} for k, v in res.items()}
        if label in ("base", "valere"):
            tally[label] = res

    # ---- the verdict, by the rule written above --------------------------
    print("")
    if not fired:
        print("THE TRAIL NEVER FIRED. That is not a result, it is dead code -")
        print("no verdict. Fix the wiring before reading anything above.")
        out["verdict"] = "DEAD"
    else:
        for tv, tname in VARIANTS:
            ok_shrink = True
            worst_cost = 0.0
            for label in ("base", "valere"):
                for part in ("full", "h1", "h2"):
                    b = tally[label]["off"][part]
                    v = tally[label][f"trail{tv}"][part]
                    bw, _, _ = losses(b)
                    vw, _, _ = losses(v)
                    if not (bw and pc(abs(vw), abs(bw)) <= -SHRINK):
                        ok_shrink = False
                    worst_cost = min(worst_cost, pc(v["net"], b["net"]))
            if not ok_shrink:
                verdict = "REJECT - the losses do not get smaller everywhere"
            elif worst_cost < -PRICEY:
                verdict = (f"REJECT - it costs up to {-worst_cost:.0f}% of "
                           f"net, over the {PRICEY:.0f}% line")
            elif worst_cost < -FREE:
                verdict = (f"A PRICE - smaller losses for up to "
                           f"{-worst_cost:.0f}% of net. The owner decides.")
            else:
                verdict = "ADOPT - smaller losses, net within the free band"
            print(f"trail {tv} ({tname}): {verdict}")
            out.setdefault("verdict", {})[f"trail{tv}"] = verdict

    with open(os.path.join(HERE, "trail_stop.json"), "w",
              encoding="utf-8") as f:
        json.dump(out, f, indent=1)
    print("")
    print("written: review/trail_stop.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
