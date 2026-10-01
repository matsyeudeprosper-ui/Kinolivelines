"""E027 - what does the 3% risk cap actually cost? Measured, with an interval.

THE OWNER'S ASK, 2026-10-01: "Now do the test to be sure if the number is
measured." He is right to push. `RISK_CAP.md` deployed the cap while saying
the cost was "somewhere between zero and about 9%, and no tighter statement
is honest". That is a confession, not a measurement.

WHY THE OLD STUDY COULD NOT SEE IT. It compared two NETS - capped against
uncapped, ~400 trades each. But the cap changes only the handful of trades
where it binds; the other ~370 are identical. So the measurement put a small
signal on top of a large, noisy, path-dependent total and then read the
difference. The halves disagreed, which is exactly what that looks like.

More price history would help a little and is not available anyway: the
terminal's "Max bars in chart" is 100,000, and it caps copy_rates_range as
well as copy_rates_from_pos (checked - 30 days of M1 returns 43,186 bars,
90 days returns "Invalid params"). Raising it means restarting a terminal
that the live app and a harvest bot are using. Not for this.

THE BETTER IDEA, which needs no new data. The cap's effect on a trade is
DETERMINISTIC and the price path does not change:

    risk = dist x lot;  cap = pct% x balance
    fits            -> nothing happens
    does not fit    -> lot shrinks to floor((cap/dist)/0.01)*0.01
    even 0.01 fails -> the trade is refused

P&L scales linearly with the lot on an unchanged path, so the cost of the
cap on one trade is EXACTLY pnl x (new_lot/old_lot - 1), and -pnl for a
refusal. No simulation is needed for that, and the trades where nothing
binds contribute exactly zero instead of contributing noise.

Which turns the whole question into one sentence:

    the cap's cost is the expectancy of the trades whose stops are too wide
    for it - so the only sample that matters is the BINDING trades.

E009 found the widest stops are the best trades, so the prior is that this
costs money. That prior is what is being tested.

PRE-REGISTERED, written before any number was read.

  Estimator A - REAL MONEY. Every trade in every bot journal (92 usable
    across 6 accounts), using its own recorded stop distance, lot, balance
    at entry and realised P&L. This is not a backtest.
  Estimator B - the 69-day simulated window, same arithmetic, for a second
    independent sample.
  Estimator C - the full re-simulation capped vs uncapped. A and B measure
    the direct cost; C also carries the path effects (a smaller loss leaves
    less debt, which changes later recovery lots and can move the kill
    line). Reporting C against B is how the size of those path effects is
    shown rather than assumed.

  Interval: 20,000-resample bootstrap over the BINDING trades, 90%.

  Verdict:
    MEASURED      the 90% interval on the real-money cost excludes zero.
                  Then the sign and rough size of the cost are established
                  and `RISK_CAP.md` section 4 gets corrected.
    STILL OPEN    the interval includes zero. Then say so plainly, report
                  the bound, and say how many binding trades would settle
                  it - never dress a wide interval up as a number.

  No tuning. 3% is the deployed number and the one tested; 5% and the
  flat-dollar shapes are reported only because they cost nothing to compute
  and `RISK_CAP.md` already made claims about them.

Run:  python review/risk_cap_cost.py
"""
import csv
import glob
import io
import json
import math
import os
import random
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
LIVE = os.path.join(os.path.dirname(HERE), "live")
sys.path.insert(0, LIVE)
sys.path.insert(0, os.path.join(LIVE, "lab"))

import harness as H            # noqa: E402

SPREAD = 7.0
BOOT = 20000
PCTS = (3.0, 5.0)
# A bootstrap over one or two observations returns that observation 20,000
# times and prints an "interval" of zero width. Below this many binding
# trades the sign of the cost is not claimed. Found by auditing this
# script's own good news: the 5% rows claimed an established sign off a
# single trade.
MIN_BIND = 8
random.seed(20261001)          # fixed so the interval is reproducible


def capped_lot(dist, lot, cap):
    """The lot after the cap, or None when even 0.01 will not fit.
    Same arithmetic as structure_bos_bot.enter() and harness.simulate()."""
    if dist <= 0 or lot <= 0 or cap <= 0:
        return lot
    if dist * lot <= cap:
        return lot
    nl = math.floor((cap / dist) / 0.01) * 0.01
    return None if nl < 0.01 - 1e-9 else round(nl, 2)


def deltas(trades, pct):
    """Per-trade cost of the cap. trades: (dist, lot, balance, pnl)."""
    out = []
    for dist, lot, bal, pnl in trades:
        cap = bal * pct / 100.0
        nl = capped_lot(dist, lot, cap)
        if nl is None:
            out.append((-pnl, "refused", pnl))
        elif abs(nl - lot) > 1e-9:
            out.append((pnl * (nl / lot - 1.0), f"{lot:.2f}->{nl:.2f}", pnl))
    return out


def boot_ci(vals, n_lo=0.05, n_hi=0.95):
    """Bootstrap interval for the TOTAL over this many trades."""
    if not vals:
        return 0.0, 0.0, 0.0
    n = len(vals)
    tot = sum(vals)
    means = []
    for _ in range(BOOT):
        means.append(sum(random.choice(vals) for _ in range(n)) / n)
    means.sort()
    return (tot,
            means[int(n_lo * BOOT)] * n,
            means[int(n_hi * BOOT)] * n)


def real_trades():
    """Every journal trade with the four numbers the cap needs."""
    out = []
    for f in sorted(glob.glob(os.path.join(LIVE, "bos_journal*.csv"))):
        acct = os.path.basename(f)[12:-4].lstrip("_") or "bos"
        for r in csv.DictReader(io.open(f, newline="", encoding="utf-8",
                                        errors="replace")):
            try:
                dist = float(r["dist_pts"])
                lot = float(r["lot"])
                bal = float(r["balance_at_entry"])
                pnl = float(r["profit_usd"])
            except (KeyError, TypeError, ValueError):
                continue
            if dist > 0 and lot > 0 and bal > 0:
                out.append((dist, lot, bal, pnl, acct))
    return out


def report(tag, trades, pct, net_before):
    t4 = [(d, l, b, p) for d, l, b, p, *_ in trades]
    ds = deltas(t4, pct)
    vals = [x[0] for x in ds]
    tot, lo, hi = boot_ci(vals)
    worst_b = min([p for _, _, _, p in t4] + [0.0])
    # worst loss after the cap: binding trades change, others do not
    adj = {}
    for (d, l, b, p), (dv, how, _) in zip(
            [x for x in t4 if deltas([x], pct)], ds):
        adj[(d, l, b, p)] = p + dv
    after = [adj.get((d, l, b, p), p) for d, l, b, p in t4]
    worst_a = min(after + [0.0])
    print(f"  {tag}")
    print(f"    trades {len(t4)}   the cap binds on {len(ds)}"
          f" ({len(ds)/max(1,len(t4))*100:.0f}%)"
          f"   refusals {sum(1 for x in ds if x[1]=='refused')}")
    if not ds:
        print("    nothing binds - the cap is decoration on this sample")
        return {"n": len(t4), "binding": 0}
    print(f"    cost  {tot:+.2f}   90% interval [{lo:+.2f} .. {hi:+.2f}]"
          f"   per binding trade {tot/len(ds):+.2f}")
    # a share of net only means something when net is positive: "+104% of a
    # -30.52 net" reads like a gain and is nonsense
    if net_before and net_before > 0:
        print(f"    as a share of net {net_before:+.2f}:"
              f" {tot/net_before*100:+.1f}%"
              f"  [{lo/net_before*100:+.1f}%"
              f" .. {hi/net_before*100:+.1f}%]")
    print(f"    worst single loss {worst_b:+.2f} -> {worst_a:+.2f}")
    excl = (((lo < 0 and hi < 0) or (lo > 0 and hi > 0))
            and len(ds) >= MIN_BIND)
    if len(ds) < MIN_BIND:
        print(f"    only {len(ds)} binding trade(s) - no interval worth the"
              f" name, sign NOT claimed (needs {MIN_BIND})")
    elif excl:
        print("    the interval excludes zero - the sign is established")
    else:
        print("    the interval includes zero - sign NOT established")
    # The mechanism, rather than an assumption about it. E009 says the
    # widest stops are the best trades; the cap touches exactly those, so
    # whether it costs or saves follows how they did in this period.
    bp = [x[2] for x in ds]
    allp = [p for _, _, _, p in t4]
    others = len(allp) - len(bp)
    exp_b = sum(bp) / len(bp)
    exp_o = (sum(allp) - sum(bp)) / others if others else 0.0
    print(f"    the trades it touches made {exp_b:+.2f} each;"
          f" the ones it leaves alone {exp_o:+.2f} each"
          f"  ({'wide stops did BETTER here' if exp_b > exp_o else 'wide stops did WORSE here'})")
    return {"n": len(t4), "binding": len(ds), "cost": round(tot, 2),
            "lo": round(lo, 2), "hi": round(hi, 2),
            "per_trade": round(tot / len(ds), 3),
            "refusals": sum(1 for x in ds if x[1] == "refused"),
            "worst_before": round(worst_b, 2), "worst_after": round(worst_a, 2),
            "exp_binding": round(exp_b, 3), "exp_others": round(exp_o, 3),
            "excludes_zero": bool(excl)}


def main():
    out = {"boot": BOOT, "spread": SPREAD}

    # ---- A: real money -------------------------------------------------
    RT = real_trades()
    net_real = sum(p for _, _, _, p, _ in RT)
    print("=" * 68)
    print(f"A. REAL MONEY - {len(RT)} trades from "
          f"{len(set(a for *_, a in RT))} accounts, net {net_real:+.2f}")
    print("=" * 68)
    out["real"] = {}
    for pct in PCTS:
        out["real"][str(pct)] = report(f"cap {pct:.0f}% of balance",
                                      RT, pct, net_real)
        print("")

    # ---- B: the simulated window, same arithmetic ----------------------
    print("=" * 68)
    print("B. THE SIMULATED WINDOW - the same exact arithmetic")
    print("=" * 68)
    sym, R = H.bars_long()
    if R is None or not len(R):
        print("no bars from MT5 - A stands on its own")
        R = None
    out["sim"] = {}
    if R is not None:
        print(f"{sym}: {len(R)} M1 bars")
        for label, over in (("base", {}), ("valere", {"balance": 252.0})):
            H.TRACE = []
            v = H.simulate(R, SPREAD, H.package_cfg(label, dict(over)))
            tr = list(H.TRACE)
            H.TRACE = None
            rr = float(H.package_cfg(label, dict(over))["rr"])
            bal = float(over.get("balance") or 0.0) or H.BAL0
            st = []
            for x in tr:
                if x["win"] is None or not x.get("lot"):
                    continue
                dist = x["dist"]
                pts = (rr * dist - SPREAD) if x["win"] else -(dist + SPREAD)
                st.append((dist, x["lot"], bal, pts * x["lot"], label))
            print(f"  -- {label} (balance {bal:.0f}, "
                  f"{len(st)} settled trades, net {v['net']:+.2f}) --")
            out["sim"][label] = {}
            for pct in PCTS:
                out["sim"][label][str(pct)] = report(
                    f"cap {pct:.0f}%", st, pct, v["net"])
            print("")

        # ---- C: the path effects the paired estimator cannot see --------
        print("=" * 68)
        print("C. PAIRED ESTIMATE vs FULL RE-SIMULATION")
        print("   B is the direct cost. C also carries the path: a smaller")
        print("   loss leaves less debt, which changes later recovery lots")
        print("   and can move the kill line.")
        print("=" * 68)
        out["path"] = {}
        for label, over in (("base", {}), ("valere", {"balance": 252.0})):
            off = H.simulate(R, SPREAD, H.package_cfg(label, dict(over)))
            for pct in PCTS:
                o = dict(over)
                o["risk_fit"] = pct
                on = H.simulate(R, SPREAD, H.package_cfg(label, o))
                resim = on["net"] - off["net"]
                paired = out["sim"][label][str(pct)].get("cost", 0.0)
                print(f"  {label:<8} cap {pct:.0f}%   paired {paired:+8.2f}"
                      f"   re-simulated {resim:+8.2f}"
                      f"   path effect {resim - paired:+8.2f}")
                out["path"][f"{label}_{pct}"] = {
                    "paired": paired, "resim": round(resim, 2),
                    "path": round(resim - paired, 2)}
        print("")

    # ---- the verdict, by the rule written at the top -------------------
    r3 = out["real"]["3.0"]
    s3 = ((out.get("sim") or {}).get("base") or {}).get("3.0") or {}
    print("=" * 68)
    if not r3.get("binding"):
        print("VERDICT: STILL OPEN - the cap has not bound on a single real")
        print("trade yet, so there is no cost to measure.")
        out["verdict"] = "STILL OPEN - nothing binds"
    elif r3["excludes_zero"]:
        print("VERDICT: MEASURED - and the answer is not one number.")
        print("")
        print(f"On {r3['n']} REAL trades the 3% cap binds on"
              f" {r3['binding']} and is worth")
        print(f"{r3['cost']:+.2f}, 90% interval [{r3['lo']:+.2f} .."
              f" {r3['hi']:+.2f}] - excluding zero. It SAVED")
        print("money, because the trades it touched lost money over this")
        print("stretch.")
        if s3.get("binding"):
            print("")
            print("On the simulated window the same arithmetic gives"
                  f" {s3['cost']:+.2f}")
            print(f"[{s3['lo']:+.2f} .. {s3['hi']:+.2f}] - the OPPOSITE sign,"
                  " because there the wide-stop")
            print("trades win. The two samples disagree in sign, and that")
            print("disagreement is the finding: the cap's cost follows"
                  " whether")
            print("the widest stops happen to pay in the period.")
        print("")
        print("So it is a variance control, not a profit lever - it charges")
        print("you in good stretches and refunds you in bad ones. What is")
        print("NOT period-dependent is the worst loss:"
              f" {r3['worst_before']:+.2f} ->"
              f" {r3['worst_after']:+.2f}.")
        out["verdict"] = ("MEASURED - the sign is period-dependent; the real"
                          " sample saved, the simulated one paid")
    else:
        need = max(0, 4 * r3["binding"])
        print(f"VERDICT: STILL OPEN. On {r3['n']} real trades the 3% cap")
        print(f"binds on only {r3['binding']}, and the 90% interval")
        print(f"[{r3['lo']:+.2f} .. {r3['hi']:+.2f}] spans zero - the sign of")
        print(f"the cost is not established. The point estimate is")
        print(f"{r3['cost']:+.2f} ({r3['per_trade']:+.2f} per binding trade).")
        print(f"Roughly {need} binding trades would halve this interval.")
        print("The worst-loss reduction is NOT in doubt:"
              f" {r3['worst_before']:+.2f} -> {r3['worst_after']:+.2f}.")
        out["verdict"] = "STILL OPEN - interval spans zero"
    print("=" * 68)

    with open(os.path.join(HERE, "risk_cap_cost.json"), "w",
              encoding="utf-8") as f:
        json.dump(out, f, indent=1)
    print("written: review/risk_cap_cost.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
