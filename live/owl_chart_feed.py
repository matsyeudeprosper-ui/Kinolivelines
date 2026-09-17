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
PASSWORD = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                     "owl_secrets.json"), encoding="utf-8"))["mt5_password"]  # not in git
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


def pullback_since(kept, t0, brk_dir):
    """Owner 2026-09-16: "pullback is opposite candle close below previous
    candle in my filtered custom chart".

    So it is judged on the SILENCE-FILTERED candles, not raw M1, and it is
    not merely an opposite-coloured candle: the close has to commit beyond
    the previous kept candle. Anticipating a break UP needs a candle that
    closed BELOW the previous one's low; anticipating a break DOWN needs one
    that closed ABOVE the previous one's high. Until that happens the level
    is only the current extreme and must not be drawn.
    """
    if not t0 or not brk_dir:
        return False
    prev = None
    for k in kept:
        if prev is not None and k[0] > t0:
            c = k[4]
            if brk_dir == 1 and c < prev[3]:
                return True
            if brk_dir == -1 and c > prev[2]:
                return True
        prev = k
    return False


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
        return [], [], 0, 0, None, None, None, None
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
            # the BOS must break a low formed AFTER the choc - the
            # choc candle itself becomes the new reference (2026-09-08
            # fix: choc+bos were collapsing onto one candle)
            lo_i, lo_v = i, l
        elif trend == -1 and prot_hi is not None and c > prot_hi[1]:
            marks.append([t, prot_hi[1], "choch", 1])
            choch = 1
            prot_hi = None
            hi_i, hi_v = i, h
        # --- higher-high close event -> may confirm a LOW dot ---
        if c > hi_v:
            span = kept[hi_i + 1:i]
            if span and any(x[5] == -1 for x in span):
                m = min(span, key=lambda x: x[3])
                nd = [m[0], m[3], 1]
                if choch == 1 and trend != 1:
                    # first bullish BOS after a bullish CHoCH.
                    # Owner 2026-09-16: the protected dot of a FRESH trend is
                    # the leg's own extreme - the level that had been the
                    # anticipated BOS on the other side - not the small
                    # pullback extreme between the CHoCH and this break.
                    # lo_v/lo_i still hold the leg's lowest low here: the
                    # bullish CHoCH resets the HIGH reference, never the low.
                    marks.append([t, hi_v, "bos", 1])
                    trend = 1
                    choch = 0
                    nd = [kept[lo_i][0], lo_v, 1]
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
                        # owner 2026-09-16: a dot means a confirmed break.
                        # While counting higher lows there is no break yet,
                        # so nothing is marked until the trend is set.
                        if up_st >= 2:
                            trend = 1
                            prot_lo = nd
                            dots.append(nd)
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
                    # mirror of the bullish case above: hi_v/hi_i still hold
                    # the leg's highest high, because a bearish CHoCH resets
                    # the LOW reference and never the high
                    marks.append([t, lo_v, "bos", -1])
                    trend = -1
                    choch = 0
                    nd = [kept[hi_i][0], hi_v, -1]
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
                        if dn_st >= 2:
                            trend = -1
                            prot_hi = nd
                            dots.append(nd)
                            up_st = 0
                    else:
                        dn_st = 0
                last_hi = m[2]
                hi_i = kept.index(m)
                hi_v = m[2]
            lo_i, lo_v = i, l
    # 2026-09-15: the two levels that decide what happens next -
    # hi_v/lo_v is the price a close must beat for the NEXT BOS,
    # prot_* is where the trend would break instead (CHoCH).
    # Owner 2026-09-16: BOTH levels that decide the next event, because the
    # owner needs both - the trend's own break for continuation trades, and
    # the break that confirms a pending flip. They sit on opposite sides and
    # neither can stand in for the other.
    #   nxt  = the CONTINUATION level, in the trend's direction
    #   flp  = the CONFIRMING level, only while a CHoCH is armed
    _dir = trend
    nxt = hi_v if _dir == 1 else (lo_v if _dir == -1 else None)
    _fdir = choch if (choch and choch != trend) else 0
    flp = hi_v if _fdir == 1 else (lo_v if _fdir == -1 else None)
    _fi = hi_i if _fdir == 1 else lo_i
    flp_t = kept[_fi][0] if (flp is not None and 0 <= _fi < len(kept)) else None
    inv = (prot_lo[1] if (trend == 1 and prot_lo) else
           (prot_hi[1] if (trend == -1 and prot_hi) else None))
    # the candle that SET each level, so the chart can anchor the line to
    # its origin instead of floating it (2026-09-16)
    _ai = hi_i if _dir == 1 else lo_i
    nxt_t = kept[_ai][0] if (nxt is not None and 0 <= _ai < len(kept)) else None
    inv_t = (prot_lo[0] if (trend == 1 and prot_lo) else
             (prot_hi[0] if (trend == -1 and prot_hi) else None))
    return (dots, marks, trend, choch, nxt, inv, nxt_t, inv_t, _dir,
            flp, flp_t, _fdir)


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


def candle_sources():
    """Any terminal that can serve BTCUSD candles. The chart must survive
    one account being closed, so the configured demo is merely the first
    candidate and every nest terminal is a fallback (2026-09-16)."""
    out = [(TERMINAL, LOGIN, SERVER, PASSWORD)]
    try:
        for u in json.load(open(os.path.join(DIR, "owl_nest_users.json"),
                                encoding="utf-8")):
            t = u.get("terminal")
            if not t or t == TERMINAL or not os.path.exists(t):
                continue
            out.append((t, int(u.get("mt5_login") or u["login"]),
                        u.get("mt5_server", SERVER),
                        u.get("mt5_password") or PASSWORD))
    except Exception:
        pass
    return out


def connect():
    for path, login, srv, pw in candle_sources():
        try:
            mt5.shutdown()
        except Exception:
            pass
        if mt5.initialize(path=path, login=login, password=pw,
                          server=srv, timeout=60000):
            if mt5.copy_rates_from_pos(SYMBOL, mt5.TIMEFRAME_M1, 0, 2) is not None:
                print(f"chart feed on {login}", flush=True)
                return True
    return False


def main():
    assert connect(), "no terminal could serve BTCUSD candles"
    print("chart feed up", flush=True)
    while True:
        try:
            R = mt5.copy_rates_from_pos(SYMBOL, mt5.TIMEFRAME_M1,
                                        0, RAW_BARS)
            tick = mt5.symbol_info_tick(SYMBOL)
            # user 2026-09-13: previous (closed) H1 candle's open/close
            # for a discreet reference on the chart; [t, o, h, l, c]
            h1 = None
            try:
                _H = mt5.copy_rates_from_pos(SYMBOL, mt5.TIMEFRAME_H1, 1, 1)
                if _H is not None and len(_H) == 1:
                    _b = _H[0]
                    h1 = [int(_b["time"]), round(float(_b["open"]), 2),
                          round(float(_b["high"]), 2), round(float(_b["low"]), 2),
                          round(float(_b["close"]), 2)]
            except Exception:
                h1 = None
            # 2026-09-16 (owner): positions are NOT published here any
            # more. This process is attached to whatever terminal serves
            # the candles, which is not the account being traded. The app
            # server injects the VIEWER's own positions instead.
            trades = []
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
                (dots, marks, trend, choch, nxt, inv,
                 nxt_t, inv_t, _mdir,
                 _mflp, _mflp_t, _mfdir) = engine(kept)
                # INTERNAL STRUCTURE (owner 2026-09-16): between two main
                # events the range can be wide enough for its own little
                # BOS patterns. Run the SAME engine over the candles since
                # the last main event only. It needs no kill switch: the
                # moment price rejoins the main structure a new mark fires
                # and this window restarts from there.
                i_dots = i_marks = []
                i_trend = i_choch = i_dir = i_fdir = 0
                i_flp = i_flp_t = None
                i_nxt = i_inv = i_nxt_t = i_inv_t = None
                i_ready = i_fready = False
                _since = inv_t if inv_t else (marks[-1][0] if marks else None)
                # Owner 2026-09-16: "the internal structure is BOS, CHoCH
                # that forms in between the space of a confirmed BOS and the
                # glowing dot created by that BOS." So the window opens at
                # the CURRENT protected dot, which moves on every break -
                # continuations included. marks[] only records flips, so
                # anchoring there left the window running for hours after a
                # continuation had already opened a new space.
                _t0 = inv_t if inv_t else (marks[-1][0] if marks else None)
                if _t0:
                    # RAW M1. The silence filter was tried here on
                    # 2026-09-16 and reverted the same day: it left the
                    # internal structure existing only 24% of the time,
                    # because inside a range the filtered series rarely
                    # produces the breaks the engine needs. The owner wants
                    # the internal structure, so this stays raw. Every OTHER
                    # rule is shared with the main structure.
                    _inner = [[int(r["time"]), float(r["open"]),
                               float(r["high"]), float(r["low"]),
                               float(r["close"]),
                               1 if r["close"] >= r["open"] else -1]
                              for r in R[:-1] if int(r["time"]) > _t0]
                    if len(_inner) >= 10:
                        (i_dots, i_marks, i_trend, i_choch,
                         i_nxt, i_inv, i_nxt_t, i_inv_t, i_dir,
                         i_flp, i_flp_t, i_fdir) = engine(_inner)
                        # owner 2026-09-16: do not anticipate the next break
                        # until price has actually pulled back from the level
                        # - at least one candle against the trend since the
                        # candle that set it. Before that the "next BOS" is
                        # just the current extreme and says nothing.
                        i_ready = pullback_since(kept, i_nxt_t, i_dir)
                        i_fready = pullback_since(kept, i_flp_t, i_fdir)
                # user 2026-09-08 (screenshot): NEVER show the
                # opposite side's dots while a trend is confirmed -
                # uptrend displays lows only, downtrend highs only.
                # Owner 2026-09-16: the internal structure obeys it too.
                if i_trend == 1:
                    i_dots = [d for d in i_dots if d[2] == 1]
                elif i_trend == -1:
                    i_dots = [d for d in i_dots if d[2] == -1]
                if trend == 1:
                    dots = [d for d in dots if d[2] == 1]
                elif trend == -1:
                    dots = [d for d in dots if d[2] == -1]
                dots = [d for d in dots if d[0] >= t0]
                marks = [m for m in marks if m[0] >= t0]
                # owner 2026-09-16: the main structure anticipates its
                # next break under the same condition as the internal one -
                # price must have pulled back from the level first
                _fready = pullback_since(kept, _mflp_t, _mfdir)
                _ready = pullback_since(kept, nxt_t, _mdir)
                _now = int(R[-1]["time"])
                _mv2 = sum(1 for m in marks if m[0] >= _now - 7200)
                _rng = [float(r["high"]) - float(r["low"]) for r in R[-60:]]
                _ref = [float(r["high"]) - float(r["low"]) for r in R[-1440:]]
                _rng.sort(); _ref.sort()
                _vn = _rng[len(_rng) // 2] if _rng else 0.0
                _vr = _ref[len(_ref) // 2] if _ref else 0.0
                json.dump(
                    {"updated": int(time.time()), "symbol": SYMBOL,
                     "moves_2h": _mv2,
                     "vol_now": round(_vn, 1), "vol_ref": round(_vr, 1),
                     "spread": round(float(tick.ask - tick.bid), 2),
                     "raw": len(R) - 1, "kept": len(kept),
                     "candles": win, "live": live, "dots": dots,
                     "marks": marks, "trend": trend, "choch": choch,
                     "next_bos": round(nxt, 2) if nxt else None,
                     "invalid": round(inv, 2) if inv else None,
                     "int_trend": i_trend,
                     "int_bos": round(i_nxt, 2) if i_nxt else None,
                     "int_inv": round(i_inv, 2) if i_inv else None,
                     "int_dots": [d for d in i_dots if d[0] >= t0],
                     "int_bos_t": i_nxt_t, "int_inv_t": i_inv_t,
                     "next_bos_t": nxt_t, "invalid_t": inv_t,
                     "int_since": _since,
                     "int_choch": i_choch,
                     "bos_dir": _mdir,
                     "int_bos_dir": i_dir,
                     "flip_bos": round(_mflp, 2) if _mflp else None,
                     "flip_bos_t": _mflp_t, "flip_bos_dir": _mfdir,
                     "flip_bos_ready": _fready,
                     "int_flip_bos": round(i_flp, 2) if i_flp else None,
                     "int_flip_bos_t": i_flp_t, "int_flip_bos_dir": i_fdir,
                     "int_flip_bos_ready": i_fready,
                     "bos_ready": _ready,
                     "int_bos_ready": i_ready,
                     # the internal engine fires every few minutes; the
                     # whole history would out-number the candles, so only
                     # the recent events are drawn
                     "int_marks": [m for m in i_marks if m[0] >= t0][-10:],
                     "trades": trades, "h1": h1,
                     "px": round(float(tick.bid), 2)},
                    open(OUT, "w"))
        except Exception as e:
            print(f"{datetime.now(timezone.utc).isoformat()} ERROR "
                  f"{type(e).__name__}: {e}", flush=True)
            time.sleep(15)
            connect()                      # the source may have gone away
        # sync with the broker minute: wake right after each candle
        # close so the chart flips forming->closed with the broker,
        # ~1s ticks otherwise (user 2026-09-08)
        time.sleep(min(60.0 - (time.time() % 60.0) + 0.2, 1.0))


if __name__ == "__main__":
    main()
