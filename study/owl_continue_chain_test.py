"""User idea: after a partial-heal win, DON'T close the chain - keep
taking normal door-fighters (same lot, sound walls, 1:1) until the
chain's books show debt repaid + $3, or 3 more real losses (storm), or
6h passes.

Replay: for every chain of the new-rules era that ended on a WIN with
net < +$3 (= partially healed), simulate the continuation on M1:
  doors = last 30 M1 bars' extremes at the moment the chain ended;
  M1 close beyond a door -> enter that direction, SL = other door,
  TP = 1:1, lock40 on; win -> add to books, stop when net >= +$3;
  loss -> ladder +0.01, new doors from the stopped trade;
  guards: min wall 60pts, $35 risk cap (unfit door = wait), max 6h.
"""
import re
from datetime import datetime, timezone, timedelta
import MetaTrader5 as mt5

LOG = r"C:\Projects\KinoliveLines\live\owl_manual.log"
ERA = "2026-09-03T21:18"
ts_re = re.compile(r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})")
kino_re = re.compile(r"KINO ENTRY: (BUY|SELL) ([\d.]+) @ ~([\d.]+)")
recov_re = re.compile(r"RECOV\[(\d+)\][ A-Za-z()\-]*ENTRY: (BUY|SELL) ([\d.]+)")
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
        pend = dict(t=t, chain=None, lot=float(g.group(2)))
        continue
    g = recov_re.search(line)
    if g:
        pend = dict(t=t, chain=g.group(1), lot=float(g.group(3)))
        continue
    g = elog_re.search(line)
    if g and pend and (t - pend["t"]).total_seconds() <= 30:
        trades.append(dict(pend, ticket=int(g.group(3))))
        pend = None
        continue
    g = exit_re.search(line)
    if g and int(g.group(1)) not in exits:
        exits[int(g.group(1))] = dict(t=t, profit=float(g.group(3)))

done = [dict(tr, **exits[tr["ticket"]]) for tr in trades
        if tr["ticket"] in exits]
for tr in done:
    if tr["chain"] is None:
        tr["chain"] = str(tr["ticket"])

# chain books
chains = {}
for tr in sorted(done, key=lambda x: x["t"]):
    c = chains.setdefault(tr["chain"], {"net": 0.0, "last": None})
    c["net"] += tr["profit"]
    c["last"] = tr

mt5.initialize(path=r"C:\Projects\MT5-KinoliveTrader\terminal64.exe")
SYM = "BTCUSDm"

def m1(t0, t1):
    r = mt5.copy_rates_range(SYM, mt5.TIMEFRAME_M1, t0, t1)
    return r if r is not None else []

def continue_chain(t0, lot, need):
    """Door-fighter ladder from t0 until +need collected, 3 real losses,
    or 6h. Returns (sim_pnl, story)."""
    rows = m1(t0, t0 + timedelta(hours=6))
    if len(rows) < 40:
        return 0.0, "no data"
    # initial doors from the 30 bars before t0
    pre = m1(t0 - timedelta(minutes=31), t0)
    if not len(pre):
        return 0.0, "no data"
    hi = max(float(b["high"]) for b in pre)
    lo = min(float(b["low"]) for b in pre)
    got, losses, story = 0.0, 0, []
    i = 0
    link = 0
    while link < 8 and i < len(rows) - 2:
        # wait for a door close
        entry = None
        for j in range(i, len(rows)):
            c = float(rows[j]["close"])
            if c > hi:
                entry = (1, c, lo, j)
                break
            if c < lo:
                entry = (-1, c, hi, j)
                break
        if entry is None:
            story.append("no door")
            break
        d, e, wall, j0 = entry
        dist = abs(e - wall)
        if dist < 60 or dist * lot > 35.27:
            # unfit wall: rebuild doors from recent bars and keep waiting
            k0 = max(0, j0 - 30)
            hi = max(float(b["high"]) for b in rows[k0:j0 + 1])
            lo = min(float(b["low"]) for b in rows[k0:j0 + 1])
            i = j0 + 1
            continue
        link += 1
        tp = e + d * dist
        lock_px = e + d * 0.4 * dist
        cur_sl, locked = wall, False
        res = None
        for j in range(j0 + 1, len(rows)):
            b = rows[j]
            h2, l2 = float(b["high"]), float(b["low"])
            up = (h2 >= tp) if d == 1 else (l2 <= tp)
            dn = (l2 <= cur_sl) if d == 1 else (h2 >= cur_sl)
            if dn:
                res = (((cur_sl - e) * d) * lot, j)
                break
            if up:
                res = (((tp - e) * d) * lot, j)
                break
            if not locked and ((h2 >= lock_px) if d == 1
                               else (l2 <= lock_px)):
                cur_sl, locked = e, True
        if res is None:
            story.append(f"L{link} open at end")
            break
        pnl, jend = res
        got += pnl
        story.append(f"L{link} {lot:.2f} {pnl:+.2f}")
        if pnl < -0.5:
            losses += 1
            if losses >= 3:
                story.append("storm")
                break
            lot = round(lot + 0.01, 2)
        if got >= need:
            story.append("HEALED")
            break
        # new doors around the exit
        k0 = max(0, jend - 30)
        hi = max(float(b["high"]) for b in rows[k0:jend + 1])
        lo = min(float(b["low"]) for b in rows[k0:jend + 1])
        i = jend + 1
    return got, " | ".join(story)

cands = [(cn, c) for cn, c in chains.items()
         if c["last"] and c["last"]["profit"] > 0.05 and c["net"] < 3.0]
print(f"chains: {len(chains)}, ended-on-a-win but under +$3: {len(cands)}\n")
tot = 0.0
for cn, c in sorted(cands, key=lambda x: x[1]["last"]["t"]):
    need = 3.0 - c["net"]
    sim, story = continue_chain(c["last"]["t"], c["last"]["lot"], need)
    tot += sim
    print(f"{c['last']['t']:%m-%d %H:%M} chain {cn}: net was "
          f"{c['net']:+.2f}, needed +{need:.2f} more -> sim {sim:+.2f}"
          f"   [{story}]")
print(f"\nTOTAL extra P&L from continuing: {tot:+.2f}")
mt5.shutdown()
