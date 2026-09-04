"""What would freeze-and-resume have done in the storms we already had?

For every chain that ghost-fought during a shelter window:
  - freeze at its shadow lot
  - at the storm's actual WEATHER CLEAR time, build fresh doors =
    extremes of the 30 M1 bars before the clear
  - walk M1 forward (max 6h): first M1 CLOSE above hi -> BUY, below lo
    -> SELL, lot = frozen lot, SL = the opposite door, TP = 1:1
  - apply lock40 (scratch ~0) and, for lots >= 0.04, bank at 70%
Reference: what the ghosts actually delivered in real money = $0.
"""
import re
from datetime import datetime, timezone, timedelta
import MetaTrader5 as mt5

LOG = r"C:\Projects\KinoliveLines\live\owl_manual.log"
ts_re = re.compile(r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})")
storm_re = re.compile(r"storm detected|FULL SHELTER")
clear_re = re.compile(r"WEATHER CLEAR|balance back above the floor")
gh_re = re.compile(
    r"SHADOW chain\[(\d+)\] ENTRY: (BUY|SELL) ([\d.]+) @ ([\d.]+)")

events = []
for line in open(LOG, encoding="utf-8", errors="replace"):
    m = ts_re.match(line)
    if not m:
        continue
    t = datetime.fromisoformat(m.group(1)).replace(tzinfo=timezone.utc)
    if storm_re.search(line):
        events.append((t, "storm", None))
    elif clear_re.search(line):
        events.append((t, "clear", None))
    else:
        g = gh_re.search(line)
        if g:
            events.append((t, "ghost", (g.group(1),
                                        1 if g.group(2) == "BUY" else -1,
                                        float(g.group(3)))))

mt5.initialize(path=r"C:\Projects\MT5-KinoliveTrader\terminal64.exe")
SYM = "BTCUSDm"

def m1(t0, t1):
    r = mt5.copy_rates_range(SYM, mt5.TIMEFRAME_M1, t0, t1)
    return r if r is not None else []

def simulate_resume(clear_t, lot):
    pre = m1(clear_t - timedelta(minutes=31), clear_t)
    if not len(pre):
        return None, "no data"
    hi = max(float(b["high"]) for b in pre)
    lo = min(float(b["low"]) for b in pre)
    rows = m1(clear_t, clear_t + timedelta(hours=6))
    entry = None
    for i, b in enumerate(rows):
        c = float(b["close"])
        if c > hi:
            entry = (1, c, lo, i)
            break
        if c < lo:
            entry = (-1, c, hi, i)
            break
    if entry is None:
        return 0.0, "no door closed in 6h"
    d, e, sl, i0 = entry
    dist = abs(e - sl)
    if dist * lot > 35.27:            # live fighter risk cap - would HOLD
        return 0.0, f"HELD by risk cap (${dist * lot:.2f} > $35.27)"
    if dist < 60.0:                   # RECOV_MIN_WALL_PTS - would wait
        return 0.0, f"held: wall {dist:.0f}pts < 60"
    tp = e + d * dist
    lock_px = e + d * 0.4 * dist
    bank_px = e + d * 0.7 * dist if lot >= 0.04 else None
    cur_sl, locked = sl, False
    for b in rows[i0 + 1:]:
        hi2, lo2 = float(b["high"]), float(b["low"])
        term = bank_px if bank_px else tp
        up = (hi2 >= term) if d == 1 else (lo2 <= term)
        dn = (lo2 <= cur_sl) if d == 1 else (hi2 >= cur_sl)
        if up and dn:
            return 0.5 * ((term - e) + (cur_sl - e)) * d * lot, "tie"
        if dn:
            return (cur_sl - e) * d * lot, ("scratch" if locked else "sl")
        if up:
            return (term - e) * d * lot, ("bank70" if bank_px else "tp")
        if not locked and ((hi2 >= lock_px) if d == 1
                           else (lo2 <= lock_px)):
            cur_sl, locked = e, True
    return 0.0, "still open at +6h"

# pair each storm window with the chains that ghost-fought in it
tot = 0.0
in_storm, chains, storm_t = False, {}, None
results = []
for t, kind, data in events:
    if kind == "storm":
        in_storm, chains, storm_t = True, {}, t
    elif kind == "ghost" and in_storm:
        cn, d, lot = data
        chains.setdefault(cn, lot)      # first shadow lot = frozen lot
    elif kind == "clear" and in_storm:
        for cn, lot in chains.items():
            pnl, how = simulate_resume(t, lot)
            if pnl is None:
                continue
            tot += pnl
            results.append((storm_t, t, cn, lot, pnl, how))
        in_storm = False
print(f"{'storm':16} {'cleared':6} {'chain':11} {'lot':>5} "
      f"{'resume P&L':>10}  outcome")
for s, c, cn, lot, pnl, how in results:
    print(f"{s:%m-%d %H:%M}      {c:%H:%M}  {cn:11} {lot:5.2f} "
          f"{pnl:+10.2f}  {how}")
print(f"\nTOTAL real P&L freeze-and-resume would have added: {tot:+.2f}")
print("(reference: the ghosts delivered $0.00 real)")
mt5.shutdown()
