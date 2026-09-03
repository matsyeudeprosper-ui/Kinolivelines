"""BELOW-HARD-FLOOR = REST, not bleed (user 2026-09-03):
Base pages alone have negative edge, so below the hard floor we no longer
run edgeless real pages. Instead: full shelter (everything virtual),
ghosts probe, 2 ghost wins -> resume the full half-size engine
(pages + fighters), 3 real losses -> rest again. The hard floor becomes
an evidence-gated brake ('no real trades unless ghosts prove weather')
rather than a fighter-block.
"""
import ast

p = r'C:\Projects\KinoliveLines\live\owl_manual_bot.py'
s = open(p, encoding='utf-8').read()

# 1) kino_open: read hard floor + shelter if forced OR below hard floor
old = '''    try:
        _cfj0 = json.load(open(os.path.join(DIR, "owl_chain_floor.json")))
        _softfloor = float(_cfj0.get("floor", 0.0))
    except Exception:
        _softfloor = 0.0
    blot = (0.01 if (_softfloor and ai is not None
                     and ai.balance < _softfloor) else KINO_LOTS)
    if ((st.get("wx") or {}).get("forced")
            and (st.get("shadow") or {}).get("streak", 0) < 2):'''
new = '''    try:
        _cfj0 = json.load(open(os.path.join(DIR, "owl_chain_floor.json")))
        _softfloor = float(_cfj0.get("floor", 0.0))
        _hardfloor = float(_cfj0.get("hard_floor", 0.0))
    except Exception:
        _softfloor = 0.0
        _hardfloor = 0.0
    blot = (0.01 if (_softfloor and ai is not None
                     and ai.balance < _softfloor) else KINO_LOTS)
    _below_hard = (_hardfloor and ai is not None
                   and ai.balance < _hardfloor)
    if (((st.get("wx") or {}).get("forced") or _below_hard)
            and (st.get("shadow") or {}).get("streak", 0) < 2):'''
assert old in s and s.count(old) == 1
s = s.replace(old, new)

# 2) chain STORM-shelter branch: also shelter below hard floor
old = '''                                elif ((st.get("wx") or {}).get("forced")
                                      and (st.get("shadow") or {})
                                      .get("streak", 0) < 2):
                                    # STORM shelter: fight virtually instead'''
new = '''                                elif (((st.get("wx") or {}).get("forced")
                                       or (hard_floor and ai is not None
                                           and ai.balance < hard_floor))
                                      and (st.get("shadow") or {})
                                      .get("streak", 0) < 2):
                                    # STORM / below-hard-floor: virtual'''
assert old in s and s.count(old) == 1
s = s.replace(old, new)

# 3) remove the now-redundant hard-floor fighter-block branch
old = '''                                elif (ai is not None and hard_floor
                                        and ai.balance < hard_floor):
                                    if not rw.get("held_hard"):
                                        rw["held_hard"] = True
                                        _dirty = True
                                        say(f"RECOV[{_cn}] held: below hard "
                                            f"floor {hard_floor:.0f} - no "
                                            f"fighters, small pages only")
                                elif (owl_open_count + len(_fired)
                                        >= MAX_OPEN_PAGES):'''
new = '''                                elif (owl_open_count + len(_fired)
                                        >= MAX_OPEN_PAGES):'''
assert old in s and s.count(old) == 1
s = s.replace(old, new)

# 4) weather.json mode: show rest ('storm') when below hard floor too
old = '''                                        _md = ("storm"
                                               if (st.get("wx") or {})
                                               .get("forced") else "floor")'''
new = '''                                        _md = ("storm"
                                               if ((st.get("wx") or {})
                                                   .get("forced")
                                                   or (hard_floor
                                                       and ai is not None
                                                       and ai.balance
                                                       < hard_floor))
                                               else "floor")'''
assert old in s and s.count(old) == 1
s = s.replace(old, new)

open(p, 'w', encoding='utf-8').write(s)
ast.parse(s)
open(p, encoding='cp1252').read()
print("below-hard-floor rest mode built, syntax OK, cp1252-safe")
