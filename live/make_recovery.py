src = open('owl_manual_bot.py', encoding='utf-8').read()

def rep(old, new):
    global src
    assert old in src, f"NOT FOUND: {old[:70]!r}"
    assert src.count(old) == 1, f"NOT UNIQUE: {old[:70]!r}"
    src = src.replace(old, new)

# 1) flags
rep("BUFFER_USD = 0.10          # guaranteed min profit on breakeven/midpoint exits",
    """RECOV_ENTRY = True         # 2026-08-31 user spec: automated RECOVERY CHAIN.
                           # When a trade (user's hand trade or a chain link)
                           # exits by SL: wait for an M1 candle to CLOSE beyond
                           # the SL line, then open the OPPOSITE direction at
                           # last lot + 0.01. New SL = the peak/dip the breaking
                           # leg created (M1 extreme since the stopped trade's
                           # entry). TP = same distance (1:1 RR). If the chain
                           # link also SLs, repeat. Chain stops when the next
                           # link's risk would reach $100, or on any TP/manual
                           # close. One chain at a time. Watch expires after
                           # 60 min without confirmation.
RECOV_STEP = 0.01
RECOV_MAX_RISK_USD = 100.0
RECOV_MIN_WALL_PTS = 10.0  # wall glued to price = wait for a better bar
BUFFER_USD = 0.10          # guaranteed min profit on breakeven/midpoint exits""")

# 2) state defaults
rep('    st.setdefault("groups", {})       # hour_id(str) -> {start_equity, realized, tickets}',
    '''    st.setdefault("groups", {})       # hour_id(str) -> {start_equity, realized, tickets}
    st.setdefault("recov_watch", None)  # armed watch: {dir, sl, lot, t0, t_sl}
    st.setdefault("recov_info", None)   # active chain link: {ticket, sl, lot}''')

# 3) per-loop recov ticket
rep('            runner_tickets = {runner.get("a"), runner.get("b")} - {None}',
    '''            runner_tickets = {runner.get("a"), runner.get("b")} - {None}
            recov_ticket = (st.get("recov_info") or {}).get("ticket")''')

# 4) hour-flat exemption
rep("""                    flatable = [p for p in manual if p.ticket not in runner_tickets
                                and (is_bot_pos(p) or not MANUAL_HANDS_OFF)]""",
    """                    flatable = [p for p in manual if p.ticket not in runner_tickets
                                and p.ticket != recov_ticket
                                and (is_bot_pos(p) or not MANUAL_HANDS_OFF)]""")

# 5) hour-clean exemption
rep("""                    members = [p for p in manual if p.ticket in g["tickets"]
                               and p.ticket not in runner_tickets
                               and (is_bot_pos(p) or not MANUAL_HANDS_OFF)]""",
    """                    members = [p for p in manual if p.ticket in g["tickets"]
                               and p.ticket not in runner_tickets
                               and p.ticket != recov_ticket
                               and (is_bot_pos(p) or not MANUAL_HANDS_OFF)]""")

# 6) chain trigger on journaled SL exits
rep("""                say(f"EXIT logged: ticket {tkey} {row.get('exit_reason')} "
                    f"profit {row.get('profit_usd')} dur {row.get('duration_min')}min")""",
    """                say(f"EXIT logged: ticket {tkey} {row.get('exit_reason')} "
                    f"profit {row.get('profit_usd')} dur {row.get('duration_min')}min")
                # --- RECOVERY CHAIN trigger (user spec 2026-08-31) ---
                if RECOV_ENTRY:
                    _ri = st.get("recov_info")
                    _t0 = None
                    try:
                        _t0 = int(datetime.fromisoformat(ent["entry_time_utc"])
                                  .replace(tzinfo=timezone.utc).timestamp())
                    except Exception:
                        pass
                    if _ri and int(tkey) == _ri.get("ticket"):
                        # our own chain link closed
                        st["recov_info"] = None
                        if row.get("exit_reason") == "sl" and _t0 is not None:
                            st["recov_watch"] = {
                                "dir": 1 if ent["direction"] == "BUY" else -1,
                                "sl": float(_ri.get("sl") or row.get("exit_price") or 0.0),
                                "lot": float(ent["volume"]),
                                "t0": _t0, "t_sl": int(time.time())}
                            say(f"RECOV: chain link {tkey} stopped -> "
                                f"watching for M1 close beyond {st['recov_watch']['sl']}")
                        else:
                            say(f"RECOV: chain ENDED (link {tkey} exit="
                                f"{row.get('exit_reason')} {row.get('profit_usd')})")
                        save_state(st)
                    elif (row.get("exit_reason") == "sl"
                          and st.get("recov_watch") is None
                          and st.get("recov_info") is None
                          and int(tkey) not in runner_tickets
                          and int(tkey) not in split_tickets
                          and _t0 is not None):
                        _sl = (ent.get("final_user_sl") or ent.get("entry_user_sl")
                               or row.get("exit_price"))
                        if _sl:
                            st["recov_watch"] = {
                                "dir": 1 if ent["direction"] == "BUY" else -1,
                                "sl": float(_sl), "lot": float(ent["volume"]),
                                "t0": _t0, "t_sl": int(time.time())}
                            save_state(st)
                            say(f"RECOV armed: {ent['direction']} {ent['volume']} "
                                f"stopped at {float(_sl):.2f} -> waiting for an M1 "
                                f"CLOSE beyond the line")""")

# 7) watch -> confirm -> enter block + SLTP babysitter
rep("            # --- hour-group cleanup: past-hour groups close when net positive ---",
    """            # --- RECOVERY CHAIN: confirmation watch + entry ---
            rw = st.get("recov_watch")
            if RECOV_ENTRY and rw and tick is not None and st.get("recov_info") is None:
                entered = False
                b1 = mt5.copy_rates_from_pos(SYMBOL, mt5.TIMEFRAME_M1, 1, 1)
                if (b1 is not None and len(b1)
                        and int(b1["time"][0]) + 60 > rw["t_sl"]):
                    _cl = float(b1["close"][0])
                    _broke = _cl < rw["sl"] if rw["dir"] == 1 else _cl > rw["sl"]
                    if _broke:
                        new_dir = -rw["dir"]
                        new_lot = round(rw["lot"] + RECOV_STEP, 2)
                        legbars = mt5.copy_rates_range(
                            SYMBOL, mt5.TIMEFRAME_M1,
                            datetime.fromtimestamp(rw["t0"] - 60, tz=timezone.utc),
                            datetime.now(timezone.utc))
                        if legbars is not None and len(legbars):
                            wall = (float(np.max(legbars["high"])) if new_dir == -1
                                    else float(np.min(legbars["low"])))
                            entry_px = tick.bid if new_dir == -1 else tick.ask
                            dist = abs(entry_px - wall)
                            risk = dist * new_lot
                            if dist < RECOV_MIN_WALL_PTS:
                                say(f"RECOV: wall {wall:.2f} too close to price "
                                    f"({dist:.1f}pts) - waiting for a better bar")
                            elif risk >= RECOV_MAX_RISK_USD:
                                say(f"RECOV chain STOPPED: next link would risk "
                                    f"${risk:.2f} >= ${RECOV_MAX_RISK_USD:.0f} cap "
                                    f"(lot {new_lot}, wall {wall:.2f}) - no trade")
                                st["recov_watch"] = None
                                save_state(st)
                            else:
                                r = open_at_market(new_dir, new_lot, "OWL-recov")
                                if r is not None and r.retcode == mt5.TRADE_RETCODE_DONE:
                                    tkt = r.order
                                    tp = (entry_px - dist if new_dir == -1
                                          else entry_px + dist)
                                    st["recov_info"] = {"ticket": tkt,
                                                        "sl": round(wall, 2),
                                                        "tp": round(tp, 2),
                                                        "lot": new_lot}
                                    if str(tkt) not in st["user_owned"]:
                                        st["user_owned"].append(str(tkt))
                                    st["recov_watch"] = None
                                    save_state(st)
                                    entered = True
                                    mt5.order_send({"action": mt5.TRADE_ACTION_SLTP,
                                                    "position": tkt, "symbol": SYMBOL,
                                                    "sl": round(wall, 2),
                                                    "tp": round(tp, 2)})
                                    say(f"RECOV ENTRY: "
                                        f"{'SELL' if new_dir == -1 else 'BUY'} "
                                        f"{new_lot} @ ~{entry_px:.2f} SL {wall:.2f} "
                                        f"TP {tp:.2f} (risk ${risk:.2f}, 1:1)")
                                else:
                                    say(f"RECOV entry FAILED retcode="
                                        f"{r.retcode if r else None}")
                if (not entered and st.get("recov_watch")
                        and time.time() - rw["t_sl"] > 3600):
                    say("RECOV watch EXPIRED (60 min, no M1 close beyond the line)")
                    st["recov_watch"] = None
                    save_state(st)
            # babysit the active link: make sure its SL/TP really stick
            _ri = st.get("recov_info")
            if RECOV_ENTRY and _ri:
                _rp = next((p for p in manual if p.ticket == _ri["ticket"]), None)
                if _rp is not None and (_rp.sl == 0.0 or _rp.tp == 0.0):
                    mt5.order_send({"action": mt5.TRADE_ACTION_SLTP,
                                    "position": _rp.ticket, "symbol": SYMBOL,
                                    "sl": _ri["sl"], "tp": _ri["tp"]})
                    say(f"RECOV: re-sent SL/TP on link {_rp.ticket}")
            # --- hour-group cleanup: past-hour groups close when net positive ---""")

open('owl_manual_bot.py', 'w', encoding='utf-8').write(src)
import ast
ast.parse(src)
open('owl_manual_bot.py', encoding='cp1252').read()
print("recovery-chain patch applied, syntax OK, cp1252-safe")
