"""HALF-SIZE CHOP MODE (user 2026-09-03 'build it, make it live'):
- Base lot = 0.01 when balance < soft chain_floor (prudent/chop), else 0.02.
  Fighters inherit the smaller base, so the whole ladder is gentler in chop.
- Chains trade REAL below the soft floor (no longer ghost-caged there);
  only a STORM (3 straight real losses / forced) ghosts everything.
- Hard floor stays absolute: below it, no new fighters (base pages only).
- 3-loss storm rest unchanged.
"""
import ast

p = r'C:\Projects\KinoliveLines\live\owl_manual_bot.py'
s = open(p, encoding='utf-8').read()

# --- 1) dynamic base lot in kino_open ---
old = '''    st["kino_last_skip"] = None
    if ((st.get("wx") or {}).get("forced")'''
new = '''    st["kino_last_skip"] = None
    # HALF-SIZE CHOP MODE: base 0.01 below the soft floor, else 0.02
    try:
        _cfj0 = json.load(open(os.path.join(DIR, "owl_chain_floor.json")))
        _softfloor = float(_cfj0.get("floor", 0.0))
    except Exception:
        _softfloor = 0.0
    blot = (0.01 if (_softfloor and ai is not None
                     and ai.balance < _softfloor) else KINO_LOTS)
    if ((st.get("wx") or {}).get("forced")'''
assert old in s and s.count(old) == 1
s = s.replace(old, new)

# replace KINO_LOTS with blot in the kino_open body (shadow + real paths)
# shadow path
s = s.replace('''                    _sdist - 0.75 / KINO_LOTS)''',
              '''                    _sdist - 0.75 / blot)''')
s = s.replace('''        _sh["links"].append({"dir": direction, "lot": KINO_LOTS,''',
              '''        _sh["links"].append({"dir": direction, "lot": blot,''')
s = s.replace('''            f"{'BUY' if direction == 1 else 'SELL'} {KINO_LOTS} @ "
            f"{entry_px:.2f} (virtual - shelter mode)")''',
              '''            f"{'BUY' if direction == 1 else 'SELL'} {blot} @ "
            f"{entry_px:.2f} (virtual - shelter mode)")''')
# real path
s = s.replace('''    risk = dist * KINO_LOTS
    r = open_at_market(direction, KINO_LOTS, "OWL-kino")''',
              '''    risk = dist * blot
    r = open_at_market(direction, blot, "OWL-kino")''')
s = s.replace('''    tp_dist = dist - disc / KINO_LOTS''',
              '''    tp_dist = dist - disc / blot''')
s = s.replace('''    say(f"KINO ENTRY: {'BUY' if direction == 1 else 'SELL'} {KINO_LOTS} @ "
        f"~{entry_px:.2f} SL {slp} TP {tp:.2f} (risk ${risk:.2f}, prize "
        f"${tp_dist * KINO_LOTS:.2f}, return to "''',
              '''    say(f"KINO ENTRY: {'BUY' if direction == 1 else 'SELL'} {blot} @ "
        f"~{entry_px:.2f} SL {slp} TP {tp:.2f} (risk ${risk:.2f}, prize "
        f"${tp_dist * blot:.2f}, return to "''')

# --- 2) chain gating: storm-only ghost + hard-floor fighter block ---
old = '''                                elif (ai is not None
                                      and (((chain_floor
                                             and ai.balance < chain_floor)
                                            or (st.get("wx") or {})
                                            .get("forced"))
                                           and (ai.balance < hard_floor
                                                or (st.get("shadow") or {})
                                                .get("streak", 0) < 2))):
                                    # SHELTER MODE: fight virtually instead'''
new = '''                                elif ((st.get("wx") or {}).get("forced")
                                      and (st.get("shadow") or {})
                                      .get("streak", 0) < 2):
                                    # STORM shelter: fight virtually instead'''
assert old in s and s.count(old) == 1
s = s.replace(old, new)

# add hard-floor real-fighter block just before the MAX_OPEN_PAGES check
old = '''                                elif (owl_open_count + len(_fired)
                                        >= MAX_OPEN_PAGES):'''
new = '''                                elif (ai is not None and hard_floor
                                        and ai.balance < hard_floor):
                                    if not rw.get("held_hard"):
                                        rw["held_hard"] = True
                                        _dirty = True
                                        say(f"RECOV[{_cn}] held: below hard "
                                            f"floor {hard_floor:.0f} - no "
                                            f"fighters, small pages only")
                                elif (owl_open_count + len(_fired)
                                        >= MAX_OPEN_PAGES):'''
assert old in s and s.count(old) == 1
s = s.replace(old, new)

open(p, 'w', encoding='utf-8').write(s)
ast.parse(s)
open(p, encoding='cp1252').read()
print("half-size chop mode built, syntax OK, cp1252-safe")
