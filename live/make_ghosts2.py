"""GHOSTS OBEY EVERY LAW (user 2026-09-02):
- Spread-honest exits (BUY judged at bid, SELL at ask)
- 80% lock for small ghosts, 40% lock + 70% bank for deep ghosts
- Heal targets for deep chain ghosts (loss ledger + extra)
- Breakeven ghost exits are NEUTRAL (streak untouched), like real ones
"""
import ast

p = r'C:\Projects\KinoliveLines\live\owl_manual_bot.py'
s = open(p, encoding='utf-8').read()

# 1) chain ghost TP: proper discount + heal target
old = '''                                    tpd = dist - min(
                                        0.5 if True else 1.0,
                                        0.25 * risk) / new_lot'''
new = '''                                    tpd = dist - min(
                                        0.75, 0.25 * risk) / new_lot
                                    if (new_lot >= DEEP_LOT
                                            and rw.get("loss")):
                                        _ghd = ((float(rw["loss"])
                                                 + HEAL_EXTRA_USD)
                                                / new_lot)
                                        if (RECOV_MIN_WALL_PTS < _ghd
                                                < tpd):
                                            tpd = _ghd'''
assert old in s
s = s.replace(old, new)

# 2) resolution loop: full law engine
old = '''                elif _sh["links"]:
                    _keepL = []
                    for L in _sh["links"]:
                        _px = tick.bid
                        _win = (_px >= L["tp"] if L["dir"] == 1
                                else _px <= L["tp"])
                        _loss = (_px <= L["sl"] if L["dir"] == 1
                                 else _px >= L["sl"])
                        if _win or _loss:
                            _tgt = L["tp"] if _win else L["sl"]
                            _pnl = ((_tgt - L["entry"]) * L["dir"]
                                    * L["lot"])
                            if _win:
                                _sh["streak"] += 1
                                say(f"SHADOW chain[{L['chain']}] WIN "
                                    f"{_pnl:+.2f} (streak "
                                    f"{_sh['streak']})")
                            else:
                                _sh["streak"] = 0
                                say(f"SHADOW chain[{L['chain']}] LOSS "
                                    f"{_pnl:+.2f} (streak reset)")
                            save_state(st)'''
new = '''                elif _sh["links"]:
                    _keepL = []
                    for L in _sh["links"]:
                        _px = tick.bid if L["dir"] == 1 else tick.ask
                        _prof = ((_px - L["entry"]) * L["dir"]
                                 * L["lot"])
                        _prize = abs(L["tp"] - L["entry"]) * L["lot"]
                        _deep = L["lot"] >= DEEP_LOT
                        _res = None
                        if (_deep and _prize > 0
                                and _prof >= RATCHET_BANK * _prize):
                            _res = round(RATCHET_BANK * _prize, 2)
                        elif (_px >= L["tp"] if L["dir"] == 1
                              else _px <= L["tp"]):
                            _res = round((L["tp"] - L["entry"])
                                         * L["dir"] * L["lot"], 2)
                        else:
                            if _prize > 0 and not L.get("rat"):
                                if ((_deep and _prof
                                     >= RATCHET_LOCK * _prize)
                                        or (not _deep and _prof
                                            >= 0.80 * _prize)):
                                    L["rat"] = 1
                                    save_state(st)
                            _wallpx = (L["entry"] if L.get("rat")
                                       else L["sl"])
                            if (_px <= _wallpx if L["dir"] == 1
                                    else _px >= _wallpx):
                                _res = round((_wallpx - L["entry"])
                                             * L["dir"] * L["lot"], 2)
                        if _res is not None:
                            _pnl = _res
                            if _pnl > 0.5:
                                _sh["streak"] += 1
                                say(f"SHADOW chain[{L['chain']}] WIN "
                                    f"{_pnl:+.2f} (streak "
                                    f"{_sh['streak']})")
                            elif _pnl < -0.5:
                                _sh["streak"] = 0
                                say(f"SHADOW chain[{L['chain']}] LOSS "
                                    f"{_pnl:+.2f} (streak reset)")
                            else:
                                say(f"SHADOW chain[{L['chain']}] "
                                    f"breakeven {_pnl:+.2f} "
                                    f"(streak kept)")
                            save_state(st)'''
assert old in s
s = s.replace(old, new)

open(p, 'w', encoding='utf-8').write(s)
ast.parse(s)
open(p, encoding='cp1252').read()
print("ghosts now obey every law, syntax OK, cp1252-safe")
