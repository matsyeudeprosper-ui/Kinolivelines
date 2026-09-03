"""WEATHER SYSTEM (user 2026-09-02 'build the weather system'):
While the chain floor blocks real fighters, blocked doors fire SHADOW
trades (virtual, zero broker orders, same walls/caps). Two consecutive
shadow WINS = weather clear -> real chains auto-resume even below the
soft floor (never below the HARD floor = 60% of journey start). A shadow
loss resets the streak back to shelter. Balance recovering above the
soft floor resets everything to normal. Status written to
owl_weather.json for the app + log lines SHADOW/WEATHER for reports.
"""
import ast, json

# hard floor into the config
cp = r'C:\Projects\KinoliveLines\live\owl_chain_floor.json'
c = json.load(open(cp))
c["hard_floor"] = round(0.60 * c["start"], 2)
c["note"] = (c.get("note", "") +
             " | hard_floor = 60% of start (absolute, weather cannot override)")
json.dump(c, open(cp, 'w'))
print("hard floor set:", c["hard_floor"])

p = r'C:\Projects\KinoliveLines\live\owl_manual_bot.py'
s = open(p, encoding='utf-8').read()

# read hard floor each loop
old = '''                chain_floor = float(_cfj.get("floor", 0.0))
                fighter_risk_cap = float(_cfj.get("risk_cap", 0.0))
            except Exception:
                chain_floor = 0.0
                fighter_risk_cap = 0.0'''
new = '''                chain_floor = float(_cfj.get("floor", 0.0))
                fighter_risk_cap = float(_cfj.get("risk_cap", 0.0))
                hard_floor = float(_cfj.get("hard_floor", 0.0))
            except Exception:
                chain_floor = 0.0
                fighter_risk_cap = 0.0
                hard_floor = 0.0'''
assert old in s
s = s.replace(old, new)

# floor branch -> shadow fire (weather-clear bypass built into condition)
old = '''                                elif (chain_floor
                                      and ai is not None
                                      and ai.balance < chain_floor):
                                    if not rw.get("held_floor"):
                                        rw["held_floor"] = True
                                        _dirty = True
                                        say(f"RECOV[{_cn}] held: balance "
                                            f"{ai.balance:.2f} below chain "
                                            f"floor {chain_floor:.0f} - "
                                            f"no new fighters")'''
new = '''                                elif (chain_floor
                                      and ai is not None
                                      and ai.balance < chain_floor
                                      and (ai.balance < hard_floor
                                           or (st.get("shadow") or {})
                                           .get("streak", 0) < 2)):
                                    # SHELTER MODE: fight virtually instead
                                    _sh = st.setdefault(
                                        "shadow",
                                        {"links": [], "streak": 0})
                                    tpd = dist - min(
                                        0.5 if True else 1.0,
                                        0.25 * risk) / new_lot
                                    _stp = (entry_px + tpd if new_dir == 1
                                            else entry_px - tpd)
                                    _sh["links"].append(
                                        {"dir": new_dir, "lot": new_lot,
                                         "entry": entry_px,
                                         "sl": round(wall, 2),
                                         "tp": round(_stp, 2),
                                         "chain": _cn})
                                    done = True
                                    _dirty = True
                                    say(f"SHADOW chain[{_cn}] ENTRY: "
                                        f"{'BUY' if new_dir == 1 else 'SELL'}"
                                        f" {new_lot} @ {entry_px:.2f} "
                                        f"(virtual - shelter mode)")
                                    try:
                                        json.dump(
                                            {"mode": "shelter",
                                             "streak": _sh["streak"]},
                                            open(os.path.join(
                                                DIR, "owl_weather.json"),
                                                "w"))
                                    except Exception:
                                        pass'''
assert old in s
s = s.replace(old, new)

# shadow resolution + weather transitions (before hour-group cleanup)
old = '''            # --- GROUP HEAL (user 2026-09-01): whole-account escape ---'''
new = '''            # --- WEATHER SYSTEM: resolve shadow fights, manage modes ---
            _sh = st.setdefault("shadow", {"links": [], "streak": 0})
            if tick is not None and ai is not None:
                if ai.balance >= chain_floor and (
                        _sh["links"] or _sh["streak"]):
                    _sh["links"] = []
                    _sh["streak"] = 0
                    save_state(st)
                    say("WEATHER: balance back above the floor - "
                        "normal mode")
                    try:
                        json.dump({"mode": "normal", "streak": 0},
                                  open(os.path.join(
                                      DIR, "owl_weather.json"), "w"))
                    except Exception:
                        pass
                elif _sh["links"]:
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
                            save_state(st)
                            _mode = ("clear" if _sh["streak"] >= 2
                                     else "shelter")
                            if _sh["streak"] == 2:
                                say("WEATHER CLEAR: two shadow wins - "
                                    "real chains AUTO-RESUME "
                                    "(hard floor still guards)")
                            try:
                                json.dump({"mode": _mode,
                                           "streak": _sh["streak"]},
                                          open(os.path.join(
                                              DIR, "owl_weather.json"),
                                              "w"))
                            except Exception:
                                pass
                        else:
                            _keepL.append(L)
                    if len(_keepL) != len(_sh["links"]):
                        _sh["links"] = _keepL
                        save_state(st)
            # --- GROUP HEAL (user 2026-09-01): whole-account escape ---'''
assert old in s
s = s.replace(old, new)

open(p, 'w', encoding='utf-8').write(s)
ast.parse(s)
open(p, encoding='cp1252').read()
print("weather system built, syntax OK, cp1252-safe")
