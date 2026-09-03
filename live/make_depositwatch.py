src = open('owl_manual_bot.py', encoding='utf-8').read()

def rep(old, new):
    global src
    assert old in src, f"NOT FOUND: {old[:70]!r}"
    assert src.count(old) == 1, f"NOT UNIQUE: {old[:70]!r}"
    src = src.replace(old, new)

# state: remember the last balance-deal time we processed
rep('''    st.setdefault("recov_watches", [])  # armed watches, one per chain:''',
    '''    st.setdefault("bal_seen", 0)        # epoch of last processed deposit/
                                        # withdrawal deal (deposit watcher)
    st.setdefault("recov_watches", [])  # armed watches, one per chain:''')

# deposit watcher: deposits raise the Squirrel target 1:1 (user 2026-08-31:
# "even if I add funds the maths still auto update and holds" - added money
# is floor, never milestone progress)
rep('''            # --- MILESTONE CUT (user order 2026-08-28: sanctioned exception''',
    '''            # --- DEPOSIT WATCHER (user 2026-08-31): deposits auto-raise the
            # Squirrel milestone target 1:1, so only PROFIT can complete a
            # milestone. Withdrawals are left to the assistant's ladder.
            try:
                if not st.get("bal_seen"):
                    st["bal_seen"] = int(time.time())
                    save_state(st)
                _dls = mt5.history_deals_get(
                    datetime.fromtimestamp(st["bal_seen"] + 1, tz=timezone.utc),
                    datetime.now(timezone.utc) + timedelta(minutes=5)) or []
                for _dl in _dls:
                    if _dl.type != mt5.DEAL_TYPE_BALANCE:
                        continue
                    st["bal_seen"] = max(st["bal_seen"], int(_dl.time))
                    save_state(st)
                    if _dl.profit > 0:
                        _mp = os.path.join(DIR, "owl_milestone.json")
                        try:
                            _mj = json.load(open(_mp))
                        except Exception:
                            _mj = {}
                        _old = float(_mj.get("milestone", 0) or 0)
                        if _old > 0:
                            _mj["milestone"] = round(_old + _dl.profit, 2)
                            _mj["note"] = (f"auto: +{_dl.profit:.2f} deposit "
                                           f"-> target {_old:.2f} -> "
                                           f"{_mj['milestone']:.2f}")
                            json.dump(_mj, open(_mp, "w"))
                            say(f"DEPOSIT detected: +{_dl.profit:.2f} -> "
                                f"Squirrel target auto-raised "
                                f"{_old:.2f} -> {_mj['milestone']:.2f} "
                                f"(deposits are floor, not progress)")
                    elif _dl.profit < 0:
                        say(f"WITHDRAWAL detected: {_dl.profit:.2f} "
                            f"(ladder handled by assistant)")
            except Exception:
                pass
            # --- MILESTONE CUT (user order 2026-08-28: sanctioned exception''')

open('owl_manual_bot.py', 'w', encoding='utf-8').write(src)
import ast
ast.parse(src)
open('owl_manual_bot.py', encoding='cp1252').read()
print("deposit-watcher patch applied, syntax OK, cp1252-safe")
