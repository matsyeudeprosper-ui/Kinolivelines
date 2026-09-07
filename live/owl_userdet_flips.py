"""VIRTUAL forward test UDET3 (2026-09-07): the user's detector with
the 2-per-half-hour ration PLUS door flips - a page that dies at its
wall arms a door: an M1 close beyond the wall enters the OPPOSITE
direction at 0.02 (flip exempt from slots, wall = M1 extreme since the
stopped entry, quarter TP, one flip per loss, no chains). NO broker
orders. Events -> owl_userdet_flips.log."""
import json
import os
import time
from datetime import datetime, timezone

import MetaTrader5 as mt5

DIR = r"C:\Projects\KinoliveLines\live"
LOG = os.path.join(DIR, "owl_userdet_flips.log")
STATE = os.path.join(DIR, "owl_userdet_flips.json")
SYMBOL = "BTCUSDm"
TERM = r"C:\Projects\MT5-KinoliveTrader\terminal64.exe"
MIN_WALL, PAGE_MAXR, PAGE_TGT = 60.0, 2.50, 1.50
TPF, LOT, FLIP_LOT, BUFFER_USD = 0.25, 0.01, 0.02, 0.10


def say(m):
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(f"{datetime.now(timezone.utc).isoformat()} {m}\n")


def load():
    try:
        return json.load(open(STATE))
    except Exception:
        return {"pos": None, "up": {}, "dn": {}, "net": 0.0,
                "n": 0, "wins": 0, "last_bar": 0, "last_slot": None,
                "watch": None}


def save(st):
    with open(STATE, "w") as f:
        json.dump(st, f)


def det_step(st, b):
    cc, ch, cl = float(b["close"]), float(b["high"]), float(b["low"])
    t = int(b["time"])
    up, dn = st["up"], st["dn"]
    sig = None
    if not up.get("pending") and not up.get("retest"):
        if up.get("hh") is None or ch > up["hh"]:
            up["hh"], up["hhlow"] = ch, cl
        elif cc < up["hhlow"]:
            up.update(pending=up["hh"], plow=cl, pt=t, retest=None,
                      hh=None, hhlow=None)
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
    if not dn.get("pending") and not dn.get("retest"):
        if dn.get("ll") is None or cl < dn["ll"]:
            dn["ll"], dn["llhigh"] = cl, ch
        elif cc > dn["llhigh"]:
            dn.update(pending=dn["ll"], phigh=ch, pt=t, retest=None,
                      ll=None, llhigh=None)
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
        say(f"UDET3 ERROR: mt5 init failed {mt5.last_error()}")
        return
    mt5.symbol_select(SYMBOL, True)
    st = load()
    say("UDET3 paper tracker STARTED (ration + door flips, virtual)")
    while True:
        time.sleep(5)
        tick = mt5.symbol_info_tick(SYMBOL)
        if tick is None:
            continue
        p = st["pos"]
        if p is not None:
            d = p["d"]
            fav = (tick.bid - p["e"]) if d == 1 else (p["e"] - tick.ask)
            prize = abs(p["tp"] - p["e"])
            if not p["locked"] and fav >= 0.40 * prize:
                spread = tick.ask - tick.bid
                bump = min(spread + BUFFER_USD / p["lot"], 0.5 * fav)
                p["locked"] = True
                p["sl"] = round(p["e"] + d * bump, 2)
                say(f"UDET3 40% LOCK (virtual): wall {p['sl']:.2f}")
                save(st)
            px = tick.bid if d == 1 else tick.ask
            hit_tp = px >= p["tp"] if d == 1 else px <= p["tp"]
            hit_sl = px <= p["sl"] if d == 1 else px >= p["sl"]
            if hit_tp or hit_sl:
                out = p["tp"] if hit_tp else p["sl"]
                pnl = round((out - p["e"]) * d * p["lot"], 2)
                kind = ("tp" if hit_tp
                        else ("scratch" if p["locked"] else "sl"))
                st["net"] = round(st["net"] + pnl, 2)
                st["n"] += 1
                if pnl > 0:
                    st["wins"] += 1
                tag = "flip " if p.get("flip") else ""
                say(f"UDET3 EXIT (virtual): {tag}{kind} {pnl:+.2f} - "
                    f"total {st['net']:+.2f} over {st['n']} trades "
                    f"({st['wins']} wins)")
                if (kind == "sl" and pnl < -0.005
                        and not p.get("flip")):
                    st["watch"] = {"d": d, "sl": p["sl0"],
                                   "t0": p["t0"],
                                   "t": int(time.time())}
                    say(f"UDET3 door armed: M1 close beyond "
                        f"{p['sl0']:.2f} = flip {FLIP_LOT} opposite")
                st["pos"] = None
                st["up"], st["dn"] = {}, {}
                save(st)
            continue
        bars = mt5.copy_rates_from_pos(SYMBOL, mt5.TIMEFRAME_M1, 1, 1)
        if bars is None or not len(bars):
            continue
        b = bars[0]
        if int(b["time"]) <= st.get("last_bar", 0):
            continue
        st["last_bar"] = int(b["time"])
        w = st.get("watch")
        if w is not None:
            if int(time.time()) - int(w["t"]) > 21600:
                st["watch"] = None
                say("UDET3 door expired (6h)")
            else:
                cc = float(b["close"])
                broke = cc < w["sl"] if w["d"] == 1 else cc > w["sl"]
                if broke:
                    nd = -w["d"]
                    lb = mt5.copy_rates_range(
                        SYMBOL, mt5.TIMEFRAME_M1,
                        datetime.fromtimestamp(int(w["t0"]) - 60,
                                               tz=timezone.utc),
                        datetime.now(timezone.utc))
                    st["watch"] = None
                    if lb is not None and len(lb):
                        import numpy as np
                        wall = (float(np.max(lb["high"])) if nd == -1
                                else float(np.min(lb["low"])))
                        e = tick.ask if nd == 1 else tick.bid
                        dist = abs(e - wall)
                        if dist >= MIN_WALL and dist * FLIP_LOT <= 35.27:
                            tpd = dist - min(1.0, 0.25 * dist
                                             * FLIP_LOT) / FLIP_LOT
                            tpd *= TPF
                            st["pos"] = {"d": nd, "lot": FLIP_LOT,
                                         "e": e, "sl": round(wall, 2),
                                         "sl0": round(wall, 2),
                                         "tp": round(e + nd * tpd, 2),
                                         "locked": False,
                                         "t0": int(time.time()),
                                         "flip": True}
                            say(f"UDET3 FLIP ENTRY (virtual): "
                                f"{'BUY' if nd == 1 else 'SELL'} "
                                f"{FLIP_LOT} @ {e:.2f} SL {wall:.2f} "
                                f"TP {st['pos']['tp']:.2f}")
                        else:
                            say(f"UDET3 flip held: wall {dist:.0f}pts")
                    save(st)
                    continue
        sig = det_step(st, b)
        if sig is not None:
            nowu = datetime.now(timezone.utc)
            skey = (nowu.strftime("%Y%m%d")
                    + "-" + str(nowu.hour * 2
                                + (0 if nowu.minute < 30 else 1)))
            if st.get("last_slot") == skey:
                sig = None
            else:
                d, wall = sig
                e = tick.ask if d == 1 else tick.bid
                dist = abs(e - wall)
                if MIN_WALL <= dist and dist * LOT <= PAGE_MAXR:
                    tpd = dist - min(1.0, 0.25 * dist * LOT) / LOT
                    tpd = min(tpd, PAGE_TGT / LOT) * TPF
                    st["last_slot"] = skey
                    st["pos"] = {"d": d, "lot": LOT, "e": e,
                                 "sl": round(wall, 2),
                                 "sl0": round(wall, 2),
                                 "tp": round(e + d * tpd, 2),
                                 "locked": False,
                                 "t0": int(time.time()),
                                 "flip": False}
                    say(f"UDET3 ENTRY (virtual): "
                        f"{'BUY' if d == 1 else 'SELL'} {LOT} @ "
                        f"{e:.2f} SL {wall:.2f} TP "
                        f"{st['pos']['tp']:.2f}")
        save(st)


if __name__ == "__main__":
    main()
