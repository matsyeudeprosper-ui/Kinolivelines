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
    # the real recovery state at the replay start (warm-up start): last "debt $X (peak ..), chest $Y" line before it
    if os.environ.get("SEED_DEBT", "1") == "1":
        import re as _re0
        _ws = int(R["time"][0])
        _d0 = _c0 = 0.0
        for _ln in open(os.path.join(LIVE, "bos_bot_kino.log"), encoding="utf-8", errors="replace"):
            _m = _re0.match(r"(\S+) .*debt \$([0-9.]+) \(peak [^)]*\), chest \$([0-9.]+)", _ln)
            if _m:
                try:
                    if ts(_m.group(1)) > _ws:
                        break
                except Exception:
                    continue
                _d0, _c0 = float(_m.group(2)), float(_m.group(3))
        cfg["debt0"], cfg["chest0"] = _d0, _c0
        print("seeded real state at %s: debt %.2f, chest %.2f" % (hm(_ws), _d0, _c0))
    cfg["nv_live"] = os.environ.get("NV_LIVE", "1") == "1"
    # downtime: "bougies figees depuis N min - reconnexion" -> no entry possible during those N minutes
    if os.environ.get("DOWN", "1") == "1":
        import re as _re1
        _dn = []
        for _ln in open(os.path.join(LIVE, "bos_bot_kino.log"), encoding="utf-8", errors="replace"):
            _m = _re1.match(r"(\S+) bougies figees depuis (\d+) min", _ln)
            if _m:
                try:
                    _te = ts(_m.group(1))
                except Exception:
                    continue
                if t0 - 86400 <= _te < t1:
                    _dn.append([_te - 60 * int(_m.group(2)), _te])
        cfg["down"] = _dn
        print("downtime windows from the live log:", len(_dn))
    H.TRACE = []
    if os.environ.get("PB_STICKY", "1") == "1":      # the live bot's sticky pullback chain, grown during the replay
        H.PB_STICKY = os.path.join(HERE, "live_vs_engine", "pbchain_replay.json")
        if os.path.exists(H.PB_STICKY):
            os.remove(H.PB_STICKY)
    H.simulate(R, 7.0, cfg)
    E = [x for x in H.TRACE if t0 <= int(x["t"]) < t1]
    eng = [{"t": int(x["t"]), "d": "BUY" if x["d"] == 1 else "SELL", "kind": "FLIP-BOS" if x.get("flip") else "BOS",
            "win": x.get("win")} for x in E]
    # 2026-10-25: REALITY = the bot's own log (bos_bot_kino.log), not the journal - the journal lacks trades (10-19 08:39
    # BUY FLIP-BOS is in the log, not in bos_journal_kino.csv). Entry = "<KIND> ENTRY: BUY|SELL", result = the next
    # "WIN +x" / "LOSS -x" main line (ADD lines are the bullets).
    import re as _re
    real = []
    cur = None
    for ln in open(os.path.join(LIVE, "bos_bot_kino.log"), encoding="utf-8", errors="replace"):
        m = _re.match(r"(\S+) (FLIP-BOS|BOS|INT) ENTRY: (BUY|SELL)", ln)
        if m:
            if cur is not None:                       # an entry whose close the log never wrote (10-19 08:39): kept, result unknown
                cur.update(win=None, outcome="?", pnl=0.0)
                real.append(cur)
            t = ts(m.group(1))
            cur = {"t": t, "d": m.group(3), "kind": m.group(2)} if t0 <= t < t1 else None
            continue
        m = _re.match(r"(\S+) (WIN|LOSS) ([+-][0-9.]+) \(lot", ln)
        if m and cur is not None:
            cur.update(win=m.group(2) == "WIN", outcome=m.group(2), pnl=float(m.group(3)))
            real.append(cur)
            cur = None
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
            rows.append({"real": rr, "eng": ee, "lag_min": round((ee["t"] - rr["t"]) / 60.0, 1), "same_result": (None if rr["win"] is None else ee["win"] == rr["win"])})
        else:
            rows.append({"real": rr, "eng": None})
    only_eng = [ee for j, ee in enumerate(eng) if j not in used]
    m = [x for x in rows if x["eng"]]
    res = {"window": [start, end], "tol_min": tol, "real_trades": len(real), "engine_trades": len(eng),
           "matched": len(m), "matched_same_result": sum(1 for x in m if x["same_result"]), "matched_result_unknown": sum(1 for x in m if x["same_result"] is None),
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
