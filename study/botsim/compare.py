"""compare.py - simulated bot log vs the real bot log, trade by trade and dollar by dollar (botsim, 2026-10-25).

    python study/botsim/compare.py <sim log> <real log> <start ISO> <end ISO> [tol_s]
A trade = "<KIND> ENTRY: BUY|SELL lot @ ~price SL x TP y" followed by its "WIN/LOSS +-x (lot" line; bullets = "ADD +-x".
Matched = same direction, entries within tol_s seconds (default 120).
"""
import datetime as dt
import re
import sys


def ts(s):
    return dt.datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()


def trades(path, a, b):
    T, cur = [], None
    for ln in open(path, encoding="utf-8", errors="replace"):
        m = re.match(r"(\S+) (FLIP-BOS|BOS|INT) ENTRY: (BUY|SELL) ([0-9.]+) @ ~([0-9.]+) SL ([0-9.]+) TP ([0-9.]+)", ln)
        if m:
            t = ts(m.group(1))
            if cur is not None:
                T.append(cur)
            cur = {"t": t, "kind": m.group(2), "d": m.group(3), "lot": float(m.group(4)), "e": float(m.group(5)),
                   "sl": float(m.group(6)), "tp": float(m.group(7)), "pnl": None, "add": 0.0, "n_add": 0} if a <= t < b else None
            continue
        if cur is None:
            continue
        m = re.match(r"\S+ (WIN|LOSS) ([+-][0-9.]+) \(lot", ln)
        if m and cur["pnl"] is None:
            cur["pnl"] = float(m.group(2))
            continue
        m = re.match(r"\S+ ADD ([+-][0-9.]+) \(lot", ln)
        if m:
            cur["add"] += float(m.group(1)); cur["n_add"] += 1
    if cur is not None:
        T.append(cur)
    return T


def main(sim, real, a, b, tol=120):
    a, b = ts(a), ts(b)
    S, R = trades(sim, a, b), trades(real, a, b)
    used, rows = set(), []
    for r in R:
        best = None
        for j, s in enumerate(S):
            if j in used or s["d"] != r["d"]:
                continue
            g = abs(s["t"] - r["t"])
            if g <= tol and (best is None or g < best[1]):
                best = (j, g)
        if best:
            used.add(best[0])
        rows.append((r, S[best[0]] if best else None))
    f = lambda t: dt.datetime.utcfromtimestamp(t).strftime("%m-%d %H:%M:%S")
    same = sum(1 for r, s in rows if s and r["pnl"] is not None and s["pnl"] is not None and (r["pnl"] > 0) == (s["pnl"] > 0))
    exact = sum(1 for r, s in rows if s and r["pnl"] is not None and s["pnl"] is not None and abs(r["pnl"] - s["pnl"]) < 0.05)
    tot = lambda L, k: round(sum((x[k] or 0) for x in L), 2)
    print("real %d trades | sim %d | matched %d | same win/loss %d | same money (<0.05 $) %d" % (len(R), len(S), len(used), same, exact))
    print("money  real main %+.2f bullets %+.2f total %+.2f | sim main %+.2f bullets %+.2f total %+.2f" % (
        tot(R, "pnl"), tot(R, "add"), tot(R, "pnl") + tot(R, "add"), tot(S, "pnl"), tot(S, "add"), tot(S, "pnl") + tot(S, "add")))
    print("\nREAL                                              | SIM")
    for r, s in rows:
        print("%s %-8s %-4s %.2f @%.2f %+7.2f %+6.2f | %s" % (f(r["t"]), r["kind"], r["d"], r["lot"], r["e"], r["pnl"] or 0, r["add"],
              ("%s @%.2f %+7.2f %+6.2f  lag %+.0fs" % (f(s["t"]), s["e"], s["pnl"] or 0, s["add"], s["t"] - r["t"])) if s else "-- not taken"))
    print("\nSIM only:")
    for j, s in enumerate(S):
        if j not in used:
            print("  %s %-8s %-4s %.2f @%.2f %+7.2f %+6.2f" % (f(s["t"]), s["kind"], s["d"], s["lot"], s["e"], s["pnl"] or 0, s["add"]))


if __name__ == "__main__":
    main(*sys.argv[1:5], *([float(sys.argv[5])] if len(sys.argv) > 5 else []))
