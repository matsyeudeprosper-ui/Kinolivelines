"""Kino's analysis tools (owner 2026-10-19: "the most smart trading companion ever ... self thinking and deciding").
Level 3 of the roadmap: Kino computes instead of guessing. The model (tool-less) may ask for up to 3 tool calls in its
JSON ("tools": [{"name", "args"}]); the server runs them HERE (whitelisted, read-only, on the tests' own candles) and
gives the results back for a second pass. Nothing the model writes is executed - arguments are validated, formulas go
through robot_expr's whitelist.

  idea_stats(market, formula, side="buy", horizon=30)
      every moment the condition turned true on ~42 days of candles: how often, what price did N minutes later (in
      ATR and %), how often it went the right way - AND the same numbers for as many RANDOM moments (the lab's rule:
      always compare a timing idea with random entries), plus the best / worst hours (UTC)
  compare(market, formulas[<=4], side, horizon)   the same, side by side
  robot_replay(market, rules, rr)                 the robot's quick replay: trades, won, average R, by-half split
"""
import time

import numpy as np

import robot_demo as RD
import robot_expr as X

TOOLS = ("idea_stats", "compare", "robot_replay")


def _fwd(R, idx, side, h):
    """forward move after h minutes for indices idx (price units of the test scale) and ATR at entry"""
    n = len(R)
    idx = np.asarray([i for i in idx if i + h < n], dtype=int)
    if not len(idx):
        return idx, np.array([]), np.array([])
    c = R["close"].astype(float)
    mv = side * (c[idx + h] - c[idx])
    return idx, mv, c[idx]


def _summ(R, B, idx, side, h, atr):
    idx, mv, px = _fwd(R, idx, side, h)
    if not len(idx):
        return {"n": 0}
    a = atr[idx]
    ok = a == a
    mva = mv[ok] / a[ok] if ok.any() else np.array([])
    return {"n": int(len(idx)), "right_way_pct": round(100.0 * float((mv > 0).mean()), 1),
            "avg_move_atr": round(float(mva.mean()), 3) if len(mva) else None,
            "median_move_atr": round(float(np.median(mva)), 3) if len(mva) else None,
            "avg_move_pct": round(100.0 * float((mv / px).mean()), 4)}


def idea_stats(market, formula, side="buy", horizon=30):
    D = RD.data(market)
    if D is None:
        RD.fetch(market)
        return {"error": "no candles for %s yet - being fetched, ask again in a minute" % market}
    if not X.is_ok(formula):
        return {"error": "formula refused"}
    h = max(1, min(int(horizon or 30), 1440))
    sd = -1 if str(side).lower() == "sell" else 1
    R, k, eyes, _ = D
    B = RD._bars(R, eyes)
    tr = X.truth(formula, B)
    edges = np.flatnonzero(tr & ~np.r_[False, tr[:-1]])
    edges = edges[(edges >= 300) & (edges < len(R) - h - 1)]
    atr = X.evaluate("atr(14)", B)
    real = _summ(R, B, edges, sd, h, atr)
    rnd = np.random.default_rng(7)
    pool = np.arange(300, len(R) - h - 1)
    rs = [_summ(R, B, rnd.choice(pool, size=max(1, len(edges)), replace=False), sd, h, atr) for _ in range(20)] if len(edges) else []
    rnd_right = sorted(x["right_way_pct"] for x in rs if x.get("n"))
    rnd_avg = sorted(x["avg_move_atr"] for x in rs if x.get("avg_move_atr") is not None)
    beat = None
    if rnd_avg and real.get("avg_move_atr") is not None:
        beat = int(round(100.0 * sum(1 for v in rnd_avg if real["avg_move_atr"] > v) / len(rnd_avg)))
    hours = {}
    if len(edges):
        idx, mv, _ = _fwd(R, edges, sd, h)
        hh = (R["time"][idx] // 3600 % 24).astype(int)
        for H in range(24):
            sel = hh == H
            if sel.sum() >= 5:
                hours[H] = (int(sel.sum()), round(100.0 * float((mv[sel] > 0).mean()), 0))
    best = sorted(hours.items(), key=lambda x: -x[1][1])[:3]
    worst = sorted(hours.items(), key=lambda x: x[1][1])[:3]
    days = (int(R["time"][-1]) - int(R["time"][0])) / 86400.0
    return {"market": market, "formula": formula, "side": "sell" if sd < 0 else "buy", "horizon_min": h, "days": round(days, 1),
            "per_day": round(len(edges) / max(days, 1), 1), "idea": real,
            "random_same_count": {"right_way_pct_median": rnd_right[len(rnd_right) // 2] if rnd_right else None,
                                  "avg_move_atr_median": rnd_avg[len(rnd_avg) // 2] if rnd_avg else None},
            "beats_random_pct": beat, "best_hours_utc": [{"h": H, "n": v[0], "right_way_pct": v[1]} for H, v in best],
            "worst_hours_utc": [{"h": H, "n": v[0], "right_way_pct": v[1]} for H, v in worst],
            "note": "no costs; a timing idea is only interesting if it beats random moments clearly (>= 95 % of them)"}


def compare(market, formulas, side="buy", horizon=30):
    out = []
    for f in (formulas or [])[:4]:
        r = idea_stats(market, f, side, horizon)
        out.append({"formula": f, "per_day": r.get("per_day"), "right_way_pct": (r.get("idea") or {}).get("right_way_pct"),
                    "avg_move_atr": (r.get("idea") or {}).get("avg_move_atr"), "beats_random_pct": r.get("beats_random_pct"),
                    "error": r.get("error")})
    return {"market": market, "side": side, "horizon_min": horizon, "rows": out}


def robot_replay(market, rules, rr=0.8):
    ex = RD.examples(market, rules, 1, [], rr, "recent")
    if ex is None:
        RD.fetch(market)
        return {"error": "no candles for %s yet - being fetched" % market}
    return {"market": market, "trades": ex["count"], "won": ex["won"],
            "won_pct": round(100.0 * ex["won"] / ex["count"], 1) if ex["count"] else None,
            "note": "quick replay on candles: no costs, no brakes - the real test decides"}


def run(calls, ctx):
    """[(name, args)] -> [{"tool", "args", "result"}]; ctx = {"market", "rules", "rr"} of the chat"""
    out = []
    for c in (calls or [])[:3]:
        if not isinstance(c, dict) or c.get("name") not in TOOLS:
            continue
        a = c.get("args") if isinstance(c.get("args"), dict) else {}
        mk = str(a.get("market") or ctx.get("market") or "BTCUSD")[:20]
        t0 = time.time()
        try:
            if c["name"] == "idea_stats":
                r = idea_stats(mk, str(a.get("formula") or "")[:400], a.get("side") or "buy", a.get("horizon") or 30)
            elif c["name"] == "compare":
                r = compare(mk, [str(f)[:400] for f in (a.get("formulas") or [])][:4], a.get("side") or "buy", a.get("horizon") or 30)
            else:
                r = robot_replay(mk, ctx.get("rules") or {}, ctx.get("rr") or 0.8)
        except Exception as e:
            r = {"error": str(e)[:120]}
        out.append({"tool": c["name"], "args": dict(a, market=mk), "result": r, "secs": round(time.time() - t0, 1)})
    return out
