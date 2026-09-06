"""VIRTUAL forward test of the user's detector definition (2026-09-06).
NO broker orders ever - pure paper. A HIGH is official when a candle
closes below the low of the candle holding the highest high (mirror for
lows); no two-same-colour requirement. Pages only (0.01), one at a
time, live page rules mirrored: min wall 60, risk cap $2.50, TP
near-1:1 with discount, $1.50 profit cap, half-TP, 40% lock ->
breakeven-plus, no-chase/retest, clean-chart reset after each close.
Events -> owl_userdet_paper.log, totals -> owl_userdet_paper.json.
Temporary: stopped on the user's word."""
import json
import os
import time
from datetime import datetime, timezone

import MetaTrader5 as mt5

DIR = r"C:\Projects\KinoliveLines\live"
LOG = os.path.join(DIR, "owl_userdet_paper.log")
STATE = os.path.join(DIR, "owl_userdet_paper.json")
SYMBOL = "BTCUSDm"
TERM = r"C:\Projects\MT5-KinoliveTrader\terminal64.exe"
MIN_WALL, PAGE_MAXR, PAGE_TGT = 60.0, 2.50, 1.50
TPF, LOT, BUFFER_USD = 0.25, 0.01, 0.10


def say(m):
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(f"{datetime.now(timezone.utc).isoformat()} {m}\n")


def load():
    try:
        return json.load(open(STATE))
    except Exception:
        return {"pos": None, "up": {}, "dn": {}, "net": 0.0,
                "n": 0, "wins": 0, "last_bar": 0}


def save(st):
    with open(STATE, "w") as f:
        json.dump(st, f)


def det_step(st, b):
    """User definition on one closed M1 bar dict."""
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
            say(f"UDET: peak {up['pending']:.2f} official (close "
                f"{cc:.2f} under the top candle's low) -> pending BUY "
                f"on close back above it")
    if up.get("pending"):
        up["plow"] = min(up.get("plow", cl), cl)
        if t - up["pt"] > 21600:
            up["pending"] = None
        elif cc > up["pending"]:
            wd = abs(up["pending"] - up["plow"])
            if cc - up["pending"] > max(20.0, 0.35 * wd):
                up.update(retest=up["pending"], rt_plow=up["plow"],
                          rt_t=t, pending=None)
                say(f"UDET: BUY confirmation ran away - retest armed "
                    f"at {up['retest']:.2f}")
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
            say(f"UDET: dip {dn['pending']:.2f} official (close "
                f"{cc:.2f} over the bottom candle's high) -> pending "
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
                say(f"UDET: SELL confirmation ran away - retest armed "
                    f"at {dn['retest']:.2f}")
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
        say(f"UDET ERROR: mt5 init failed {mt5.last_error()}")
        return
    mt5.symbol_select(SYMBOL, True)
    st = load()
    say("UDET paper tracker STARTED (virtual only, no broker orders)")
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
                bump = min(spread + BUFFER_USD / LOT, 0.5 * fav)
                p["locked"] = True
                p["sl"] = round(p["e"] + d * bump, 2)
                say(f"UDET 40% LOCK (virtual): wall moved to "
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
                dur = round((time.time() - p["t0"]) / 60, 1)
                say(f"UDET EXIT (virtual): {kind} {pnl:+.2f} after "
                    f"{dur}min - running total {st['net']:+.2f} over "
                    f"{st['n']} trades ({st['wins']} wins)")
                st["pos"] = None
                st["up"], st["dn"] = {}, {}   # clean chart, like live
                save(st)
            continue
        bars = mt5.copy_rates_from_pos(SYMBOL, mt5.TIMEFRAME_M1, 1, 1)
        if bars is None or not len(bars):
            continue
        b = bars[0]
        if int(b["time"]) <= st.get("last_bar", 0):
            continue
        st["last_bar"] = int(b["time"])
        sig = det_step(st, b)
        if sig is not None:
            d, wall = sig
            e = tick.ask if d == 1 else tick.bid
            dist = abs(e - wall)
            if dist < MIN_WALL:
                say(f"UDET skipped: wall {dist:.0f}pts too close")
            elif dist * LOT > PAGE_MAXR:
                say(f"UDET skipped: wall {dist:.0f}pts would risk "
                    f"${dist * LOT:.2f} > ${PAGE_MAXR:.2f}")
            else:
                tpd = dist - min(1.0, 0.25 * dist * LOT) / LOT
                tpd = min(tpd, PAGE_TGT / LOT) * TPF
                st["pos"] = {"d": d, "e": e, "sl": round(wall, 2),
                             "tp": round(e + d * tpd, 2),
                             "locked": False, "t0": time.time()}
                say(f"UDET ENTRY (virtual): "
                    f"{'BUY' if d == 1 else 'SELL'} {LOT} @ {e:.2f} "
                    f"SL {wall:.2f} TP {st['pos']['tp']:.2f} (risk "
                    f"${dist * LOT:.2f}, prize ${tpd * LOT:.2f})")
        save(st)


if __name__ == "__main__":
    main()
