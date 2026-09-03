src = open('owl_manual_bot.py', encoding='utf-8').read()

def rep(old, new):
    global src
    assert old in src, f"NOT FOUND: {old[:60]!r}"
    src = src.replace(old, new)

# flag + helper
rep("BUFFER_USD = 0.10",
    """MANUAL_HANDS_OFF = True    # 2026-08-25 user: NEVER modify/close/TP the
                           # user's own hand trades. Bot-opened positions
                           # (comment OWL-*) keep full management. Hand trades
                           # are only JOURNALED. They also no longer count
                           # toward the auto stack cap.
def is_bot_pos(p):
    return (p.comment or "").startswith("OWL-")

BUFFER_USD = 0.10""")
# hour-flat: sweep bot positions only
rep("                    flatable = [p for p in manual if p.ticket not in runner_tickets]",
    "                    flatable = [p for p in manual if p.ticket not in runner_tickets\n"
    "                                and (is_bot_pos(p) or not MANUAL_HANDS_OFF)]")
# reassign/TP management: bot positions only
rep("                reassign(st, manual, tick)\n                st[\"last_tickets\"] = cur_ids",
    "                reassign(st, [p for p in manual if is_bot_pos(p) or not MANUAL_HANDS_OFF], tick)\n"
    "                st[\"last_tickets\"] = cur_ids")
rep("                    reassign(st, manual, tick)   # restore normal management",
    "                    reassign(st, [p for p in manual if is_bot_pos(p) or not MANUAL_HANDS_OFF], tick)")
# enforcement loop: never touch hand trades
rep("                if p.ticket in runner_tickets:\n                    continue          # runner legs have their own manager",
    "                if p.ticket in runner_tickets:\n                    continue          # runner legs have their own manager\n"
    "                if MANUAL_HANDS_OFF and not is_bot_pos(p):\n                    continue          # user's hand trade: fully hands-off")
# escape/hedge detection: bot positions only
rep("            buys = [p for p in manual if p.type == mt5.POSITION_TYPE_BUY]",
    "            _mgd = [p for p in manual if is_bot_pos(p) or not MANUAL_HANDS_OFF]\n"
    "            buys = [p for p in _mgd if p.type == mt5.POSITION_TYPE_BUY]")
rep("            sells = [p for p in manual if p.type == mt5.POSITION_TYPE_SELL]",
    "            sells = [p for p in _mgd if p.type == mt5.POSITION_TYPE_SELL]")
# stack counts: bot positions only (dip clone + croc blocks share the same pattern)
src = src.replace(
    "n_stack = (len([p for p in manual\n"
    "                                        if p.ticket not in runner_tickets\n"
    "                                        and p.ticket not in split_tickets])\n"
    "                                   + len(st.get(\"splits\") or []))",
    "n_stack = (len([p for p in manual\n"
    "                                        if p.ticket not in runner_tickets\n"
    "                                        and p.ticket not in split_tickets\n"
    "                                        and (is_bot_pos(p) or not MANUAL_HANDS_OFF)])\n"
    "                                   + len(st.get(\"splits\") or []))")
src = src.replace(
    "n_stack = (len([p for p in manual\n"
    "                                                if p.ticket not in runner_tickets\n"
    "                                                and p.ticket not in split_tickets])\n"
    "                                           + len(st.get(\"splits\") or []))",
    "n_stack = (len([p for p in manual\n"
    "                                                if p.ticket not in runner_tickets\n"
    "                                                and p.ticket not in split_tickets\n"
    "                                                and (is_bot_pos(p) or not MANUAL_HANDS_OFF)])\n"
    "                                           + len(st.get(\"splits\") or []))")
open('owl_manual_bot.py', 'w', encoding='utf-8').write(src)
import ast
ast.parse(src)
open('owl_manual_bot.py', encoding='cp1252').read()
print("hands-off patch applied, syntax OK, cp1252-safe")
print("stack-count patches applied:", src.count("and (is_bot_pos(p) or not MANUAL_HANDS_OFF)])"))
