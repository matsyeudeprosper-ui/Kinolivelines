"""Chop-rule replay (2026-09-02): would rule X have saved the chop tax,
and what trend profit would it have cost?

Rules tested against the machine era's REAL trades (approximation: a
blocked trade simply doesn't happen; later trades unchanged):
  A WHIPSAW NAP: >=3 chain-link exits within 20min -> block all CHAIN
    entries for the next 2h.
  B RANGE BOX: chain entries blocked while the last 90 M1 bars' range
    < 250 pts.
  C NIGHT: chain entries blocked 20:00-06:00 UTC.
"""
import sys
from datetime import datetime, timezone, timedelta
import numpy as np
import MetaTrader5 as mt5

TERMINAL = r"C:\Projects\MT5-KinoliveTrader\terminal64.exe"
ERA = datetime(2026, 8, 31, 3, 30, tzinfo=timezone.utc)

mt5.initialize(path=TERMINAL)
now = datetime.now(timezone.utc)
deals = mt5.history_deals_get(ERA, now + timedelta(minutes=5)) or []
ins = {d.position_id: d for d in deals if d.entry == mt5.DEAL_ENTRY_IN}
trades = []
for d in deals:
    if d.entry != mt5.DEAL_ENTRY_OUT:
        continue
    e = ins.get(d.position_id)
    if e is None:
        continue
    cm = (e.comment or "")
    if not cm.startswith("OWL-"):
        continue
    trades.append({
        "kind": "chain" if "recov" in cm else "page",
        "t_in": e.time, "t_out": d.time,
        "pnl": d.profit + d.commission + d.swap})
trades.sort(key=lambda x: x["t_in"])
chains = [t for t in trades if t["kind"] == "chain"]
total = sum(t["pnl"] for t in trades)
ctotal = sum(t["pnl"] for t in chains)
print(f"era trades: {len(trades)} (chains {len(chains)}) "
      f"| total {total:+.2f} | chains {ctotal:+.2f}")

# M1 bars for rule B
bars = mt5.copy_rates_range("BTCUSDm", mt5.TIMEFRAME_M1,
                            ERA - timedelta(hours=2),
                            now)
bt = bars["time"]

def boxed(ts, n=90, pts=250.0):
    i = np.searchsorted(bt, ts)
    if i < n:
        return False
    hi = float(np.max(bars["high"][i - n:i]))
    lo = float(np.min(bars["low"][i - n:i]))
    return (hi - lo) < pts

# rule A block windows
exits = sorted(t["t_out"] for t in chains)
blockA = []
for i in range(len(exits)):
    win = [x for x in exits if exits[i] - 1200 <= x <= exits[i]]
    if len(win) >= 3:
        blockA.append((exits[i], exits[i] + 7200))

def blockedA(ts):
    return any(a <= ts <= b for a, b in blockA)

def blockedB(ts):
    return boxed(ts)

def blockedC(ts):
    h = datetime.fromtimestamp(ts, tz=timezone.utc).hour
    return h >= 20 or h < 6

for name, fn in (("A whipsaw-nap", blockedA),
                 ("B range-box", blockedB),
                 ("C night", blockedC)):
    blocked = [t for t in chains if fn(t["t_in"])]
    bl_pnl = sum(t["pnl"] for t in blocked)
    saved = -sum(t["pnl"] for t in blocked if t["pnl"] < 0)
    lost = sum(t["pnl"] for t in blocked if t["pnl"] > 0)
    print(f"{name}: blocks {len(blocked)}/{len(chains)} chain trades | "
          f"blocked pnl {bl_pnl:+.2f} (saves {saved:.2f} of losses, "
          f"gives up {lost:.2f} of wins) -> era result would be "
          f"{total - bl_pnl:+.2f}")
mt5.shutdown()
