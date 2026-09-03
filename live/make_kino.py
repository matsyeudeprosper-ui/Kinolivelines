src = open('owl_manual_bot.py', encoding='utf-8').read()

def rep(old, new):
    global src
    assert old in src, f"NOT FOUND: {old[:70]!r}"
    assert src.count(old) == 1, f"NOT UNIQUE: {old[:70]!r}"
    src = src.replace(old, new)

# 1) flags
rep("MANUAL_HANDS_OFF = True    # 2026-08-25 user: NEVER modify/close/TP the",
    """KINO_ENTRY = True          # 2026-08-31 user: auto-trade THEIR entry system.
                           # M1 only. UP: 2 consecutive greens, 2nd CLOSES
                           # above 1st's high = leg born; the leg's PEAK
                           # becomes official when a candle CLOSES below the
                           # last green's low; when a later M1 CLOSES back
                           # above that peak -> BUY (entry at the return to
                           # the proven extreme). Mirror for SELL. SL = the
                           # pullback's dip/peak, TP near-1:1 (same discount
                           # as RECOV). Guarded by the two-door chains like
                           # any page. Max 2 pages, 1 fire/hour, base lot:
KINO_LOTS = 0.02
MANUAL_HANDS_OFF = True    # 2026-08-25 user: NEVER modify/close/TP the""")

# 2) state defaults
rep('''    st.setdefault("bal_seen", 0)        # epoch of last processed deposit/
                                        # withdrawal deal (deposit watcher)''',
    '''    st.setdefault("bal_seen", 0)        # epoch of last processed deposit/
                                        # withdrawal deal (deposit watcher)
    st.setdefault("kino", {"up": {}, "dn": {}})  # peak/dip detector state
    st.setdefault("kino_tickets", [])   # open KINO entries (page trades)
    st.setdefault("kino_walls", {})     # ticket(str) -> [sl, tp] babysitter''')

# 3) module function: guarded open
rep("def reent_trigger(dirn, entry_price, t0):",
    '''def kino_open(direction, wall, st, ai, manual, runner_tickets,
              split_tickets, recov_tickets, conf_bar):
    """Open one KINO entry (the user's peak/dip-return system). Guards:
    max 2 pages (hand + kino, chains excluded), 1 fire/hour, balance,
    min wall distance. SL = wall, TP = near-1:1 with the strength discount.
    Returns the ticket or None."""
    pages = [p for p in manual
             if p.ticket not in runner_tickets
             and p.ticket not in split_tickets
             and p.ticket not in recov_tickets]
    if len(pages) >= 2:
        say(f"KINO skipped: {len(pages)} pages already open")
        return None
    if ai is None or ai.balance < AUTO_MIN_BAL:
        say(f"KINO skipped: balance {ai.balance if ai else None} "
            f"< {AUTO_MIN_BAL}")
        return None
    hid = int(time.time()) // 3600
    if st.get("kino_hour") == hid:
        say("KINO skipped: already fired this hour")
        return None
    tick = mt5.symbol_info_tick(SYMBOL)
    if tick is None:
        return None
    entry_px = tick.ask if direction == 1 else tick.bid
    dist = abs(entry_px - wall)
    if dist < RECOV_MIN_WALL_PTS:
        say(f"KINO skipped: wall {wall:.2f} too close ({dist:.1f}pts)")
        return None
    risk = dist * KINO_LOTS
    r = open_at_market(direction, KINO_LOTS, "OWL-kino")
    if r is None or r.retcode != mt5.TRADE_RETCODE_DONE:
        say(f"KINO entry FAILED retcode={r.retcode if r else None}")
        return None
    tkt = r.order
    body = abs(float(conf_bar["close"]) - float(conf_bar["open"]))
    m1b = mt5.copy_rates_from_pos(SYMBOL, mt5.TIMEFRAME_M1, 1, 120)
    a14 = (atr(m1b["high"], m1b["low"], m1b["close"])
           if m1b is not None and len(m1b) > 20 else 0.0)
    strong = a14 > 0 and body >= a14
    disc = min(0.5 if strong else 1.0, 0.25 * risk)
    tp_dist = dist - disc / KINO_LOTS
    tp = entry_px + tp_dist if direction == 1 else entry_px - tp_dist
    slp = round(wall, 2)
    mt5.order_send({"action": mt5.TRADE_ACTION_SLTP, "position": tkt,
                    "symbol": SYMBOL, "sl": slp, "tp": round(tp, 2)})
    st.setdefault("kino_tickets", []).append(tkt)
    st.setdefault("kino_walls", {})[str(tkt)] = [slp, round(tp, 2)]
    st["kino_hour"] = hid
    if str(tkt) not in st["user_owned"]:
        st["user_owned"].append(str(tkt))
    save_state(st)
    say(f"KINO ENTRY: {'BUY' if direction == 1 else 'SELL'} {KINO_LOTS} @ "
        f"~{entry_px:.2f} SL {slp} TP {tp:.2f} (risk ${risk:.2f}, prize "
        f"${tp_dist * KINO_LOTS:.2f}, return to "
        f"{'peak' if direction == 1 else 'dip'}, "
        f"{'strong' if strong else 'calm'} mkt)")
    return tkt

def reent_trigger(dirn, entry_price, t0):''')

# 4) per-loop ticket set + prune
rep('            recov_tickets = {int(k) for k in (st.get("recov_links") or {})}',
    '''            recov_tickets = {int(k) for k in (st.get("recov_links") or {})}
            if st.get("kino_tickets"):
                st["kino_tickets"] = [t for t in st["kino_tickets"]
                                      if t in open_tickets]
            kino_tickets = set(st.get("kino_tickets") or [])''')

# 5) hour-flat exemption
rep('''                    flatable = [p for p in manual if p.ticket not in runner_tickets
                                and p.ticket not in recov_tickets
                                and (is_bot_pos(p) or not MANUAL_HANDS_OFF)]''',
    '''                    flatable = [p for p in manual if p.ticket not in runner_tickets
                                and p.ticket not in recov_tickets
                                and p.ticket not in kino_tickets
                                and (is_bot_pos(p) or not MANUAL_HANDS_OFF)]''')

# 6) hour-clean exemption
rep('''                               and p.ticket not in runner_tickets
                               and p.ticket not in recov_tickets''',
    '''                               and p.ticket not in runner_tickets
                               and p.ticket not in recov_tickets
                               and p.ticket not in kino_tickets''')

# 7) escape blindness for kino pages (they are user-style pages)
rep('''            _mgd = [p for p in manual if (is_bot_pos(p) or not MANUAL_HANDS_OFF)
                    and p.ticket not in recov_tickets]  # chains are NOT hedges''',
    '''            _mgd = [p for p in manual if (is_bot_pos(p) or not MANUAL_HANDS_OFF)
                    and p.ticket not in recov_tickets
                    and p.ticket not in kino_tickets]  # chains/pages: not hedges''')

# 8) the detector, in the main loop
rep("            # --- RECOVERY CHAIN: confirmation watches + entries (per chain) ---",
    '''            # --- KINO ENTRY: the user's own peak/dip-return system ---
            if KINO_ENTRY and tick is not None:
                for _tk in list((st.get("kino_walls") or {}).keys()):
                    if int(_tk) not in open_tickets:
                        st["kino_walls"].pop(_tk, None)
                        save_state(st)
                        continue
                    _kp = next((p for p in manual
                                if p.ticket == int(_tk)), None)
                    _w = st["kino_walls"].get(_tk)
                    if (_kp is not None and _w
                            and (_kp.sl == 0.0 or _kp.tp == 0.0)):
                        mt5.order_send({"action": mt5.TRADE_ACTION_SLTP,
                                        "position": _kp.ticket,
                                        "symbol": SYMBOL,
                                        "sl": _w[0], "tp": _w[1]})
                        say(f"KINO: re-sent SL/TP on {_tk}")
                kb = mt5.copy_rates_from_pos(SYMBOL, mt5.TIMEFRAME_M1, 1, 2)
                if (kb is not None and len(kb) == 2
                        and int(kb[1]["time"]) != st.get("kino_last_bar")):
                    st["kino_last_bar"] = int(kb[1]["time"])
                    pv, cb = kb[0], kb[1]
                    po, pc = float(pv["open"]), float(pv["close"])
                    ph, pl = float(pv["high"]), float(pv["low"])
                    co, cc = float(cb["open"]), float(cb["close"])
                    ch, clo = float(cb["high"]), float(cb["low"])
                    ks = st.setdefault("kino", {"up": {}, "dn": {}})
                    up, dn = ks["up"], ks["dn"]
                    now_t = int(cb["time"])
                    # UP side: leg birth -> official peak -> return = BUY
                    if pc > po and cc > co and cc > ph:
                        up["leg"] = True
                        up["peak"] = ch
                        up["glow"] = clo
                    elif up.get("leg"):
                        up["peak"] = max(up.get("peak", ch), ch)
                        if cc > co:
                            up["glow"] = clo
                        elif cc < up.get("glow", float("-inf")):
                            up["pending"] = up["peak"]
                            up["pt"] = now_t
                            up["plow"] = clo
                            up["leg"] = False
                            say(f"KINO: peak {up['peak']:.2f} official -> "
                                f"pending BUY on M1 close back above it")
                    if up.get("pending"):
                        up["plow"] = min(up.get("plow", clo), clo)
                        if now_t - up.get("pt", now_t) > 21600:
                            say(f"KINO: pending BUY {up['pending']:.2f} "
                                f"expired (6h)")
                            up["pending"] = None
                        elif cc > up["pending"]:
                            up["pending"] = None
                            kino_open(1, up.get("plow", clo), st, ai, manual,
                                      runner_tickets, split_tickets,
                                      recov_tickets, cb)
                    # DOWN side: mirror -> official dip -> return = SELL
                    if pc < po and cc < co and cc < pl:
                        dn["leg"] = True
                        dn["dip"] = clo
                        dn["rhigh"] = ch
                    elif dn.get("leg"):
                        dn["dip"] = min(dn.get("dip", clo), clo)
                        if cc < co:
                            dn["rhigh"] = ch
                        elif cc > dn.get("rhigh", float("inf")):
                            dn["pending"] = dn["dip"]
                            dn["pt"] = now_t
                            dn["phigh"] = ch
                            dn["leg"] = False
                            say(f"KINO: dip {dn['dip']:.2f} official -> "
                                f"pending SELL on M1 close back below it")
                    if dn.get("pending"):
                        dn["phigh"] = max(dn.get("phigh", ch), ch)
                        if now_t - dn.get("pt", now_t) > 21600:
                            say(f"KINO: pending SELL {dn['pending']:.2f} "
                                f"expired (6h)")
                            dn["pending"] = None
                        elif cc < dn["pending"]:
                            dn["pending"] = None
                            kino_open(-1, dn.get("phigh", ch), st, ai, manual,
                                      runner_tickets, split_tickets,
                                      recov_tickets, cb)
                    save_state(st)
            # --- RECOVERY CHAIN: confirmation watches + entries (per chain) ---''')

open('owl_manual_bot.py', 'w', encoding='utf-8').write(src)
import ast
ast.parse(src)
open('owl_manual_bot.py', encoding='cp1252').read()
print("KINO entry patch applied, syntax OK, cp1252-safe")
