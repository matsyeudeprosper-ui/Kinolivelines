"""Two frozen-law refinements (user 2026-09-02 'build both fixes'):
1. CHAINS-FIRST PRIORITY: recovery doors hunt each heartbeat BEFORE fresh
   KINO pages - the wounded fighter now claims a shared signal first.
2. 80% LOCK for ALL trades: any trade (small pages included) that walks
   80% of its prize gets its wall moved to entry - the 'three points from
   TP then reversal' heartbreak now costs $0 instead of a loss.
"""
import ast

p = r'C:\Projects\KinoliveLines\live\owl_manual_bot.py'
s = open(p, encoding='utf-8').read()

# ---- 1) move the KINO block AFTER the recovery-watch block ----
k0 = s.index("            # --- KINO ENTRY: the user's own peak/dip-return system ---")
k1 = s.index("            # --- RECOVERY CHAIN: confirmation watches + entries (per chain) ---")
kino_seg = s[k0:k1]
lf_line = "            loop_fired = []\n"
assert lf_line in kino_seg, "loop_fired line not inside kino segment"
kino_seg_nolf = kino_seg.replace(lf_line, "", 1)
s = s[:k0] + lf_line + s[k1:]
anchor = "            # babysit open links: SL/TP stickiness + DEEP-FIGHTER RATCHET"
assert anchor in s
s = s.replace(anchor, kino_seg_nolf + anchor, 1)
print("chains-first priority: KINO block moved after recovery doors")

# ---- 2a) 80% lock for small chain links ----
old = '''                    if _rp.volume >= DEEP_LOT and _rp.tp:'''
new = '''                    if (_rp.volume < DEEP_LOT and _rp.tp
                            and not _ri.get("rat")):
                        _d = (1 if _rp.type == mt5.POSITION_TYPE_BUY
                              else -1)
                        _prize = ((_rp.tp - _rp.price_open) * _d
                                  * _rp.volume)
                        if _prize > 0 and _rp.profit >= 0.80 * _prize:
                            r = mt5.order_send(
                                {"action": mt5.TRADE_ACTION_SLTP,
                                 "position": _rp.ticket,
                                 "symbol": SYMBOL,
                                 "sl": round(_rp.price_open, 2),
                                 "tp": _rp.tp})
                            if (r is not None and r.retcode
                                    == mt5.TRADE_RETCODE_DONE):
                                _ri["rat"] = 1
                                _ri["sl"] = round(_rp.price_open, 2)
                                save_state(st)
                                say(f"RECOV[{_ri.get('chain')}] 80% "
                                    f"LOCK: link {_rp.ticket} wall "
                                    f"moved to entry")
                    if _rp.volume >= DEEP_LOT and _rp.tp:'''
assert old in s and s.count(old) == 1
s = s.replace(old, new)
print("80% lock: chain links covered")

# ---- 2b) 80% lock for fresh KINO pages ----
old = '''                    if (_kp is not None and _w
                            and (_kp.sl == 0.0 or _kp.tp == 0.0)):
                        mt5.order_send({"action": mt5.TRADE_ACTION_SLTP,
                                        "position": _kp.ticket,
                                        "symbol": SYMBOL,
                                        "sl": _w[0], "tp": _w[1]})
                        say(f"KINO: re-sent SL/TP on {_tk}")'''
new = '''                    if (_kp is not None and _w
                            and (_kp.sl == 0.0 or _kp.tp == 0.0)):
                        mt5.order_send({"action": mt5.TRADE_ACTION_SLTP,
                                        "position": _kp.ticket,
                                        "symbol": SYMBOL,
                                        "sl": _w[0], "tp": _w[1]})
                        say(f"KINO: re-sent SL/TP on {_tk}")
                    if (_kp is not None and _w and len(_w) < 3
                            and _kp.tp):
                        _d = (1 if _kp.type == mt5.POSITION_TYPE_BUY
                              else -1)
                        _prize = ((_kp.tp - _kp.price_open) * _d
                                  * _kp.volume)
                        if _prize > 0 and _kp.profit >= 0.80 * _prize:
                            r = mt5.order_send(
                                {"action": mt5.TRADE_ACTION_SLTP,
                                 "position": _kp.ticket,
                                 "symbol": SYMBOL,
                                 "sl": round(_kp.price_open, 2),
                                 "tp": _kp.tp})
                            if (r is not None and r.retcode
                                    == mt5.TRADE_RETCODE_DONE):
                                _w.append(1)
                                st["kino_walls"][_tk] = _w
                                save_state(st)
                                say(f"KINO 80% LOCK: {_tk} wall moved "
                                    f"to entry")'''
assert old in s and s.count(old) == 1
s = s.replace(old, new)
print("80% lock: KINO pages covered")

open(p, 'w', encoding='utf-8').write(s)
ast.parse(s)
open(p, encoding='cp1252').read()
print("both fixes applied, syntax OK, cp1252-safe")
