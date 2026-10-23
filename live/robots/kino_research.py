"""kino_research.py (2026-10-21, owner: "next upgrades - all 12", the results part) - Kino's research desk.

    python robots/kino_research.py night        factory + lessons (+ scout on Mondays or when missing) + self-review
    python robots/kino_research.py factory      the idea factory only
    python robots/kino_research.py scout        the market scout only
    python robots/kino_research.py review       the self-review only

1 IDEA FACTORY - every robot entry that made money on ANY market is a seed; each night it becomes variants (the same idea
  on the other prepared markets, with a session, with the bigger trend), each measured against 100 random moments of the
  same market, after the market's spread. The best 3 are kept for the morning ("3 candidates, here is why").
3 MARKET SCOUT - per prepared market: what a round trip costs against how far the price moves (spread / ATR), and how
  many factory ideas beat chance there; plus the broker's cheap markets that are not prepared yet (the old cost census).
4 LESSONS - an idea x market that lost on both halves of its real test, or did no better than chance in the factory, is
  written down as dead; the factory never measures it again and Kino sees the list before building.
11 SELF-REVIEW - Kino re-reads the last day of conversations and lists his own slips: a number he could not point to, a
  promise left late, a sentence said twice, a permission or menu question.
Light: candles only (no MT5 terminal), one process, below-normal priority (the server starts it), ~2-5 minutes.
"""
import glob
import json
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
LIVE = os.path.dirname(HERE)
STUDY = os.path.join(os.path.dirname(LIVE), "study")
sys.path.insert(0, HERE)
FACTORY = os.path.join(HERE, "kino_factory.json")
SCOUT = os.path.join(HERE, "kino_scout.json")
REVIEW = os.path.join(HERE, "kino_selfreview.json")
LESSONS = os.path.join(HERE, "kino_lessons.json")      # 2026-10-23: one line per (robot, market) verdict, written by Kino
RESULTS = os.path.join(HERE, "results")
CHATS = os.path.join(HERE, "chats")
DRAWS = 100
MAX_PER_NIGHT = 40


def _load(p, d):
    try:
        return json.load(open(p, encoding="utf-8"))
    except Exception:
        return d


def _save(p, x):
    json.dump(x, open(p + ".tmp", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    os.replace(p + ".tmp", p)


def markets():
    """the markets whose candles are prepared (test packs) - the factory and the scout work only there"""
    out = ["BTCUSD"]
    for d in sorted(glob.glob(os.path.join(STUDY, "markets", "*", "bars.npz"))):
        out.append(os.path.basename(os.path.dirname(d)))
    return out


def _reg():
    return _load(os.path.join(HERE, "robots.json"), {"robots": [], "pieces": []})


def _result(rid, sym):
    f = os.path.join(RESULTS, ("%s.json" % rid) if sym == "BTCUSD" else ("%s@%s.json" % (rid, sym)))
    return (_load(f, {}).get("robot") or {}) if os.path.exists(f) else {}


def seeds():
    """every formula entry of a robot whose real test made money (any market, any member) -> {formula, side, market, rid, uid, net}"""
    R = _reg()
    P = {p["id"]: p for p in R.get("pieces") or []}
    out, seen = [], set()
    for r in R.get("robots") or []:
        ent = P.get((r.get("parts") or {}).get("entry") or "")
        rule = (ent or {}).get("rule") or {}
        if rule.get("event") != "formula":
            continue
        for f in glob.glob(os.path.join(RESULTS, r["id"] + ".json")) + glob.glob(os.path.join(RESULTS, r["id"] + "@*.json")):
            b = os.path.basename(f)[:-5]
            sym = b.split("@", 1)[1] if "@" in b else "BTCUSD"
            x = _load(f, {}).get("robot") or {}
            if (x.get("net") or 0) <= 0 or (x.get("trades") or 0) < 20:
                continue
            for side in ("buy", "sell"):
                fm = rule.get(side)
                if fm and (fm, side) not in seen:
                    seen.add((fm, side))
                    out.append({"formula": fm, "side": side, "market": sym, "rid": r["id"], "uid": r.get("by_uid"), "net": x.get("net"),
                                "name": r.get("name_fr") or r["id"]})
    # the ideas Kino measured himself (his questions) that beat chance clearly - seeds too, after the robots
    for q in (_load(os.path.join(HERE, "kino_inner.json"), {}).get("questions") or []):
        try:
            if q.get("status") == "answered" and q.get("formula") and float(q.get("br") or 0) >= 90 and (q["formula"], q.get("side")) not in seen:
                seen.add((q["formula"], q.get("side")))
                out.append({"formula": q["formula"], "side": q.get("side") or "buy", "market": q.get("market") or "BTCUSD", "rid": None,
                            "uid": q.get("uid"), "net": 0, "name": "idée mesurée par Kino : " + str(q.get("q"))[:60]})
        except Exception:
            pass
    return out


def _cost_atr(sym):
    """a round trip's spread in ATR(14) units of the 1-minute candles (the unit of the factory's moves)"""
    import numpy as np
    import robot_demo as RD
    D = RD.data(sym)
    if D is None:
        return None
    R, k = D[0], D[1]
    hl = (R["high"] - R["low"]).astype(float)
    atr = float(np.median(np.convolve(hl, np.ones(14) / 14, mode="valid")))
    try:
        meta = json.load(open(os.path.join(STUDY, "markets", sym, "meta.json"), encoding="utf-8"))
        sp = float(meta.get("spread_med_points") or np.median(R["spread"])) * float(meta["point"]) * float(meta["k"])
    except Exception:
        sp = (float(np.median(R["spread"])) if "spread" in (R.dtype.names or ()) else 0.0) * 0.01 * k if sym != "BTCUSD" else 14.0 * k
    return round(sp / atr, 3) if atr > 0 else None


def measure(formula, side, sym, horizon=30, draws=DRAWS):
    """the idea against `draws` random moments of the same market (idea_stats with more draws), after the spread"""
    import numpy as np
    import robot_demo as RD
    import robot_expr as X
    import robot_tools as T
    D = RD.data(sym)
    if D is None:
        return {"error": "no candles"}
    if not X.is_ok(formula):
        return {"error": "formula refused"}
    R, k, eyes, _ = D
    B = RD._bars(R, eyes)
    tr = X.truth(formula, B)
    h = horizon
    edges = np.flatnonzero(tr & ~np.r_[False, tr[:-1]])
    edges = edges[(edges >= 300) & (edges < len(R) - h - 1)]
    if len(edges) < 20:
        return {"n": int(len(edges)), "error": "too few signals"}
    sd = -1 if side == "sell" else 1
    atr = X.evaluate("atr(14)", B)
    real = T._summ(R, B, edges, sd, h, atr)
    rnd = np.random.default_rng(11)
    pool = np.arange(300, len(R) - h - 1)
    av = [T._summ(R, B, rnd.choice(pool, size=len(edges), replace=False), sd, h, atr).get("avg_move_atr") for _ in range(draws)]
    av = [v for v in av if v is not None]
    beat = round(100.0 * sum(1 for v in av if real["avg_move_atr"] > v) / max(1, len(av)))
    days = (int(R["time"][-1]) - int(R["time"][0])) / 86400.0
    half = len(edges) // 2
    h1 = T._summ(R, B, edges[:half], sd, h, atr).get("avg_move_atr")
    h2 = T._summ(R, B, edges[half:], sd, h, atr).get("avg_move_atr")
    cost = _cost_atr(sym)
    return {"n": int(len(edges)), "per_day": round(len(edges) / max(days, 1), 1), "right_pct": real["right_way_pct"],
            "avg_atr": real["avg_move_atr"], "beats": beat, "halves": [h1, h2], "cost_atr": cost,
            "net_atr": round(real["avg_move_atr"] - (cost or 0), 3) if real["avg_move_atr"] is not None else None}


def _key(f, side, sym):
    return "%s|%s|%s" % (sym, side, re.sub(r"\s+", " ", f.strip()))


def variants(seed, mk):
    """the same idea elsewhere, with a session, with the bigger trend - never a pair already known dead"""
    f, side = seed["formula"], seed["side"]
    tr = "close < ema(close, 50) @ H1" if side == "sell" else "close > ema(close, 50) @ H1"
    V = []
    for m in mk:
        if m != seed["market"]:
            V.append((f, m, "la même idée sur %s" % m))
            V.append(("(%s) and %s" % (f, tr), m, "sur %s, dans le sens de la grande tendance" % m))
    for s_, sn in (("london", "Londres"), ("newyork", "New York"), ("asia", "Asie")):
        V.append(("(%s) and %s" % (f, s_), seed["market"], "seulement pendant la session de %s" % sn))
    V.append(("(%s) and %s" % (f, tr), seed["market"], "dans le sens de la grande tendance (moyenne 1 h)"))
    return V


def lessons_from_results():
    """an idea x market whose real test lost on BOTH halves is dead (not bad luck: the idea did not hold)"""
    R = _reg()
    P = {p["id"]: p for p in R.get("pieces") or []}
    dead = {}
    for r in R.get("robots") or []:
        rule = ((P.get((r.get("parts") or {}).get("entry") or "") or {}).get("rule") or {})
        if rule.get("event") != "formula":
            continue
        for f in glob.glob(os.path.join(RESULTS, r["id"] + ".json")) + glob.glob(os.path.join(RESULTS, r["id"] + "@*.json")):
            b = os.path.basename(f)[:-5]
            sym = b.split("@", 1)[1] if "@" in b else "BTCUSD"
            x = _load(f, {}).get("robot") or {}
            if (x.get("trades") or 0) >= 20 and (x.get("first_half") or 0) < 0 and (x.get("later_half") or 0) < 0:
                for side in ("buy", "sell"):
                    if rule.get(side):
                        dead[_key(rule[side], side, sym)] = {"why": "real test lost on both halves (%+.2f $ then %+.2f $)" % (x["first_half"], x["later_half"]),
                                                             "name": r.get("name_fr") or r["id"], "t": int(time.time())}
    return dead


def factory():
    F = _load(FACTORY, {"tried": {}, "dead": {}, "runs": []})
    F["dead"].update(lessons_from_results())
    mk = markets()
    todo = []
    for s in seeds():
        for f, m, why in variants(s, mk):
            k = _key(f, s["side"], m)
            old = F["tried"].get(k)
            if k in F["dead"] or (old and time.time() - old.get("t", 0) < 14 * 86400):
                continue
            todo.append((s, f, m, why, k))
    todo.sort(key=lambda x: (-(x[0].get("net") or 0)))
    out = []
    for s, f, m, why, k in todo[:MAX_PER_NIGHT]:
        try:
            r = measure(f, s["side"], m)
        except Exception as e:
            r = {"error": str(e)[:120]}
        r.update(formula=f, side=s["side"], market=m, why=why, seed=s["name"], seed_market=s["market"], uid=s.get("uid"), t=int(time.time()))
        F["tried"][k] = r
        out.append(r)
        if not r.get("error") and ((r.get("beats") or 0) < 60 or (r.get("net_atr") or 0) <= 0):
            F["dead"][k] = {"why": "factory: beats only %s%% of random moments, %+.2f ATR after the spread" % (r.get("beats"), r.get("net_atr") or 0),
                            "name": "%s (%s)" % (s["name"], why), "t": int(time.time())}
    good = [r for r in out if not r.get("error") and (r.get("beats") or 0) >= 95 and (r.get("per_day") or 0) >= 1.0
            and (r.get("net_atr") or 0) > 0.1 and min([(h or 0) for h in r.get("halves") or [0]]) >= 0.3 * (r.get("avg_atr") or 0)]
    good.sort(key=lambda r: -(r["net_atr"] * (r["n"] ** 0.5)))
    F["runs"] = (F.get("runs") or [])[-20:] + [{"t": int(time.time()), "measured": len(out), "top": good[:3]}]
    F["tried"] = dict(sorted(F["tried"].items(), key=lambda kv: -kv[1].get("t", 0))[:800])
    _save(FACTORY, F)
    return {"measured": len(out), "top": good[:3], "dead": len(F["dead"])}


def scout():
    """per prepared market: the cost of a round trip against the move, and how many factory ideas beat chance there"""
    F = _load(FACTORY, {"tried": {}})
    rows = []
    for m in markets():
        try:
            c = _cost_atr(m)
        except Exception:
            c = None
        T_ = [r for r in F.get("tried", {}).values() if r.get("market") == m and not r.get("error")]
        rows.append({"market": m, "cost_atr": c, "ideas": len(T_), "beat": sum(1 for r in T_ if (r.get("beats") or 0) >= 95),
                     "verdict": ("cheap" if c is not None and c < 0.15 else "fair" if c is not None and c < 0.35 else "expensive" if c is not None else "?")})
    rows.sort(key=lambda r: (r["cost_atr"] if r["cost_atr"] is not None else 9))
    cand = []
    try:
        import csv
        prep = {r["market"] for r in rows}
        for x in csv.DictReader(open(os.path.join(STUDY, "cost_census.csv"), encoding="utf-8")):
            sym = x["symbol"].rstrip("m")
            if x.get("status") == "ok" and sym not in prep and "Indicator" not in str(x.get("category")) and float(x.get("cost_pct") or 99) < 6 and float(x.get("risk_pct_equity") or 9) < 0.02:
                cand.append({"market": sym, "category": x.get("category"), "cost_pct_of_h1_move": round(float(x["cost_pct"]), 1)})
        cand.sort(key=lambda r: r["cost_pct_of_h1_move"])
    except Exception:
        pass
    S = {"t": int(time.time()), "markets": rows, "worth_preparing": cand[:8],
         "note": "cost = a round trip's spread in units of the 1-minute ATR(14); worth_preparing = cheap markets of the broker (cost census, H1 moves) not prepared yet"}
    _save(SCOUT, S)
    return S


SAY_TWICE_MIN = 40


def self_review(hours=24):
    """Kino's own slips in the last day of conversations (owner's and members', hidden test copies excluded)"""
    import robot_chat as RCx
    now = time.time()
    items = {"numbers": [], "late_promises": [], "twice": [], "permission": [], "menu": [], "corrections": []}
    try:
        for ln in open(os.path.join(HERE, "numcheck.log"), encoding="utf-8").read().splitlines()[-200:]:
            items["numbers"].append(ln[:160])
        items["numbers"] = items["numbers"][-6:]
    except Exception:
        pass
    for f in glob.glob(os.path.join(CHATS, "*.json")):
        if f.endswith("9999999999999.json") or now - os.path.getmtime(f) > hours * 3600:
            continue
        c = _load(f, {})
        if c.get("archived"):
            continue
        A = [m for m in c.get("msgs") or [] if m.get("role") == "ai" and m.get("text") and now - float(m.get("t") or 0) < hours * 3600]
        seen = {}
        for m in A:
            for sn in re.split(r"(?<=[.!?])\s+", str(m["text"])):
                k = re.sub(r"\W+", " ", sn.lower()).strip()
                if len(k) >= SAY_TWICE_MIN:
                    seen[k] = seen.get(k, 0) + 1
                    if seen[k] == 2:
                        items["twice"].append(sn[:140])
            if CORR.search(str(m["text"])):          # 2026-10-23 (owner): a correction = a fact said without checking
                items["corrections"].append(str(m["text"])[:140])
            last = re.split(r"(?<=[.!?])\s+", str(m["text"]).strip())[-1]
            if last.endswith("?") and RCx.PERMISSION.search(last):
                items["permission"].append(last[:140])
            elif last.endswith("?") and re.search(r"\bou\b[^?]{2,60}\?$", last):
                items["menu"].append(last[:140])
        for w in c.get("work") or []:
            if now - float(w.get("due") or now) > 1800:
                items["late_promises"].append(str(w.get("what"))[:140])
    for k in items:
        items[k] = items[k][-5:]
    habits = []
    if items["twice"]:
        habits.append("you said the same sentence twice %d times - say a thing once" % len(items["twice"]))
    if items["permission"]:
        habits.append("you asked permission %d times (\"tu veux que...?\") - decide and say what you do" % len(items["permission"]))
    if items["menu"]:
        habits.append("you offered a menu %d times (\"X ou Y ?\") - pick and say why" % len(items["menu"]))
    if items["late_promises"]:
        habits.append("%d promise(s) were late by more than 30 min - keep the time you give" % len(items["late_promises"]))
    if items["numbers"]:
        habits.append("%d figure(s) you could not point to were cut from quick replies - check before you say" % len(items["numbers"]))
    if items["corrections"]:
        habits.append("you corrected yourself %d time(s) - name the fact and where you read it in your inner voice BEFORE you say it" % len(items["corrections"]))
    fr = []
    if items["twice"]:
        fr.append("il a dit la même phrase deux fois (%d fois) - dire une chose une seule fois" % len(items["twice"]))
    if items["permission"]:
        fr.append("il a demandé la permission %d fois (« tu veux que... ? ») - décider et dire ce qu'il fait" % len(items["permission"]))
    if items["menu"]:
        fr.append("il a proposé un menu %d fois (« X ou Y ? ») - choisir et dire pourquoi" % len(items["menu"]))
    if items["late_promises"]:
        fr.append("%d promesse(s) en retard de plus de 30 min - tenir l'heure donnée" % len(items["late_promises"]))
    if items["numbers"]:
        fr.append("%d chiffre(s) impossibles à justifier retirés de ses réponses rapides - vérifier avant de dire" % len(items["numbers"]))
    if items["corrections"]:
        fr.append("il s'est corrigé %d fois - nommer le fait et où il l'a lu dans sa voix intérieure AVANT de le dire" % len(items["corrections"]))
    R = {"t": int(now), "items": items, "habits": habits, "habits_fr": fr}
    H = _load(REVIEW, {"days": []})
    H["days"] = (H.get("days") or [])[-29:] + [R]
    H["last"] = R
    _save(REVIEW, H)
    return R


CORR = re.compile(r"(\*\s*petite correction|\*\s*small correction|one more fix|quick fix:|that was my slip|my slip|je me suis (planté|trompé)|"
                  r"I mixed (them|it) up|j'ai mélangé|correction\s*:)", re.I)


def habits_block(lang="fr"):
    """2026-10-23 (owner, upgrade 4): last night's self-review, read back by Kino the next day - the loop was open"""
    R = (_load(REVIEW, {}) or {}).get("last") or {}
    H = R.get("habits_fr" if lang != "en" else "habits") or []
    if not H or time.time() - float(R.get("t") or 0) > 3 * 86400:
        return ""
    return ("YOUR HABITS TO FIX TODAY (found by YOUR OWN review of yesterday's messages - fix them without mentioning the review): "
            + " | ".join(H[:4]))


def _lesson_key(f):
    return f[:-5]


def own_lessons(max_new=8):
    """2026-10-23 (owner, upgrade 2: "let him write his own lessons"): one line per (robot, market) that reached a verdict - luck
    test passed or failed, or a test that lost on both halves - written by Kino himself from the numbers (one small model call,
    under the background budget; a plain mechanical line when the budget refuses). Never rewritten once written."""
    import robot_warm as W
    R = _reg()
    P = {p["id"]: p for p in R.get("pieces") or []}
    RB = {r["id"]: r for r in R.get("robots") or []}
    owl = (RB.get("owl") or {}).get("parts") or {}
    Lz = _load(LESSONS, {})
    new = 0
    for f in sorted(os.listdir(RESULTS)) if os.path.isdir(RESULTS) else []:
        if not f.endswith(".json") or new >= max_new:
            continue
        rid = f[:-5].split("@")[0]
        sym = f[:-5].split("@")[1] if "@" in f else "BTCUSD"
        key = _lesson_key(f)
        if rid == "owl" or key in Lz:
            continue
        j = _load(os.path.join(RESULTS, f), {}) or {}
        r = j.get("robot") or {}
        if r.get("net") is None:
            continue
        c = _load(os.path.join(STUDY, "random_control_%s_%s.json" % (rid, sym)), None)
        verdict = None
        if c and c.get("percentile") is not None:
            bt = c.get("beats") if c.get("beats") is not None else sum(1 for x in c.get("nets") or [] if x >= float((c.get("real") or {}).get("net") or 0))
            verdict = ("PASSED the luck test (%s of %s random robots as good)" % (bt, c.get("seeds"))) if (c.get("seeds") or 0) >= 100 and bt <= 5 else \
                      ("FAILED the luck test (%s random robots did as well)" % bt)
        elif (r.get("first_half") or 0) < 0 and (r.get("later_half") or 0) < 0:
            verdict = "lost on BOTH halves of its test"
        elif float(r["net"]) <= 0:
            verdict = "lost over the whole test"
        if not verdict:
            continue
        parts = j.get("parts") or {}
        diff = []
        for kk in ("entry", "stop", "exit", "recovery", "money"):
            if parts.get(kk) and parts.get(kk) != owl.get(kk):
                diff.append("%s: %s" % (kk, ((P.get(parts[kk]) or {}).get("plain_en") or parts[kk])[:100]))
        of, nf = set(owl.get("filters") or []), set(parts.get("filters") or [])
        if of - nf:
            diff.append("without the Owl's " + ", ".join(sorted((P.get(x) or {}).get("name_en") or x for x in of - nf)))
        if nf - of:
            diff.append("filters added: " + "; ".join(((P.get(x) or {}).get("plain_en") or x)[:80] for x in sorted(nf - of)))
        facts = ("robot '%s' on %s: %s. Result %+.2f $ over %s trades (win rate %s, worst dip %s $, halves %+.2f / %+.2f; the Owl there %+.2f $). "
                 "Verdict: %s." % ((RB.get(rid) or {}).get("name_fr") or rid, sym, "; ".join(diff) or "the Owl's pieces", float(r["net"]), r.get("trades"),
                                   r.get("win_rate"), r.get("cc_dd"), float(r.get("first_half") or 0), float(r.get("later_half") or 0),
                                   float((j.get("parent_result") or {}).get("net") or 0), verdict))
        line = None
        try:
            raw = W.ask_json("You are Kino, a trading-robot builder, writing ONE lesson for yourself after a verdict. Plain words, one sentence of at "
                             "most 28 words, in English: what this verdict teaches about the IDEA (not the number), honest, no hype, no promise. "
                             "Reply with JSON only: {\"lesson\": \"...\"}", facts, models=("haiku",), timeout=60, warm=False)
            if isinstance(raw, dict) and str(raw.get("lesson") or "").strip():
                line = str(raw["lesson"]).strip()[:220]
        except Exception:
            line = None
        if not line:
            line = "%s on %s (%s): %s - %+.2f $ over %s trades." % ((RB.get(rid) or {}).get("name_fr") or rid, sym, "; ".join(diff) or "the Owl's pieces",
                                                                  verdict, float(r["net"]), r.get("trades"))
        Lz[key] = {"t": int(time.time()), "rid": rid, "sym": sym, "verdict": verdict, "line": line, "by": "kino" if line and raw else "facts"}
        new += 1
    if new:
        _save(LESSONS, Lz)
    return {"new": new, "total": len(Lz)}


def lessons_block():
    Lz = _load(LESSONS, {}) or {}
    if not Lz:
        return ""
    rows = sorted(Lz.values(), key=lambda x: -x.get("t", 0))[:30]
    return ("YOUR OWN LESSONS (written by you, one per verdict - these are what you know for real; an idea marked FAILED is not "
            "rebuilt as it was, a PASSED one is the model to start from):\n" + "\n".join("- [%s] %s" % (x.get("sym"), x.get("line")) for x in rows))


def board(uid):
    """the research board of one member: each idea / robot at its stage, with Kino's note"""
    R = _reg()
    rows = []
    try:
        sd = os.path.join(STUDY, "luck")
        Q = _load(os.path.join(sd, "queue.json"), [])
    except Exception:
        Q = []
    for r in R.get("robots") or []:
        if r.get("by_uid") != uid or r.get("id") == "owl" or r.get("archived"):
            continue
        for f in (glob.glob(os.path.join(RESULTS, r["id"] + ".json")) + glob.glob(os.path.join(RESULTS, r["id"] + "@*.json"))) or [None]:
            sym = (os.path.basename(f)[:-5].split("@", 1) + ["BTCUSD"])[1] if f else (r.get("market") or "BTCUSD")
            x = (_load(f, {}).get("robot") or {}) if f else {}
            st = _load(os.path.join(STUDY, "luck", "%s_%s.status.json" % (r["id"], sym)), {})
            stage, note = "idea", "pas encore testé"
            if x.get("net") is not None:
                stage, note = "tested", "%+.2f $ sur %s trades" % (float(x["net"]), x.get("trades"))
                if float(x["net"]) <= 0:
                    stage = "dead"
            if st.get("state") in ("running", "paused"):
                stage, note = "luck", "test de chance %s/100" % (st.get("n") or 0)
            elif any(e.get("rid") == r["id"] and e.get("sym") == sym for e in Q) and st.get("state") not in ("pass", "fail") and stage == "tested":
                stage, note = "luck", "test de chance en file"
            if st.get("state") == "pass":
                stage, note = "proven", "prouvé contre le hasard"
            elif st.get("state") == "fail" and stage != "dead":
                stage, note = "dead", "pas prouvé contre le hasard"
            rows.append({"rid": r["id"], "name": r.get("name_fr") or r["id"], "market": sym, "stage": stage, "note": note})
    F = _load(FACTORY, {"runs": []})
    top = ((F.get("runs") or [{}])[-1] or {}).get("top") or []
    for c in top:
        rows.append({"rid": None, "name": "%s - %s" % (c.get("seed"), c.get("why")), "market": c.get("market"), "stage": "measured",
                     "note": "bat %s%% du hasard, %s signaux/jour, %+.2f ATR après le spread" % (c.get("beats"), c.get("per_day"), c.get("net_atr") or 0)})
    return rows


if __name__ == "__main__":
    try:
        import ctypes
        ctypes.windll.kernel32.SetPriorityClass(ctypes.windll.kernel32.GetCurrentProcess(), 0x00004000)   # below normal
    except Exception:
        pass
    a = sys.argv[1:] or ["night"]
    out = {}
    if a[0] in ("night", "factory"):
        out["factory"] = factory()
    if a[0] == "scout" or (a[0] == "night" and (time.gmtime().tm_wday == 0 or not os.path.exists(SCOUT))):
        out["scout"] = scout()
    if a[0] in ("night", "review"):
        out["review"] = self_review()
    if a[0] in ("night", "lessons"):
        out["lessons"] = own_lessons()
    print(json.dumps(out, ensure_ascii=False)[:3000])
