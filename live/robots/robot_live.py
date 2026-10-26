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
2026-10-19 FORMULA pieces (robot_expr): the bot keeps its own memory of 1-minute candles (Candles) and asks
  formula_entry  a buy / sell formula that turned true at the candle that just closed (bench: robot_runner.robot_opps)
  filters_ok     a formula filter true at that candle, for the trade's side          (bench: DslArm.late_gates)
  stop_for       a formula stop price at that candle                                (bench: DslArm._with_stop)
  formula_exit   a close formula true at that candle                                 (bench: DslArm.tick)
  Every value is read at the LAST candle of the memory; the formula language never looks ahead, so it is the same
  number the bench reads at that candle over its whole array.
"""
try:
    import numpy as np
    import robot_expr as X
except Exception:              # an account without formula pieces never needs them
    np = X = None

KIND_EVENT = {"FLIP-BOS": "choch", "BOS": "bos", "TOUCH": "bos", "INT": "bos"}


def uses_formulas(rules):
    r = rules or {}
    ex = r.get("exit") or {}
    return (r.get("entry") or {}).get("event") == "formula" or (r.get("stop") or {}).get("kind") == "formula" \
        or any(f.get("kind") == "formula" for f in r.get("filters") or []) or bool(ex.get("close_buy") or ex.get("close_sell"))


class Candles:
    """the bot's memory of closed 1-minute candles + the eyes' facts on each (what a formula reads)"""
    KEEP = 60000                       # ~42 days, the bench's window

    def __init__(self):
        self.rows = []                 # (t, o, h, l, c, v, bos_up, bos_down, choch_up, choch_down, trend)
        self.pb = []                   # 2026-10-26: per row, the pullback chart's facts (robot_expr.PB order) or None
        self.trend = 0
        self._B = None
        self._memo = {}

    def add(self, t, o, h, l, c, v, d=0, flip=False, trend=None, pb=None):
        """one closed candle; d = the eyes' break on it (+1 / -1 / 0), flip = that break turned the trend,
        trend = the background trend read at that break (kept until the next break, as the bench does)"""
        if self.rows and int(t) <= self.rows[-1][0]:
            return
        if d and trend in (1, -1):             # "no trend" keeps the last one (bench: eyes_from_opps)
            self.trend = int(trend)
        self.rows.append((int(t), float(o), float(h), float(l), float(c), float(v),
                          1.0 if d == 1 and not flip else 0.0, 1.0 if d == -1 and not flip else 0.0,
                          1.0 if d == 1 and flip else 0.0, 1.0 if d == -1 and flip else 0.0, float(self.trend)))
        self.pb.append(pb)
        if len(self.rows) > self.KEEP + 500:
            del self.rows[:len(self.rows) - self.KEEP]
            del self.pb[:len(self.pb) - self.KEEP]
        self._B = None
        self._memo = {}

    def bars(self):
        if self._B is None:
            A = np.array(self.rows, dtype=float).reshape(-1, 11)
            eyes = {k: A[:, 6 + j] for j, k in enumerate(("bos_up", "bos_down", "choch_up", "choch_down", "trend"))}
            if any(p is not None for p in self.pb):
                P = np.array([p if p is not None else [np.nan] * len(X.PB) for p in self.pb], dtype=float).reshape(-1, len(X.PB))
                eyes.update({k: P[:, j] for j, k in enumerate(X.PB)})
            self._B = X.Bars(A[:, 0].astype(np.int64), A[:, 1], A[:, 2], A[:, 3], A[:, 4], A[:, 5], eyes)
        return self._B

    def values(self, src):
        """the formula over the whole memory (computed once per new candle)"""
        if src not in self._memo:
            self._memo[src] = X.evaluate(src, self.bars())
        return self._memo[src]

    def now(self, src):
        """the formula's value at the last closed candle (nan = unknown)"""
        if not self.rows:
            return float("nan")
        return float(self.values(src)[-1])

    def true_now(self, src):
        v = self.now(src)
        return v == v and v != 0

    def turned_true(self, src):
        """true at the last candle and not at the one before (the bench's edge)"""
        if len(self.rows) < 2:
            return False
        a = self.values(src)
        return bool(a[-1] == a[-1] and a[-1] != 0 and not (a[-2] == a[-2] and a[-2] != 0))


def formula_entry(rules, C):
    """(d, protected point) when the robot's formula entry fires at the candle that just closed, else None.
    The protected point does not exist for a formula entry: the extreme of the last 20 candles stands in for it
    (a fixed stop measures from the close), exactly as the bench's robot_opps."""
    en = (rules or {}).get("entry") or {}
    if en.get("event") != "formula" or C is None or not C.rows:
        return None
    st = (rules or {}).get("stop") or {}
    for d, src in ((-1, en.get("sell")), (1, en.get("buy"))):      # the bench sorts a candle's signals sell first
        if src and C.turned_true(src):
            cl = C.rows[-1][4]
            slp = C.now("lowest(low, 20)") if d == 1 else C.now("highest(high, 20)")
            if st.get("kind") == "fixed":
                slp = cl - d * float(st["points"])
            if slp == slp:
                return d, slp
    return None


def formula_exit(rules, d, C):
    """("close", why) when the robot's close formula for this side is true at the candle that just closed"""
    ex = (rules or {}).get("exit") or {}
    src = ex.get("close_buy") if d == 1 else ex.get("close_sell")
    if src and C is not None and C.rows and C.true_now(src):
        return ("close", "formule de sortie vraie")
    return None


def entry_ok(rules, kind):
    en = (rules or {}).get("entry")
    if not en or en.get("event") == "any":
        return True, ""
    if en.get("event") == "formula":             # only its own formula enters; the eyes' breaks do not
        return (True, "") if kind == "FORMULA" else (False, "seulement sa formule d'entree")
    if kind == "FORMULA":
        return False, "pas une formule"
    ev = KIND_EVENT.get(kind, "bos")
    if en["event"] != ev:
        return False, ("seulement les CHoCH" if en["event"] == "choch" else "seulement les BOS")
    return True, ""


def filters_ok(rules, hour, weekday, nerv, moves_2h, d=None, C=None):
    """nerv = the weather card's vol_now / vol_ref (the bot's nervosity), moves_2h = its big moves in 2 h,
    d = the trade's side and C = the candle memory (formula filters)"""
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
        if k == "formula":
            src = f.get("buy") if d == 1 else f.get("sell")
            if src is None:
                continue
            if C is None or not C.rows:
                return False, "formule sans bougies"
            if not C.true_now(src):
                return False, "formule du filtre fausse"
    return True, ""


def stop_for(rules, d, slp, close, bar_low, bar_high, C=None):
    """the stop price; `slp` = the protected point the structure gave, close / bar_* = the break candle;
    a formula stop with no value = nan (the bot then refuses, like the bench)"""
    st = (rules or {}).get("stop")
    if not st:
        return slp
    if st["kind"] == "protected":
        return slp - d * float(st.get("buffer") or 0)
    if st["kind"] == "break_candle":
        return (bar_low if d == 1 else bar_high) - d * float(st.get("buffer") or 0)
    if st["kind"] == "fixed":
        return close - d * float(st["points"])
    if st["kind"] == "formula":
        src = st.get("buy") if d == 1 else st.get("sell")
        return C.now(src) if (src and C is not None) else float("nan")
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
