"""Replay every OWL trade (KINO + RECOV) under lock/bank protection variants.

Rules simulated per trade (entry e, sl, tp known from the log):
  lock f: when price reaches f*prize, SL moves to entry
  bank b: when price reaches b*prize, close at market (b*prize banked)
Walk M1 bars (bid) from the bar after entry to the actual exit time.
Ambiguous bars (terminal up + terminal down in one M1 bar) are scored
tie->split (half/half), per the tie-scoring trap in FINDINGS.
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

trades = []          # dicts
pending_sig = None
exits = {}
for line in open(LOG, encoding="utf-8", errors="replace"):
    m = ts_re.match(line)
    if not m:
        continue
    t = datetime.fromisoformat(m.group(1) )
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    g = sig_re.search(line)
    if g:
        pending_sig = dict(t=t, kind=g.group(1)[:4], dir=1 if g.group(2) == "BUY" else -1,
                           lot=float(g.group(3)), sl=float(g.group(5)),
                           tp=float(g.group(6)))
        continue
    g = elog_re.search(line)
    if g and pending_sig and (t - pending_sig["t"]).total_seconds() <= 30:
        d = 1 if g.group(1) == "BUY" else -1
        if d == pending_sig["dir"]:
            tr = dict(pending_sig)
            tr["e"] = float(g.group(2))
            tr["ticket"] = int(g.group(3))
            tr["t_in"] = t
            trades.append(tr)
        pending_sig = None
        continue
    g = exit_re.search(line)
    if g:
        exits[int(g.group(1))] = dict(t=t, reason=g.group(2),
                                      profit=float(g.group(3)))

done = [tr for tr in trades if tr["ticket"] in exits]
for tr in done:
    tr.update(exits[tr["ticket"]])

mt5.initialize(path=r"C:\Projects\MT5-KinoliveTrader\terminal64.exe")
SYM = "BTCUSDm"

def bars_between(t0, t1):
    r = mt5.copy_rates_range(SYM, mt5.TIMEFRAME_M1, t0, t1)
    return r if r is not None else []

def replay(tr, lock, bank):
    """Return simulated $ profit under (lock, bank). None = no data."""
    d, e, sl, tp, lot = tr["dir"], tr["e"], tr["sl"], tr["tp"], tr["lot"]
    prize = abs(tp - e)
    lock_px = e + d * lock * prize if lock else None
    bank_px = e + d * bank * prize if bank else None
    term_up = bank_px if bank else tp     # favourable terminal level
    cur_sl = sl
    t0 = tr["t_in"] + timedelta(minutes=1)
    t1 = tr["t"] + timedelta(minutes=1)
    rows = bars_between(t0.replace(second=0), t1)
    if not len(rows):
        return None
    for b in rows:
        hi, lo = float(b["high"]), float(b["low"])
        up_hit = (hi >= term_up) if d == 1 else (lo <= term_up)
        dn_hit = (lo <= cur_sl) if d == 1 else (hi >= cur_sl)
        if up_hit and dn_hit:                       # ambiguous bar
            return 0.5 * ((term_up - e) * d * lot + (cur_sl - e) * d * lot)
        if dn_hit:
            return (cur_sl - e) * d * lot
        if up_hit:
            return (term_up - e) * d * lot
        if lock_px is not None and cur_sl != e:
            if (hi >= lock_px) if d == 1 else (lo <= lock_px):
                cur_sl = e                          # lock: wall to entry
    return tr["profit"]                             # no event: actual close

grid = [(None, None), (0.4, None), (0.6, None), (0.8, None),
        (None, 0.7), (0.4, 0.7), (0.4, 0.85), (0.6, 0.85)]
print(f"trades parsed {len(trades)}, with exits {len(done)}")
actual = sum(tr["profit"] for tr in done)
print(f"ACTUAL total: {actual:+.2f}\n")
print(f"{'lock':>5} {'bank':>5} {'total$':>8} {'vs actual':>10} {'n':>4}")
for lock, bank in grid:
    tot, n = 0.0, 0
    for tr in done:
        p = replay(tr, lock, bank)
        if p is None:
            continue
        tot += p
        n += 1
    lbl_l = f"{int(lock*100)}%" if lock else "-"
    lbl_b = f"{int(bank*100)}%" if bank else "-"
    print(f"{lbl_l:>5} {lbl_b:>5} {tot:8.2f} {tot-actual:+10.2f} {n:4d}")

# split by ROLE (signal page vs recovery fighter), lock-40 only - the workhorse
print("\nby role (lock40 only vs actual):")
for kind, lbl in [("KINO", "signal page"), ("RECO", "fighter")]:
    sub = [tr for tr in done if tr["kind"] == kind]
    if not sub:
        continue
    a = sum(tr["profit"] for tr in sub)
    s = sum(p for p in (replay(tr, 0.4, None) for tr in sub) if p is not None)
    wins_a = sum(1 for tr in sub if tr["profit"] > 0)
    print(f"  {lbl:12} n={len(sub):3d}  actual {a:+8.2f}  lock40 {s:+8.2f}"
          f"  delta {s-a:+7.2f}  (win rate now {100*wins_a/len(sub):.0f}%)")

# split by lot size for the best diagnosis
print("\nby lot size (lock40+bank70 vs actual):")
for lo_min, lo_max, lbl in [(0.0, 0.015, "0.01"), (0.015, 0.035, "0.02-0.03"),
                            (0.035, 9, "0.04+")]:
    sub = [tr for tr in done if lo_min < tr["lot"] <= lo_max]
    if not sub:
        continue
    a = sum(tr["profit"] for tr in sub)
    s = sum(p for p in (replay(tr, 0.4, 0.7) for tr in sub) if p is not None)
    print(f"  {lbl:9} n={len(sub):3d}  actual {a:+8.2f}  variant {s:+8.2f}"
          f"  delta {s-a:+7.2f}")
mt5.shutdown()
