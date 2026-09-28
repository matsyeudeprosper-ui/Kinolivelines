"""What if Valere's account had only taken CALM entries (nervosity < 1.0x)
since it started (2026-09-14)?  Owner question, 2026-09-28.

Source of truth: the broker's deal history read from Valere's own terminal
(C:\\NestTerminals\\u224016179), one row per POSITION (the log's WIN/LOSS
lines only print the main position, the catch-up adds are separate
positions - the bot's "net +28.22" only reconciles with the deals).

Nervosity is recomputed from M1 history exactly as the feed does it
(owl_chart_feed.py): median M1 range of the last 60 closed candles over the
median of the last 1440, at the entry minute.

Caveat: dropping trades does not re-size the survivors - the catch-up lots
depended on losses that would not have happened - so "calm only" is a
first-order answer, not a replay.

Result 2026-09-28 (14/09 -> 28/09): 36 positions, net +28.22.
  calme <1,0        27 positions, 19 wins (70%), net +27.59
  soutenu 1,0-1,3    7 positions,  4 wins (57%), net  +5.42
  rapide 1,3-1,85    2 positions,  0 wins,       net  -4.79
  calm only: 27 positions, +27.59  |  skipped: 9 positions, +0.63
"""
import sys, datetime as dt, statistics, bisect
from collections import defaultdict
import MetaTrader5 as mt5

TERM = r"C:\NestTerminals\u224016179\terminal64.exe"
SYMBOL = "BTCUSD"
SINCE = dt.datetime(2026, 9, 13, tzinfo=dt.timezone.utc)

if not mt5.initialize(path=TERM):
    sys.exit("MT5 init failed: " + str(mt5.last_error()))
ai = mt5.account_info()
print("account", ai.login, "balance", ai.balance)
now = dt.datetime.now(dt.timezone.utc)
deals = mt5.history_deals_get(SINCE, now) or []
pos = defaultdict(lambda: {"in": None, "p": 0.0, "lots": 0.0})
for d in deals:
    if d.symbol != SYMBOL:
        continue
    P = pos[d.position_id]
    if d.entry == 0:                       # IN deal
        if P["in"] is None or d.time < P["in"]:
            P["in"] = d.time
        P["lots"] += d.volume
    P["p"] += d.profit + d.swap + d.commission
closed = sorted((v["in"], v["p"], v["lots"]) for v in pos.values() if v["in"])
mt5.symbol_select(SYMBOL, True)
rates = mt5.copy_rates_range(SYMBOL, mt5.TIMEFRAME_M1, SINCE, now)
mt5.shutdown()
if rates is None or len(rates) == 0:
    sys.exit("no M1 history")
times = [int(r["time"]) for r in rates]
rng = [float(r["high"]) - float(r["low"]) for r in rates]


def nerv(ts):
    i = bisect.bisect_left(times, ts)
    if i < 1441:
        return None
    return statistics.median(rng[i - 60:i]) / max(statistics.median(rng[i - 1440:i]), 1e-9)


def band(n):
    return "calme <1,0" if n < 1.0 else ("soutenu 1,0-1,3" if n < 1.30 else ("rapide 1,3-1,85" if n < 1.85 else "tres rapide >=1,85"))


d = defaultdict(lambda: [0, 0, 0.0]); calm = allp = 0.0; kept = miss = 0
print(f"{len(closed)} positions, net {sum(p for _, p, _ in closed):+.2f}\n")
print(" entry (UTC)        lot   nerv   band                 result")
for ts, p, l in closed:
    n = nerv(ts)
    if n is None:
        miss += 1; continue
    b = band(n); d[b][0] += 1; d[b][1] += (p > 0); d[b][2] += p; allp += p
    if n < 1.0:
        calm += p; kept += 1
    print(f" {dt.datetime.fromtimestamp(ts, dt.timezone.utc):%d/%m %H:%M}  {l:5.2f}  {n:5.2f}x  {b:20s} {p:+7.2f}")
print("\nby band:")
for b in ["calme <1,0", "soutenu 1,0-1,3", "rapide 1,3-1,85", "tres rapide >=1,85"]:
    n, w, p = d[b]
    if n:
        print(f"  {b:20s} {n:2d} positions {w:2d} wins ({100*w/n:3.0f}%)  net {p:+7.2f}")
tot = sum(v[0] for v in d.values())
print(f"\nactual, all positions : {tot}, net {allp:+.2f}")
print(f"calm only (<1.0x)     : {kept}, net {calm:+.2f}")
print(f"skipped (>=1.0x)      : {tot - kept}, net {allp - calm:+.2f}")
if miss:
    print(f"(no history for {miss} positions)")
