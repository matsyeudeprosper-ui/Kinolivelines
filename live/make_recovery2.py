src = open('owl_manual_bot.py', encoding='utf-8').read()

def rep(old, new):
    global src
    assert old in src, f"NOT FOUND: {old[:70]!r}"
    assert src.count(old) == 1, f"NOT UNIQUE: {old[:70]!r}"
    src = src.replace(old, new)

# 1) state: single watch/link -> per-chain collections
rep('''    st.setdefault("recov_watch", None)  # armed watch: {dir, sl, lot, t0, t_sl}
    st.setdefault("recov_info", None)   # active chain link: {ticket, sl, lot}''',
    '''    st.setdefault("recov_watches", [])  # armed watches, one per chain:
                                        # [{dir, sl, lot, t0, t_sl, chain}]
    st.setdefault("recov_links", {})    # open links: ticket(str) ->
                                        # {sl, tp, lot, chain}''')

# 2) per-loop ticket set
rep('            recov_ticket = (st.get("recov_info") or {}).get("ticket")',
    '            recov_tickets = {int(k) for k in (st.get("recov_links") or {})}')

# 3) hour-flat exemption
rep("""                    flatable = [p for p in manual if p.ticket not in runner_tickets
                                and p.ticket != recov_ticket""",
    """                    flatable = [p for p in manual if p.ticket not in runner_tickets
                                and p.ticket not in recov_tickets""")

# 4) hour-clean exemption
rep("""                               and p.ticket not in runner_tickets
                               and p.ticket != recov_ticket""",
    """                               and p.ticket not in runner_tickets
                               and p.ticket not in recov_tickets""")

# 5) trigger block -> per-chain
rep('''                # --- RECOVERY CHAIN trigger (user spec 2026-08-31) ---
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
                                f"CLOSE beyond the line")''',
    '''                # --- RECOVERY CHAIN trigger (user spec 2026-08-31;
                # 2026-08-31 amendment: MULTI-PAGE - every stopped trade gets
                # its OWN chain, tracked separately by origin ticket) ---
                if RECOV_ENTRY:
                    _t0 = None
                    try:
                        _t0 = int(datetime.fromisoformat(ent["entry_time_utc"])
                                  .replace(tzinfo=timezone.utc).timestamp())
                    except Exception:
                        pass
                    _links = st.setdefault("recov_links", {})
                    if tkey in _links:
                        _lk = _links.pop(tkey)
                        _cn = _lk.get("chain")
                        if row.get("exit_reason") == "sl" and _t0 is not None:
                            st.setdefault("recov_watches", []).append({
                                "dir": 1 if ent["direction"] == "BUY" else -1,
                                "sl": float(_lk.get("sl") or row.get("exit_price")
                                            or 0.0),
                                "lot": float(ent["volume"]),
                                "t0": _t0, "t_sl": int(time.time()),
                                "chain": _cn})
                            say(f"RECOV[{_cn}]: link {tkey} stopped -> watching "
                                f"for M1 close beyond "
                                f"{float(_lk.get('sl') or 0.0):.2f}")
                        else:
                            say(f"RECOV[{_cn}]: chain ENDED (link {tkey} exit="
                                f"{row.get('exit_reason')} {row.get('profit_usd')})")
                        save_state(st)
                    elif (row.get("exit_reason") == "sl"
                          and int(tkey) not in runner_tickets
                          and int(tkey) not in split_tickets
                          and _t0 is not None):
                        _sl = (ent.get("final_user_sl") or ent.get("entry_user_sl")
                               or row.get("exit_price"))
                        if _sl:
                            st.setdefault("recov_watches", []).append({
                                "dir": 1 if ent["direction"] == "BUY" else -1,
                                "sl": float(_sl), "lot": float(ent["volume"]),
                                "t0": _t0, "t_sl": int(time.time()),
                                "chain": tkey})
                            save_state(st)
                            say(f"RECOV[{tkey}] armed: {ent['direction']} "
                                f"{ent['volume']} stopped at {float(_sl):.2f} -> "
                                f"waiting for an M1 CLOSE beyond the line")''')

# 6) watch/entry + babysitter -> iterate all chains
_old_watch = src[src.index("            # --- RECOVERY CHAIN: confirmation watch + entry ---"):
                 src.index("            # --- hour-group cleanup: past-hour groups close when net positive ---")]
_new_watch = '''            # --- RECOVERY CHAIN: confirmation watches + entries (per chain) ---
            if RECOV_ENTRY and st.get("recov_watches") and tick is not None:
                b1 = mt5.copy_rates_from_pos(SYMBOL, mt5.TIMEFRAME_M1, 1, 1)
                _keep = []
                _dirty = False
                for rw in st["recov_watches"]:
                    _cn = rw.get("chain")
                    done = False
                    if (b1 is not None and len(b1)
                            and int(b1["time"][0]) + 60 > rw["t_sl"]):
                        _cl = float(b1["close"][0])
                        _broke = (_cl < rw["sl"] if rw["dir"] == 1
                                  else _cl > rw["sl"])
                        if _broke:
                            new_dir = -rw["dir"]
                            new_lot = round(rw["lot"] + RECOV_STEP, 2)
                            legbars = mt5.copy_rates_range(
                                SYMBOL, mt5.TIMEFRAME_M1,
                                datetime.fromtimestamp(rw["t0"] - 60,
                                                       tz=timezone.utc),
                                datetime.now(timezone.utc))
                            if legbars is not None and len(legbars):
                                wall = (float(np.max(legbars["high"]))
                                        if new_dir == -1
                                        else float(np.min(legbars["low"])))
                                entry_px = (tick.bid if new_dir == -1
                                            else tick.ask)
                                dist = abs(entry_px - wall)
                                risk = dist * new_lot
                                if dist < RECOV_MIN_WALL_PTS:
                                    say(f"RECOV[{_cn}]: wall {wall:.2f} too "
                                        f"close ({dist:.1f}pts) - waiting")
                                elif risk >= RECOV_MAX_RISK_USD:
                                    say(f"RECOV[{_cn}] chain STOPPED: next link "
                                        f"would risk ${risk:.2f} >= "
                                        f"${RECOV_MAX_RISK_USD:.0f} cap "
                                        f"(lot {new_lot}, wall {wall:.2f})")
                                    done = True
                                    _dirty = True
                                else:
                                    r = open_at_market(new_dir, new_lot,
                                                       "OWL-recov")
                                    if (r is not None and r.retcode
                                            == mt5.TRADE_RETCODE_DONE):
                                        tkt = r.order
                                        _body = abs(float(b1["close"][0])
                                                    - float(b1["open"][0]))
                                        _m1b = mt5.copy_rates_from_pos(
                                            SYMBOL, mt5.TIMEFRAME_M1, 1, 120)
                                        _a14 = (atr(_m1b["high"], _m1b["low"],
                                                    _m1b["close"])
                                                if _m1b is not None
                                                and len(_m1b) > 20 else 0.0)
                                        strong = _a14 > 0 and _body >= _a14
                                        disc_usd = min(0.5 if strong else 1.0,
                                                       0.25 * risk)
                                        tp_dist = dist - disc_usd / new_lot
                                        tp = (entry_px - tp_dist
                                              if new_dir == -1
                                              else entry_px + tp_dist)
                                        st.setdefault("recov_links", {})[
                                            str(tkt)] = {
                                            "sl": round(wall, 2),
                                            "tp": round(tp, 2),
                                            "lot": new_lot, "chain": _cn}
                                        if str(tkt) not in st["user_owned"]:
                                            st["user_owned"].append(str(tkt))
                                        done = True
                                        _dirty = True
                                        mt5.order_send(
                                            {"action": mt5.TRADE_ACTION_SLTP,
                                             "position": tkt, "symbol": SYMBOL,
                                             "sl": round(wall, 2),
                                             "tp": round(tp, 2)})
                                        say(f"RECOV[{_cn}] ENTRY: "
                                            f"{'SELL' if new_dir == -1 else 'BUY'} "
                                            f"{new_lot} @ ~{entry_px:.2f} "
                                            f"SL {wall:.2f} TP {tp:.2f} "
                                            f"(risk ${risk:.2f}, prize "
                                            f"${tp_dist * new_lot:.2f}, "
                                            f"{'strong' if strong else 'calm'} "
                                            f"mkt -> -${disc_usd:.2f} early)")
                                    else:
                                        say(f"RECOV[{_cn}] entry FAILED "
                                            f"retcode="
                                            f"{r.retcode if r else None}")
                    if not done and time.time() - rw["t_sl"] > 3600:
                        say(f"RECOV[{_cn}] watch EXPIRED (60 min, no M1 close "
                            f"beyond the line)")
                        done = True
                        _dirty = True
                    if not done:
                        _keep.append(rw)
                st["recov_watches"] = _keep
                if _dirty:
                    save_state(st)
            # babysit open links: make sure every SL/TP really stuck
            if RECOV_ENTRY and st.get("recov_links"):
                for _tk, _ri in list(st["recov_links"].items()):
                    _rp = next((p for p in manual if str(p.ticket) == _tk), None)
                    if _rp is not None and (_rp.sl == 0.0 or _rp.tp == 0.0):
                        mt5.order_send({"action": mt5.TRADE_ACTION_SLTP,
                                        "position": _rp.ticket,
                                        "symbol": SYMBOL,
                                        "sl": _ri["sl"], "tp": _ri["tp"]})
                        say(f"RECOV[{_ri.get('chain')}]: re-sent SL/TP on "
                            f"link {_tk}")
'''
src = src.replace(_old_watch, _new_watch)

open('owl_manual_bot.py', 'w', encoding='utf-8').write(src)
import ast
ast.parse(src)
open('owl_manual_bot.py', encoding='cp1252').read()
print("multi-chain patch applied, syntax OK, cp1252-safe")
