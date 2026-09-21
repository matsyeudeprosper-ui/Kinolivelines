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
RAW_BARS = 8000          # owner 2026-09-17: was 3000 (~50 h). The main
                         # structure can go 2 days without an event, and
                         # when its last mark slid out of the window the
                         # internal window had no start and the whole
                         # internal block was skipped - the structure
                         # vanished from the chart at random.
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


# Owner 2026-09-17: a single look-back is unstable. At one moment 200 chart
# candles finds nothing while 300 and 500 find a full structure, and at
# another 200 works and 400 finds nothing. The cause is the engine's cold
# start - it needs two consecutive higher lows to establish a direction, and
# whether it gets them depends on where the window happens to begin, which
# does not improve monotonically with length.
# So try several lengths and take the first that yields a direction. This is
# a DISPLAY choice, stated plainly: it decides what is drawn, never what a
# trade does. If no length finds a structure, there genuinely is none.
# Tried IN ORDER; the first one that finds a direction wins, so appending
# is safe - an entry can only rescue a case the earlier ones failed.
#
# Owner 2026-09-21: "why no internal structure yet, I can see lower lows and
# higher highs now already inside that range." Because after a one-way run
# the engine's references sit at the two ENDS of it - lo_v at the window's
# first candle, hi_v at the top - and nothing in between can confirm a dot.
# The window was 56 candles and EVERY entry below took all 56, so there was
# nothing shorter to fall back to: the "adaptive" list was trying the same
# slice four times (the real pool has a median of 58 kept candles, while the
# smallest entry was 200). The short tails re-seed the references near price.
# Measured, review/int_window_stuck.py, 5.6 days / 221 samples:
#   structure found today 52.5%  ->  66.5%,  +14.0 points, and by
#   construction never a different answer where one already existed.
INT_WINDOWS = (200, 300, 400, 550, 120, 80, 50, 30, 20)
INT_MAX = max(INT_WINDOWS)     # the most it will ever look back


def _snap_dot(snap, span, kind):
    """The span's extreme among DRAWN candles, or None if the span covers
    none. kind +1 = a low dot, -1 = a high dot."""
    if not snap or not span:
        return None
    t_a, t_b = span[0][0], span[-1][0]
    cand = [k for k in snap if t_a <= k[0] <= t_b]
    if not cand:
        # the whole span sits inside filtered-out noise, so on THIS chart
        # there is no swing between the two highs. Snapping to the nearest
        # candle would put the dot OUTSIDE its own span, at a price that is
        # not the span's extreme - so no dot is drawn at all.
        return None
    # Owner 2026-09-17: "a dot is always sitting between a previous high and
    # a new high separated by at least one opposite candle." The engine
    # already demands that of the RAW span; demand it of the VISIBLE span
    # too, or a dot can land in a run of candles that shows no pullback at
    # all on this chart.
    if not any(k[5] == -kind for k in cand):
        return None
    if kind == 1:
        k = min(cand, key=lambda x: x[3])
        return [k[0], k[3], 1]
    k = max(cand, key=lambda x: x[2])
    return [k[0], k[2], -1]


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


def engine(kept, snap=None, brk_out=None):
    """`snap`: when the engine runs on RAW candles (the internal structure)
    the swing it finds often sits on a minute the silence filter removed, so
    the dot floats between drawn candles at a price no visible candle
    reaches. Pass the filtered series here and each dot is placed on the
    extreme of the SAME span among candles that are actually drawn - the
    main structure's own dot rule, on the chart the owner is looking at
    (owner 2026-09-16).

    Structure engine v5 (user 2026-09-08, CHoCH + BOS rules).

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
    first_lo = first_hi = None   # the founding dot, drawn with the second
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
                _vis = _snap_dot(snap, span, 1)
                vis = snap is None or _vis is not None
                nd = _vis or [m[0], m[3], 1]
                if choch == 1 and trend != 1:
                    # first bullish BOS after a bullish CHoCH.
                    # 2026-09-16 this took the LEG's extreme instead of the
                    # pullback between the CHoCH and this break. That was a
                    # workaround for the engine reading raw M1, where the
                    # post-CHoCH span was 1-3 noise minutes and its extreme
                    # meant nothing. Now that the engine reads the chart the
                    # span is a real pullback, so the pullback's extreme is
                    # the right protected dot again (owner 2026-09-17).
                    marks.append([t, hi_v, "bos", 1])
                    trend = 1
                    choch = 0
                    if vis:
                        dots.append(nd)
                    if brk_out is not None:
                        brk_out.append((t, 1))
                    prot_lo = nd
                    up_st = dn_st = 0
                elif trend == 1:
                    if vis:
                        dots.append(nd)
                    if brk_out is not None:
                        brk_out.append((t, 1))
                    prot_lo = nd
                    choch = 0    # new BOS up repairs a pending choc
                elif trend == 0:
                    # Owner 2026-09-19: "if 2 glowing dots form, we already
                    # have a structure - a trend forming is enough". The old
                    # bootstrap wanted two CONSECUTIVE HIGHER lows, and the
                    # first confirmed low never counted at all (last_lo was
                    # still None) - so a window that swung down, up, up sat
                    # at "no structure" for hours. Now: two confirmed low
                    # dots = uptrend, whatever their prices. A high dot in
                    # between resets the count, so alternating low/high
                    # cannot bootstrap a direction.
                    up_st += 1
                    dn_st = 0
                    if up_st == 1:
                        first_lo = nd if vis else None
                    if up_st >= 2:
                        trend = 1
                        prot_lo = nd
                        # both founding dots are drawn, not only the second:
                        # a trend the chart shows with one dot reads as a
                        # one-dot trend, which the rule never was
                        if first_lo is not None:
                            dots.append(first_lo)
                        if vis:
                            dots.append(nd)
                last_lo = m[3]
                lo_i = kept.index(m)
                lo_v = m[3]
            hi_i, hi_v = i, h
        # --- lower-low close event -> may confirm a HIGH dot ---
        elif c < lo_v:
            span = kept[lo_i + 1:i]
            if span and any(x[5] == 1 for x in span):
                m = max(span, key=lambda x: x[2])
                _vis = _snap_dot(snap, span, -1)
                vis = snap is None or _vis is not None
                nd = _vis or [m[0], m[2], -1]
                if choch == -1 and trend != -1:
                    # mirror of the bullish case above
                    marks.append([t, lo_v, "bos", -1])
                    trend = -1
                    choch = 0
                    if vis:
                        dots.append(nd)
                    if brk_out is not None:
                        brk_out.append((t, -1))
                    prot_hi = nd
                    up_st = dn_st = 0
                elif trend == -1:
                    if vis:
                        dots.append(nd)
                    if brk_out is not None:
                        brk_out.append((t, -1))
                    prot_hi = nd
                    choch = 0    # new BOS down repairs a pending choc
                elif trend == 0:
                    # mirror of the bullish bootstrap (owner 2026-09-19)
                    dn_st += 1
                    up_st = 0
                    if dn_st == 1:
                        first_hi = nd if vis else None
                    if dn_st >= 2:
                        trend = -1
                        prot_hi = nd
                        if first_hi is not None:
                            dots.append(first_hi)
                        if vis:
                            dots.append(nd)
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
                i_brk1h = 0
                _since = inv_t if inv_t else (marks[-1][0] if marks else None)
                # Owner 2026-09-16: "the internal structure is BOS, CHoCH
                # that forms in between the space of a confirmed BOS and the
                # glowing dot created by that BOS." So the window opens at
                # the CURRENT protected dot, which moves on every break -
                # continuations included. marks[] only records flips, so
                # anchoring there left the window running for hours after a
                # continuation had already opened a new space.
                # belt and braces: if the main structure has neither a
                # protected dot nor a mark in range, open the internal
                # window at the oldest candle instead of skipping it. The
                # look-back below trims it to size anyway.
                _t0 = (inv_t if inv_t
                       else (marks[-1][0] if marks
                             else (kept[0][0] if kept else None)))
                # Owner 2026-09-18: "the moment we touch either of the main
                # structure's borders - the BOS level or the glowing dot -
                # we stop all internal structure, we reset, and we follow
                # the main structure again."
                #
                # The internal structure only means anything INSIDE the main
                # range. Anchoring on the protected dot was not enough: a
                # TOUCH is not a close, so price could reach a border, fail
                # to confirm, and the internal structure would carry on
                # across a boundary it had already crossed. The window now
                # restarts at the last touch of either border.
                # 2026-09-19 fix: the first version assumed next_bos was the
                # UPPER border and the dot the LOWER one - true in an uptrend,
                # reversed in a downtrend. There, every candle whose high sat
                # above the (lower) BOS level counted as a touch, the window
                # restarted on every bar, and no internal structure could ever
                # form while the main trend was down. The borders are now the
                # min and max of whatever main levels exist - the BOS level,
                # the dot, and the flip level that stands in for the dot once
                # a CHoCH has consumed it - with no assumption about sides.
                if _t0 and kept:
                    _bs = [v for v in (nxt, inv, _mflp) if v is not None]
                    _hi_b = max(_bs) if _bs else None
                    _lo_b = min(_bs) if _bs else None
                    _touch = None
                    # Owner 2026-09-19: "touching the border lines is not
                    # enough to cancel the internal structure - a CLOSE
                    # beyond those lines is what confirms it." Same standard
                    # as every other confirmation in this engine: the close
                    # commits, a wick does not. So the window restarts on the
                    # last candle that CLOSED strictly beyond a main border.
                    for _k in kept:
                        if _k[0] <= _t0:
                            continue
                        if ((_hi_b is not None and _k[4] > _hi_b)
                                or (_lo_b is not None and _k[4] < _lo_b)):
                            _touch = _k[0]
                    if _touch and _touch > _t0:
                        _t0 = _touch
                if _t0:
                    # Owner 2026-09-17: the internal structure reads the
                    # CUSTOM CHART - the candles that close completely
                    # beyond the previous one. Not raw M1, and not raw with
                    # a snap patched on top. A dot is the valley between two
                    # confirmed highs, and both the highs and the valley
                    # have to be candles that exist on this chart.
                    # This was tried on raw first and the snapping that
                    # followed produced dots outside their own span; see
                    # review/STRUCTURE_RULES.md.
                    # ...and capped in length. When the main structure
                    # goes quiet the window since its protected dot reaches
                    # 14 h and 891 chart candles, and the engine then tracks
                    # only the largest swings - 14 breaks, 11 of them back
                    # to back, 0 dots. A cap keeps the references resetting
                    # often enough to see structure INSIDE the range.
                    # Swept 30/40/60/80/120/200/400: structure present
                    # 30/35/55/70/82/88/90% of samples, dots 0/0/2/4/4/13/0.
                    # 200 is the best of them (review/window_sweep.py).
                    _pool = [k for k in kept if k[0] > _t0]
                    _inner, _ibrk = [], []
                    for _w in INT_WINDOWS:
                        _try = _pool[-_w:]
                        if len(_try) < 5:
                            continue
                        _b = []
                        _r = engine(_try, brk_out=_b)
                        if _r[2] != 0:          # a direction was found
                            _inner, _ibrk = _try, _b
                            (i_dots, i_marks, i_trend, i_choch,
                             i_nxt, i_inv, i_nxt_t, i_inv_t, i_dir,
                             i_flp, i_flp_t, i_fdir) = _r
                            break
                    else:
                        _inner = _pool[-INT_WINDOWS[0]:]
                    if i_trend != 0:
                        # owner 2026-09-16: do not anticipate the next break
                        # until price has actually pulled back from the level
                        # - at least one candle against the trend since the
                        # candle that set it. Before that the "next BOS" is
                        # just the current extreme and says nothing.
                        _nw = int(R[-1]["time"])
                        i_brk1h = sum(1 for b in _ibrk
                                      if b[0] > _nw - 3600)
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
                     "int_win": len(_inner),
                     "int_brk_1h": i_brk1h,
                     "int_awake": i_brk1h >= 1,
                     "int_state": (
                         "none" if not i_trend else
                         ("flip" if (i_choch and i_choch != i_trend) else
                          ("ready" if i_ready else "forming"))),
                     "int_bos_ready": i_ready,
                     # the internal engine fires every few minutes; the
                     # whole history would out-number the candles, so only
                     # the recent events are drawn
                     "int_marks": [m for m in i_marks if m[0] >= t0][-10:],
                     "trades": trades, "h1": h1,
                     "px": round(float(tick.bid), 2)},
                    open(OUT + ".tmp", "w"))
                for _ in range(12):
                    try:
                        os.replace(OUT + ".tmp", OUT)
                        break
                    except PermissionError:
                        time.sleep(0.05)
                else:
                    try:
                        os.replace(OUT + ".tmp", OUT)
                    except Exception:
                        pass
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
