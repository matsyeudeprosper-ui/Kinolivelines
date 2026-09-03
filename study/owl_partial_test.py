"""Partial-exit test: close HALF at X% of prize, rest runs to TP with lock40.

vs deployed lock40 (full size to TP). Same 123-trade M1 replay, tie->split.
Payoffs per variant (d=dir, prize in points, lot L):
  reach X%: bank 0.5*L*X*prize immediately; remaining 0.5*L continues,
  lock40 already moved SL to entry (X >= 40): rest ends at TP (+prize/2)
  or back at entry (0).
"""
import re
from datetime import datetime, timezone, timedelta
import MetaTrader5 as mt5

LOG = r"C:\Projects\KinoliveLines\live\owl_manual.log"
ts_re = re.compile(r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})")
sig_re = re.compile(
    r"(KINO ENTRY|RECOV\[\d+\][ A-Za-z-]*ENTRY): (BUY|SELL) ([\d.]+) @ ~([\d.]+) "
    r"SL ([\d.]+) TP ([\d.]+)")
elog_re = re.compile(r"ENTRY logged: (BUY|SELL) [\d.]+ @ ([\d.]+) ticket (\d+)")
exit_re = re.compile(r"EXIT logged: ticket (\d+) (\S+) profit (-?[\d.]+)")

trades, pending_sig, exits = [], None, {}
for line in open(LOG, encoding="utf-8", errors="replace"):
    m = ts_re.match(line)
    if not m:
        continue
    t = datetime.fromisoformat(m.group(1)).replace(tzinfo=timezone.utc)
    g = sig_re.search(line)
    if g:
        pending_sig = dict(t=t, dir=1 if g.group(2) == "BUY" else -1,
                           lot=float(g.group(3)), sl=float(g.group(5)),
                           tp=float(g.group(6)))
        continue
    g = elog_re.search(line)
    if g and pending_sig and (t - pending_sig["t"]).total_seconds() <= 30:
        if (1 if g.group(1) == "BUY" else -1) == pending_sig["dir"]:
            trades.append(dict(pending_sig, e=float(g.group(2)),
                               ticket=int(g.group(3)), t_in=t))
        pending_sig = None
        continue
    g = exit_re.search(line)
    if g:
        exits[int(g.group(1))] = dict(t=t, reason=g.group(2),
                                      profit=float(g.group(3)))

done = [dict(tr, **exits[tr["ticket"]]) for tr in trades
        if tr["ticket"] in exits]
mt5.initialize(path=r"C:\Projects\MT5-KinoliveTrader\terminal64.exe")
SYM = "BTCUSDm"

def replay(tr, part_frac):
    """lock40 + close half at part_frac of prize (None = no partial)."""
    d, e, sl, tp, lot = tr["dir"], tr["e"], tr["sl"], tr["tp"], tr["lot"]
    prize = abs(tp - e)
    cur_sl, locked, parted, banked, size = sl, False, False, 0.0, lot
    lock_px = e + d * 0.40 * prize
    part_px = e + d * part_frac * prize if part_frac else None
    rows = mt5.copy_rates_range(
        SYM, mt5.TIMEFRAME_M1,
        (tr["t_in"] + timedelta(minutes=1)).replace(second=0),
        tr["t"] + timedelta(minutes=1))
    if rows is None or not len(rows):
        return None
    for b in rows:
        hi, lo = float(b["high"]), float(b["low"])
        up_hit = (hi >= tp) if d == 1 else (lo <= tp)
        dn_hit = (lo <= cur_sl) if d == 1 else (hi >= cur_sl)
        if up_hit and dn_hit:
            return banked + 0.5 * ((tp - e) + (cur_sl - e)) * d * size
        if dn_hit:
            return banked + (cur_sl - e) * d * size
        if up_hit:
            return banked + (tp - e) * d * size
        if not locked and ((hi >= lock_px) if d == 1 else (lo <= lock_px)):
            cur_sl, locked = e, True
        if (part_px is not None and not parted and lot >= 0.02
                and ((hi >= part_px) if d == 1 else (lo <= part_px))):
            # real broker constraint: close in 0.01 steps only
            closed = (int(round(lot / 0.01)) // 2) * 0.01
            banked = closed * part_frac * prize
            size = lot - closed
            parted = True
    return banked + tr["profit"] * (size / lot)

actual = sum(tr["profit"] for tr in done)
print(f"n={len(done)}  ACTUAL {actual:+.2f}\n")
for name, pf in [("lock40, no partial (now)", None),
                 ("lock40 + half out at 50%", 0.5),
                 ("lock40 + half out at 70%", 0.7),
                 ("lock40 + half out at 85%", 0.85)]:
    tot = sum(p for p in (replay(tr, pf) for tr in done) if p is not None)
    print(f"{name:28} {tot:+8.2f}")
mt5.shutdown()
