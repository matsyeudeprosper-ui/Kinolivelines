"""PAPER TWIN of the BOS bot's flip + TOUCH configuration (2026-09-11).

The live bot (structure_bos_bot.py, TOUCH_ENTRIES=False since the
execution audit) now enters continuations on the candle close. This
process keeps trading the previous rule set VIRTUALLY, on the same
Pro price feed, so the two records can be compared trade by trade:

  - same structure engine (Struct imported from the bot), same awake
    gate, same SL (pending dot), same TP (0.8R), same S_MIN_DIST;
  - flip-BOS entries on the closed candle, continuation entries the
    moment the bid touches the level (1 s polling), one position at a
    time, flat 0.02 - NO war-chest sizing, NO adds (compare against the
    live bot's BASE trades normalised to 0.02);
  - exits judged on live ticks: SL at the bid/ask that crosses it, TP
    at the TP price.

Log: bos_paper_touch.log ("VT ..." lines). State + full trade list:
bos_paper_touch_state.json. Read-only MT5 use on the demo Pro terminal
(476954287, same $7 spread as the real account).
"""
import json
import os
import sys
import time
from datetime import datetime, timezone

import MetaTrader5 as mt5

sys.argv = [sys.argv[0], "paper"]          # neutral variant for the import
import structure_bos_bot as B              # noqa: E402  (Struct + constants)

DIR = os.path.dirname(os.path.abspath(__file__))
LOG = os.path.join(DIR, "bos_paper_touch.log")
STATE = os.path.join(DIR, "bos_paper_touch_state.json")
TERMINAL = r"C:\NestTerminals\u476954287\terminal64.exe"
LOGIN = 476954287
SERVER = "Exness-MT5Trial9"
SYMBOL = B.SYMBOL
LOT = 0.02
RR = B.RR
S_MIN_DIST = B.S_MIN_DIST
AWAKE_WIN = B.AWAKE_WIN
SEED_BARS = B.SEED_BARS


def say(msg):
    line = f"{datetime.now(timezone.utc).isoformat()} {msg}"
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def load_state():
    try:
        return json.load(open(STATE, encoding="utf-8"))
    except Exception:
        return {"pos": None, "trades": [], "net": 0.0, "used_hi": None,
                "used_lo": None, "last_bar": 0}


def save_state(st):
    tmp = STATE + ".tmp"
    json.dump(st, open(tmp, "w", encoding="utf-8"))
    os.replace(tmp, STATE)


def main():
    assert mt5.initialize(path=TERMINAL, login=LOGIN, password=B.PASSWORD,
                          server=SERVER, timeout=60000), "MT5 init failed"
    mt5.symbol_select(SYMBOL, True)
    eng = B.Struct()
    eng.quiet = True                      # never write into the bot's log
    flips = []
    R = mt5.copy_rates_from_pos(SYMBOL, mt5.TIMEFRAME_M1, 1, SEED_BARS)
    assert R is not None and len(R) > 100, "no history"
    for r in R:
        _pt = eng.trend
        eng.step(int(r["time"]), float(r["open"]), float(r["high"]),
                 float(r["low"]), float(r["close"]))
        if eng.trend != _pt and eng.trend != 0 and _pt != 0:
            flips.append(int(r["time"]))
    flips = flips[-20:]
    st = load_state()
    st["last_bar"] = int(R["time"][-1])
    save_state(st)
    say(f"PAPER-TOUCH twin starting (flip+touch, flat {LOT}, RR {RR}) "
        f"seeded {len(R)} bars: trend {eng.trend} choch {eng.choch} "
        f"kept {len(eng.kept)} | net so far {st['net']:+.2f} "
        f"({len(st['trades'])} trades)")

    def enter(d, slp, kind, tick):
        e = tick.ask if d == 1 else tick.bid
        dist = abs(e - slp)
        if dist <= S_MIN_DIST:
            say(f"VT {kind} skipped: dot {dist:.0f}pts inside the spread zone")
            return
        tp = e + d * RR * dist
        st["pos"] = {"d": d, "e": e, "sl": round(slp, 2), "tp": round(tp, 2),
                     "kind": kind, "t": time.time()}
        save_state(st)
        say(f"VT {kind} ENTRY: {'BUY' if d == 1 else 'SELL'} {LOT} @ "
            f"~{e:.2f} SL {slp:.2f} TP {tp:.2f} (risk ${dist * LOT:.2f}, "
            f"trend {'up' if d == 1 else 'down'})")

    def close(px, why):
        p = st["pos"]
        pnl = round((px - p["e"]) * p["d"] * LOT, 2)
        st["net"] = round(st["net"] + pnl, 2)
        st["trades"].append({"kind": p["kind"], "d": p["d"], "e": p["e"],
                             "sl": p["sl"], "tp": p["tp"], "x": px,
                             "why": why, "pnl": pnl,
                             "t_open": p["t"], "t_close": time.time()})
        st["pos"] = None
        save_state(st)
        n = len(st["trades"])
        w = sum(1 for x in st["trades"] if x["pnl"] > 0)
        say(f"VT {'WIN' if pnl > 0 else 'LOSS'} {pnl:+.2f} ({p['kind']}, "
            f"{why}) - twin net {st['net']:+.2f} ({n} trades, {w}W/{n - w}L)")

    while True:
        _to_min = 60.0 - (time.time() % 60.0) + 0.2
        time.sleep(min(_to_min, 1.0))
        try:
            tick = mt5.symbol_info_tick(SYMBOL)
            if tick is None:
                continue
            p = st.get("pos")
            if p:
                if p["d"] == 1:
                    if tick.bid <= p["sl"]:
                        close(tick.bid, "sl")
                    elif tick.bid >= p["tp"]:
                        close(p["tp"], "tp")
                else:
                    if tick.ask >= p["sl"]:
                        close(tick.ask, "sl")
                    elif tick.ask <= p["tp"]:
                        close(p["tp"], "tp")
            # TOUCH continuation (the rule under test)
            if (st.get("pos") is None
                    and any(f > time.time() - AWAKE_WIN for f in flips)):
                if (eng.trend == 1 and eng.hi_v is not None
                        and tick.bid > eng.hi_v
                        and st.get("used_hi") != eng.hi_v):
                    span = eng.kept[eng.hi_i + 1:]
                    if span and any(x[5] == -1 for x in span):
                        m = min(span, key=lambda x: x[3])
                        st["used_hi"] = eng.hi_v
                        save_state(st)
                        enter(1, m[3], "TOUCH", tick)
                elif (eng.trend == -1 and eng.lo_v is not None
                        and tick.bid < eng.lo_v
                        and st.get("used_lo") != eng.lo_v):
                    span = eng.kept[eng.lo_i + 1:]
                    if span and any(x[5] == 1 for x in span):
                        m = max(span, key=lambda x: x[2])
                        st["used_lo"] = eng.lo_v
                        save_state(st)
                        enter(-1, m[2], "TOUCH", tick)
            kb = mt5.copy_rates_from_pos(SYMBOL, mt5.TIMEFRAME_M1, 1, 2)
            if kb is None or len(kb) < 2:
                continue
            bar = kb[-1]
            bt = int(bar["time"])
            if bt == st.get("last_bar"):
                continue
            st["last_bar"] = bt
            _pt = eng.trend
            _hv, _lv = eng.hi_v, eng.lo_v
            sig = eng.step(bt, float(bar["open"]), float(bar["high"]),
                           float(bar["low"]), float(bar["close"]))
            if eng.trend != _pt and eng.trend != 0 and _pt != 0:
                flips.append(bt)
                del flips[:-20]
            awake = any(f > bt - AWAKE_WIN for f in flips)
            save_state(st)
            if sig is None or st.get("pos") is not None or not awake:
                continue
            d, slp = sig
            flip = eng.trend != _pt
            if not flip:
                lvl = _hv if d == 1 else _lv
                if (d == 1 and st.get("used_hi") == lvl) or \
                        (d == -1 and st.get("used_lo") == lvl):
                    continue          # touch owned this level
            tk = mt5.symbol_info_tick(SYMBOL)
            if tk is not None:
                enter(d, slp, "FLIP-BOS" if flip else "BOS", tk)
        except Exception as e:
            say(f"ERROR {type(e).__name__}: {e}")
            time.sleep(30)


if __name__ == "__main__":
    main()
