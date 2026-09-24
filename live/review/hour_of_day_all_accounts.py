"""Owner 2026-09-24: "test which range of the hour makes more money.
Check all journal ever recorded of trades of all bots and strategies
ever tested."

Pulls REAL closed-deal history straight from MT5 for every real/demo
account this project has ever traded - not a backtest replay, the
actual recorded outcomes. Pairs each position's entry deal (for the
UTC hour it was OPENED, matching the convention already used in
mt5_owl_packages.md's 2026-09-19 session_test.py) with its exit deal
(for the realised $).

Accounts covered: the 5 live structure-bot accounts (Dad/Mike/Valere/
demo/Infinity), CROC (retired 2026-09-24, magic 0), Harvest BTC+ETH
(magic 909001/909002), and the retired std account - one row per
account, no magic filter on std/CROC since those aren't shared
terminals. sniper/halfdebt (both "compte mort") attempted too if their
terminals are still reachable; skipped cleanly if not.

Reports BOTH a per-strategy breakdown (different strategies trade very
differently - pooling them blindly can mislead) AND an all-pooled view.

    python review/hour_of_day_all_accounts.py
"""
import json
import os
from datetime import datetime, timedelta, timezone

import MetaTrader5 as mt5

HERE = os.path.dirname(os.path.abspath(__file__))
LIVE = os.path.dirname(HERE)

_users = {x["id"]: x for x in json.load(open(os.path.join(
    LIVE, "owl_nest_users.json"), encoding="utf-8"))}


def u(uid):
    x = _users[uid]
    return dict(terminal=x["terminal"], login=int(x["mt5_login"]),
               server=x["mt5_server"], password=x.get("mt5_password"))


ACCOUNTS = [
    dict(label="Structure/SMC - Dad", strategy="Structure/SMC",
         magic=909101, **u("bos")),
    dict(label="Structure/SMC - Mike", strategy="Structure/SMC",
         magic=909501, **u("kino")),
    dict(label="Structure/SMC - Valere", strategy="Structure/SMC",
         magic=909401, **u("u224016179")),
    dict(label="Structure/SMC - demo", strategy="Structure/SMC",
         magic=909601, **u("demo")),
    dict(label="Structure/SMC - Infinity", strategy="Structure/SMC",
         magic=909701, **u("infinity")),
    dict(label="Harvest H1 - BTC", strategy="Harvest H1",
         magic=909001, **u("fresh")),
    dict(label="Harvest H1 - ETH", strategy="Harvest H1",
         magic=909002, **u("fresh")),
    dict(label="CROC (retired)", strategy="CROC",
         magic=0, terminal=r"C:\Projects\MT5-KinoliveTrader-Session3\terminal64.exe",
         login=476715495, server="Exness-MT5Trial9",
         password=json.load(open(os.path.join(
             LIVE, "owl_secrets.json"), encoding="utf-8"))["mt5_password"]),
    dict(label="std (retired, historical)", strategy="std/other",
         magic=None, terminal=r"C:\Projects\MT5-KinoliveTrader\terminal64.exe",
         login=None, server=None, password=None),
    dict(label="sniper (dead trial)", strategy="std/other", magic=909201,
         terminal=r"C:\NestTerminals\u476989735\terminal64.exe",
         login=476989735, server="Exness-MT5Trial9", password=None),
    dict(label="halfdebt (dead trial)", strategy="std/other", magic=909301,
         terminal=r"C:\NestTerminals\u476989740\terminal64.exe",
         login=476989740, server="Exness-MT5Trial9", password=None),
]

SESSIONS = [("Asia 0-7", 0, 7), ("London 7-13", 7, 13),
            ("New York 13-20", 13, 20), ("Late 20-24", 20, 24)]


def pull(acc, days_back=365):
    kw = dict(path=acc["terminal"], timeout=60000)
    if acc.get("login"):
        kw["login"] = acc["login"]
    if acc.get("server"):
        kw["server"] = acc["server"]
    if acc.get("password"):
        kw["password"] = acc["password"]
    if not mt5.initialize(**kw):
        print(f"  {acc['label']:<28} SKIP - init failed {mt5.last_error()}")
        return []
    ai = mt5.account_info()
    now = datetime.now(timezone.utc)
    deals = mt5.history_deals_get(now - timedelta(days=days_back), now) or []
    mt5.shutdown()
    magic = acc.get("magic")
    deals = [d for d in deals if magic is None or d.magic == magic]
    entry_t = {}
    for d in deals:
        if d.entry == mt5.DEAL_ENTRY_IN:
            entry_t.setdefault(d.position_id, d.time)
    rows = []
    for d in deals:
        if d.entry != mt5.DEAL_ENTRY_OUT:
            continue
        pnl = d.profit + d.swap + d.commission
        et = entry_t.get(d.position_id, d.time)
        hr = datetime.fromtimestamp(et, tz=timezone.utc).hour
        rows.append(dict(label=acc["label"], strategy=acc["strategy"],
                         hour=hr, pnl=pnl, win=pnl > 0))
    print(f"  {acc['label']:<28} login={ai.login if ai else '?':<10} "
          f"{len(rows):>4} closed trades")
    return rows


def summarize(rows, name):
    if not rows:
        print(f"    {name:<20} (no trades)")
        return
    n = len(rows)
    wins = sum(1 for r in rows if r["win"])
    net = sum(r["pnl"] for r in rows)
    print(f"    {name:<20} n={n:<5} win%={100*wins/n:5.1f}  "
          f"net=${net:+9.2f}  avg=${net/n:+.3f}")


def main():
    all_rows = []
    print("  PULLING REAL DEAL HISTORY (up to 365 days back per account)\n")
    for acc in ACCOUNTS:
        all_rows.extend(pull(acc))
    print(f"\n  {len(all_rows)} total closed real trades found across "
          f"every account\n")

    strategies = sorted(set(r["strategy"] for r in all_rows))

    print("  ===== BY HOUR (UTC), ALL STRATEGIES POOLED =====")
    for h in range(24):
        summarize([r for r in all_rows if r["hour"] == h], f"{h:02d}:00")

    print("\n  ===== BY SESSION, ALL STRATEGIES POOLED =====")
    for lab, a, b in SESSIONS:
        summarize([r for r in all_rows if a <= r["hour"] < b], lab)

    for strat in strategies:
        srows = [r for r in all_rows if r["strategy"] == strat]
        print(f"\n  ===== BY SESSION - {strat} only ({len(srows)} trades) =====")
        for lab, a, b in SESSIONS:
            summarize([r for r in srows if a <= r["hour"] < b], lab)
    print()


if __name__ == "__main__":
    main()
