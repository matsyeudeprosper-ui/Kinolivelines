"""scanner_score_f2.py - the SCANNER-F2 scorer (review/SCANNER_FORWARD_PROTOCOL_F2.md).

Reads live/scanner/forward_v3.jsonl (strategy) and control_v3.jsonl (live random controls, same execution path),
keeps records tagged engine v3-quote whose OPEN falls inside the protocol window, and computes per market:
  E (mean R, fills as recorded), sum R, max drawdown R, win rate, cost R, stop slippage R, latency / quote age,
  the one-sided 90 % day-block bootstrap lower / upper bounds of E (UTC-day blocks, 5000 resamples, seed 7),
  E under cost stress (+0.5 and +1.0 x the entry spread per trade, in R),
  the controls: E of every stream (coin / trend variants) and the real E's percentile among them,
  coverage: closed trades, uptime (heartbeat minutes / window minutes), operational misses share, guard blocks;
and the verdict per primary market (PASS / FAIL / INCONCLUSIVE) exactly as the protocol defines.
    python study/scanner_score_f2.py [--window live/scanner/protocol_window.json]
"""
import json
import os
import sys
from collections import defaultdict

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SD = os.path.join(ROOT, "live", "scanner")
PRIMARY, SECONDARY, REFERENCE = ("USTEC", "XAUUSD"), ("US30", "US500"), ("BTCUSD",)
OPS = ("late", "no_quote", "stale_quote")


def load(p):
    out = []
    try:
        for ln in open(p, encoding="utf-8"):
            try:
                out.append(json.loads(ln))
            except Exception:
                pass
    except FileNotFoundError:
        pass
    return out


def closed_in(recs, start, end, key="sym"):
    """closes whose OPEN time (detect) lies inside the window"""
    by = defaultdict(list)
    for x in recs:
        if x.get("engine") != "v3-quote" or x.get("ev") != "close":
            continue
        t0 = x.get("detect") or x.get("t")
        if t0 is not None and start <= float(t0) < end:
            by[x[key]].append(x)
    return by


def boot(r, days, reps=5000, seed=7):
    rng = np.random.default_rng(seed)
    u = sorted(set(days)); idx = {d: [i for i, x in enumerate(days) if x == d] for d in u}
    means = np.empty(reps)
    for k in range(reps):
        pick = rng.choice(len(u), size=len(u), replace=True)
        sel = [i for p in pick for i in idx[u[p]]]
        means[k] = np.mean(r[sel])
    return float(np.percentile(means, 10)), float(np.percentile(means, 90))


def stats(trs):
    if not trs:
        return {"n": 0}
    r = np.array([t["r"] for t in trs], float)
    cum = np.cumsum(r); peak = np.maximum.accumulate(np.concatenate([[0.0], cum]))[1:]
    cost = np.array([(t.get("spread") or 0.0) / t["risk"] for t in trs], float)
    days = [int(float(t.get("detect") or t["t"]) // 86400) for t in trs]
    lb, ub = boot(r, days) if len(r) >= 5 else (None, None)
    lat = [t.get("latency_s") for t in trs if t.get("latency_s") is not None]
    qa = [t.get("quote_age_s") for t in trs if t.get("quote_age_s") is not None]
    return {"n": int(len(r)), "E": round(float(r.mean()), 4), "sum_r": round(float(r.sum()), 2),
            "max_dd_r": round(float(np.max(peak - cum)), 2), "wr": round(float((r > 0).mean() * 100), 1),
            "cost_r": round(float(cost.mean()), 4), "slip_r": round(float(np.mean([t.get("slip_r") or 0 for t in trs])), 4),
            "eow": int(sum(1 for t in trs if t.get("eow"))),
            "E_stress_0_5": round(float((r - 0.5 * cost).mean()), 4), "E_stress_1_0": round(float((r - 1.0 * cost).mean()), 4),
            "lb90": None if lb is None else round(lb, 4), "ub90": None if ub is None else round(ub, 4),
            "latency_med": float(np.median(lat)) if lat else None, "latency_p95": float(np.percentile(lat, 95)) if lat else None,
            "quote_age_med": float(np.median(qa)) if qa else None}


def main():
    wp = sys.argv[sys.argv.index("--window") + 1] if "--window" in sys.argv else os.path.join(SD, "protocol_window.json")
    W = json.load(open(wp, encoding="utf-8"))
    start, end = float(W["start"]), float(W["end"])
    F = load(os.path.join(SD, "forward_v3.jsonl"))
    C = load(os.path.join(SD, "control_v3.jsonl"))
    strat = closed_in(F, start, end)
    ctrl = closed_in(C, start, end, key="sid")
    miss = defaultdict(lambda: defaultdict(int))
    opens = defaultdict(int)
    for x in F:
        t0 = x.get("detect") or x.get("t") or x.get("sig_bar")
        if x.get("engine") != "v3-quote" or t0 is None or not (start <= float(t0) < end):
            continue
        if x.get("ev") == "missed":
            miss[x["sym"]][x.get("why")] += 1
        elif x.get("ev") == "open":
            opens[x["sym"]] += 1
    hb = [x for x in load(os.path.join(SD, "heartbeat.jsonl")) if start <= x.get("t", 0) < end]
    minutes = max(1.0, (min(end, max([x["t"] for x in hb] or [start])) - start) / 60.0) if hb else 1.0
    full_minutes = (end - start) / 60.0
    uptime = len(hb) / full_minutes
    blocked = sum(1 for x in hb if x.get("drift"))
    out = {"protocol": W.get("protocol"), "window": [start, end], "uptime": round(uptime, 4), "guard_blocked_minutes": blocked,
           "markets": {}}
    for sym in PRIMARY + SECONDARY + REFERENCE:
        s = stats(strat.get(sym, []))
        ops = sum(miss[sym][k] for k in OPS)
        reach = opens[sym] + ops
        s["missed"] = dict(miss[sym]); s["ops_share"] = round(ops / reach, 4) if reach else None
        cs = {}
        for var in ("coin", "trend"):
            es = [np.mean([t["r"] for t in v]) for sid, v in ctrl.items() if sid.startswith(sym + ":" + var + ":") and len(v) >= 5]
            if es and s.get("n"):
                es = np.array(es)
                cs[var] = {"streams": int(len(es)), "p95": round(float(np.percentile(es, 95)), 4),
                           "real_pct": round(float((es < s["E"]).mean() * 100), 1)}
        s["controls"] = cs
        cov = (s.get("n", 0) >= 100 and uptime >= 0.95 and (s["ops_share"] or 0) <= 0.05 and blocked == 0)
        if sym in PRIMARY:
            if not cov:
                v = "INCONCLUSIVE"
            elif (s["E"] > 0 and s["lb90"] is not None and s["lb90"] > 0 and s["E_stress_1_0"] > 0
                  and all(c.get("streams", 0) >= 20 and s["E"] > c["p95"] for c in (cs.get("coin", {}), cs.get("trend", {})))):
                v = "PASS"
            elif s["E"] <= 0 or (s["ub90"] is not None and s["ub90"] < 0):
                v = "FAIL"
            else:
                v = "INCONCLUSIVE"
            s["verdict"] = v
        s["coverage_met"] = bool(cov)
        out["markets"][sym] = s
    print(json.dumps(out, indent=1))
    return out


if __name__ == "__main__":
    main()
