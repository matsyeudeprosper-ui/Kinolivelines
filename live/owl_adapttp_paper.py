"""VIRTUAL forward test: CURRENT live detector (two-colour legs,
no-chase/retest) + ADAPTIVE TP (2026-09-06 user idea). TP distance =
60th percentile of the last 40 trades' max favourable excursion,
floor 15pts, capped at the normal 1:1-with-discount target; quarter-TP
until 20 trades of history exist. Pages only (0.01), one at a time,
40% lock -> breakeven-plus, clean chart after each close. NO broker
orders. Events -> owl_adapttp_paper.log."""
import json
import os
import time
from datetime import datetime, timezone

import MetaTrader5 as mt5

DIR = r"C:\Projects\KinoliveLines\live"
LOG = os.path.join(DIR, "owl_adapttp_paper.log")
STATE = os.path.join(DIR, "owl_adapttp_paper.json")
SYMBOL = "BTCUSDm"
TERM = r"C:\Projects\MT5-KinoliveTrader\terminal64.exe"
MIN_WALL, PAGE_MAXR, PAGE_TGT = 60.0, 2.50, 1.50
LOT, BUFFER_USD = 0.01, 0.10


def say(m):
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(f"{datetime.now(timezone.utc).isoformat()} {m}\n")


def load():
    try:
        return json.load(open(STATE))
    except Exception:
        return {"pos": None, "up": {}, "dn": {}, "net": 0.0,
                "n": 0, "wins": 0, "last_bar": 0, "fe": []}


def save(st):
    with open(STATE, "w") as f:
        json.dump(st, f)


def det_step(st, pb, b):
    """The LIVE detector: leg (2 same-colour closes) -> pullback
    officializes -> close-beyond confirms; no-chase + retest."""
    po, pc, ph, pl = (float(pb["open"]), float(pb["close"]),
                      float(pb["high"]), float(pb["low"]))
    co, cc, ch, cl = (float(b["open"]), float(b["close"]),
                      float(b["high"]), float(b["low"]))
    t = int(b["time"])
    up, dn = st["up"], st["dn"]
    sig = None
    if pc > po and cc > co and cc > ph:
        up.clear()
        up.update(leg=True, peak=ch, glow=cl)
    elif up.get("leg"):
        up["peak"] = max(up["peak"], ch)
        if cc > co:
            up["glow"] = cl
        elif cc < up["glow"]:
            up.update(pending=up["peak"], plow=cl, leg=False,
                      pt=t, retest=None)
            say(f"ADTP: peak {up['pending']:.2f} official -> pending "
                f"BUY on close back above it")
    if up.get("pending"):
        up["plow"] = min(up.get("plow", cl), cl)
        if t - up["pt"] > 21600:
            up["pending"] = None
        elif cc > up["pending"]:
            wd = abs(up["pending"] - up["plow"])
            if cc - up["pending"] > max(20.0, 0.35 * wd):
                up.update(retest=up["pending"], rt_plow=up["plow"],
                          rt_t=t, pending=None)
            else:
                sig = (1, up["plow"])
                up["pending"] = None
    elif up.get("retest"):
        if t - up.get("rt_t", t) > 21600:
            up["retest"] = None
        elif cl <= up["retest"] + 15.0 and cc >= up["retest"] - 15.0:
            sig = (1, up.get("rt_plow", cl))
            up["retest"] = None
    if pc < po and cc < co and cc < pl:
        dn.clear()
        dn.update(leg=True, dip=cl, rhigh=ch)
    elif dn.get("leg"):
        dn["dip"] = min(dn["dip"], cl)
        if cc < co:
            dn["rhigh"] = ch
        elif cc > dn["rhigh"]:
            dn.update(pending=dn["dip"], phigh=ch, leg=False,
                      pt=t, retest=None)
            say(f"ADTP: dip {dn['pending']:.2f} official -> pending "
                f"SELL on close back below it")
    if dn.get("pending") and sig is None:
        dn["phigh"] = max(dn.get("phigh", ch), ch)
        if t - dn["pt"] > 21600:
            dn["pending"] = None
        elif cc < dn["pending"]:
            wd = abs(dn["phigh"] - dn["pending"])
            if dn["pending"] - cc > max(20.0, 0.35 * wd):
                dn.update(retest=dn["pending"], rt_phigh=dn["phigh"],
                          rt_t=t, pending=None)
            else:
                sig = (-1, dn["phigh"])
                dn["pending"] = None
    elif dn.get("retest") and sig is None:
        if t - dn.get("rt_t", t) > 21600:
            dn["retest"] = None
        elif ch >= dn["retest"] - 15.0 and cc <= dn["retest"] + 15.0:
            sig = (-1, dn.get("rt_phigh", ch))
            dn["retest"] = None
    return sig


def main():
    if not mt5.initialize(path=TERM):
        say(f"ADTP ERROR: mt5 init failed {mt5.last_error()}")
        return
    mt5.symbol_select(SYMBOL, True)
    st = load()
    say("ADTP paper tracker STARTED (live detector + adaptive TP, "
        "virtual only)")
    while True:
        time.sleep(5)
        tick = mt5.symbol_info_tick(SYMBOL)
        if tick is None:
            continue
        p = st["pos"]
        if p is not None:
            d = p["d"]
            fav = (tick.bid - p["e"]) if d == 1 else (p["e"] - tick.ask)
            p["mf"] = max(p.get("mf", 0.0), fav)
            prize = abs(p["tp"] - p["e"])
            if not p["locked"] and fav >= 0.40 * prize:
                spread = tick.ask - tick.bid
                bump = min(spread + BUFFER_USD / LOT, 0.5 * fav)
                p["locked"] = True
                p["sl"] = round(p["e"] + d * bump, 2)
                say(f"ADTP 40% LOCK (virtual): wall moved to "
                    f"{p['sl']:.2f}")
                save(st)
            px = tick.bid if d == 1 else tick.ask
            hit_tp = px >= p["tp"] if d == 1 else px <= p["tp"]
            hit_sl = px <= p["sl"] if d == 1 else px >= p["sl"]
            if hit_tp or hit_sl:
                out = p["tp"] if hit_tp else p["sl"]
                pnl = round((out - p["e"]) * d * LOT, 2)
                kind = ("tp" if hit_tp
                        else ("scratch" if p["locked"] else "sl"))
                st["net"] = round(st["net"] + pnl, 2)
                st["n"] += 1
                if pnl > 0:
                    st["wins"] += 1
                st["fe"] = (st.get("fe", [])
                            + [round(p.get("mf", 0.0), 1)])[-40:]
                dur = round((time.time() - p["t0"]) / 60, 1)
                say(f"ADTP EXIT (virtual): {kind} {pnl:+.2f} after "
                    f"{dur}min - running total {st['net']:+.2f} over "
                    f"{st['n']} trades ({st['wins']} wins)")
                st["pos"] = None
                st["up"], st["dn"] = {}, {}
                save(st)
            continue
        bars = mt5.copy_rates_from_pos(SYMBOL, mt5.TIMEFRAME_M1, 1, 2)
        if bars is None or len(bars) < 2:
            continue
        pb, b = bars[0], bars[1]
        if int(b["time"]) <= st.get("last_bar", 0):
            continue
        st["last_bar"] = int(b["time"])
        sig = det_step(st, pb, b)
        if sig is not None:
            d, wall = sig
            e = tick.ask if d == 1 else tick.bid
            dist = abs(e - wall)
            if dist < MIN_WALL or dist * LOT > PAGE_MAXR:
                say(f"ADTP skipped: wall {dist:.0f}pts")
            else:
                tpd = dist - min(1.0, 0.25 * dist * LOT) / LOT
                tpd = min(tpd, PAGE_TGT / LOT)
                fe = st.get("fe", [])
                if len(fe) >= 20:
                    adp = sorted(fe)[int(0.6 * len(fe))]
                    tpd = min(tpd, max(15.0, adp))
                    mode = f"adaptive P60 of {len(fe)}"
                else:
                    tpd = tpd * 0.25
                    mode = f"warmup quarter ({len(fe)}/20)"
                st["pos"] = {"d": d, "e": e, "sl": round(wall, 2),
                             "tp": round(e + d * tpd, 2),
                             "locked": False, "t0": time.time()}
                say(f"ADTP ENTRY (virtual): "
                    f"{'BUY' if d == 1 else 'SELL'} {LOT} @ {e:.2f} "
                    f"SL {wall:.2f} TP {st['pos']['tp']:.2f} (risk "
                    f"${dist * LOT:.2f}, prize ${tpd * LOT:.2f}, "
                    f"{mode})")
        save(st)


if __name__ == "__main__":
    main()
