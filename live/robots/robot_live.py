"""The LIVE bot's side of the piece language (owner 2026-10-13, step 4).

structure_bos_bot.py calls these pure functions only when the account's package carries `robot_rules` (a robot
plugged onto it); with no rules every function says "no change" and the bot behaves exactly as before.
The decisions mirror the bench's interpreter (study/robot_dsl_arm.py) - live/robots/test_robot_live.py checks
both on the same cases:
  entry_ok    BOS only / CHoCH only            (bench: DslArm._entry_ok)
  filters_ok  hours, weekdays, pace, moves     (bench: DslArm.late_gates, at the weather brakes' position)
  stop_for    protected + margin, break candle + margin, fixed distance   (bench: DslArm._with_stop)
  tp_for      target N x risk, or none                                  (bench: rr / no tp)
  manage      on an open trade: CHoCH against it, time limit, breakeven (bench: DslArm.signal / tick)
"""

KIND_EVENT = {"FLIP-BOS": "choch", "BOS": "bos", "TOUCH": "bos", "INT": "bos"}


def entry_ok(rules, kind):
    en = (rules or {}).get("entry")
    if not en or en.get("event") == "any":
        return True, ""
    ev = KIND_EVENT.get(kind, "bos")
    if en["event"] != ev:
        return False, ("seulement les CHoCH" if en["event"] == "choch" else "seulement les BOS")
    return True, ""


def filters_ok(rules, hour, weekday, nerv, moves_2h):
    """nerv = the weather card's vol_now / vol_ref (the bot's nervosity), moves_2h = its big moves in 2 h"""
    for f in (rules or {}).get("filters") or []:
        k = f.get("kind")
        if k == "hours" and not (f["from"] <= int(hour) < f["to"]):
            return False, "en dehors des heures %d h - %d h UTC" % (f["from"], f["to"])
        if k == "weekdays" and int(weekday) not in f["days"]:
            return False, "pas un des jours choisis"
        if k == "pace" and nerv is not None:
            if f.get("min") is not None and nerv < f["min"]:
                return False, "marche trop lent (%.2fx < %.2fx)" % (nerv, f["min"])
            if f.get("max") is not None and nerv > f["max"]:
                return False, "marche trop rapide (%.2fx > %.2fx)" % (nerv, f["max"])
        if k == "moves" and moves_2h is not None and int(moves_2h) < f["min"]:
            return False, "pas assez de grands mouvements (%d < %d)" % (int(moves_2h), f["min"])
    return True, ""


def stop_for(rules, d, slp, close, bar_low, bar_high):
    """the stop price; `slp` = the protected point the structure gave, close / bar_* = the break candle"""
    st = (rules or {}).get("stop")
    if not st:
        return slp
    if st["kind"] == "protected":
        return slp - d * float(st.get("buffer") or 0)
    if st["kind"] == "break_candle":
        return (bar_low if d == 1 else bar_high) - d * float(st.get("buffer") or 0)
    if st["kind"] == "fixed":
        return close - d * float(st["points"])
    return slp


def tp_for(rules, d, e, dist, rr):
    """the target price; 0 = no target order (MT5: no TP)"""
    ex = (rules or {}).get("exit")
    if not ex:
        return e + d * rr * dist
    if ex.get("target") is None:
        return 0.0
    return e + d * float(ex["target"]) * dist


def manage(rules, d, e, sl, opened_at, now, price, choch_against, be_done):
    """what to do with the open main trade now: None, ("close", why) or ("sl", new stop)"""
    ex = (rules or {}).get("exit")
    if not ex:
        return None
    if ex.get("choch") and choch_against:
        return ("close", "CHoCH contre le trade")
    if ex.get("time_min") and now - opened_at >= int(ex["time_min"]) * 60:
        return ("close", "duree maximum %d min" % int(ex["time_min"]))
    if ex.get("breakeven_at") and not be_done and sl and d * (price - e) >= float(ex["breakeven_at"]) * abs(e - sl):
        return ("sl", e)
    return None
