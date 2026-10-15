"""E030 - current sizing vs a CONSTANT 1.5% of balance per trade.

Owner 2026-10-15: "test what would be better: current risk management, or a
fixed risk per trade of 1.5% of the account balance, no matter the distance
between entry and SL - big or small, the same percentage per trade."

  current   the account's own package: base lot scaled by balance, its
            sizing policies, half lot in debt, the 3% cap that shrinks the
            lot on wide stops.
  const1.5  every MAIN entry: lot = floor(balance x 1.5% / stop / 0.01) x
            0.01, never below 0.01 (broker minimum - on the widest stops
            0.01 then risks MORE than 1.5%; counted). The recovery bullets
            (adds) keep their own sizing in both arms.

Three estimators, written before any number was read:

  A  REAL MONEY. Every journal trade. Sizing does not move the price path,
     so a re-sized trade earns exactly pnl x new_lot/old_lot. No simulator.
     The new lot uses the balance the trade actually saw (no compounding of
     the counterfactual - the path effect is C's job).
  B  RANDOM-LOT CONTROL (the E009 control). The same multiset of 1.5% lots
     shuffled at random over the same trades, 5000 times. If the 1.5% net
     sits below the 50th percentile, sizing by stop distance is putting the
     big lots on the worse trades.
  C  FULL RE-SIMULATION in lab/harness on the long M1 window, each live
     package, $200 start, compounding, debt and recovery included
     (harness option risk_const).

Verdict per estimator (fixed in advance):
  BETTER     net >= current AND max drawdown <= current
  WORSE      net <  current AND max drawdown >  current
  TRADE-OFF  one better, one worse - report both, no ranking
A is the evidence that matters most (real fills, real costs); C carries the
path; the simulator's dollars are not account dollars (engine-dollar rule).

Run:  python review/e030_const_risk.py   -> review/e030_const_risk.json
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

PCT = 1.5
SPREAD = 7.0
SHUFFLES = 5000
random.seed(30)


def const_lot(bal, dist, pct=PCT):
    return max(0.01, math.floor((bal * pct / 100.0 / dist) / 0.01 + 1e-9) * 0.01)


def max_dd(pnls):
    run = pk = dd = 0.0
    for p in pnls:
        run += p
        pk = max(pk, run)
        dd = max(dd, pk - run)
    return dd


def real_trades():
    """main + add trades from every Bitcoin journal (USTEC prices are scaled - left out)"""
    out = []
    for f in sorted(glob.glob(os.path.join(LIVE, "bos_journal*.csv"))):
        if "USTEC" in f:
            continue
        acct = os.path.basename(f)[12:-4].lstrip("_") or "bos"
        for r in csv.DictReader(io.open(f, newline="", encoding="utf-8", errors="replace")):
            try:
                dist, lot = float(r["dist_pts"]), float(r["lot"])
                bal, pnl = float(r["balance_at_entry"]), float(r["profit_usd"])
            except (KeyError, TypeError, ValueError):
                continue
            if not (dist > 0 and lot > 0 and bal > 0 and r.get("exit_time_utc")):
                continue
            out.append({"acct": acct, "t": r["exit_time_utc"], "dist": dist, "lot": lot, "bal": bal, "pnl": pnl,
                        "add": str(r.get("is_add")) == "True"})
    out.sort(key=lambda x: x["t"])
    return out


def verdict(net_a, dd_a, net_b, dd_b):
    if net_b >= net_a and dd_b <= dd_a:
        return "BETTER"
    if net_b < net_a and dd_b > dd_a:
        return "WORSE"
    return "TRADE-OFF"


def part_a(out):
    T = real_trades()
    print("=" * 72)
    print("A. REAL MONEY - %d closed trades, %d accounts" % (len(T), len({x["acct"] for x in T})))
    print("=" * 72)
    for x in T:
        x["nlot"] = x["lot"] if x["add"] else const_lot(x["bal"], x["dist"])
        x["npnl"] = x["pnl"] * x["nlot"] / x["lot"]
        x["over"] = (not x["add"]) and x["dist"] * x["nlot"] > x["bal"] * PCT / 100.0 * 1.0001
    rows = {}
    for acct in sorted({x["acct"] for x in T}) + ["ALL"]:
        S = [x for x in T if acct in ("ALL", x["acct"])]
        a = [x["pnl"] for x in S]
        b = [x["npnl"] for x in S]
        rows[acct] = r = {"n": len(S), "main": sum(1 for x in S if not x["add"]),
                          "net_cur": round(sum(a), 2), "net_15": round(sum(b), 2),
                          "dd_cur": round(max_dd(a), 2), "dd_15": round(max_dd(b), 2),
                          "worst_cur": round(min(a), 2), "worst_15": round(min(b), 2),
                          "over_15pct": sum(1 for x in S if x["over"]),
                          "verdict": verdict(sum(a), max_dd(a), sum(b), max_dd(b))}
        print("  %-11s %3d trades  net %+8.2f -> %+8.2f   max dip %6.2f -> %6.2f   worst %+7.2f -> %+7.2f   %s"
              % (acct, r["n"], r["net_cur"], r["net_15"], r["dd_cur"], r["dd_15"], r["worst_cur"], r["worst_15"], r["verdict"]))
    # which trades get bigger / smaller, and how they did
    M = [x for x in T if not x["add"]]
    up = [x for x in M if x["nlot"] > x["lot"] + 1e-9]
    dn = [x for x in M if x["nlot"] < x["lot"] - 1e-9]
    same = [x for x in M if abs(x["nlot"] - x["lot"]) <= 1e-9]
    for tag, G in (("bigger lot (tight stops)", up), ("smaller lot (wide stops)", dn), ("unchanged", same)):
        if G:
            print("    %-26s %3d trades, they made %+7.2f (%+.2f each), median stop %4.0f pts"
                  % (tag, len(G), sum(x["pnl"] for x in G), sum(x["pnl"] for x in G) / len(G), sorted(x["dist"] for x in G)[len(G) // 2]))
    print("")
    print("  A2. SAME AVERAGE RISK, ONLY THE SHAPE CHANGES (each account's 1.5%% lots scaled so its total risk")
    print("      equals what it really risked) - separates 'how much' from 'constant %% vs current'")
    a2 = {}
    for acct in sorted({x["acct"] for x in T}) + ["ALL"]:
        S = [x for x in T if acct in ("ALL", x["acct"])]
        k = {}
        for ac in {x["acct"] for x in S}:
            G = [x for x in S if x["acct"] == ac and not x["add"]]
            cr, nr = sum(x["dist"] * x["lot"] for x in G), sum(x["dist"] * x["nlot"] for x in G)
            k[ac] = cr / nr if nr else 1.0
        a = [x["pnl"] for x in S]
        m = [x["pnl"] if x["add"] else x["npnl"] * k[x["acct"]] for x in S]
        a2[acct] = {"net_cur": round(sum(a), 2), "net_shape": round(sum(m), 2), "dd_cur": round(max_dd(a), 2),
                    "dd_shape": round(max_dd(m), 2), "verdict": verdict(sum(a), max_dd(a), sum(m), max_dd(m))}
        print("      %-11s net %+8.2f -> %+8.2f   max dip %6.2f -> %6.2f   %s"
              % (acct, sum(a), sum(m), max_dd(a), max_dd(m), a2[acct]["verdict"]))
    out["A2"] = a2
    out["A"] = {"rows": rows, "bigger": len(up), "smaller": len(dn), "unchanged": len(same),
                "bigger_pnl": round(sum(x["pnl"] for x in up), 2), "smaller_pnl": round(sum(x["pnl"] for x in dn), 2)}

    print("")
    print("=" * 72)
    print("B. RANDOM-LOT CONTROL - the same 1.5%% lots shuffled over the same %d main trades, %d times" % (len(M), SHUFFLES))
    print("=" * 72)
    ratios = [x["nlot"] / x["lot"] for x in M]
    struct = sum(x["pnl"] * r for x, r in zip(M, ratios))
    nets = []
    for _ in range(SHUFFLES):
        random.shuffle(ratios)
        nets.append(sum(x["pnl"] * r for x, r in zip(M, ratios)))
    nets.sort()
    pct = sum(1 for v in nets if v < struct) / len(nets) * 100.0
    print("  1.5%% sizing on main trades: %+.2f   random assignment: median %+.2f, 5-95%% [%+.2f .. %+.2f]   -> %.0fth percentile"
          % (struct, nets[len(nets) // 2], nets[int(.05 * len(nets))], nets[int(.95 * len(nets))], pct))
    out["B"] = {"struct": round(struct, 2), "median": round(nets[len(nets) // 2], 2), "p05": round(nets[int(.05 * len(nets))], 2),
                "p95": round(nets[int(.95 * len(nets))], 2), "percentile": round(pct, 1)}


# package setting -> harness dial (review/bot_harness_parity.py RULE_MAP). package_cfg() carries only 5 of
# them, so a first run gave four packages the IDENTICAL result (no trend gate, no 3% cap, generic rr).
DIALS = {"internal_entries": "internal", "risk_fit_pct": "risk_fit", "nervosity": "nerv_gate", "day_cap": "day_cap",
         "kill_net": "kill_net", "jar": "jar", "base_lot": "lot", "rr": "rr", "k_streak": "k_streak",
         "pb_dir_gate": "pb_dir_gate", "pb_gate_mode": "pb_gate_mode", "max_extra": "bullets"}
NOT_MODELLED = ("eq_half", "recov_bullets_only", "debt_gate", "max_risk_pct")


def merged(name):
    P = json.load(open(os.path.join(LIVE, "owl_packages.json"), encoding="utf-8"))["packages"]
    ch, cur, seen = [], name, set()
    while cur and cur in P and cur not in seen:
        seen.add(cur); ch.append(P[cur]); cur = P[cur].get("extends")
    m = {}
    for layer in reversed(ch):
        m.update(layer)
    return m


def cfg_for(H, pkg, **over):
    m = merged(pkg)
    o = {"balance": 200.0 if m.get("scale_with_balance", True) else 0.0}
    for k, d in DIALS.items():
        if k in m and m[k] is not None:
            v = m[k]
            o[d] = (1 if v else 0) if d == "internal" else v
    o.update(over)
    return H.cfg_of(o), [k for k in NOT_MODELLED if m.get(k)]


def part_c(out):
    import harness as H
    print("")
    print("=" * 72)
    print("C. FULL RE-SIMULATION - $200 start, compounding, debt + recovery, spread %.0f" % SPREAD)
    print("   each account's own dials (rr, 3%% cap, trend gate, streak, adds, kill line)")
    print("=" * 72)
    sym, R = H.bars_long()
    if R is None or not len(R):
        print("  no bars from MT5 - C skipped")
        return
    print("  %s: %d M1 bars" % (sym, len(R)))
    out["C"] = {"bars": len(R)}
    for who, pkg in (("Mike/Infinity", "valere"), ("Valere", "valere_cap3"), ("Dad", "special_10"), ("Depenses", "robot-pekos-owl")):
        res = {}
        for arm, over in (("current", {}), ("const1.5", {"risk_const": PCT, "risk_fit": 0.0})):
            cfg, nm = cfg_for(H, pkg, **over)
            v = H.simulate(R, SPREAD, cfg)
            p = v.get("pnls") or []
            res[arm] = {"net": round(v["net"], 2), "dd": round(max_dd(p), 2) if p else 0.0, "trades": len(p),
                        "worst": round(min(p), 2) if p else 0.0, "rc_over": v.get("rc_over", 0)}
        a, b = res["current"], res["const1.5"]
        res["verdict"] = verdict(a["net"], a["dd"], b["net"], b["dd"])
        res["not_modelled"] = nm
        out["C"][pkg] = res
        print("  %-14s net %+8.2f -> %+8.2f   max dip %6.2f -> %6.2f   worst %+7.2f -> %+7.2f   trades %d/%d  over1.5%% %d   %s%s"
              % (who, a["net"], b["net"], a["dd"], b["dd"], a["worst"], b["worst"], a["trades"], b["trades"], b["rc_over"], res["verdict"],
                 ("   (not modelled: " + ", ".join(nm) + ")") if nm else ""))


if __name__ == "__main__":
    out = {"pct": PCT, "spread": SPREAD}
    part_a(out)
    part_c(out)
    json.dump(out, open(os.path.join(HERE, "e030_const_risk.json"), "w", encoding="utf-8"), indent=1)
    print("\nsaved review/e030_const_risk.json")
