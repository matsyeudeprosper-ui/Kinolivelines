"""WEATHER v2 (user 2026-09-02: 'could the weather system get even
smarter? the normal 0.02 lot also still losing'):
- STORM DETECTOR: 3 consecutive REAL losses (any trade) -> FULL SHELTER:
  fresh pages AND chain fighters all go virtual, regardless of balance.
- Two consecutive shadow wins -> weather clear -> everything real again.
- Real win resets the loss streak. Hard floor unchanged.
"""
import ast

p = r'C:\Projects\KinoliveLines\live\owl_manual_bot.py'
s = open(p, encoding='utf-8').read()

# A) state
old = '''    st.setdefault("recov_watches", [])  # armed watches, one per chain:'''
new = '''    st.setdefault("wx", {"ls": 0, "forced": False})  # weather v2:
                                        # real-loss streak + forced shelter
    st.setdefault("recov_watches", [])  # armed watches, one per chain:'''
assert old in s
s = s.replace(old, new)

# B) storm detector on every journaled exit
old = '''                # --- RECOVERY CHAIN trigger (user spec 2026-08-31;'''
new = '''                # --- WEATHER v2 storm detector ---
                if RECOV_ENTRY:
                    _wx = st.setdefault("wx", {"ls": 0, "forced": False})
                    _px2 = float(row.get("profit_usd") or 0.0)
                    if _px2 < -0.5:
                        _wx["ls"] += 1
                        if _wx["ls"] >= 3 and not _wx["forced"]:
                            _wx["forced"] = True
                            _sh0 = st.setdefault(
                                "shadow", {"links": [], "streak": 0})
                            _sh0["streak"] = 0
                            say("WEATHER: storm detected (3 straight "
                                "real losses) - FULL SHELTER, everything "
                                "goes virtual")
                            try:
                                json.dump({"mode": "shelter",
                                           "streak": 0},
                                          open(os.path.join(
                                              DIR, "owl_weather.json"),
                                              "w"))
                            except Exception:
                                pass
                    elif _px2 > 0.5:
                        _wx["ls"] = 0
                    save_state(st)
                # --- RECOVERY CHAIN trigger (user spec 2026-08-31;'''
assert old in s
s = s.replace(old, new)

# C) chain shelter condition includes forced shelter
old = '''                                elif (chain_floor
                                      and ai is not None
                                      and ai.balance < chain_floor
                                      and (ai.balance < hard_floor
                                           or (st.get("shadow") or {})
                                           .get("streak", 0) < 2)):'''
new = '''                                elif (ai is not None
                                      and (((chain_floor
                                             and ai.balance < chain_floor)
                                            or (st.get("wx") or {})
                                            .get("forced"))
                                           and (ai.balance < hard_floor
                                                or (st.get("shadow") or {})
                                                .get("streak", 0) < 2))):'''
assert old in s
s = s.replace(old, new)

# D) kino entries go virtual in forced shelter
old = '''    st["kino_last_skip"] = None
    tick = mt5.symbol_info_tick(SYMBOL)'''
assert old in s
# (anchor split: keep the dup-check ordering; inject after dup check)
old2 = '''    st["kino_last_skip"] = None
'''
new2 = '''    st["kino_last_skip"] = None
    if ((st.get("wx") or {}).get("forced")
            and (st.get("shadow") or {}).get("streak", 0) < 2):
        _sh = st.setdefault("shadow", {"links": [], "streak": 0})
        _sdist = abs(entry_px - wall)
        _stpd = max(RECOV_MIN_WALL_PTS / 2.0,
                    _sdist - 0.75 / KINO_LOTS)
        _stp = (entry_px + _stpd if direction == 1
                else entry_px - _stpd)
        _sh["links"].append({"dir": direction, "lot": KINO_LOTS,
                             "entry": entry_px, "sl": round(wall, 2),
                             "tp": round(_stp, 2), "chain": "page"})
        save_state(st)
        say(f"SHADOW page ENTRY: "
            f"{'BUY' if direction == 1 else 'SELL'} {KINO_LOTS} @ "
            f"{entry_px:.2f} (virtual - shelter mode)")
        return -1
'''
assert s.count(old2) == 1
s = s.replace(old2, new2)

# E) weather clear also lifts forced shelter + resets loss streak
old = '''                            if _sh["streak"] == 2:
                                say("WEATHER CLEAR: two shadow wins - "
                                    "real chains AUTO-RESUME "
                                    "(hard floor still guards)")'''
new = '''                            if _sh["streak"] == 2:
                                _wx2 = st.setdefault(
                                    "wx", {"ls": 0, "forced": False})
                                _wx2["forced"] = False
                                _wx2["ls"] = 0
                                say("WEATHER CLEAR: two shadow wins - "
                                    "everything real AUTO-RESUMES "
                                    "(hard floor still guards)")'''
assert old in s
s = s.replace(old, new)

# F) balance-recovery reset only when not in forced shelter
old = '''                if ai.balance >= chain_floor and (
                        _sh["links"] or _sh["streak"]):'''
new = '''                if (ai.balance >= chain_floor
                        and not (st.get("wx") or {}).get("forced")
                        and (_sh["links"] or _sh["streak"])):'''
assert old in s
s = s.replace(old, new)

open(p, 'w', encoding='utf-8').write(s)
ast.parse(s)
open(p, encoding='cp1252').read()
print("weather v2 built, syntax OK, cp1252-safe")
