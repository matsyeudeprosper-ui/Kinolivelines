src = open('owl_manual_bot.py', encoding='utf-8').read()

def rep(old, new):
    global src
    assert old in src, "NOT FOUND: " + old[:70]
    assert src.count(old) == 1, "NOT UNIQUE: " + old[:70]
    src = src.replace(old, new)

# constants
rep("RECOV_MAX_RISK_USD = 100.0",
    """RECOV_MAX_RISK_USD = 100.0
DEEP_LOT = 0.04            # 2026-09-01 user "build both": fighters at/above
                           # this lot get the two deep-fighter rules:
RATCHET_LOCK = 0.40        # profit >= 40% of prize -> wall moves to entry
RATCHET_BANK = 0.70        # profit >= 70% of prize -> bank at market
HEAL_EXTRA_USD = 3.0       # heal target = page losses repaid + this""")

# arm site A (link re-arm): carry accumulated page loss
rep('''                                "trig": _tr, "chain": _cn,
                                "kino": bool(_lk.get("kino"))})''',
    '''                                "trig": _tr, "chain": _cn,
                                "kino": bool(_lk.get("kino")),
                                "loss": (float(_lk.get("loss") or 0.0)
                                         + abs(float(row.get("profit_usd")
                                                     or 0.0)))})''')

# arm site B (origin trade): start the loss ledger
rep('''                                "trig": _tr, "chain": tkey,
                                "kino": int(tkey) in
                                        (st.get("kino_born") or [])})''',
    '''                                "trig": _tr, "chain": tkey,
                                "kino": int(tkey) in
                                        (st.get("kino_born") or []),
                                "loss": abs(float(row.get("profit_usd")
                                                  or 0.0))})''')

# entry: heal-target cap for deep fighters
rep('''                                        disc_usd = min(0.5 if strong else 1.0,
                                                       0.25 * risk)
                                        tp_dist = dist - disc_usd / new_lot''',
    '''                                        disc_usd = min(0.5 if strong else 1.0,
                                                       0.25 * risk)
                                        tp_dist = dist - disc_usd / new_lot
                                        _healed = False
                                        if new_lot >= DEEP_LOT:
                                            _hd = ((float(rw.get("loss") or 0.0)
                                                    + HEAL_EXTRA_USD) / new_lot)
                                            if RECOV_MIN_WALL_PTS < _hd < tp_dist:
                                                tp_dist = _hd
                                                _healed = True''')

# link record: keep loss + note heal
rep('''                                            "lot": new_lot, "chain": _cn,
                                            "kino": bool(rw.get("kino"))}''',
    '''                                            "lot": new_lot, "chain": _cn,
                                            "kino": bool(rw.get("kino")),
                                            "loss": float(rw.get("loss")
                                                          or 0.0)}''')

# entry log: mention heal target
rep('''                                            f"{'strong' if strong else 'calm'} "
                                            f"mkt -> -${disc_usd:.2f} early)")''',
    '''                                            f"{'strong' if strong else 'calm'} "
                                            f"mkt -> -${disc_usd:.2f} early"
                                            + (", HEAL target" if _healed
                                               else "") + ")")''')

# babysitter: add the ratchet for deep fighters
rep('''            # babysit open links: make sure every SL/TP really stuck
            if RECOV_ENTRY and st.get("recov_links"):
                for _tk, _ri in list(st["recov_links"].items()):
                    _rp = next((p for p in manual if str(p.ticket) == _tk), None)
                    if _rp is not None and (_rp.sl == 0.0 or _rp.tp == 0.0):
                        mt5.order_send({"action": mt5.TRADE_ACTION_SLTP,
                                        "position": _rp.ticket,
                                        "symbol": SYMBOL,
                                        "sl": _ri["sl"], "tp": _ri["tp"]})
                        say(f"RECOV[{_ri.get('chain')}]: re-sent SL/TP on "
                            f"link {_tk}")''',
    '''            # babysit open links: SL/TP stickiness + DEEP-FIGHTER RATCHET
            if RECOV_ENTRY and st.get("recov_links"):
                for _tk, _ri in list(st["recov_links"].items()):
                    _rp = next((p for p in manual if str(p.ticket) == _tk), None)
                    if _rp is None:
                        continue
                    if _rp.sl == 0.0 or _rp.tp == 0.0:
                        mt5.order_send({"action": mt5.TRADE_ACTION_SLTP,
                                        "position": _rp.ticket,
                                        "symbol": SYMBOL,
                                        "sl": _ri["sl"], "tp": _ri["tp"]})
                        say(f"RECOV[{_ri.get('chain')}]: re-sent SL/TP on "
                            f"link {_tk}")
                        continue
                    if _rp.volume >= DEEP_LOT and _rp.tp:
                        _d = 1 if _rp.type == mt5.POSITION_TYPE_BUY else -1
                        _prize = ((_rp.tp - _rp.price_open) * _d
                                  * _rp.volume)
                        if _prize > 0 and _rp.profit >= RATCHET_BANK * _prize:
                            r = close_at_market(_rp, "OWL-ratchet-bank")
                            if (r is not None and r.retcode
                                    == mt5.TRADE_RETCODE_DONE):
                                say(f"RECOV[{_ri.get('chain')}] RATCHET "
                                    f"BANK: link {_tk} taken at "
                                    f"{_rp.profit:+.2f} "
                                    f"({RATCHET_BANK:.0%} of prize)")
                        elif (_prize > 0
                                and _rp.profit >= RATCHET_LOCK * _prize
                                and not _ri.get("rat")):
                            _be = round(_rp.price_open, 2)
                            r = mt5.order_send(
                                {"action": mt5.TRADE_ACTION_SLTP,
                                 "position": _rp.ticket, "symbol": SYMBOL,
                                 "sl": _be, "tp": _rp.tp})
                            if (r is not None and r.retcode
                                    == mt5.TRADE_RETCODE_DONE):
                                _ri["rat"] = 1
                                _ri["sl"] = _be
                                save_state(st)
                                say(f"RECOV[{_ri.get('chain')}] RATCHET "
                                    f"LOCK: link {_tk} wall moved to "
                                    f"entry {_be} (can no longer lose)")''')

open('owl_manual_bot.py', 'w', encoding='utf-8').write(src)
import ast
ast.parse(src)
open('owl_manual_bot.py', encoding='cp1252').read()
print("deep-fighter rules built, syntax OK, cp1252-safe")
