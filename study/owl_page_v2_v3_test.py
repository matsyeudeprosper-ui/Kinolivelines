"""Compare page-sizing ideas on the historical KINO pages (M1 replay, lock40 on):

  BASE - what actually ran: structure SL, near-1:1 TP
  V2   - skip pages whose wall is too far (risk > 1.5x target)
  V3   - take every page, but cap TP at $3 profit at 0.02 / $1.50 at 0.01
         (= 150 pts either way); lock scales with the smaller prize

All three replayed identically with the 40% lock. Ties -> split.
"""
import re
from datetime import datetime, timezone, timedelta
import MetaTrader5 as mt5

LOG = r"C:\Projects\KinoliveLines\live\owl_manual.log"
ts_re = re.compile(r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})")
sig_re = re.compile(
    r"KINO ENTRY: (BUY|SELL) ([\d.]+) @ ~([\d.]+) SL ([\d.]+) TP ([\d.]+)")
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
        pending_sig = dict(t=t, dir=1 if g.group(1) == "BUY" else -1,
                           lot=float(g.group(2)), sl=float(g.group(4)),
                           tp=float(g.group(5)))
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

CAP_PTS = 150.0        # $3 at 0.02 / $1.50 at 0.01 - same distance
SKIP_PTS = 225.0       # v2: risk > 1.5x target <=> wall > 225 pts

def replay(tr, tp_cap_pts=None):
    """lock40 replay; optionally cap the TP distance."""
    d, e, sl, lot = tr["dir"], tr["e"], tr["sl"], tr["lot"]
    tpd = abs(tr["tp"] - e)
    if tp_cap_pts is not None:
        tpd = min(tpd, tp_cap_pts)
    tp = e + d * tpd
    lock_px = e + d * 0.40 * tpd
    cur_sl, locked = sl, False
    rows = mt5.copy_rates_range(
        SYM, mt5.TIMEFRAME_M1,
        (tr["t_in"] + timedelta(minutes=1)).replace(second=0),
        tr["t"] + timedelta(minutes=1) + timedelta(minutes=240))
    if rows is None or not len(rows):
        return None
    for b in rows:
        hi, lo = float(b["high"]), float(b["low"])
        up = (hi >= tp) if d == 1 else (lo <= tp)
        dn = (lo <= cur_sl) if d == 1 else (hi >= cur_sl)
        if up and dn:
            return 0.5 * ((tp - e) + (cur_sl - e)) * d * lot
        if dn:
            return (cur_sl - e) * d * lot
        if up:
            return (tp - e) * d * lot
        if not locked and ((hi >= lock_px) if d == 1 else (lo <= lock_px)):
            cur_sl, locked = e, True
    return tr["profit"]

res = {"BASE": [], "V2": [], "V3": [], "V2+V3": []}
skipped = 0
for tr in done:
    dist = abs(tr["e"] - tr["sl"])
    b = replay(tr)
    v3 = replay(tr, CAP_PTS)
    if b is None or v3 is None:
        continue
    res["BASE"].append(b)
    res["V3"].append(v3)
    if dist > SKIP_PTS:
        skipped += 1
    else:
        res["V2"].append(b)
        res["V2+V3"].append(v3)

print(f"pages replayed: {len(res['BASE'])}   (V2 skips {skipped})")
for k in ("BASE", "V2", "V3", "V2+V3"):
    v = res[k]
    wins = sum(1 for p in v if p > 0.05)
    print(f"{k:5} n={len(v):3d}  total {sum(v):+8.2f}  "
          f"avg {sum(v)/len(v):+6.3f}  win% {100*wins/len(v):.0f}")
mt5.shutdown()
