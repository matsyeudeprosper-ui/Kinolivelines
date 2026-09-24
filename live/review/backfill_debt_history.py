"""Owner 2026-09-24: "we already have few past days of debts in the
trading journal right? ... use existing historical past trades daily
losses to come up with the starting daily realistic debt to work with
instead of waiting for another 3 days."

Replays each account's REAL closed deal history (same MAGIC filter, same
high-water-mark debt formula as book_closes() in structure_bos_bot.py)
day by day, and for every day that OPENED already in debt (>0.5),
records that day's real total pnl - exactly what day_roll() would have
appended to st["debt_day_pnls"] had this feature existed from the start.

Writes the result into each account's own bos_state*.json
(debt_day_pnls, capped at DEBT_CAP_WINDOW like the live code), so
debt_recoverable() has real history immediately instead of needing 3
more live debt-days. Sanity-checks the replay against the state file's
own banked/debt before writing anything - if they don't match (missed
deals, manual edits), it refuses to write rather than seed bad history.

    python review/backfill_debt_history.py            (dry run, prints only)
    python review/backfill_debt_history.py --write     (writes state files)
"""
import json
import os
import sys
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
LIVE = os.path.dirname(HERE)
sys.path.insert(0, LIVE)

import MetaTrader5 as mt5              # noqa: E402
import structure_bos_bot as B          # noqa: E402
B.say = lambda *a, **k: None

WRITE = "--write" in sys.argv[1:]

ACCOUNTS = [
    # name, state file, magic, terminal/login/server source
    dict(name="Dad", state="bos_state.json", magic=909101,
         terminal=r"C:\NestTerminals\u223995441\terminal64.exe",
         login=223995441, server="Exness-MT5Real30"),
    dict(name="Mike", state="bos_state_kino.json", magic=909501,
         uid="kino"),
    dict(name="Valere", state="bos_state_valere.json", magic=909401,
         uid="u224016179"),
    dict(name="demo", state="bos_state_demo.json", magic=909601,
         uid="demo"),
    dict(name="Infinity", state="bos_state_infinity.json", magic=909701,
         uid="infinity"),
]


def creds(acc):
    if "uid" in acc:
        u = next(x for x in json.load(open(os.path.join(
            LIVE, "owl_nest_users.json"), encoding="utf-8"))
            if x["id"] == acc["uid"])
        return u["terminal"], int(u["mt5_login"]), u["mt5_server"], \
            u["mt5_password"]
    return acc["terminal"], acc["login"], acc["server"], None


def day_key_utc(ts):
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")


def replay(acc):
    terminal, login, server, pwd = creds(acc)
    kw = dict(path=terminal, login=login, server=server, timeout=60000)
    if pwd:
        kw["password"] = pwd
    if not mt5.initialize(**kw):
        print(f"  {acc['name']}: MT5 init failed {mt5.last_error()}")
        return None
    ai = mt5.account_info()
    now = datetime.now(timezone.utc)
    deals = mt5.history_deals_get(now - timedelta(days=120), now) or []
    mt5.shutdown()
    outs = sorted(
        [d for d in deals if d.magic == acc["magic"]
         and d.entry == mt5.DEAL_ENTRY_OUT],
        key=lambda d: d.time)

    banked = peak = 0.0
    debt_at_open = 0.0
    day_pnl = 0.0
    cur_day = None
    samples = []
    for d in outs:
        dk = day_key_utc(d.time)
        if dk != cur_day:
            if cur_day is not None and debt_at_open > 0.5:
                samples.append(round(day_pnl, 2))
            debt_at_open = round(max(0.0, peak - banked), 2)
            day_pnl = 0.0
            cur_day = dk
        pnl = d.profit + d.swap + d.commission
        banked = round(banked + pnl, 2)
        day_pnl = round(day_pnl + pnl, 2)
        if banked > peak:
            peak = banked
        debt_now = round(max(0.0, peak - banked), 2)
    if cur_day is not None and debt_at_open > 0.5:
        samples.append(round(day_pnl, 2))

    final_debt = round(max(0.0, peak - banked), 2)
    return dict(n_deals=len(outs), banked=banked, peak=peak,
                debt=final_debt, samples=samples,
                live_login=ai.login if ai else None)


def main():
    for acc in ACCOUNTS:
        print(f"\n  === {acc['name']} ===")
        r = replay(acc)
        if r is None:
            continue
        print(f"  {r['n_deals']} closed deals replayed, login "
              f"{r['live_login']}")
        print(f"  reconstructed: banked={r['banked']:.2f} "
              f"peak={r['peak']:.2f} debt={r['debt']:.2f}")

        st_path = os.path.join(LIVE, acc["state"])
        st = json.load(open(st_path, encoding="utf-8"))
        live_banked = st.get("banked", 0.0)
        live_debt = st.get("debt", 0.0)
        print(f"  live state file: banked={live_banked:.2f} "
              f"debt={live_debt:.2f}")
        ok = (abs(r["banked"] - live_banked) < 0.05
              and abs(r["debt"] - live_debt) < 0.05)
        print(f"  matches live state: {ok}")

        print(f"  debt-day samples found ({len(r['samples'])}): "
              f"{r['samples']}")

        if not ok:
            print("  MISMATCH - refusing to write for this account")
            continue
        if not r["samples"]:
            print("  no qualifying debt-days in the window - nothing to add")
            continue

        if WRITE:
            existing = st.get("debt_day_pnls") or []
            merged = (r["samples"] + existing)[-B.DEBT_CAP_WINDOW:]
            st["debt_day_pnls"] = merged
            tmp = st_path + ".tmp"
            json.dump(st, open(tmp, "w", encoding="utf-8"))
            os.replace(tmp, st_path)
            print(f"  WROTE debt_day_pnls = {merged}")
        else:
            print("  (dry run - pass --write to actually save)")
    print()


if __name__ == "__main__":
    main()
