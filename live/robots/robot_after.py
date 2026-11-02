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
      "expire_min": 5..10080 | null,     give up waiting after N minutes (null = wait for the trigger)
      "alt": null | {"entry": ENTRY RULE, "stop": STOP RULE | null, "direction": ..., "target": ...}}   (2026-11-02)
   It applies to ONE trade: the one right after such a stop-out of a NORMAL trade. While it waits, the robot's normal
   entry is off; once that trade closes (whatever its result) the robot is back to normal.

3. 2026-11-02 (owner: "after a stop-out, enter the reverse trade on a 1-minute candle that CLOSES fully beyond the stop
   that was just hit. If that close never comes, a new breakout in the first direction is a second entry"):
   - the trigger {"event": "stop_close", "buffer": 0.0}: the FIRST closed 1-minute candle (one that closes after the
     stop-out) whose close is beyond the stopped trade's EXACT stop price - below it after a stopped buy, above it after
     a stopped sell - by more than `buffer` (price units, >= 0; 0 = any close beyond). The trade is taken at that
     candle's close, on the block's side ("reverse" normally; "any" means reverse here: the close is against the
     stopped trade). The stop price is the one the stopped trade had when it was hit (robot_lot.History last_trade["sl"]:
     the bench's stop, the desk's broker stop); unknown = this trigger never fires (the alt one still can).
   - the second branch "alt": its own trigger, side ("same" by default), stop and target. Whichever of the two fires
     FIRST takes the one after-loss trade; the other is dropped. "on" and "expire_min" are the block's, for both.
   The owner's rule: {"entry": {"event": "stop_close", "buffer": 0}, "direction": "reverse",
                      "alt": {"entry": {"event": "bos"}, "direction": "same"}}
"""
import robot_lot as L

DIRS = ("reverse", "same", "any")
ONS = ("sl", "loss")
T_LO, T_HI = 0.3, 5.0          # the same range as a fixed target piece (robot_dsl: target 0.3..5)
STOP_CLOSE = "stop_close"      # the trigger on the stopped trade's own stop price (robot_dsl validates its buffer)


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


def uses_stop_close(al):
    """does this after-loss block (rules form) wait for a 1-minute close beyond the stop? (the bench then adds the
    1-minute candles to the robot's stream, the desk keeps its candle memory - no other robot pays for it)"""
    if not isinstance(al, dict):
        return False
    return any((b.get("entry") or {}).get("event") == STOP_CLOSE for b in (al, al.get("alt") or {}) if isinstance(b, dict))


def _branch(b, check_rule, what, d_default):
    """one trigger branch -> (True, cleaned {entry, stop, direction, target}) or (False, reason)"""
    ok, en = check_rule("entry", b.get("entry"))
    if not ok:
        return False, "%s entry: %s" % (what, en)
    if en.get("order"):
        return False, "%s entry: no waiting order here" % what
    st = None
    if b.get("stop") is not None:
        ok, st = check_rule("stop", b["stop"])
        if not ok:
            return False, "%s stop: %s" % (what, st)
    d = b.get("direction") or d_default
    if d not in DIRS:
        return False, "%s direction" % what
    ok, tg = check_target(b.get("target"))
    if not ok:
        return False, "%s %s" % (what, tg)
    return True, {"entry": en, "stop": st, "direction": d, "target": tg}


def validate(al, check_rule):
    """(True, cleaned) or (False, reason); check_rule(kind, rule) = robot_dsl.validate (the caller passes it, so this
    module has no numpy import for the desk)"""
    if not isinstance(al, dict):
        return False, "after_loss"
    ok, br = _branch(al, check_rule, "after_loss", "reverse")
    if not ok:
        return False, br
    on = al.get("on") or "sl"
    if on not in ONS:
        return False, "after_loss on"
    ex = al.get("expire_min")
    if ex is not None:
        try:
            ex = int(ex)
        except Exception:
            return False, "after_loss expire_min"
        if not 5 <= ex <= 10080:
            return False, "after_loss expire_min"
    out = dict(br, on=on, expire_min=ex)
    if al.get("alt") is not None:            # 2026-11-02: the second trigger (absent = the block as before, no "alt" key)
        if not isinstance(al["alt"], dict):
            return False, "after_loss alt"
        ok, alt = _branch(al["alt"], check_rule, "after_loss alt", "same")
        if not ok:
            return False, alt
        out["alt"] = alt
    return True, out


def _rule_of(pid, P, kind):
    """a piece id -> its rule; the Owl's engine pieces read as rules (break entry = every break, protected point)"""
    p = P.get(pid) or {}
    if kind == "entry":
        return p.get("rule") or ({"event": "any"} if p.get("type") == "entry" and p.get("live") else None)
    return p.get("rule") or ({"kind": "protected", "buffer": 0.0} if (p.get("engine") or {}).get("stop") == "protected" else None)


def from_parts(al, P):
    """robots.json form {"entry": piece id, "stop": piece id | null, direction, target, on, expire_min, alt?} -> the rules
    form; P = pieces by id. The Owl's engine pieces read as rules: its break entry = every break ("any"), the protected
    point = {"kind": "protected"}. None = no block, or a piece that cannot be read (the robot then has no after-loss)."""
    if not isinstance(al, dict) or not al.get("entry"):
        return None
    en = _rule_of(al["entry"], P, "entry")
    if not en:
        return None
    st = None
    if al.get("stop"):
        st = _rule_of(al["stop"], P, "stop")
        if st is None:
            return None
    out = {"entry": en, "stop": st, "direction": al.get("direction") or "reverse", "target": al.get("target"),
           "on": al.get("on") or "sl", "expire_min": al.get("expire_min")}
    alt = al.get("alt")
    if isinstance(alt, dict) and alt.get("entry"):       # 2026-11-02: the second trigger, piece ids too
        aen = _rule_of(alt["entry"], P, "entry")
        ast_ = _rule_of(alt["stop"], P, "stop") if alt.get("stop") else None
        if not aen or (alt.get("stop") and ast_ is None):
            return None
        out["alt"] = {"entry": aen, "stop": ast_, "direction": alt.get("direction") or "same", "target": alt.get("target")}
    return out


def _side(dr, last, entry=None):
    d = int(last.get("d") or 0)
    if (entry or {}).get("event") == STOP_CLOSE and dr == "any":
        dr = "reverse"                       # a close beyond the stop is against the stopped trade
    return 0 if dr == "any" or not d else (-d if dr == "reverse" else d)


def pending(al, last, now=None):
    """the side the after-loss trade must take: +1 / -1, 0 = either side; None = normal mode.
    last = the robot's last CLOSED trade {"d", "hit_sl", "pnl", "al", "tc", "sl", "e"} (robot_lot.History.last_trade)
    or None; now = the time (s) of the decision, for expire_min"""
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
    return _side(al.get("direction") or "reverse", last, al.get("entry"))


def branches(al, last, now=None):
    """2026-11-02: None = normal mode; else the triggers waiting for the after-loss trade, [(branch, side)] - the
    block itself first, then its "alt" (side +1 / -1, 0 = either). A branch = {entry, stop, direction, target}."""
    s = pending(al, last, now)
    if s is None:
        return None
    out = [(al, s)]
    alt = al.get("alt")
    if isinstance(alt, dict) and alt.get("entry"):
        out.append((alt, _side(alt.get("direction") or "same", last, alt.get("entry"))))
    return out


def has_branches(al):
    """does this block need the branch reading (an alt trigger or a stop_close trigger)? Blocks without either keep the
    original single-trigger path, unchanged (bench: DslArm._signal_hist)"""
    return isinstance(al, dict) and (bool(al.get("alt")) or uses_stop_close(al))


def stop_close_fires(rule, last, close):
    """the stop_close trigger: is this 1-minute close beyond the stopped trade's stop by more than the buffer?
    (below the stop after a stopped buy, above it after a stopped sell); no stop price known = never"""
    if not last or last.get("sl") is None or close is None:
        return False
    d = int(last.get("d") or 0)
    if not d:
        return False
    b = max(0.0, float((rule or {}).get("buffer") or 0.0))
    return d * (float(close) - float(last["sl"])) < -b


def trigger(br, side, last, kind, d=0, close=None, t_close=None):
    """does this signal open the after-loss trade of branch `br` (its side `side` from branches())?
    kind: "minute" = a closed 1-minute candle (close = its close), "formula" = that branch's own entry formula turned
    true, "bos" / "choch" = an eyes break (choch = a break that turned the trend); d = the signal's side;
    t_close = the candle's close time (s): a candle that closed before the stop-out never counts.
    Returns the side the trade takes (+1 / -1), or 0 = no."""
    if t_close is not None and last and last.get("tc") is not None and float(t_close) < float(last["tc"]):
        return 0
    ev = (br.get("entry") or {}).get("event")
    if ev == STOP_CLOSE:
        if kind != "minute" or not stop_close_fires(br["entry"], last, close):
            return 0
        return side or -int(last.get("d") or 0)
    if kind == "minute":
        return 0
    if ev == "formula":
        if kind != "formula":
            return 0
    elif kind not in ("bos", "choch") or (ev in ("bos", "choch") and ev != kind):
        return 0
    d = int(d or 0)
    if not d or (side and d != side):
        return 0
    return d


# the order of one candle's signals on the bench (robot_runner.robot_stream sorts by (time, side) and keeps the
# stream order within one side); the desk picks among a candle's candidates with the same key
SRC_RANK = {"main": 0, "al": 1, "alt": 2, "eyes": 3, "close": 4}


def first_of(cands):
    """cands = [(stream side, src, payload)] fired on one candle -> the payload the bench would have taken first"""
    if not cands:
        return None
    return min(cands, key=lambda c: (int(c[0]), SRC_RANK.get(c[1], 9)))[2]


def rules_for(rules, al):
    """the robot's rules for the after-loss trade: its entry, its stop (or the robot's), its target (or the robot's);
    every other part (filters, exit timing, breakeven) stays the robot's. `al` may be the block or one of its
    branches (its "alt")."""
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


def _words(b, entry_rule):
    """(fr, en) of one branch: its side, its trigger, its target"""
    ev_rule = b.get("entry") if isinstance(b.get("entry"), dict) and b["entry"].get("event") else (entry_rule or {})
    dr = b.get("direction") or "reverse"
    if ev_rule.get("event") == STOP_CLOSE and dr == "any":
        dr = "reverse"
    side = {"reverse": ("dans le sens inverse du trade perdu", "in the opposite direction of the lost trade"),
            "same": ("dans le même sens que le trade perdu", "in the same direction as the lost trade"),
            "any": ("dans un sens ou l'autre", "either way")}[dr]
    t = b.get("target")
    tw = ("", "") if t is None else ((" avec un objectif de %s fois le risque" % ("%g" % t).replace(".", ","), " with a target of %g times the risk" % t)
                                     if not is_formula(t) else (" avec l'objectif « %s » fois le risque" % t, " with the target '%s' times the risk" % t))
    if ev_rule.get("event") == STOP_CLOSE:
        bf = float(ev_rule.get("buffer") or 0)
        bw = ("", "") if not bf else (" de plus de %s" % ("%g" % bf).replace(".", ","), " by more than %g" % bf)
        ew = ("dès qu'une bougie d'une minute clôture au-delà du stop touché%s" % bw[0],
              "as soon as a 1-minute candle closes beyond the stop that was hit%s" % bw[1])
    else:
        ew = {"bos": ("à la prochaine cassure qui continue la tendance (BOS)", "on the next break that continues the trend (BOS)"),
              "choch": ("au prochain changement de structure (CHoCH)", "on the next change of structure (CHoCH)"),
              "formula": ("quand sa formule d'entrée devient vraie", "when its entry formula turns true")}.get(
            ev_rule.get("event"), ("à la prochaine cassure de structure", "on the next structure break"))
    return side, ew, tw


def describe(al, entry_rule=None, alt_entry_rule=None):
    """(fr, en) plain words; entry_rule / alt_entry_rule = the triggers' rules when al["entry"] / al["alt"]["entry"]
    are not rules (piece slots)"""
    on = ("touche son stop" if (al.get("on") or "sl") == "sl" else "perd", "hits its stop" if (al.get("on") or "sl") == "sl" else "loses")
    side, ew, tw = _words(al, entry_rule)
    ex = al.get("expire_min")
    xw = ("", "") if not ex else (" (abandonné après %d min)" % ex, " (given up after %d min)" % ex)
    alt = al.get("alt")
    if isinstance(alt, dict) and alt.get("entry"):
        s2, e2, t2 = _words(alt, alt_entry_rule)
        return ("Quand un trade %s, le trade suivant se prend %s, %s%s ; si avant cela %s, il se prend %s%s - le premier "
                "des deux qui arrive%s, puis le robot reprend sa règle normale." % (on[0], side[0], ew[0], tw[0], _si(e2[0]), s2[0], t2[0], xw[0]),
                "When a trade %s, the next trade is taken %s, %s%s; if instead %s comes first, it is taken %s%s - whichever "
                "happens first%s, then the robot goes back to its normal rule." % (on[1], side[1], ew[1], tw[1], _if(e2[1]), s2[1], t2[1], xw[1]))
    return ("Quand un trade %s, le trade suivant se prend %s, %s%s%s, puis le robot reprend sa règle normale." % (on[0], side[0], ew[0], tw[0], xw[0]),
            "When a trade %s, the next trade is taken %s, %s%s%s, then the robot goes back to its normal rule." % (on[1], side[1], ew[1], tw[1], xw[1]))


def _si(w):
    """'à la prochaine cassure ...' -> 'la prochaine cassure ... arrive' (the alt trigger as the subject of a clause)"""
    for a, b in (("à la ", "la "), ("au ", "le "), ("dès qu'", ""), ("quand ", "")):
        if w.startswith(a):
            return b + w[len(a):] + ("" if a in ("dès qu'", "quand ") else " arrive")
    return w


def _if(w):
    """'on the next break ...' -> 'the next break ...'"""
    for a in ("on ", "as soon as ", "when "):
        if w.startswith(a):
            return w[len(a):]
    return w


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
    # 2026-11-02: the stop_close trigger and the alt branch (the owner's rule)
    own = {"entry": {"event": STOP_CLOSE, "buffer": 0.0}, "stop": None, "direction": "reverse", "target": None, "on": "sl",
           "expire_min": 120, "alt": {"entry": {"event": "bos"}, "stop": None, "direction": "same", "target": None}}
    buy_out = {"d": 1, "hit_sl": True, "pnl": -2.0, "al": False, "tc": 1000.0, "sl": 100.0, "e": 110.0}   # a buy stopped at 100
    sell_out = dict(buy_out, d=-1, sl=120.0, e=110.0)                                                    # a sell stopped at 120
    B = branches(own, buy_out, now=1060)
    assert [s for _, s in B] == [-1, 1] and B[0][0] is own and B[1][0] is own["alt"]
    assert branches(al, buy_out) == [(al, -1)] and branches(own, None) is None
    assert trigger(B[0][0], B[0][1], buy_out, "minute", close=99.5, t_close=1020) == -1        # close below the stop: SELL
    assert trigger(B[0][0], B[0][1], buy_out, "minute", close=100.0, t_close=1020) == 0        # AT the stop: not beyond
    assert trigger(B[0][0], B[0][1], buy_out, "minute", close=101.0, t_close=1020) == 0        # above it: no
    assert trigger(B[0][0], B[0][1], buy_out, "minute", close=99.5, t_close=990) == 0          # closed before the stop-out
    assert trigger(B[0][0], B[0][1], buy_out, "bos", d=-1, t_close=1020) == 0                  # a break is not this trigger
    assert trigger(dict(own, entry={"event": STOP_CLOSE, "buffer": 1.0}), -1, buy_out, "minute", close=99.5, t_close=1020) == 0
    assert trigger(dict(own, entry={"event": STOP_CLOSE, "buffer": 1.0}), -1, buy_out, "minute", close=98.9, t_close=1020) == -1
    Bs = branches(own, sell_out, now=1060)
    assert [s for _, s in Bs] == [1, -1]
    assert trigger(Bs[0][0], Bs[0][1], sell_out, "minute", close=120.5, t_close=1020) == 1     # close above a sell's stop: BUY
    assert trigger(Bs[0][0], Bs[0][1], sell_out, "minute", close=119.0, t_close=1020) == 0
    assert trigger(B[1][0], B[1][1], buy_out, "bos", d=1, t_close=1020) == 1                   # the alt: a BOS on the stopped side
    assert trigger(B[1][0], B[1][1], buy_out, "bos", d=-1, t_close=1020) == 0                  # not on the other side
    assert trigger(B[1][0], B[1][1], buy_out, "choch", d=1, t_close=1020) == 0                 # bos only, not a CHoCH
    assert trigger(B[1][0], B[1][1], buy_out, "minute", close=99.0, t_close=1020) == 0
    assert not stop_close_fires(own["entry"], dict(buy_out, sl=None), 50.0)                    # no stop price known: never
    assert branches(own, buy_out, now=1000 + 121 * 60) is None                                 # expired: back to normal
    assert branches(own, dict(buy_out, al=True)) is None                                       # the after-loss trade closed
    assert first_of([(1, "eyes", "bos-buy"), (0, "close", "close-sell")]) == "close-sell"      # the bench's candle order
    assert first_of([(-1, "eyes", "a"), (0, "close", "b")]) == "a" and first_of([]) is None
    assert uses_stop_close(own) and not uses_stop_close(al) and has_branches(own) and not has_branches(al)
    assert has_branches(dict(al, alt={"entry": {"event": "bos"}}))
    r2 = rules_for({"entry": {"event": "formula", "buy": "close > open", "sell": None}, "after_loss": own}, own["alt"])
    assert r2["entry"] == {"event": "bos"} and "after_loss" not in r2
    fr, en = describe(own)
    assert "clôture au-delà du stop touché" in fr and "closes beyond the stop that was hit" in en and "whichever" in en, (fr, en)
    assert describe(al)[1].startswith("When a trade hits its stop, the next trade is taken in the opposite direction")
    print("ok")
