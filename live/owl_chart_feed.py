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
        h, l, c = kept[i][2], kept[i][3], kept[i][4]
        # user precision 2026-09-08: the confirming candle must
        # CLOSE beyond the reference extreme - a wick poke does not
        # confirm a swing dot
        if c > hi_v:
            span = kept[hi_i + 1:i]
            if span and any(x[5] == -1 for x in span):
                m = min(span, key=lambda x: x[3])
                dots.append([m[0], m[3], 1])
                lo_i = kept.index(m)
                lo_v = m[3]
            hi_i, hi_v = i, h
        elif c < lo_v:
            span = kept[lo_i + 1:i]
            if span and any(x[5] == 1 for x in span):
                m = max(span, key=lambda x: x[2])
                dots.append([m[0], m[2], -1])
                hi_i = kept.index(m)
                hi_v = m[2]
            lo_i, lo_v = i, l
    return dots


def engine(kept):
    """Structure engine v5 (user 2026-09-08, CHoCH + BOS rules).

    Swing dots as before: a candle CLOSING beyond the reference
    high/low confirms the span's swing low/high (needs one opposite-
    color candle in the span).

    Trend states and transitions:
    - from NEUTRAL: two higher low-dots in a row = uptrend, two
      lower high-dots = downtrend (the original 2-dot rule);
    - a candle closing completely beyond the CURRENT trend's newest
      glowing dot, first time = CHoCH (marked, trend keeps its
      color but is now wounded);
    - after a CHoCH, the FIRST dot-confirmed break of extreme in
      the new direction = BOS -> the trend actually flips there.
      No flip without CHoCH first, and no flip on CHoCH alone.
    - while a trend holds, only its own dot side is drawn.

    Returns (dots, marks, trend, choch_pending)
      dots  [[t, price, kind]]           kind 1=low, -1=high
      marks [[t, price, label, dir]]     label 'choch'|'bos'
    """
    if len(kept) < 3:
        return [], [], 0, 0
    dots = []
    marks = []
    hi_i, hi_v = 0, kept[0][2]
    lo_i, lo_v = 0, kept[0][3]
    trend = 0
    choch = 0            # pending direction after a CHoCH, else 0
    last_lo = last_hi = None
    up_st = dn_st = 0
    prot_lo = prot_hi = None     # the trend's newest glowing dot
    for i in range(1, len(kept)):
        t, o, h, l, c, d = kept[i]
        # --- CHoCH: close fully beyond the trend's newest dot ---
        if trend == 1 and prot_lo is not None and c < prot_lo[1]:
            marks.append([t, prot_lo[1], "choch", -1])
            choch = -1
            prot_lo = None
        elif trend == -1 and prot_hi is not None and c > prot_hi[1]:
            marks.append([t, prot_hi[1], "choch", 1])
            choch = 1
            prot_hi = None
        # --- higher-high close event -> may confirm a LOW dot ---
        if c > hi_v:
            span = kept[hi_i + 1:i]
            if span and any(x[5] == -1 for x in span):
                m = min(span, key=lambda x: x[3])
                nd = [m[0], m[3], 1]
                if choch == 1 and trend != 1:
                    # first bullish BOS after a bullish CHoCH
                    marks.append([t, hi_v, "bos", 1])
                    trend = 1
                    choch = 0
                    dots.append(nd)
                    prot_lo = nd
                    up_st = dn_st = 0
                elif trend == 1:
                    dots.append(nd)
                    prot_lo = nd
                    choch = 0    # new BOS up repairs a pending choc
                elif trend == 0:
                    if last_lo is not None and m[3] > last_lo:
                        up_st += 1
                        dots.append(nd)
                        if up_st >= 2:
                            trend = 1
                            prot_lo = nd
                            dn_st = 0
                    else:
                        up_st = 0
                last_lo = m[3]
                lo_i = kept.index(m)
                lo_v = m[3]
            hi_i, hi_v = i, h
        # --- lower-low close event -> may confirm a HIGH dot ---
        elif c < lo_v:
            span = kept[lo_i + 1:i]
            if span and any(x[5] == 1 for x in span):
                m = max(span, key=lambda x: x[2])
                nd = [m[0], m[2], -1]
                if choch == -1 and trend != -1:
                    marks.append([t, lo_v, "bos", -1])
                    trend = -1
                    choch = 0
                    dots.append(nd)
                    prot_hi = nd
                    up_st = dn_st = 0
                elif trend == -1:
                    dots.append(nd)
                    prot_hi = nd
                    choch = 0    # new BOS down repairs a pending choc
                elif trend == 0:
                    if last_hi is not None and m[2] < last_hi:
                        dn_st += 1
                        dots.append(nd)
                        if dn_st >= 2:
                            trend = -1
                            prot_hi = nd
                            up_st = 0
                    else:
                        dn_st = 0
                last_hi = m[2]
                hi_i = kept.index(m)
                hi_v = m[2]
            lo_i, lo_v = i, l
    return dots, marks, trend, choch


def trend_filter(cands):
    """Trend layer (user 2026-09-08): a low dot is kept only when it
    is HIGHER than the previous low dot; a high dot only when LOWER
    than the previous high dot. Two kept dots of the same type in a
    row = confirmed trend (up for higher lows, down for lower highs).
    While a trend is confirmed, only its own dot type is drawn; the
    opposite stream still runs silently and flips the trend when it
    confirms twice. A broken chain drops the trend back to neutral.
    Returns (dots, trend)."""
    trend = 0
    last_lo = last_hi = None
    up_st = dn_st = 0
    out = []
    for t, price, kind in cands:
        if kind == 1:
            higher = last_lo is not None and price > last_lo
            last_lo = price
            if higher:
                up_st += 1
                if trend >= 0:
                    out.append([t, price, 1])
                    if up_st >= 2:
                        trend = 1
                        dn_st = 0
                elif up_st >= 2:
                    trend = 1
                    dn_st = 0
                    out.append([t, price, 1])
            else:
                up_st = 0
                if trend == 1:
                    trend = 0
        else:
            lower = last_hi is not None and price < last_hi
            last_hi = price
            if lower:
                dn_st += 1
                if trend <= 0:
                    out.append([t, price, -1])
                    if dn_st >= 2:
                        trend = -1
                        up_st = 0
                elif dn_st >= 2:
                    trend = -1
                    up_st = 0
                    out.append([t, price, -1])
            else:
                dn_st = 0
                if trend == -1:
                    trend = 0
    return out, trend


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
            trades = []
            for p in (mt5.positions_get(symbol=SYMBOL) or []):
                trades.append([
                    1 if p.type == mt5.POSITION_TYPE_BUY else -1,
                    float(p.volume), round(p.price_open, 2),
                    round(p.sl, 2), round(p.tp, 2),
                    round(p.profit, 2)])
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
                dots, marks, trend, choch = engine(kept)
                # user 2026-09-08 (screenshot): NEVER show the
                # opposite side's dots while a trend is confirmed -
                # uptrend displays lows only, downtrend highs only
                if trend == 1:
                    dots = [d for d in dots if d[2] == 1]
                elif trend == -1:
                    dots = [d for d in dots if d[2] == -1]
                dots = [d for d in dots if d[0] >= t0]
                marks = [m for m in marks if m[0] >= t0]
                json.dump(
                    {"updated": int(time.time()), "symbol": SYMBOL,
                     "raw": len(R) - 1, "kept": len(kept),
                     "candles": win, "live": live, "dots": dots,
                     "marks": marks, "trend": trend, "choch": choch,
                     "trades": trades,
                     "px": round(float(tick.bid), 2)},
                    open(OUT, "w"))
        except Exception as e:
            print(f"{datetime.now(timezone.utc).isoformat()} ERROR "
                  f"{type(e).__name__}: {e}", flush=True)
            time.sleep(30)
        time.sleep(3)


if __name__ == "__main__":
    main()
