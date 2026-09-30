"""Does a per-trade risk cap cost money, and which kind?

The owner's question: cap one trade's risk at about 12 USD, expressed as a
percentage so it follows the balance. The open decision was "paper twin
first or straight to demo". Both spend weeks of forward time. The harness
already holds 99k minutes of bars and each account's own deployed rules, so
the cheap answer comes first.

The thing worth testing is not the number, it is the MECHANISM:

  SKIP  refuse any trade whose risk exceeds the cap.
  FIT   keep the trade, shrink the lot until the risk fits, and only refuse
        when even 0.01 lot would exceed the cap.

E009 found the widest stops are the BEST trades, so SKIP is expected to
throw away the good ones. FIT should keep them and only cap the money. That
is the hypothesis this measures.

Reported for each: net, worst drawdown, trades, and the biggest single loss
- that last one is the number the owner actually wants smaller.

Run:  python review/risk_cap.py
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
# the real balances, so a percentage cap means what it will mean live
ACCOUNTS = [("Valere", 270.75), ("Dad 441", 378.29),
            ("Depenses", 200.00), ("Infinity", 175.99)]


def run(R, base_over):
    cfg = H.package_cfg("valere", base_over)
    H.TRACE = []
    res = H.simulate(R, SPREAD, cfg)
    tr = H.TRACE
    H.TRACE = None
    losses = [t["pnl"] for t in tr if t.get("pnl") is not None and t["pnl"] < 0]
    res["worst_trade"] = round(min(losses), 2) if losses else 0.0
    res["n_loss"] = len(losses)
    return res


def line(tag, r, base=None):
    d = ""
    if base and base["net"]:
        d = f"   net {(r['net']-base['net'])/abs(base['net'])*100:+6.1f}%"
    print(f"  {tag:<26} net {r['net']:+8.2f}  worst DD {r['worst_debt']:6.2f}"
          f"  trades {r['trades']:4d}  biggest loss {r['worst_trade']:7.2f}{d}")


def main():
    print("loading bars...")
    sym, R = H.bars_long()
    if R is None or not len(R):
        print("no bars from MT5 - is a terminal running?")
        return 2
    print(f"{sym}: {len(R)} M1 bars, engine {H.ENGINE}, spread {SPREAD}")

    out = {"engine": H.ENGINE, "bars": len(R), "accounts": {}}
    for name, bal in ACCOUNTS:
        print("")
        print(f"=== {name}  (balance ${bal:.2f}) ===")
        b = {"balance": bal, "scale_ref": 230.0}
        base = run(R, b)
        line("no cap (deployed today)", base)
        res = {"base": base}
        for pct in (3.0, 5.0, 8.0):
            cap = bal * pct / 100.0
            r1 = run(R, dict(b, risk_pct=pct))
            r2 = run(R, dict(b, risk_fit=pct))
            line(f"SKIP over {pct:.0f}% (${cap:.2f})", r1, base)
            line(f"FIT  under {pct:.0f}% (${cap:.2f})", r2, base)
            res[f"skip{pct:g}"] = r1
            res[f"fit{pct:g}"] = r2
        r3 = run(R, dict(b, risk_max=12.0))
        r4 = run(R, dict(b, risk_fit_abs=12.0))
        line("SKIP over $12 flat", r3, base)
        line("FIT  under $12 flat", r4, base)
        res["skip12usd"] = r3
        res["fit12usd"] = r4
        out["accounts"][name] = {k: {kk: vv for kk, vv in v.items()
                                     if kk not in ("curve", "pnls")}
                                 for k, v in res.items()}

    with open(os.path.join(HERE, "risk_cap.json"), "w") as f:
        json.dump(out, f, indent=1)
    print("")
    print("written: review/risk_cap.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
