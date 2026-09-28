"""What do Valere's losing positions have in common - against the winners?
Owner question, 2026-09-28.  Sources: the bot log (kind, direction, stop,
trend, debt, adds, flips), the broker deal history on Valere's terminal
(profit, lots, exit), M1 history (nervosity at entry, the move of the
previous hour).  One row per position (adds included).
"""
import re, sys, datetime as dt, statistics, bisect
from collections import defaultdict, Counter
import MetaTrader5 as mt5

DIR = r"C:\Projects\KinoliveLines\live"
LOG = DIR + r"\bos_bot_valere.log"
TERM = r"C:\NestTerminals\u224016179\terminal64.exe"
SYMBOL = "BTCUSD"
SINCE = dt.datetime(2026, 9, 13, tzinfo=dt.timezone.utc)

# ---- log: entries, adds, results, flips, debt ----
entries, adds, flips, results = [], [], [], []
debt = 0.0
for line in open(LOG, encoding="utf-8", errors="replace"):
    m = re.match(r'^(\S+) ', line)
    if not m:
        continue
    t = dt.datetime.fromisoformat(m.group(1)).timestamp()
    body = line[len(m.group(0)):]
    me = re.match(r'([A-Z-]+) ENTRY: (BUY|SELL) ([\d.]+) @ ~([\d.]+) SL ([\d.]+) TP ([\d.]+) \(risk \$([\d.]+), trend (\w+)\)', body)
    if me:
        entries.append({"t": t, "kind": me.group(1), "dir": me.group(2), "lot": float(me.group(3)), "e": float(me.group(4)),
                        "sl": float(me.group(5)), "tp": float(me.group(6)), "risk": float(me.group(7)), "trend": me.group(8), "debt": debt})
        continue
    ma = re.match(r'PULLBACK ADD: (\d+) bullets', body)
    if ma:
        adds.append({"t": t, "n": int(ma.group(1)), "debt": debt}); continue
    mf = re.match(r'FLIP: trend now (\w+)', body)
    if mf:
        flips.append((t, mf.group(1))); continue
    mr = re.match(r'(WIN|LOSS|ADD) ([+-][\d.]+) \(lot ([\d.]+)\): debt \$([\d.]+)', body)
    if mr:
        debt = float(mr.group(4)); results.append({"t": t, "o": mr.group(1), "p": float(mr.group(2)), "debt_after": debt})

# ---- broker: positions ----
if not mt5.initialize(path=TERM):
    sys.exit("MT5 init failed")
now = dt.datetime.now(dt.timezone.utc)
deals = mt5.history_deals_get(SINCE, now) or []
pos = defaultdict(lambda: {"in": None, "out": None, "p": 0.0, "lots": 0.0, "dir": None, "e": None, "x": None})
for d in deals:
    if d.symbol != SYMBOL:
        continue
    P = pos[d.position_id]
    if d.entry == 0:
        if P["in"] is None or d.time < P["in"]:
            P["in"] = d.time; P["e"] = d.price; P["dir"] = "BUY" if d.type == 0 else "SELL"
        P["lots"] += d.volume
    else:
        P["out"] = max(P["out"] or 0, d.time); P["x"] = d.price
    P["p"] += d.profit + d.swap + d.commission
mt5.symbol_select(SYMBOL, True)
rates = mt5.copy_rates_range(SYMBOL, mt5.TIMEFRAME_M1, SINCE, now)
mt5.shutdown()
times = [int(r["time"]) for r in rates]
rng = [float(r["high"]) - float(r["low"]) for r in rates]
close = [float(r["close"]) for r in rates]


def idx(ts):
    return bisect.bisect_left(times, ts)


def nerv(ts):
    i = idx(ts)
    return statistics.median(rng[i - 60:i]) / max(statistics.median(rng[i - 1440:i]), 1e-9) if i >= 1441 else None


def move1h(ts):
    i = idx(ts)
    return (close[i - 1] - close[i - 61]) if i >= 62 else None


rows = []
for pid, P in pos.items():
    if P["in"] is None or P["out"] is None:
        continue
    ts = P["in"]
    ent = min(entries, key=lambda e: abs(e["t"] - ts)) if entries else None
    is_add = not ent or abs(ent["t"] - ts) > 120
    if is_add:
        ad = min(adds, key=lambda a: abs(a["t"] - ts)) if adds else None
        kind = "ADD"; ent2 = max((e for e in entries if e["t"] <= ts), key=lambda e: e["t"], default=None)
        trend = ent2["trend"] if ent2 else "?"; sl = ent2["sl"] if ent2 else None; risk = None; dbt = ad["debt"] if ad else None
    else:
        kind = ent["kind"]; trend = ent["trend"]; sl = ent["sl"]; risk = ent["risk"]; dbt = ent["debt"]
    lastflip = max((f for f in flips if f[0] <= ts), key=lambda f: f[0], default=None)
    prev = max((r for r in results if r["t"] < ts), key=lambda r: r["t"], default=None)
    n = nerv(ts); mv = move1h(ts)
    d0 = dt.datetime.fromtimestamp(ts, dt.timezone.utc)
    rows.append({"t": ts, "when": d0, "hour": d0.hour, "wd": d0.strftime("%a"), "kind": kind, "dir": P["dir"], "lots": P["lots"],
                 "p": P["p"], "win": P["p"] > 0, "dur": (P["out"] - ts) / 60, "stop_pts": abs(P["e"] - sl) if sl else None,
                 "risk": risk, "debt": dbt, "trend": trend, "nerv": n, "mv1h": mv,
                 "with_trend": (P["dir"] == "BUY") == (trend == "up") if trend in ("up", "down") else None,
                 "since_flip_min": (ts - lastflip[0]) / 60 if lastflip else None,
                 "prev_loss": (prev["o"] == "LOSS") if prev else None,
                 "since_prev_min": (ts - prev["t"]) / 60 if prev else None,
                 "mv_against": (mv is not None and ((P["dir"] == "BUY" and mv < 0) or (P["dir"] == "SELL" and mv > 0)))})
rows.sort(key=lambda r: r["t"])
L = [r for r in rows if not r["win"]]; W = [r for r in rows if r["win"]]
print(f"{len(rows)} positions: {len(W)} wins, {len(L)} losses\n")


def share(rs, f):
    v = [f(r) for r in rs if f(r) is not None]
    return f"{100*sum(v)/len(v):3.0f}% ({sum(v)}/{len(v)})" if v else "n/a"


def med(rs, f):
    v = [f(r) for r in rs if f(r) is not None]
    return f"{statistics.median(v):.2f}" if v else "n/a"


print(f"{'feature':34s} {'losses':>16s} {'wins':>16s}")
for name, f, kind in [
    ("catch-up add position", lambda r: r["kind"] == "ADD", "share"),
    ("kind = BOS (continuation)", lambda r: r["kind"] == "BOS", "share"),
    ("kind = FLIP-BOS", lambda r: r["kind"] == "FLIP-BOS", "share"),
    ("kind = INT", lambda r: r["kind"] == "INT", "share"),
    ("direction = SELL", lambda r: r["dir"] == "SELL", "share"),
    ("with the main trend", lambda r: r["with_trend"], "share"),
    ("previous trade was a loss", lambda r: r["prev_loss"], "share"),
    ("debt at entry > 0", lambda r: (r["debt"] or 0) > 0.5, "share"),
    ("nervosity >= 1.0x", lambda r: (r["nerv"] or 0) >= 1.0 if r["nerv"] is not None else None, "share"),
    ("last hour moved AGAINST the trade", lambda r: r["mv_against"], "share"),
    ("weekend (Sat/Sun)", lambda r: r["wd"] in ("Sat", "Sun"), "share"),
    ("hour 00-06 UTC", lambda r: r["hour"] < 6, "share"),
    ("hour 06-12 UTC", lambda r: 6 <= r["hour"] < 12, "share"),
    ("hour 12-18 UTC", lambda r: 12 <= r["hour"] < 18, "share"),
    ("hour 18-24 UTC", lambda r: r["hour"] >= 18, "share"),
    ("median nervosity", lambda r: r["nerv"], "med"),
    ("median stop distance (pts)", lambda r: r["stop_pts"], "med"),
    ("median risk $ (main entries)", lambda r: r["risk"], "med"),
    ("median lots", lambda r: r["lots"], "med"),
    ("median duration (min)", lambda r: r["dur"], "med"),
    ("median minutes since last flip", lambda r: r["since_flip_min"], "med"),
    ("median minutes since previous trade", lambda r: r["since_prev_min"], "med"),
    ("median |move| previous hour (pts)", lambda r: abs(r["mv1h"]) if r["mv1h"] is not None else None, "med")]:
    fn = share if kind == "share" else med
    print(f"{name:34s} {fn(L, f):>16s} {fn(W, f):>16s}")

print("\nlosses, one per line:")
print(" date (UTC)     kind      dir  lots  nerv  stop  dur  sinceFlip debt prevLoss  mv1h  p")
for r in L:
    print(f" {r['when']:%d/%m %H:%M} {r['kind']:9s} {r['dir']:4s} {r['lots']:.2f}  {r['nerv'] or 0:.2f}  {int(r['stop_pts'] or 0):4d} {int(r['dur']):4d}  {int(r['since_flip_min'] or -1):8d} {r['debt'] or 0:5.1f}  {str(r['prev_loss']):5s} {int(r['mv1h'] or 0):+5d} {r['p']:+7.2f}")
print("\nby weekday (losses / total):")
c = Counter(r["wd"] for r in rows); cl = Counter(r["wd"] for r in L)
print(" ".join(f"{d}:{cl[d]}/{c[d]}" for d in ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"] if c[d]))
print("by day:")
cd = Counter(r["when"].strftime("%d/%m") for r in rows); cdl = Counter(r["when"].strftime("%d/%m") for r in L)
print(" ".join(f"{d}:{cdl[d]}/{cd[d]}" for d in sorted(cd)))
