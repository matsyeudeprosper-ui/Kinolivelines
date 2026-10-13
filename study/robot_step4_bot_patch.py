import io
L = r'C:\Projects\KinoliveLines\live'


def patch(p, R):
    a = io.open(p, encoding='utf-8').read()
    for o, n in R:
        assert a.count(o) == 1, (p, a.count(o), o[:80])
        a = a.replace(o, n)
    io.open(p, 'w', encoding='utf-8', newline='').write(a)


# 1. the package can carry a robot's rule pieces (default: none = no change)
patch(L + r'\owl_package.py', [
    ('''          "pb_gate_mode")''', '''          "pb_gate_mode",
          # 2026-10-13 (owner, robot builder step 4): the rule pieces of a robot
          # plugged onto the account (live/robots/robot_live.py reads them);
          # None everywhere else, so every other account is unchanged
          "robot_rules")'''),
    ('''        "pb_dir_gate": False, "pb_gate_mode": "trend"}''', '''        "pb_dir_gate": False, "pb_gate_mode": "trend", "robot_rules": None}'''),
])
B = L + r'\structure_bos_bot.py'
patch(B, [
    # 2. read the rules once, like every other package dial
    ('''from pb_gate import pb_gate
_PB_CACHE = {"t": 0.0, "v": (0, 0, None, None)}''',
     '''from pb_gate import pb_gate
_PB_CACHE = {"t": 0.0, "v": (0, 0, None, None)}
# 2026-10-13 (owner, robot builder step 4): a robot plugged onto this account brings RULE pieces (entry, filters,
# stop, exit) from its package; robot_live.py decides them exactly as the bench does (live/robots/
# test_robot_live.py). No rules (every account until a robot is plugged) = no change anywhere below.
ROBOT_RULES = _P.get("robot_rules") or {}
_sys.path.insert(0, os.path.join(DIR, "robots"))
import robot_live as _RL'''),
    # 3. the banner names the robot's rules
    ('''        + (" | reprise: balles seulement" if RECOV_BULLETS_ONLY else "")
        + _scale_line)''', '''        + (" | reprise: balles seulement" if RECOV_BULLETS_ONLY else "")
        + (" | robot: " + ", ".join(sorted(ROBOT_RULES)) + " " + json.dumps(ROBOT_RULES, separators=(",", ":")) if ROBOT_RULES else "")
        + _scale_line)'''),
    # 4. entry piece: before the recovery allowance is consumed
    ('''        if my_positions() or st.get("ghost"):
            return False
        if paused():
            return False''', '''        if my_positions() or st.get("ghost"):
            return False
        if paused():
            return False
        if ROBOT_RULES:
            _rok, _rwhy = _RL.entry_ok(ROBOT_RULES, kind)
            if not _rok:
                say(f"{kind} refuse: robot - {_rwhy}")
                return False'''),
    # 5. filter pieces: where the weather brakes are, before the day cap (the bench's order)
    ('''                            SHADOW.open_trade(
                                PAUSE_UID, d, _e, slp,
                                _e + d * RR * _ds, _wg, BASE_LOT)
            return False
        _why = day_blocked(st)''', '''                            SHADOW.open_trade(
                                PAUSE_UID, d, _e, slp,
                                _e + d * RR * _ds, _wg, BASE_LOT)
            return False
        if ROBOT_RULES.get("filters"):
            _nw = datetime.now(timezone.utc)
            _rvn, _rvr = (_cj0 or {}).get("vol_now"), (_cj0 or {}).get("vol_ref")
            _rok, _rwhy = _RL.filters_ok(ROBOT_RULES, _nw.hour, _nw.weekday(),
                                         (_rvn / max(_rvr, 1e-9)) if (_rvn and _rvr) else None,
                                         (_cj0 or {}).get("moves_2h"))
            if not _rok:
                say(f"{kind} refuse: robot - {_rwhy}")
                return False
        _why = day_blocked(st)'''),
    # 6. stop piece: from the break candle the loop just closed
    ('''        e_ref = tick.ask if d == 1 else tick.bid
        dist = abs(e_ref - slp)''', '''        e_ref = tick.ask if d == 1 else tick.bid
        if ROBOT_RULES.get("stop"):
            _kb1 = _KB[-1] if _KB else None
            _slp0 = slp
            slp = _RL.stop_for(ROBOT_RULES, d, slp,
                               float(_kb1["close"]) if _kb1 is not None else e_ref,
                               float(_kb1["low"]) if _kb1 is not None else e_ref,
                               float(_kb1["high"]) if _kb1 is not None else e_ref)
            if (d == 1 and slp >= e_ref) or (d == -1 and slp <= e_ref):
                say(f"{kind} refuse: robot - stop {slp:.2f} du mauvais cote du prix {e_ref:.2f}")
                return False
            say(f"{kind} stop du robot {slp:.2f} (point protege {_slp0:.2f})")
        dist = abs(e_ref - slp)'''),
    # 7. exit piece: the target (0 = none)
    ('''        tp = e_ref + d * RR * dist
        # forward record for the FVG filter''', '''        tp = _RL.tp_for(ROBOT_RULES, d, e_ref, dist, RR) if ROBOT_RULES else e_ref + d * RR * dist
        # forward record for the FVG filter'''),
    ('''        SHADOW.open_trade(PAUSE_UID, d, e_ref, slp, tp,
                          f"fvg={fvg_pts(d):.0f} {kind} ord={_ordt} "''', '''        SHADOW.open_trade(PAUSE_UID, d, e_ref, slp, tp if tp > 0 else e_ref + d * RR * dist,
                          f"fvg={fvg_pts(d):.0f} {kind} ord={_ordt} "'''),
    # 8. remember when the robot's trade opened (its time limit counts from here)
    ('''        say(f"{kind} ENTRY: {'BUY' if d == 1 else 'SELL'} {lot} @ "
            f"~{e_ref:.2f} SL {slp:.2f} TP {tp:.2f} "''', '''        if ROBOT_RULES.get("exit"):
            st.setdefault("robot_open", {})[str(r.order)] = {"t": time.time(), "be": False}
            for _ok_ in list(st["robot_open"])[:-10]:
                del st["robot_open"][_ok_]
        say(f"{kind} ENTRY: {'BUY' if d == 1 else 'SELL'} {lot} @ "
            f"~{e_ref:.2f} SL {slp:.2f} TP {tp:.2f} "'''),
    # 9. a recovery ghost with no target never "wins" by a 0 target
    ('''                    if _gh["d"] == 1:
                        _gl, _gw = _tkg.bid <= _gh["sl"], _tkg.bid >= _gh["tp"]
                    else:
                        _gl, _gw = _tkg.ask >= _gh["sl"], _tkg.ask <= _gh["tp"]''', '''                    if _gh["d"] == 1:
                        _gl, _gw = _tkg.bid <= _gh["sl"], _tkg.bid >= _gh["tp"]
                    else:
                        _gl, _gw = _tkg.ask >= _gh["sl"], _tkg.ask <= _gh["tp"]
                    if not _gh.get("tp"):
                        _gw = False            # a robot with no target: the ghost ends at its stop only'''),
    # 10. the open trade, every ~1 s: time limit and breakeven (the CHoCH exit is at the bar close, below)
    ('''            # recovery GHOST (recov_bullets_only): its own SL/TP on ticks,''', '''            if ROBOT_RULES.get("exit") and my_positions():
                robot_manage(st, None)
            # recovery GHOST (recov_bullets_only): its own SL/TP on ticks,'''),
    ('''            if eng.trend != _pt and eng.trend != 0 and _pt != 0:
                flips.append(bt)
                del flips[:-20]
                say(f"FLIP: trend now "
                    f"{'up' if eng.trend == 1 else 'down'}")''', '''            if eng.trend != _pt and eng.trend != 0 and _pt != 0:
                flips.append(bt)
                del flips[:-20]
                say(f"FLIP: trend now "
                    f"{'up' if eng.trend == 1 else 'down'}")
                if ROBOT_RULES.get("exit") and my_positions():
                    robot_manage(st, eng.trend)       # a CHoCH against the open trade closes it'''),
    # 11. the manager itself (module level, next to my_positions)
    ('''def my_positions():
    return [p for p in (mt5.positions_get(symbol=SYMBOL) or [])
            if p.magic == MAGIC]''', '''def my_positions():
    return [p for p in (mt5.positions_get(symbol=SYMBOL) or [])
            if p.magic == MAGIC]


def robot_close_all(why):
    """close every position of this bot (the main trade and its adds) at market"""
    for p in my_positions():
        tick = mt5.symbol_info_tick(SYMBOL)
        if tick is None:
            continue
        r = mt5.order_send({
            "action": mt5.TRADE_ACTION_DEAL, "symbol": SYMBOL, "volume": p.volume, "position": p.ticket,
            "type": mt5.ORDER_TYPE_SELL if p.type == mt5.POSITION_TYPE_BUY else mt5.ORDER_TYPE_BUY,
            "price": tick.bid if p.type == mt5.POSITION_TYPE_BUY else tick.ask,
            "deviation": 200, "magic": MAGIC, "comment": COMMENT + "-robot", "type_filling": mt5.ORDER_FILLING_IOC})
        say(f"ROBOT SORTIE ({why}): position {p.ticket} fermee"
            + ("" if r is not None and r.retcode == mt5.TRADE_RETCODE_DONE else f" - ECHEC retcode={r.retcode if r else None}"))


def robot_manage(st, new_trend):
    """the robot's exit piece on the open MAIN trade: a CHoCH against it (new_trend set at a flip), its time
    limit, its breakeven move - robot_live.manage decides, exactly as the bench (DslArm.tick / .signal)"""
    adds = set(st.get("add_ids") or [])
    tick = mt5.symbol_info_tick(SYMBOL)
    if tick is None:
        return
    for p in my_positions():
        if p.ticket in adds:
            continue
        d = 1 if p.type == mt5.POSITION_TYPE_BUY else -1
        rec = (st.get("robot_open") or {}).get(str(p.ticket)) or {}
        opened = float(rec.get("t") or p.time)
        act = _RL.manage(ROBOT_RULES, d, p.price_open, p.sl, opened, time.time(),
                         tick.bid if d == 1 else tick.ask, new_trend is not None and new_trend == -d, bool(rec.get("be")))
        if not act:
            continue
        if act[0] == "close":
            robot_close_all(act[1])
            return
        if act[0] == "sl":
            r = mt5.order_send({"action": mt5.TRADE_ACTION_SLTP, "symbol": SYMBOL, "position": p.ticket,
                                "sl": round(act[1], 2), "tp": p.tp})
            ok = r is not None and r.retcode == mt5.TRADE_RETCODE_DONE
            if ok:
                st.setdefault("robot_open", {}).setdefault(str(p.ticket), {"t": opened})["be"] = True
                save_state(st)
            say(f"ROBOT stop au prix d'entree {act[1]:.2f} (position {p.ticket})"
                + ("" if ok else f" - ECHEC retcode={r.retcode if r else None}"))'''),
])
print("ok")
