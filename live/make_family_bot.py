"""make_family_bot.py <uid> - generate a per-user Owl bot (2026-09-05).

User decision: family members trade their REAL accounts with the same
bot; outside people go through MQL5 instead. One bot instance per user
terminal, cloned from owl_manual_bot.py with:
  - the user's login/password/server + their provisioned terminal
  - every state/log/config file per-user (owl_fam_<uid>_*)
  - its own pause file (owl_trading_pause_<uid>.json) which the app's
    pause button writes for this user

The generated file embeds the account password -> live/owl_fam_* is
gitignored. Regenerate after master-bot changes: the clone does NOT
auto-update.

Usage: python make_family_bot.py luc
Then:  pythonw owl_fam_luc_bot.py   (or add to boot_all.ps1)
"""
import json
import os
import sys

DIR = r"C:\Projects\KinoliveLines\live"
uid = sys.argv[1]
users = json.load(open(os.path.join(DIR, "owl_nest_users.json"),
                       encoding="utf-8"))
u = next(x for x in users if x["id"] == uid)
src = open(os.path.join(DIR, "owl_manual_bot.py"),
           encoding="utf-8").read()


def rep(a, b):
    global src
    assert a in src, f"anchor missing: {a[:60]}"
    src = src.replace(a, b)


login = int(u.get("mt5_login") or u["login"])
server = u.get("mt5_server", "")
pwd = u.get("mt5_password", "")
assert u.get("terminal"), f"{uid} has no terminal - provision first"
assert pwd, f"{uid} has no mt5_password in the record"

rep("LOGIN = 134499778",
    f"LOGIN = {login}\nFAM_SERVER = {server!r}\nFAM_PASSWORD = {pwd!r}")
rep('TERMINAL = r"C:\\Projects\\MT5-KinoliveTrader\\terminal64.exe"',
    f'TERMINAL = r"{u["terminal"]}"')
rep("if not mt5.initialize(path=TERMINAL):",
    "if not mt5.initialize(path=TERMINAL, login=LOGIN, "
    "password=FAM_PASSWORD, server=FAM_SERVER):")

for a, b in [
    ("owl_manual.log", f"owl_fam_{uid}.log"),
    ("owl_manual_alive.json", f"owl_fam_{uid}_alive.json"),
    ("owl_manual_state.json", f"owl_fam_{uid}_state.json"),
    ("owl_manual_journal.csv", f"owl_fam_{uid}_journal.csv"),
    ("owl_market_log.csv", f"owl_fam_{uid}_market_log.csv"),
    ("owl_trading_pause.json", f"owl_trading_pause_{uid}.json"),
    ("owl_weather.json", f"owl_weather_{uid}.json"),
    ("owl_chain_floor.json", f"owl_chain_floor_{uid}.json"),
    ("owl_milestone.json", f"owl_milestone_{uid}.json"),
    ("owl_equity_trail.json", f"owl_equity_trail_{uid}.json"),
    ("owl_kino_pause.json", f"owl_kino_pause_{uid}.json"),
]:
    src = src.replace(a, b)

out = os.path.join(DIR, f"owl_fam_{uid}_bot.py")
open(out, "w", encoding="utf-8").write(src)
print("written", out)
