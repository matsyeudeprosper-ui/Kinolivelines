import json

json.dump({"floor": 250.0, "pct_of_start": 0.78, "start": 320.61,
           "note": "chain floor = 78% of journey start; assistant recomputes "
                   "on every reset (user 2026-09-01)"},
          open(r'C:\Projects\KinoliveLines\live\owl_chain_floor.json', 'w'))

src = open('owl_manual_bot.py', encoding='utf-8').read()

def rep(old, new):
    global src
    assert old in src, "NOT FOUND: " + old[:70]
    assert src.count(old) == 1, "NOT UNIQUE: " + old[:70]
    src = src.replace(old, new)

rep("GROUP_HEAL_ENABLED = False  # 2026-09-01 user: \"rethink it later, dont",
    """MAX_OPEN_PAGES = 3         # 2026-09-01 user: never more than 3 open Owl
                           # trades (pages + fighters) at once; extra doors
                           # wait their turn.
GROUP_HEAL_ENABLED = False  # 2026-09-01 user: \"rethink it later, dont""")

# per-loop: chain floor + open-page count
rep('''            kino_tickets = set(st.get("kino_tickets") or [])''',
    '''            kino_tickets = set(st.get("kino_tickets") or [])
            try:
                _cfj = json.load(open(os.path.join(
                    DIR, "owl_chain_floor.json")))
                chain_floor = float(_cfj.get("floor", 0.0))
            except Exception:
                chain_floor = 0.0
            owl_open_count = len([p for p in manual
                                  if p.ticket in recov_tickets
                                  or p.ticket in kino_tickets])''')

# chain-entry gates (before the same-signal hold)
rep('''                                elif (same_signal_taken(
                                        new_dir, entry_px, manual,
                                        st) is not None''',
    '''                                elif (chain_floor
                                      and ai is not None
                                      and ai.balance < chain_floor):
                                    if not rw.get("held_floor"):
                                        rw["held_floor"] = True
                                        _dirty = True
                                        say(f"RECOV[{_cn}] held: balance "
                                            f"{ai.balance:.2f} below chain "
                                            f"floor {chain_floor:.0f} - "
                                            f"no new fighters")
                                elif (owl_open_count + len(_fired)
                                        >= MAX_OPEN_PAGES):
                                    if not rw.get("held_pages"):
                                        rw["held_pages"] = True
                                        _dirty = True
                                        say(f"RECOV[{_cn}] held: "
                                            f"{MAX_OPEN_PAGES} open pages "
                                            f"already - door waits")
                                elif (same_signal_taken(
                                        new_dir, entry_px, manual,
                                        st) is not None''')

# kino gate: max open pages
rep('''    tick = mt5.symbol_info_tick(SYMBOL)
    if tick is None:
        return None
    entry_px = tick.ask if direction == 1 else tick.bid
    _dup = same_signal_taken(direction, entry_px, manual, st)''',
    '''    _own = ({int(k) for k in (st.get("recov_links") or {})}
            | set(st.get("kino_tickets") or []))
    _nopen = len([p for p in manual if p.ticket in _own])
    if _nopen >= MAX_OPEN_PAGES:
        _kmsg = f"KINO skipped: {MAX_OPEN_PAGES} open pages already"
        if st.get("kino_last_skip") != _kmsg:
            st["kino_last_skip"] = _kmsg
            say(_kmsg)
        return None
    tick = mt5.symbol_info_tick(SYMBOL)
    if tick is None:
        return None
    entry_px = tick.ask if direction == 1 else tick.bid
    _dup = same_signal_taken(direction, entry_px, manual, st)''')

open('owl_manual_bot.py', 'w', encoding='utf-8').write(src)
import ast
ast.parse(src)
open('owl_manual_bot.py', encoding='cp1252').read()
print("chain floor + 3-page cap built, syntax OK, cp1252-safe")
