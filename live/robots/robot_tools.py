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

TOOLS = ("idea_stats", "compare", "robot_replay", "event_impact", "portfolio", "trade_explain", "search_chats")
CHARTS = {}               # chart_key -> a demo trade (candles) - shown in the chat, never sent to the model


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


# ---------------------------------------------------------------- 2026-10-19 (owner items 6 and 5)
FOMC = ["2026-01-28", "2026-03-18", "2026-04-29", "2026-06-17", "2026-07-29", "2026-09-16", "2026-10-28", "2026-12-09",
        "2025-09-17", "2025-10-29", "2025-12-10"]


def _us_dst(dt):
    import datetime as _d
    y = dt.year
    m2 = _d.date(y, 3, 8); start = m2 + _d.timedelta(days=(6 - m2.weekday()) % 7)
    n1 = _d.date(y, 11, 1); end = n1 + _d.timedelta(days=(6 - n1.weekday()) % 7)
    return start <= dt.date() < end


def _events(t0, t1):
    """big US events between t0 and t1 (epoch): jobs report (first Friday, 08:30 New York), Fed decisions (14:00 New York),
    plus every high-impact event of the archived calendar"""
    import datetime as _d, os as _o, json as _j
    out = []
    d = _d.datetime.utcfromtimestamp(t0).replace(day=1, hour=0, minute=0, second=0)
    while d.timestamp() < t1:
        f = d + _d.timedelta(days=(4 - d.weekday()) % 7)
        h = 12 if _us_dst(f) else 13
        out.append(("Emploi US (NFP)", int(f.replace(hour=h, minute=30).timestamp())))
        d = (d + _d.timedelta(days=32)).replace(day=1)
    for s_ in FOMC:
        f = _d.datetime.strptime(s_, "%Y-%m-%d")
        out.append(("Décision de la Fed", int(f.replace(hour=18 if _us_dst(f) else 19).timestamp())))
    try:
        for h in _j.load(open(_o.path.join(RD.CACHE, "cal_history.json"), encoding="utf-8")):
            if h.get("cc") in ("USD", "All"):
                out.append((h["title"], int(_d.datetime.fromisoformat(h["date"]).timestamp())))
    except Exception:
        pass
    return sorted(set(e for e in out if t0 <= e[1] <= t1), key=lambda e: e[1])


def event_impact(market, rules, rr=0.8, before=30, after=60):
    """the robot's quick-replay trades opened around big US events vs all its other trades"""
    ex = RD.examples(market, rules, 1, [], rr, "all")
    if ex is None:
        RD.fetch(market)
        return {"error": "no candles for %s yet - being fetched" % market}
    T = ex.get("all") or []
    if not T:
        return {"market": market, "trades": 0}
    ev = _events(T[0]["t_in"] - 86400, T[-1]["t_out"] + 86400)
    near, other = [], []
    for t in T:
        hit = next((e for e in ev if e[1] - before * 60 <= t["t_in"] <= e[1] + after * 60), None)
        (near if hit else other).append(dict(t, ev=hit[0] if hit else None))
    st = lambda L: {"trades": len(L), "won_pct": round(100.0 * sum(1 for x in L if x["r"] > 0) / len(L), 1) if L else None,
                    "avg_r": round(sum(x["r"] for x in L) / len(L), 2) if L else None, "sum_r": round(sum(x["r"] for x in L), 2)}
    return {"market": market, "window": "%d min before to %d min after" % (before, after), "events_in_data": len(ev),
            "around_events": st(near), "other_trades": st(other), "examples": [{"event": x["ev"], "r": x["r"]} for x in near[:6]],
            "note": "quick replay, no costs; few events = a small sample. Any pause is the MEMBER's choice - suggest, never do."}


def portfolio(items, ctx):
    """several robots / markets together: each one's result and worst dip (in R), how much their days move together,
    and the combined result - which ones complement each other"""
    import math
    rows, series = [], {}
    for it in (items or [])[:4]:
        mk = str(it.get("market") or ctx.get("market") or "BTCUSD")[:20]
        who = str(it.get("robot") or "chat")
        if who == "chat":
            rules, rr = ctx.get("rules") or {}, ctx.get("rr") or 0.8
        else:
            rules, rr = {"entry": {"event": "any"}, "stop": {"kind": "protected"}}, (1.0 if who == "pekos-owl" else 0.8)
        ex = RD.examples(mk, rules, 1, [], rr, "all")
        if ex is None:
            RD.fetch(mk)
            rows.append({"item": "%s@%s" % (who, mk), "error": "no candles yet"})
            continue
        day = {}
        for t in ex.get("all") or []:
            k = t["t_out"] // 86400
            day[k] = day.get(k, 0) + t["r"]
        eq = peak = dd = 0.0
        for k in sorted(day):
            eq += day[k]; peak = max(peak, eq); dd = max(dd, peak - eq)
        key = "%s@%s" % (who, mk)
        series[key] = day
        rows.append({"item": key, "trades": ex["count"], "sum_r": round(sum(day.values()), 2), "worst_dip_r": round(dd, 2)})
    keys = list(series)
    corr = []
    for i in range(len(keys)):
        for j in range(i + 1, len(keys)):
            a, b = series[keys[i]], series[keys[j]]
            ds = sorted(set(a) | set(b))
            x = [a.get(k, 0) for k in ds]; y = [b.get(k, 0) for k in ds]
            mx, my = sum(x) / len(x), sum(y) / len(y)
            num = sum((p - mx) * (q - my) for p, q in zip(x, y))
            den = math.sqrt(sum((p - mx) ** 2 for p in x) * sum((q - my) ** 2 for q in y)) or 1
            corr.append({"pair": "%s + %s" % (keys[i], keys[j]), "daily_correlation": round(num / den, 2)})
    comb = {}
    for d_ in series.values():
        for k, v in d_.items():
            comb[k] = comb.get(k, 0) + v
    eq = peak = dd = 0.0
    for k in sorted(comb):
        eq += comb[k]; peak = max(peak, eq); dd = max(dd, peak - eq)
    return {"items": rows, "correlations": corr, "combined": {"sum_r": round(sum(comb.values()), 2), "worst_dip_r": round(dd, 2)},
            "note": "R = multiples of each trade's risk; low or negative correlation + both positive = they complement each other"}


# ---------------------------------------------------------------- 2026-10-19 (owner list-4 items 3 and 4)
def trade_explain(uid, which="last"):
    """one REAL trade of the member's account (nest_data): its numbers, the candles around it (live feed, else the test
    data) as a chart for the chat, and the market's state at entry - so Kino explains why it opened and closed"""
    import json, os, datetime as _d
    nd = json.load(open(os.path.join(os.path.dirname(RD.HERE), "nest_data", "%s.json" % uid), encoding="utf-8"))
    tr = nd.get("trades") or []
    if not tr:
        return {"error": "no closed trade on their account yet"}
    if str(which).isdigit() and int(which) < 50:
        t = tr[min(len(tr) - 1, int(which) - 1 if int(which) > 0 else 0)]
    else:
        t = next((x for x in tr if str(x.get("pid")) == str(which)), tr[0])
    yr = time.gmtime().tm_year
    t_out = int(_d.datetime.strptime("%d/%s" % (yr, t["w"]), "%Y/%d/%m %H:%M").replace(tzinfo=_d.timezone.utc).timestamp())
    if t_out > time.time() + 86400:
        t_out = int(_d.datetime.strptime("%d/%s" % (yr - 1, t["w"]), "%Y/%d/%m %H:%M").replace(tzinfo=_d.timezone.utc).timestamp())
    t_in = t_out - int(t.get("dur") or 0) * 60
    d = 1 if t.get("dir") == "A" else -1
    out = {"trade": {"closed_utc": time.strftime("%d/%m %H:%M", time.gmtime(t_out)), "opened_utc": time.strftime("%d/%m %H:%M", time.gmtime(t_in)),
                     "side": "buy" if d == 1 else "sell", "entry": t.get("ep"), "exit": t.get("xp"), "result_usd": t.get("p"), "lot": t.get("lot"),
                     "minutes": t.get("dur"), "kind": t.get("k")},
           "of_last": "%d trades on the account; today %+.2f $, week %+.2f $" % (len(tr), nd.get("today") or 0, nd.get("week") or 0)}
    Rw = None
    try:
        import robot_ghost as G
        Rw, k = G.live_bars("BTCUSD")
        if Rw is not None and not (Rw["time"][0] <= t_in - 3600 and t_out <= Rw["time"][-1] + 60):
            Rw = None
    except Exception:
        Rw = None
    if Rw is None:
        D = RD.data("BTCUSD")
        if D is not None and D[0]["time"][0] <= t_in - 3600 and t_out <= D[0]["time"][-1] + 60:
            Rw, k = D[0], D[1]
    if Rw is None:
        out["chart"] = "no candles for that moment any more (live memory keeps ~2 days)"
        return out
    T = Rw["time"]
    i = int(np.searchsorted(T, t_in, side="right")) - 1
    j = int(np.searchsorted(T, t_out, side="right")) - 1
    i0, i1 = max(0, i - 70), min(len(Rw), j + 20)
    step = max(1, (i1 - i0) // 160)
    tf = "M1" if step == 1 else ("M5" if step <= 5 else ("M15" if step <= 15 else "H1"))
    try:
        e, x = float(t["ep"]), float(t["xp"])
        lo = float(Rw["low"][i:j + 1].min()) / k
        hi = float(Rw["high"][i:j + 1].max()) / k
        out["during"] = {"best_move_in_favour": round((hi - e) if d == 1 else (e - lo), 2), "worst_move_against": round((e - lo) if d == 1 else (hi - e), 2)}
        key = "c%d" % int(time.time() * 1000)
        CHARTS[key] = {"tf": tf, "candles": RD._rows(Rw, k, i0, i1, tf), "t_in": int(T[i]), "t_out": int(T[j]), "d": d, "entry": e, "exit": x,
                       "stop": None, "target": None, "why": "real", "r": round(float(t.get("p") or 0), 2), "overlays": [], "usd": t.get("p")}
        out["chart_key"] = key
        out["chart"] = "shown in the chat"
    except Exception as ex:
        out["chart"] = "could not draw (%s)" % str(ex)[:60]
    return out


def _norm(x):
    import unicodedata
    return "".join(c for c in unicodedata.normalize("NFD", str(x).lower()) if unicodedata.category(c) != "Mn")


def search_chats(uid, query):
    """the member's OWN past conversations: the messages that best match the query, with their date and context"""
    import json, os, re as _re
    CH = os.path.join(RD.HERE, "chats")
    stop = set("le la les un une des de du et a au aux en on tu je il elle est pas que qui quoi ce ca the a an of to and is it we you i".split())
    words = [w for w in _re.findall(r"[a-z0-9]{3,}", _norm(query)) if w not in stop][:8]
    if not words:
        return {"error": "query too vague"}
    hits = []
    for f in os.listdir(CH):
        if not f.endswith(".json"):
            continue
        try:
            c = json.load(open(os.path.join(CH, f), encoding="utf-8"))
        except Exception:
            continue
        if c.get("uid") != uid or c.get("hidden"):
            continue
        M = [m for m in c.get("msgs") or [] if m.get("role") in ("user", "ai") and m.get("text")]
        for n, m in enumerate(M):
            tx = _norm(m["text"])
            sc = sum(1 for w in words if w in tx)
            if sc:
                ctx_ = M[max(0, n - 1):n + 2]
                hits.append((sc, int(m.get("t") or 0), {"date": time.strftime("%d/%m/%Y", time.gmtime(int(m.get("t") or 0))),
                                                         "conversation": (c.get("robot") or {}).get("name") or c.get("title") or "",
                                                         "exchange": [("THEM: " if x["role"] == "user" else "YOU: ") + str(x["text"])[:260] for x in ctx_]}))
    hits.sort(key=lambda h: (-h[0], -h[1]))
    return {"query": query, "found": len(hits), "best": [h[2] for h in hits[:5]]}


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
            elif c["name"] == "event_impact":
                r = event_impact(mk, ctx.get("rules") or {}, ctx.get("rr") or 0.8)
            elif c["name"] == "portfolio":
                r = portfolio(a.get("items") or [], ctx)
            elif c["name"] == "trade_explain":
                r = trade_explain(ctx.get("uid"), str(a.get("which") or "last")[:20]) if ctx.get("uid") else {"error": "no member"}
            elif c["name"] == "search_chats":
                r = search_chats(ctx.get("uid"), str(a.get("query") or "")[:200]) if ctx.get("uid") else {"error": "no member"}
            else:
                r = robot_replay(mk, ctx.get("rules") or {}, ctx.get("rr") or 0.8)
        except Exception as e:
            r = {"error": str(e)[:120]}
        out.append({"tool": c["name"], "args": dict(a, market=mk), "result": r, "secs": round(time.time() - t0, 1)})
    return out
