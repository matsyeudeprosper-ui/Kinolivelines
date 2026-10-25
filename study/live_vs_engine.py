"""live_vs_engine.py (2026-10-25, owner: "backtest from the 14th of last month until today, to compare with the real
forward trading"). The same engine and the same live settings as live_cfg_months.py, replayed on the Exness archive from
2026-09-14 to the last archived minute, at today's 7 $ spread; then lined up day by day against the REAL account P&L
(nest_data/kino.json months) and the real journal (live/bos_journal_kino.csv).

Engine lot: scaled from the real balance at the window start, the way the bot scales (scale_with_balance, ref 200 $).
"""
import csv
import datetime as dt
import io
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import live_cfg_months as LC          # noqa: E402  (month_m1, RATES, log paths)

LIVE = LC.LIVE
OUT = os.path.join(HERE, "live_vs_engine")
START = "2026-09-14"


def main():
    os.makedirs(OUT, exist_ok=True)
    LC.OUT = OUT
    LC.CACHE = os.path.join(HERE, "live_cfg_months", "m1")
    sys.path.insert(0, os.path.join(LIVE, "lab"))
    sys.path.insert(0, LIVE)
    os.chdir(LIVE)
    import harness as H
    import owl_package as PKM
    L = PKM.for_account("kino")
    # the real balance at the window start, from the journal's first entry on/after START (else 200)
    J = list(csv.DictReader(open(os.path.join(LIVE, "bos_journal_kino.csv"), encoding="utf-8")))
    bal0 = next((float(r["balance_at_entry"]) for r in J if r["entry_time_utc"][:10] >= START and r.get("balance_at_entry")), 200.0)
    cfg = H.cfg_of({
        "lot": float(L["base_lot"]), "bullets": float(L["max_extra"]), "jar": bool(L["jar"]),
        "kill_net": float(L["kill_net"] or 0.0), "day_cap": float(L.get("day_cap") or 0.0),
        "nerv_gate": bool(L.get("nervosity", True)), "storm": 1.85 if L.get("storm_ceiling") is None else float(L["storm_ceiling"]),
        "rr": float(L.get("rr") or 0.8), "k_streak": int(L.get("k_streak") or 2),
        "pb_dir_gate": bool(L.get("pb_dir_gate", False)), "pb_gate_mode": str(L.get("pb_gate_mode") or "trend"),
        "risk_pct": 100.0 * float(L.get("max_risk_pct") or 0.0), "risk_fit": float(L.get("risk_fit_pct") or 0.0),
        "internal": 1 if L.get("internal_entries") else 0, "debt_gate": 1 if L.get("debt_gate", True) else 0,
        "scale_ref": float(L.get("scale_ref_balance") or 200.0), "balance": bal0 if L.get("scale_with_balance") else 0.0, "drag": 0.0})
    R9 = LC.month_m1(2026, 9)[0]
    R10 = LC.month_m1(2026, 10)[0]
    t0 = int(dt.datetime.fromisoformat(START).replace(tzinfo=dt.timezone.utc).timestamp())
    W = R9[(R9["time"] >= t0 - 3 * 86400) & (R9["time"] < t0)]
    R = np.concatenate([R9[R9["time"] >= t0], R10])
    full = np.concatenate([W, R])
    sf = H.simulate(full, 7.0, cfg)
    sw = H.simulate(W, 7.0, cfg)
    pn = (sf.get("pnls") or [])[len(sw.get("pnls") or []):]
    # engine daily P&L from the dated curve (running net at the START of each day)
    cur = sf["curve"]
    eng_day = {}
    for (d0, v0), (d1, v1) in zip(cur, cur[1:]):
        if d0 >= START:
            eng_day[d0] = round(v1 - v0, 2)
    last_day = dt.datetime.fromtimestamp(int(R["time"][-1]), tz=dt.timezone.utc).strftime("%Y-%m-%d")
    nd = json.load(open(os.path.join(LIVE, "nest_data", "kino.json"), encoding="utf-8"))
    real_day = {}
    for ym, rows in (nd.get("months") or {}).items():
        for r in rows:
            if START <= r["d"] <= last_day:
                real_day[r["d"]] = float(r["p"])
    jr = [r for r in J if START <= r["entry_time_utc"][:10] <= last_day and r.get("profit_usd") not in (None, "")]
    rows = []
    for d in sorted(set(eng_day) | set(real_day)):
        if d <= last_day:
            rows.append((d, eng_day.get(d), real_day.get(d)))
    drag = LC.DRAG * float(cfg["lot"]) / 0.02 * (bal0 / 200.0 if cfg["balance"] else 1.0)
    res = {"window": [START, last_day], "balance_start": bal0, "spread": 7.0,
           "engine": {"trades": len(pn), "won": sum(1 for p in pn if p > 0), "net_engine": round(sum(pn), 2),
                      "net_after_drag": round(sum(pn) - drag * len(pn), 2), "drag_per_trade": round(drag, 2)},
           "real": {"journal_trades": len(jr), "journal_won": sum(1 for r in jr if float(r["profit_usd"]) > 0),
                    "journal_net": round(sum(float(r["profit_usd"]) for r in jr), 2),
                    "account_net_days": round(sum(v for v in real_day.values()), 2)},
           "days": rows}
    json.dump(res, open(os.path.join(OUT, "result.json"), "w", encoding="utf-8"), indent=1)
    print(json.dumps({k: v for k, v in res.items() if k != "days"}, indent=1))
    print("day        engine    real")
    for d, e, r in rows:
        print("%s %8s %8s" % (d, "%+.2f" % e if e is not None else "-", "%+.2f" % r if r is not None else "-"))


if __name__ == "__main__":
    main()
