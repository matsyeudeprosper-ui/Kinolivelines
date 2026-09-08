"""owl_chart_feed.py - data feed for the custom BTC chart page
(user 2026-09-08). Step 1: M1 candles with the NOISE-SILENCE filter:
a closed candle is shown only if it makes a HIGHER HIGH or a LOWER
LOW than the last SHOWN candle; inside candles are silenced. The
reference walks forward with the kept candles, so consecutive
inside bars all vanish until price breaks either extreme.

Writes owl_chart_btc.json every ~10s:
  {"updated": ts, "symbol", "raw": N_raw, "kept": N_kept,
   "candles": [[t, o, h, l, c, dir], ...],   # kept only, last 400
   "px": last_price}
"""
import json
import os
import time
from datetime import datetime, timezone

import MetaTrader5 as mt5

TERMINAL = r"C:\NestTerminals\u476954287\terminal64.exe"
LOGIN = 476954287
PASSWORD = "M@tsy1983"
SERVER = "Exness-MT5Trial9"
SYMBOL = "BTCUSD"
RAW_BARS = 3000
KEEP_LAST = 400

DIR = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(DIR, "owl_chart_btc.json")


def build(rates):
    """v2 filter (user 2026-09-08): a candle is shown only if its
    CLOSE lands beyond the last shown candle's high or low - wick
    pokes no longer count, the close has to commit."""
    kept = []
    ref_h = ref_l = None
    for r in rates:
        h, l = float(r["high"]), float(r["low"])
        c = float(r["close"])
        if ref_h is None or c > ref_h or c < ref_l:
            o = float(r["open"])
            kept.append([int(r["time"]), round(o, 2), round(h, 2),
                         round(l, 2), round(c, 2),
                         1 if c >= o else -1])
            ref_h, ref_l = h, l
    return kept


def swings(kept):
    """Swing markers (user 2026-09-08), computed on VISIBLE candles:
    - a new higher high confirms a SWING LOW = the lowest low
      strictly between the last high and the new high, valid only if
      at least one red candle sits in that span;
    - a new lower low confirms a SWING HIGH = the highest high in
      the span, valid only with at least one green candle there.
    Bullish legs therefore mark lows, bearish legs mark highs.
    Returns [[time, price, kind], ...], kind 1=low, -1=high."""
    if len(kept) < 3:
        return []
    dots = []
    hi_i, hi_v = 0, kept[0][2]
    lo_i, lo_v = 0, kept[0][3]
    for i in range(1, len(kept)):
        h, l = kept[i][2], kept[i][3]
        if h > hi_v:
            span = kept[hi_i + 1:i]
            if span and any(x[5] == -1 for x in span):
                m = min(span, key=lambda x: x[3])
                dots.append([m[0], m[3], 1])
                lo_i = kept.index(m)
                lo_v = m[3]
            hi_i, hi_v = i, h
        elif l < lo_v:
            span = kept[lo_i + 1:i]
            if span and any(x[5] == 1 for x in span):
                m = max(span, key=lambda x: x[2])
                dots.append([m[0], m[2], -1])
                hi_i = kept.index(m)
                hi_v = m[2]
            lo_i, lo_v = i, l
    return dots


def main():
    assert mt5.initialize(path=TERMINAL, login=LOGIN,
                          password=PASSWORD, server=SERVER,
                          timeout=60000), "MT5 init failed"
    print("chart feed up", flush=True)
    while True:
        try:
            R = mt5.copy_rates_from_pos(SYMBOL, mt5.TIMEFRAME_M1,
                                        0, RAW_BARS)
            tick = mt5.symbol_info_tick(SYMBOL)
            if R is not None and len(R) > 1 and tick is not None:
                kept = build(R[:-1])       # closed bars only
                lv = R[-1]                 # the forming candle, live
                live = [int(lv["time"]), round(float(lv["open"]), 2),
                        round(float(lv["high"]), 2),
                        round(float(lv["low"]), 2),
                        round(float(lv["close"]), 2),
                        1 if lv["close"] >= lv["open"] else -1]
                win = kept[-KEEP_LAST:]
                t0 = win[0][0] if win else 0
                dots = [d for d in swings(kept) if d[0] >= t0]
                json.dump(
                    {"updated": int(time.time()), "symbol": SYMBOL,
                     "raw": len(R) - 1, "kept": len(kept),
                     "candles": win, "live": live, "dots": dots,
                     "px": round(float(tick.bid), 2)},
                    open(OUT, "w"))
        except Exception as e:
            print(f"{datetime.now(timezone.utc).isoformat()} ERROR "
                  f"{type(e).__name__}: {e}", flush=True)
            time.sleep(30)
        time.sleep(3)


if __name__ == "__main__":
    main()
