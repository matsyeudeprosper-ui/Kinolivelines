"""Would extending the HEAL target to 0.02/0.03 fighters have helped?

For every small (sub-deep) recovery link since the new-rules era:
  debt = -(sum of the chain's P&L before this link), if negative
  heal distance = (debt + $3) / lot
  applicable when 60pts < heal distance < the link's actual 1:1 TP dist
Replay those links on M1 with the closer heal TP (lock40 scaled to the
smaller prize) and compare with what actually happened.
"""
import re
from datetime import datetime, timezone, timedelta
import MetaTrader5 as mt5

LOG = r"C:\Projects\KinoliveLines\live\owl_manual.log"
ERA = "2026-09-03T21:18"          # lock40 era start
ts_re = re.compile(r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})")
kino_re = re.compile(
    r"KINO ENTRY: (BUY|SELL) ([\d.]+) @ ~([\d.]+) SL ([\d.]+) TP ([\d.]+)")
recov_re = re.compile(
    r"RECOV\[(\d+)\][ A-Za-z()\-]*ENTRY: (BUY|SELL) ([\d.]+) @ ~([\d.]+) "
    r"SL ([\d.]+) TP ([\d.]+)")
elog_re = re.compile(r"ENTRY logged: (BUY|SELL) [\d.]+ @ ([\d.]+) ticket (\d+)")
exit_re = re.compile(r"EXIT logged: ticket (\d+) (\S+) profit (-?[\d.]+)")

trades, pend, exits = [], None, {}
for line in open(LOG, encoding="utf-8", errors="replace"):
    m = ts_re.match(line)
    if not m or m.group(1) < ERA:
        continue
    t = datetime.fromisoformat(m.group(1)).replace(tzinfo=timezone.utc)
    g = kino_re.search(line)
    if g:
        pend = dict(t=t, kind="page", chain=None,
                    dir=1 if g.group(1) == "BUY" else -1,
                    lot=float(g.group(2)), sl=float(g.group(4)),
                    tp=float(g.group(5)))
        continue
    g = recov_re.search(line)
    if g:
        pend = dict(t=t, kind="link", chain=g.group(1),
                    dir=1 if g.group(2) == "BUY" else -1,
                    lot=float(g.group(3)), sl=float(g.group(5)),
                    tp=float(g.group(6)))
        continue
    g = elog_re.search(line)
    if g and pend and (t - pend["t"]).total_seconds() <= 30:
        if (1 if g.group(1) == "BUY" else -1) == pend["dir"]:
            trades.append(dict(pend, e=float(g.group(2)),
                               ticket=int(g.group(3)), t_in=t))
        pend = None
        continue
    g = exit_re.search(line)
    if g and int(g.group(1)) not in exits:
        exits[int(g.group(1))] = dict(t=t, profit=float(g.group(3)))

done = [dict(tr, **exits[tr["ticket"]]) for tr in trades
        if tr["ticket"] in exits]
# chain id of a page = its own ticket
for tr in done:
    if tr["kind"] == "page":
        tr["chain"] = str(tr["ticket"])

mt5.initialize(path=r"C:\Projects\MT5-KinoliveTrader\terminal64.exe")
SYM = "BTCUSDm"

def replay_heal(tr, heal_dist):
    d, e, sl, lot = tr["dir"], tr["e"], tr["sl"], tr["lot"]
    tp = e + d * heal_dist
    lock_px = e + d * 0.40 * heal_dist
    cur_sl, locked = sl, False
    rows = mt5.copy_rates_range(
        SYM, mt5.TIMEFRAME_M1,
        (tr["t_in"] + timedelta(minutes=1)).replace(second=0),
        tr["t"] + timedelta(minutes=1) + timedelta(hours=4))
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

# walk chains chronologically, tracking debt
chains = {}
cands = []
for tr in sorted(done, key=lambda x: x["t_in"]):
    cn = tr["chain"]
    debt = -min(0.0, chains.get(cn, 0.0))
    if (tr["kind"] == "link" and tr["lot"] in (0.02, 0.03)
            and debt > 0.5):
        dist = abs(tr["tp"] - tr["e"])
        heal = (debt + 3.0) / tr["lot"]
        if 60.0 < heal < dist:
            sim = replay_heal(tr, heal)
            cands.append((tr["t_in"], cn, tr["lot"], debt,
                          tr["profit"], sim))
    chains[cn] = chains.get(cn, 0.0) + tr["profit"]

print(f"chains tracked: {len(chains)}   small-fighter links where the "
      f"heal target would have applied: {len(cands)}")
ta = ts = 0.0
for t, cn, lot, debt, actual, sim in cands:
    if sim is None:
        continue
    ta += actual
    ts += sim
    print(f"{t:%m-%d %H:%M} chain {cn} lot {lot} debt ${debt:.2f}  "
          f"actual {actual:+.2f}  with-heal {sim:+.2f}")
print(f"\nTOTAL actual {ta:+.2f}   with heal-target {ts:+.2f}   "
      f"difference {ts - ta:+.2f}")
mt5.shutdown()
