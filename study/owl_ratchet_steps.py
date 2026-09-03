"""Second ratchet step test: does 'reach 70% -> SL to +40%' beat lock40 alone?

Variants (all on the same 123 trades, M1 replay, tie->split):
  A lock40 only                    (deployed today)
  B lock40 + bank85                (replay's best grid cell - suspect)
  C lock40 + step(70% -> SL +40%)  (the user's near-miss protection)
  D lock40 + step(80% -> SL +60%)  (later, tighter variant)
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
            tr = dict(pending_sig, e=float(g.group(2)),
                      ticket=int(g.group(3)), t_in=t)
            trades.append(tr)
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

def replay(tr, steps, bank=None):
    """steps: list of (trigger_frac, sl_frac). SL moves to e+sl_frac*prize
    when price reaches e+trigger_frac*prize. Applied in order, once each."""
    d, e, sl, tp, lot = tr["dir"], tr["e"], tr["sl"], tr["tp"], tr["lot"]
    prize = abs(tp - e)
    term_up = e + d * bank * prize if bank else tp
    cur_sl = sl
    todo = list(steps)
    rows = mt5.copy_rates_range(
        SYM, mt5.TIMEFRAME_M1,
        (tr["t_in"] + timedelta(minutes=1)).replace(second=0),
        tr["t"] + timedelta(minutes=1))
    if rows is None or not len(rows):
        return None
    for b in rows:
        hi, lo = float(b["high"]), float(b["low"])
        up_hit = (hi >= term_up) if d == 1 else (lo <= term_up)
        dn_hit = (lo <= cur_sl) if d == 1 else (hi >= cur_sl)
        if up_hit and dn_hit:
            return 0.5 * ((term_up - e) + (cur_sl - e)) * d * lot
        if dn_hit:
            return (cur_sl - e) * d * lot
        if up_hit:
            return (term_up - e) * d * lot
        while todo:
            trig_px = e + d * todo[0][0] * prize
            if (hi >= trig_px) if d == 1 else (lo <= trig_px):
                cur_sl = e + d * todo[0][1] * prize
                todo.pop(0)
            else:
                break
    return tr["profit"]

variants = [
    ("A lock40 only",          [(0.4, 0.0)],              None),
    ("B lock40 + bank85",      [(0.4, 0.0)],              0.85),
    ("C lock40 + 70->+40",     [(0.4, 0.0), (0.7, 0.4)],  None),
    ("D lock40 + 80->+60",     [(0.4, 0.0), (0.8, 0.6)],  None),
    ("E lock40 + both steps",  [(0.4, 0.0), (0.7, 0.4), (0.9, 0.7)], None),
]
actual = sum(tr["profit"] for tr in done)
print(f"n={len(done)}  ACTUAL {actual:+.2f}\n")
for name, steps, bank in variants:
    tot = sum(p for p in (replay(tr, steps, bank) for tr in done)
              if p is not None)
    print(f"{name:24} {tot:+8.2f}  ({tot-actual:+.2f} vs actual)")
mt5.shutdown()
