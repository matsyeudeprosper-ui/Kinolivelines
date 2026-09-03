src = open('owl_manual_bot.py', encoding='utf-8').read()

def rep(old, new):
    global src
    assert old in src, "NOT FOUND: " + old[:70]
    assert src.count(old) == 1, "NOT UNIQUE: " + old[:70]
    src = src.replace(old, new)

rep("HEAL_EXTRA_USD = 3.0       # heal target = page losses repaid + this",
    """HEAL_EXTRA_USD = 3.0       # heal target = page losses repaid + this
GROUP_HEAL_USD = 2.0       # 2026-09-01 user: while deep fighters are out,
                           # if the FLOATING profit of all Owl trades covers
                           # every fighting page's realized losses (+ this
                           # buffer), cut ALL Owl trades and reset - being
                           # whole beats waiting for far prizes.""")

# one-time loss-ledger backfill for links born before the ledger existed
rep('''    st.setdefault("recov_watches", [])  # armed watches, one per chain:''',
    '''    _bf = {"1047817831": 66.02, "1047817853": 27.60,
           "1047817902": 60.25}   # one-time ledger backfill (2026-09-01)
    for _k, _v in _bf.items():
        _lk = (st.get("recov_links") or {}).get(_k)
        if _lk is not None and not _lk.get("loss"):
            _lk["loss"] = _v
    st.setdefault("recov_watches", [])  # armed watches, one per chain:''')

# the group-heal block, after the ratchet babysitter
rep('''            # --- hour-group cleanup: past-hour groups close when net positive ---''',
    '''            # --- GROUP HEAL (user 2026-09-01): whole-account escape ---
            if RECOV_ENTRY and ai is not None:
                _gl = st.get("recov_links") or {}
                _gw = st.get("recov_watches") or []
                _deep = any(float(v.get("lot", 0)) >= DEEP_LOT
                            for v in _gl.values())
                if _deep:
                    _tot_loss = (sum(float(v.get("loss") or 0.0)
                                     for v in _gl.values())
                                 + sum(float(w.get("loss") or 0.0)
                                       for w in _gw))
                    _float = ai.equity - ai.balance
                    if _float >= _tot_loss + GROUP_HEAL_USD:
                        say(f"GROUP HEAL: floating {_float:+.2f} covers all "
                            f"fighting pages' losses ({_tot_loss:.2f}) "
                            f"-> cutting ALL Owl trades, fresh start")
                        for p in manual:
                            if is_bot_pos(p):
                                r = close_at_market(p, "OWL-group-heal")
                                if (r is not None and r.retcode
                                        == mt5.TRADE_RETCODE_DONE):
                                    say(f"  healed: ticket {p.ticket} "
                                        f"({p.profit:+.2f})")
                                else:
                                    say(f"  heal cut FAILED {p.ticket} "
                                        f"retcode="
                                        f"{r.retcode if r else None}")
                        st["recov_watches"] = []
                        save_state(st)
            # --- hour-group cleanup: past-hour groups close when net positive ---''')

open('owl_manual_bot.py', 'w', encoding='utf-8').write(src)
import ast
ast.parse(src)
open('owl_manual_bot.py', encoding='cp1252').read()
print("group heal built, syntax OK, cp1252-safe")
