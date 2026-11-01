"""robot_after.py - robot rules that depend on the LAST TRADE'S RESULT (owner 2026-11-01: "normally a 1:1 trade on the
2-chart entry; if that trade hits its stop-loss, IMMEDIATELY take the reverse trade when price breaks structure in the
new direction, this time 1:2" - the builder had told him it could not give one trade another target after a loss).

Shared, word for word, by the bench (study/robot_dsl_arm.py through study/robot_runner.py), the member's desk
(owl_manual_trader.robot_tick) and the builder (robot_chat.clean, owl_app_server) - so backtest = live.

1. A TARGET FORMULA. exit.target (in R = times the risk) may be a formula in robot_lot's language, read at the signal
   with the robot's own closed trades, e.g.  "2 if last_hit_sl else 1"   "2 if last_pnl < 0 else 1"
   names: robot_lot.NAMES (losses_since_peak loss_streak win_streak trades wins losses net peak drawdown balance
   start_balance last_pnl) + last_dir (+1 buy / -1 sell of the last closed trade, 0 before any) + last_hit_sl (1 when
   the last trade closed on its stop-loss, else 0). The value is clamped to T_LO..T_HI R.

2. AFTER A STOP-OUT. robot["after_loss"] (rules form; robots.json parts hold piece ids instead of the rules):
     {"entry": ENTRY RULE,               the trigger of the next trade, e.g. {"event": "any"} = the next structure break
      "stop": STOP RULE | null,          null = the robot's own stop
      "direction": "reverse" | "same" | "any",   vs the stopped trade (reverse: a buy after a stopped sell)
      "target": R | TARGET FORMULA | null,       null = the robot's own target
      "on": "sl" | "loss",               sl (default) = the last trade closed on its stop with a loss; loss = any losing close
      "expire_min": 5..10080 | null}     give up waiting after N minutes (null = wait for the trigger)
   It applies to ONE trade: the one right after such a stop-out of a NORMAL trade. While it waits, the robot's normal
   entry is off; once that trade closes (whatever its result) the robot is back to normal.
"""
import robot_lot as L

DIRS = ("reverse", "same", "any")
ONS = ("sl", "loss")
T_LO, T_HI = 0.3, 5.0          # the same range as a fixed target piece (robot_dsl: target 0.3..5)


def is_formula(t):
    return isinstance(t, str)


def check_target(t):
    """(True, cleaned) or (False, reason): None, a number 0.3..5 or a formula over the history"""
    if t is None:
        return True, None
    if is_formula(t):
        try:
            L.check(t)
        except L.LotError as e:
            return False, "target formula: %s" % e
        return True, " ".join(t.split())
    try:
        f = float(t)
    except Exception:
        return False, "target"
    if not (T_LO <= f <= T_HI):
        return False, "target_range"
    return True, round(f, 2)


def target_r(t, V=None, default=None):
    """the target in R for the next trade: a number as is, a formula computed with the history names V"""
    if t is None:
        return default
    if not is_formula(t):
        return float(t)
    v = L._ev(L.check(t), V or {})
    if not (v == v):
        return default if default is not None else 1.0
    return round(max(T_LO, min(T_HI, v)), 4)


def uses(rules):
    """does this robot need its own trade history (a target formula or an after_loss block)?"""
    r = rules or {}
    return bool(r.get("after_loss")) or is_formula((r.get("exit") or {}).get("target"))


def validate(al, check_rule):
    """(True, cleaned) or (False, reason); check_rule(kind, rule) = robot_dsl.validate (the caller passes it, so this
    module has no numpy import for the desk)"""
    if not isinstance(al, dict):
        return False, "after_loss"
    ok, en = check_rule("entry", al.get("entry"))
    if not ok:
        return False, "after_loss entry: %s" % en
    if en.get("order"):
        return False, "after_loss entry: no waiting order here"
    st = None
    if al.get("stop") is not None:
        ok, st = check_rule("stop", al["stop"])
        if not ok:
            return False, "after_loss stop: %s" % st
    d = al.get("direction") or "reverse"
    if d not in DIRS:
        return False, "after_loss direction"
    on = al.get("on") or "sl"
    if on not in ONS:
        return False, "after_loss on"
    ok, tg = check_target(al.get("target"))
    if not ok:
        return False, "after_loss " + tg
    ex = al.get("expire_min")
    if ex is not None:
        try:
            ex = int(ex)
        except Exception:
            return False, "after_loss expire_min"
        if not 5 <= ex <= 10080:
            return False, "after_loss expire_min"
    return True, {"entry": en, "stop": st, "direction": d, "target": tg, "on": on, "expire_min": ex}


def from_parts(al, P):
    """robots.json form {"entry": piece id, "stop": piece id | null, direction, target, on, expire_min} -> the rules
    form; P = pieces by id. The Owl's engine pieces read as rules: its break entry = every break ("any"), the protected
    point = {"kind": "protected"}. None = no block, or a piece that cannot be read (the robot then has no after-loss)."""
    if not isinstance(al, dict) or not al.get("entry"):
        return None
    pe = P.get(al["entry"]) or {}
    en = pe.get("rule") or ({"event": "any"} if pe.get("type") == "entry" and pe.get("live") else None)
    if not en:
        return None
    st = None
    if al.get("stop"):
        ps = P.get(al["stop"]) or {}
        st = ps.get("rule") or ({"kind": "protected", "buffer": 0.0} if (ps.get("engine") or {}).get("stop") == "protected" else None)
        if st is None:
            return None
    return {"entry": en, "stop": st, "direction": al.get("direction") or "reverse", "target": al.get("target"),
            "on": al.get("on") or "sl", "expire_min": al.get("expire_min")}


def pending(al, last, now=None):
    """the side the after-loss trade must take: +1 / -1, 0 = either side; None = normal mode.
    last = the robot's last CLOSED trade {"d", "hit_sl", "pnl", "al", "tc"} (robot_lot.History.last_trade) or None;
    now = the time (s) of the decision, for expire_min"""
    if not al or not last:
        return None
    if last.get("al"):                       # the after-loss trade itself closed: back to normal, whatever its result
        return None
    pnl = float(last.get("pnl") or 0.0)
    if (al.get("on") or "sl") == "sl":
        if not (last.get("hit_sl") and pnl < 0):
            return None
    elif pnl >= 0:
        return None
    ex = al.get("expire_min")
    if ex and now is not None and last.get("tc") is not None and float(now) - float(last["tc"]) > int(ex) * 60:
        return None
    d = int(last.get("d") or 0)
    dr = al.get("direction") or "reverse"
    return 0 if dr == "any" or not d else (-d if dr == "reverse" else d)


def rules_for(rules, al):
    """the robot's rules for the after-loss trade: its entry, its stop (or the robot's), its target (or the robot's);
    every other part (filters, exit timing, breakeven) stays the robot's"""
    r = dict(rules or {})
    r["entry"] = al["entry"]
    if al.get("stop"):
        r["stop"] = al["stop"]
    if al.get("target") is not None:
        ex = dict(r.get("exit") or {"target": None, "choch": False, "time_min": None, "breakeven_at": None})
        ex["target"] = al["target"]
        ex.pop("levels", None)               # the member said "this time 1:2": a plain R target
        r["exit"] = ex
    r.pop("after_loss", None)
    return r


def describe(al, entry_rule=None):
    """(fr, en) plain words; entry_rule = the trigger's rule when al["entry"] is not one (a piece slot)"""
    side = {"reverse": ("dans le sens inverse du trade perdu", "in the opposite direction of the lost trade"),
            "same": ("dans le même sens que le trade perdu", "in the same direction as the lost trade"),
            "any": ("dans un sens ou l'autre", "either way")}[al.get("direction") or "reverse"]
    on = ("touche son stop" if (al.get("on") or "sl") == "sl" else "perd", "hits its stop" if (al.get("on") or "sl") == "sl" else "loses")
    t = al.get("target")
    tw = ("", "") if t is None else ((" avec un objectif de %s fois le risque" % ("%g" % t).replace(".", ","), " with a target of %g times the risk" % t)
                                     if not is_formula(t) else (" avec l'objectif « %s » fois le risque" % t, " with the target '%s' times the risk" % t))
    er = al.get("entry") if isinstance(al.get("entry"), dict) and al["entry"].get("event") else (entry_rule or {})
    ew = {"bos": ("à la prochaine cassure qui continue la tendance (BOS)", "on the next break that continues the trend (BOS)"),
          "choch": ("au prochain changement de structure (CHoCH)", "on the next change of structure (CHoCH)"),
          "formula": ("quand sa formule d'entrée devient vraie", "when its entry formula turns true")}.get(
        er.get("event"), ("à la prochaine cassure de structure", "on the next structure break"))
    ex = al.get("expire_min")
    xw = ("", "") if not ex else (" (abandonné après %d min)" % ex, " (given up after %d min)" % ex)
    return ("Quand un trade %s, le trade suivant se prend %s, %s%s%s, puis le robot reprend sa règle normale." % (on[0], side[0], ew[0], tw[0], xw[0]),
            "When a trade %s, the next trade is taken %s, %s%s%s, then the robot goes back to its normal rule." % (on[1], side[1], ew[1], tw[1], xw[1]))


if __name__ == "__main__":
    al = {"entry": {"event": "any"}, "stop": None, "direction": "reverse", "target": 2.0, "on": "sl", "expire_min": None}
    assert pending(al, None) is None
    assert pending(al, {"d": -1, "hit_sl": True, "pnl": -2.0, "al": False, "tc": 0}) == 1          # stopped sell -> buy
    assert pending(al, {"d": 1, "hit_sl": True, "pnl": -2.0, "al": True, "tc": 0}) is None         # the reversal closed
    assert pending(al, {"d": 1, "hit_sl": False, "pnl": -0.5, "al": False, "tc": 0}) is None       # a time exit, not a stop
    assert pending(dict(al, on="loss"), {"d": 1, "hit_sl": False, "pnl": -0.5, "al": False, "tc": 0}) == -1
    assert pending(dict(al, expire_min=30), {"d": 1, "hit_sl": True, "pnl": -1, "al": False, "tc": 0}, now=1801) is None
    assert target_r("2 if last_hit_sl else 1", {"last_hit_sl": 1}) == 2.0 and target_r("2 if last_hit_sl else 1", {}) == 1.0
    assert target_r(1.5) == 1.5 and target_r(None, default=0.8) == 0.8 and target_r("99", {}) == T_HI
    assert check_target("2 if last_dir < 0 else 1")[0] and not check_target("open('x')")[0] and not check_target(9)[0]
    print("ok")
