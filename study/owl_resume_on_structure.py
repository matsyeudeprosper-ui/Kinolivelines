"""User idea v2: after a storm's FIRST ghost target-hit, wait for the
standard KINO structure (leg -> pullback -> official level -> M1 close
confirmation) and enter with the frozen chain's lot. SL = pullback wall,
TP = 1:1, lock40 applied, bank70 for lots >= 0.04, $35 risk cap, 60pt
min wall - all live constraints.

Replay every storm in the log: storm start -> first ghost WIN (target
hit; under the old scoring: any ghost resolution with pnl > 0, since
target-hit implies positive) -> run the KINO detector on M1 from there
(max 6h) -> score the resumed fighter.
"""
import re
from datetime import datetime, timezone, timedelta
import MetaTrader5 as mt5

LOG = r"C:\Projects\KinoliveLines\live\owl_manual.log"
ts_re = re.compile(r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})")
storm_re = re.compile(r"storm detected|FULL SHELTER")
clear_re = re.compile(r"WEATHER CLEAR|balance back above the floor")
win_re = re.compile(r"SHADOW chain\[[^\]]+\] WIN \+([\d.]+)")
gh_re = re.compile(r"SHADOW chain\[(\d+)\] ENTRY: (BUY|SELL) ([\d.]+)")

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
    elif win_re.search(line):
        events.append((t, "ghostwin", None))
    else:
        g = gh_re.search(line)
        if g:
            events.append((t, "glot", float(g.group(3))))

mt5.initialize(path=r"C:\Projects\MT5-KinoliveTrader\terminal64.exe")
SYM = "BTCUSDm"

def kino_detect_and_trade(t0, lot):
    """Run the KINO detector on M1 closes from t0 (max 6h): leg (2 greens,
    2nd closes above 1st high) -> peak tracked -> pullback close below last
    green's low = official -> M1 close back above peak = ENTRY (BUY side;
    mirror for SELL - whichever forms first). Then score with lock40/bank70."""
    rows = mt5.copy_rates_range(SYM, mt5.TIMEFRAME_M1, t0,
                                t0 + timedelta(hours=6))
    if rows is None or len(rows) < 10:
        return None, "no data"
    up, dn = {}, {}
    entry = None
    for i in range(1, len(rows)):
        pv, cb = rows[i - 1], rows[i]
        po, pc = float(pv["open"]), float(pv["close"])
        ph, pl = float(pv["high"]), float(pv["low"])
        co, cc = float(cb["open"]), float(cb["close"])
        ch, cl = float(cb["high"]), float(cb["low"])
        # UP side
        if pc > po and cc > co and cc > ph:
            up = {"leg": True, "peak": ch, "glow": cl}
        elif up.get("leg"):
            up["peak"] = max(up["peak"], ch)
            if cc > co:
                up["glow"] = cl
            elif cc < up["glow"]:
                up["pending"], up["plow"], up["leg"] = up["peak"], cl, False
        if up.get("pending"):
            up["plow"] = min(up.get("plow", cl), cl)
            if cc > up["pending"]:
                entry = (1, cc, up["plow"], i)
                break
        # DOWN side (mirror)
        if pc < po and cc < co and cc < pl:
            dn = {"leg": True, "dip": cl, "rhigh": ch}
        elif dn.get("leg"):
            dn["dip"] = min(dn["dip"], cl)
            if cc < co:
                dn["rhigh"] = ch
            elif cc > dn["rhigh"]:
                dn["pending"], dn["phigh"], dn["leg"] = dn["dip"], ch, False
        if dn.get("pending"):
            dn["phigh"] = max(dn.get("phigh", ch), ch)
            if cc < dn["pending"]:
                entry = (-1, cc, dn["phigh"], i)
                break
    if entry is None:
        return 0.0, "no structure formed in 6h"
    d, e, wall, i0 = entry
    dist = abs(e - wall)
    if dist < 60:
        return 0.0, f"wall {dist:.0f}pts < 60 min"
    if dist * lot > 35.27:
        return 0.0, f"HELD by cap (${dist * lot:.2f})"

    # --- FULL LADDER: after an SL, two doors (close beyond SL = flip,
    # close back beyond entry = re-enter) at lot+0.01, wall = M1 extreme
    # since the stopped entry. Locks/bank/caps live. Max 6 links.
    total = 0.0
    story = []
    link = 0
    i = i0
    while link < 6 and i < len(rows) - 2:
        link += 1
        dist = abs(e - wall)
        if dist < 60 or dist * lot > 35.27 or dist * lot >= 100:
            story.append(f"L{link} held/capped")
            break
        tp = e + d * dist
        lock_px = e + d * 0.4 * dist
        bank_px = e + d * 0.7 * dist if lot >= 0.04 else None
        cur_sl, locked = wall, False
        res, j_end = None, None
        for j in range(i + 1, len(rows)):
            b = rows[j]
            hi2, lo2 = float(b["high"]), float(b["low"])
            term = bank_px if bank_px else tp
            upx = (hi2 >= term) if d == 1 else (lo2 <= term)
            dnx = (lo2 <= cur_sl) if d == 1 else (hi2 >= cur_sl)
            if dnx:
                res = ("sl", ((cur_sl - e) * d) * lot, locked)
                j_end = j
                break
            if upx:
                res = ("win", ((term - e) * d) * lot, locked)
                j_end = j
                break
            if not locked and ((hi2 >= lock_px) if d == 1
                               else (lo2 <= lock_px)):
                cur_sl, locked = e, True
        if res is None:
            story.append(f"L{link} open at end")
            break
        kind, pnl, was_locked = res
        total += pnl
        story.append(f"L{link} {lot:.2f} {pnl:+.2f}")
        if kind == "win" or (kind == "sl" and was_locked and pnl >= 0):
            break                      # profitable close ends the chain
        if kind == "sl" and was_locked:
            pass                       # scratch: doors re-arm at entry
        # doors after the stop: flip on close beyond cur_sl, re-enter on
        # close back beyond e
        stopped_e, stopped_sl, stopped_i = e, cur_sl, j_end
        nxt = None
        for j in range(j_end + 1, len(rows)):
            c = float(rows[j]["close"])
            broke = (c < stopped_sl) if d == 1 else (c > stopped_sl)
            reent = (c > stopped_e) if d == 1 else (c < stopped_e)
            if broke or reent:
                nd = -d if broke else d
                lo_ext = min(float(b["low"]) for b in rows[stopped_i:j + 1])
                hi_ext = max(float(b["high"]) for b in rows[stopped_i:j + 1])
                nwall = lo_ext if nd == 1 else hi_ext
                nxt = (nd, c, nwall, j)
                break
        if nxt is None:
            story.append("no door in time")
            break
        d, e, wall, i = nxt
        lot = round(lot + 0.01, 2)
    return total, " | ".join(story)

tot = 0.0
in_storm, first_win_t, max_lot, storm_t = False, None, 0.0, None
results = []
for t, kind, data in events:
    if kind == "storm":
        in_storm, first_win_t, max_lot, storm_t = True, None, 0.0, t
    elif kind == "glot" and in_storm:
        max_lot = max(max_lot, data)
    elif kind == "ghostwin" and in_storm and first_win_t is None:
        first_win_t = t
    elif kind == "clear" and in_storm:
        if first_win_t is not None and max_lot > 0:
            pnl, how = kino_detect_and_trade(first_win_t, max_lot)
            if pnl is not None:
                tot += pnl
                results.append((storm_t, first_win_t, max_lot, pnl, how))
        in_storm = False
print(f"{'storm':14} {'1st win':8} {'lot':>5} {'P&L':>8}  outcome")
for s, w, lot, pnl, how in results:
    print(f"{s:%m-%d %H:%M}   {w:%H:%M}    {lot:5.2f} {pnl:+8.2f}  {how}")
print(f"\nTOTAL: {tot:+.2f}")
mt5.shutdown()
