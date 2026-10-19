"""The piece language of the robot builder (owner 2026-10-13, step 2).

A piece written in this language is a small JSON `rule` built ONLY from what the eyes (the nest's structure)
already see: the break that fired (BOS or CHoCH, at a candle close), its protected point, the break candle, the
market's pace, the big moves of the last 2 hours, the hour and the weekday, the R multiple of an open trade, the
main-structure CHoCH. Nothing else - so every piece is testable on the bench (study/robot_dsl_arm.py) and can later
be run by the live bot with the same interpreter (step 4).

Kinds and fields (every number has a range; anything else is refused):
  entry   {"event": "any" | "bos" | "choch"}                     which breaks may open a trade (always at the close)
  filter  {"kind": "hours",    "from": 0..23, "to": 1..24}         trade only between these UTC hours (from < to)
          {"kind": "weekdays", "days": [0..6]}                     trade only on these days (0 = Monday)
          {"kind": "pace",     "min": 0.3..3 | null, "max": 0.3..3 | null}   market pace vs usual (1 = usual)
          {"kind": "moves",    "min": 1..10}                       at least N big moves in the last 2 hours
  stop    {"kind": "protected", "buffer": 0..500}                  the protected point, N points further
          {"kind": "break_candle", "buffer": 0..500}               beyond the break candle's low (buy) / high (sell)
          {"kind": "fixed", "points": 20..3000}                    always N points from the close
  exit    {"target": 0.3..5 | null, "choch": bool, "time_min": 5..1440 | null, "breakeven_at": 0.2..3 | null}
          the first that happens closes the trade; breakeven moves the stop to the entry once the trade has
          gained that many R; at least one of target / choch / time_min is required (the stop is always there)
"""

KINDS = ("entry", "filter", "stop", "exit")

# 2026-10-19 (owner: "even if the piece doesn't exist the AI creates it"): FORMULA pieces - written in the formula
# language of robot_expr.py (checked against its whitelist, computed by the bench, never executed as code):
#   entry   {"event": "formula", "buy": F | null, "sell": F | null}   a trade at the close of the candle where F
#                                                                    becomes true (at least one side)
#   filter  {"kind": "formula", "buy": F | null, "sell": F | null}    the trade is allowed only when F is true at
#                                                                    its candle (one side null = that side free)
#   stop    {"kind": "formula", "buy": P | null, "sell": P | null}    the stop PRICE (P = a price formula, e.g.
#                                                                    "lowest(low, 10)" or "close - 2 * atr(14)")
#   exit    adds "close_buy": F | null, "close_sell": F | null        closes the trade at the close of the candle
#                                                                    where F is true (counts as an exit on its own)
# Formula pieces run on the bench only for now (live: false) - the live bot reads the fixed language.
import robot_expr as X


def _formula(v, nullable=True):
    if v is None or (isinstance(v, str) and not v.strip()):
        return nullable, None
    if not isinstance(v, str):
        return False, None
    ok, why = X.is_ok(v)
    return (ok, " ".join(v.split())) if ok else (False, why)


def _sides(rule, need_one=True):
    oa, a = _formula(rule.get("buy")); ob, b = _formula(rule.get("sell"))
    if not oa or not ob:
        return False, "formula: " + str(a if not oa else b)
    if need_one and a is None and b is None:
        return False, "formula: empty"
    return True, (a, b)


def is_formula(kind, rule):
    rule = rule or {}
    return (kind == "entry" and rule.get("event") == "formula") or (kind in ("filter", "stop") and rule.get("kind") == "formula")         or (kind == "exit" and bool(rule.get("close_buy") or rule.get("close_sell")))


def _num(v, lo, hi, nullable=False):
    if v is None:
        return nullable
    try:
        f = float(v)
    except Exception:
        return False
    return lo <= f <= hi


def validate(kind, rule):
    """(True, cleaned rule) or (False, error code)"""
    if kind not in KINDS or not isinstance(rule, dict):
        return False, "kind"
    if kind == "entry":
        if rule.get("event") == "formula":
            ok, ab = _sides(rule)
            return (True, {"event": "formula", "buy": ab[0], "sell": ab[1]}) if ok else (False, ab)
        if rule.get("event") not in ("any", "bos", "choch"):
            return False, "event"
        return True, {"event": rule["event"]}
    if kind == "filter":
        k = rule.get("kind")
        if k == "formula":
            ok, ab = _sides(rule)
            return (True, {"kind": "formula", "buy": ab[0], "sell": ab[1]}) if ok else (False, ab)
        if k == "hours":
            if not (_num(rule.get("from"), 0, 23) and _num(rule.get("to"), 1, 24)) or int(rule["from"]) >= int(rule["to"]):
                return False, "hours"
            return True, {"kind": "hours", "from": int(rule["from"]), "to": int(rule["to"])}
        if k == "weekdays":
            D = rule.get("days")
            if not isinstance(D, list) or not D or any(not isinstance(x, int) or x < 0 or x > 6 for x in D) or len(set(D)) != len(D) or len(D) == 7:
                return False, "days"
            return True, {"kind": "weekdays", "days": sorted(D)}
        if k == "pace":
            mn, mx = rule.get("min"), rule.get("max")
            if not (_num(mn, 0.3, 3, True) and _num(mx, 0.3, 3, True)) or (mn is None and mx is None) or (mn is not None and mx is not None and float(mn) >= float(mx)):
                return False, "pace"
            return True, {"kind": "pace", "min": None if mn is None else round(float(mn), 2), "max": None if mx is None else round(float(mx), 2)}
        if k == "moves":
            if not _num(rule.get("min"), 1, 10):
                return False, "moves"
            return True, {"kind": "moves", "min": int(rule["min"])}
        return False, "filter"
    if kind == "stop":
        k = rule.get("kind")
        if k in ("protected", "break_candle"):
            b = rule.get("buffer", 0) or 0
            if not _num(b, 0, 500):
                return False, "buffer"
            return True, {"kind": k, "buffer": round(float(b), 1)}
        if k == "formula":
            ok, ab = _sides(rule)
            return (True, {"kind": "formula", "buy": ab[0], "sell": ab[1]}) if ok else (False, ab)
        if k == "fixed":
            if not _num(rule.get("points"), 20, 3000):
                return False, "points"
            return True, {"kind": "fixed", "points": round(float(rule["points"]), 1)}
        return False, "stop"
    # exit
    t, c, tm, be = rule.get("target"), bool(rule.get("choch")), rule.get("time_min"), rule.get("breakeven_at")
    if not (_num(t, 0.3, 5, True) and _num(tm, 5, 1440, True) and _num(be, 0.2, 3, True)):
        return False, "exit_range"
    oa, cb = _formula(rule.get("close_buy")); ob, cs = _formula(rule.get("close_sell"))
    if not oa or not ob:
        return False, "formula: " + str(cb if not oa else cs)
    if t is None and not c and tm is None and cb is None and cs is None:
        return False, "exit_none"
    if be is not None and t is not None and float(be) >= float(t):
        return False, "breakeven"
    out = {"target": None if t is None else round(float(t), 2), "choch": c, "time_min": None if tm is None else int(tm),
           "breakeven_at": None if be is None else round(float(be), 2)}
    if cb is not None or cs is not None:
        out.update(close_buy=cb, close_sell=cs)
    return True, out


DAYS_FR = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
DAYS_EN = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def _f(x):
    s = ("%g" % x)
    return s, s.replace(".", ",")


def _fside(rule, a, b, lead_fr, lead_en):
    fr, en = [], []
    if rule.get(a):
        fr.append("à l'achat : %s" % rule[a]); en.append("to buy: %s" % rule[a])
    if rule.get(b):
        fr.append("à la vente : %s" % rule[b]); en.append("to sell: %s" % rule[b])
    return lead_fr + " ; ".join(fr) + ".", lead_en + "; ".join(en) + "."


def describe(kind, rule):
    """the piece in plain words, (fr, en) - generated, so the words always say what the rule does"""
    if kind == "entry" and rule.get("event") == "formula":
        return _fside(rule, "buy", "sell", "Entre à la clôture de la bougie où la formule devient vraie, ", "Enters at the close of the candle where the formula turns true, ")
    if kind == "filter" and rule.get("kind") == "formula":
        return _fside(rule, "buy", "sell", "Trade seulement si la formule est vraie, ", "Trades only when the formula is true, ")
    if kind == "stop" and rule.get("kind") == "formula":
        return _fside(rule, "buy", "sell", "Stop au prix donné par la formule, ", "Stop at the price given by the formula, ")
    if kind == "entry":
        return {"any": ("Entre à la clôture de chaque cassure de structure (BOS ou CHoCH).", "Enters at the close of every structure break (BOS or CHoCH)."),
                "bos": ("Entre seulement sur les cassures qui continuent la tendance (BOS), à la clôture.", "Enters only on breaks that continue the trend (BOS), at the close."),
                "choch": ("Entre seulement quand la structure change de sens (CHoCH), à la clôture.", "Enters only when the structure changes direction (CHoCH), at the close.")}[rule["event"]]
    if kind == "filter":
        k = rule["kind"]
        if k == "hours":
            return ("Trade seulement entre %d h et %d h (UTC)." % (rule["from"], rule["to"]), "Trades only between %02d:00 and %02d:00 UTC." % (rule["from"], rule["to"]))
        if k == "weekdays":
            return ("Trade seulement le " + ", ".join(DAYS_FR[d] for d in rule["days"]) + ".", "Trades only on " + ", ".join(DAYS_EN[d] for d in rule["days"]) + ".")
        if k == "pace":
            mn, mx = rule["min"], rule["max"]
            fr, en = [], []
            if mn is not None:
                fr.append("au moins %s fois son rythme habituel" % _f(mn)[1]); en.append("at least %s times its usual pace" % _f(mn)[0])
            if mx is not None:
                fr.append("au plus %s fois son rythme habituel" % _f(mx)[1]); en.append("at most %s times its usual pace" % _f(mx)[0])
            return ("Trade seulement quand le marché va " + " et ".join(fr) + ".", "Trades only when the market moves " + " and ".join(en) + ".")
        if k == "moves":
            return ("Trade seulement après au moins %d grands mouvements dans les 2 dernières heures." % rule["min"],
                    "Trades only after at least %d big moves in the last 2 hours." % rule["min"])
    if kind == "stop":
        k = rule["kind"]
        if k == "protected":
            b = rule["buffer"]
            return ("Stop sur le point protégé" + (", %s points plus loin." % _f(b)[1] if b else "."), "Stop on the protected point" + (", %s points further." % _f(b)[0] if b else "."))
        if k == "break_candle":
            b = rule["buffer"]
            return ("Stop de l'autre côté de la bougie de cassure" + (", %s points plus loin." % _f(b)[1] if b else "."),
                    "Stop on the other side of the break candle" + (", %s points further." % _f(b)[0] if b else "."))
        return ("Stop toujours à %s points de l'entrée." % _f(rule["points"])[1], "Stop always %s points from the entry." % _f(rule["points"])[0])
    fr, en = [], []
    if rule.get("target") is not None:
        fr.append("à %s fois le risque" % _f(rule["target"])[1]); en.append("at %s times the risk" % _f(rule["target"])[0])
    if rule.get("choch"):
        fr.append("au CHoCH contre le trade"); en.append("on a CHoCH against the trade")
    if rule.get("time_min") is not None:
        fr.append("après %d minutes" % rule["time_min"]); en.append("after %d minutes" % rule["time_min"])
    if rule.get("close_buy"):
        fr.append("quand « %s » (achat)" % rule["close_buy"]); en.append("when '%s' (buy)" % rule["close_buy"])
    if rule.get("close_sell"):
        fr.append("quand « %s » (vente)" % rule["close_sell"]); en.append("when '%s' (sell)" % rule["close_sell"])
    many = len(fr) > 1
    s_fr = "Ferme " + ", ".join(fr[:-1]) + (" ou " if many else "") + fr[-1] + (" (le premier qui arrive)" if many else "") + ", ou au stop."
    s_en = "Closes " + ", ".join(en[:-1]) + (" or " if many else "") + en[-1] + (" (whichever comes first)" if many else "") + ", or at the stop."
    if rule.get("breakeven_at") is not None:
        s_fr += " Le stop passe au prix d'entrée dès que le trade gagne %s R." % _f(rule["breakeven_at"])[1]
        s_en += " The stop moves to the entry price once the trade gains %sR." % _f(rule["breakeven_at"])[0]
    return s_fr, s_en
