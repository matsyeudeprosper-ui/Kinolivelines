"""live_vs_engine_trades.py (2026-10-25, owner: "I want to see if backtesting is really trustworthy: same trades taken,
and did they both win or lose").

Trade-by-trade match of the backtest engine (lab/harness.simulate with the account's live settings, the one behind the
2025 / 2026 month runs) against the REAL Owl journal of the owner's account (live/bos_journal_kino.csv) on the window
where the live rules equal today's (pullback-direction gate live since 2026-10-10 08:49 UTC):

  real trade  = a journal row that is not an add (FLIP-BOS / BOS / INT), entry time, direction, WIN / LOSS
  engine trade = harness TRACE entry (bar time of the decision, direction, win)
  match       = same direction and entry within TOL minutes (the bot enters on the candle close, the engine on the bar)

Prices: Exness public archive BTCUSD M1 from bid ticks (the 2026 run's data), constant 7 $ spread, lot 0.01 as live.
    python study/live_vs_engine_trades.py [start] [end] [tol_min]
-> study/live_vs_engine/trades_match.json + a printed table
"""
import csv
import datetime as dt
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
LIVE = os.path.join(ROOT, "live")
M1 = os.path.join(HERE, "live_cfg_months", "m1")


def ts(s):
    return int(dt.datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp())


def hm(t):
    return dt.datetime.fromtimestamp(t, tz=dt.timezone.utc).strftime("%m-%d %H:%M")


def main(start="2026-10-10T08:49:00+00:00", end="2026-10-25T00:00:00+00:00", tol=3):
    sys.path.insert(0, os.path.join(LIVE, "lab"))
    sys.path.insert(0, LIVE)
    os.chdir(LIVE)
    import harness as H
    import owl_package as PKM
    L = PKM.for_account("kino")
    cfg = H.cfg_of({
        "lot": 0.01, "bullets": float(L["max_extra"]), "jar": bool(L["jar"]), "kill_net": float(L["kill_net"] or 0.0),
        "day_cap": float(L.get("day_cap") or 0.0), "nerv_gate": bool(L.get("nervosity", True)), "storm": 1.85,
        "rr": float(L.get("rr") or 0.8), "k_streak": int(L.get("k_streak") or 2),
        "pb_dir_gate": bool(L.get("pb_dir_gate", False)), "pb_gate_mode": str(L.get("pb_gate_mode") or "trend"),
        "risk_pct": 100.0 * float(L.get("max_risk_pct") or 0.0), "internal": 1 if L.get("internal_entries") else 0,
        "debt_gate": 1 if L.get("debt_gate", True) else 0, "balance": 0.0, "drag": 0.0})
    for _k, _v in json.loads(os.environ.get("OVER", "{}")).items():     # diagnostic overrides, e.g. OVER='{"pb_dir_gate": false}'
        cfg[_k] = _v
    t0, t1 = ts(start), ts(end)
    R = np.concatenate([np.load(os.path.join(M1, "2026-09.npz"))["R"], np.load(os.path.join(M1, "2026-10.npz"))["R"]])
    WARM = int(os.environ.get("WARM_DAYS", "3"))
    R = R[(R["time"] >= t0 - WARM * 86400) & (R["time"] < t1)]
    H.TRACE = []
    H.simulate(R, 7.0, cfg)
    E = [x for x in H.TRACE if t0 <= int(x["t"]) < t1]
    eng = [{"t": int(x["t"]), "d": "BUY" if x["d"] == 1 else "SELL", "kind": "FLIP-BOS" if x.get("flip") else "BOS",
            "win": x.get("win")} for x in E]
    J = list(csv.DictReader(open(os.path.join(LIVE, "bos_journal_kino.csv"), encoding="utf-8")))
    real = []
    for r in J:
        if r.get("is_add") == "True" or not r.get("entry_time_utc"):
            continue
        t = ts(r["entry_time_utc"])
        if t0 <= t < t1 and r.get("outcome"):
            real.append({"t": t, "d": r["direction"], "kind": r["kind"], "win": float(r.get("profit_usd") or 0) > 0,
                         "outcome": r["outcome"], "pnl": float(r.get("profit_usd") or 0)})
    used = set()
    rows = []
    for rr in real:
        best = None
        for j, ee in enumerate(eng):
            if j in used or ee["d"] != rr["d"]:
                continue
            dtm = abs(ee["t"] - rr["t"]) / 60.0
            if dtm <= tol and (best is None or dtm < best[1]):
                best = (j, dtm)
        if best:
            used.add(best[0])
            ee = eng[best[0]]
            rows.append({"real": rr, "eng": ee, "lag_min": round((ee["t"] - rr["t"]) / 60.0, 1), "same_result": (ee["win"] == rr["win"])})
        else:
            rows.append({"real": rr, "eng": None})
    only_eng = [ee for j, ee in enumerate(eng) if j not in used]
    m = [x for x in rows if x["eng"]]
    res = {"window": [start, end], "tol_min": tol, "real_trades": len(real), "engine_trades": len(eng),
           "matched": len(m), "matched_same_result": sum(1 for x in m if x["same_result"]),
           "real_only": len(real) - len(m), "engine_only": len(only_eng),
           "real_won": sum(1 for x in real if x["win"]), "engine_won": sum(1 for x in eng if x["win"])}
    os.makedirs(os.path.join(HERE, "live_vs_engine"), exist_ok=True)
    json.dump({"summary": res, "rows": rows, "engine_only": only_eng}, open(os.path.join(HERE, "live_vs_engine", "trades_match.json"), "w"), indent=1)
    print(json.dumps(res, indent=1))
    print("\nREAL trade                         | ENGINE")
    for x in rows:
        rr = x["real"]
        e = x["eng"]
        print("%s %-4s %-8s %-4s %+6.2f | %s" % (hm(rr["t"]), rr["d"], rr["kind"], "WIN" if rr["win"] else "LOSS", rr["pnl"],
              ("%s %-8s %-4s lag %+.0f min %s" % (hm(e["t"]), e["kind"], "WIN" if e["win"] else "LOSS", x["lag_min"], "same" if x["same_result"] else "DIFFERENT"))
              if e else "-- not taken"))
    print("\nENGINE only (real bot did not take):")
    for e in only_eng:
        print("  %s %-4s %-8s %s" % (hm(e["t"]), e["d"], e["kind"], "WIN" if e["win"] else "LOSS"))


if __name__ == "__main__":
    a = sys.argv[1:]
    main(*(a[:2] if len(a) >= 2 else []), *( [int(a[2])] if len(a) > 2 else []))
