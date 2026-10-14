"""mt5_history_check.py <terminal64.exe> - how much deal history does this
terminal hold? Prints first/last deal and deals in the last 7 and 30 days.
A terminal whose history stops weeks ago while its bot traded since needs
mt5_history_resync.ps1 (see that file for the 2026-10-14 story)."""
import sys
from datetime import datetime, timedelta, timezone

import MetaTrader5 as mt5

path = sys.argv[1]
if not mt5.initialize(path=path, timeout=120000):
    print(f"{path}: cannot connect {mt5.last_error()}")
    sys.exit(1)
now = datetime.now(timezone.utc)
deals = mt5.history_deals_get(datetime(2020, 1, 1, tzinfo=timezone.utc), now + timedelta(days=1)) or []
ts = sorted(d.time for d in deals)
a = mt5.account_info()
first = datetime.fromtimestamp(ts[0], timezone.utc).strftime("%Y-%m-%d") if ts else "-"
last = datetime.fromtimestamp(ts[-1], timezone.utc).strftime("%Y-%m-%d %H:%M") if ts else "-"
n7 = sum(t > (now - timedelta(days=7)).timestamp() for t in ts)
n30 = sum(t > (now - timedelta(days=30)).timestamp() for t in ts)
print(f"{a.login if a else '?'}: {len(ts)} deals, {first} -> {last}, last 7d {n7}, last 30d {n30}")
mt5.shutdown()
