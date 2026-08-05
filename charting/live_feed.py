"""Keep the custom-chart CSVs current so the MT5 side can stream them live.

Runs forever. Every POLL seconds it rebuilds both series and writes them to the
MT5 COMMON folder, where KLCustomFeed.mq5 (a Service) picks them up.

WHAT UPDATES WHEN, and why they differ:

  breakout  advances only when a SOURCE BAR CLOSES. The rule is "did this candle
            close outside the previous candle's range", and a forming candle has
            no close yet - deciding on it would make bars appear and disappear as
            price wobbled. So closed bars only. On M5 that is one update per five
            minutes, and it never repaints.

  renko     advances the moment price travels one brick, using the live bid.
            A brick is decided by distance alone, not by a bar boundary, so it
            can be built in real time and a completed brick never changes. This
            is the livelier of the two.

ATOMIC WRITES. The Service may read at any instant, so writing in place would
sometimes hand it a half-finished file. Each CSV is written to a .tmp and then
os.replace()d, which is atomic on Windows.

ONE MT5 CONNECTION, held open. Re-initialising every few seconds is what
exhausted the terminal's API slots on 2026-08-02 and stalled the whole stack.
"""
import csv, os, sys, time
from datetime import datetime

import MetaTrader5 as mt5

TERMINAL = r"C:\Program Files\MetaTrader 5\terminal64.exe"
LOGIN    = 436771046
SYMBOL   = "BTCUSDm"
POLL     = 5                      # seconds
# Two different source timeframes, on purpose.
#   breakout  M5 - the user's rule is about one candle closing outside the
#             previous candle's range, and on M1 that is mostly spread noise.
#   renko     M1 - a brick is decided by DISTANCE, so the source timeframe only
#             controls how often we CHECK. Checking every minute instead of
#             every five cuts the worst-case lag 5x without any of the costs of
#             switching to wicks: no bricks from spikes that snap straight back,
#             and no guessing which of a candle's high/low came first.
SRC_TF_BRK   = mt5.TIMEFRAME_M5
SRC_TF_RENKO = mt5.TIMEFRAME_M1
# Fixed anchor date. Everything is rebuilt from this same bar every cycle, so a
# brick that has printed keeps the same boundaries forever. Move it and the whole
# series re-derives - which is fine, but do it deliberately, not by accident.
ANCHOR_FROM = datetime(2026, 7, 17)
BRICK    = 50.0
REVERSAL = 2                      # bricks of counter-move needed to turn; 2 = classic

COMMON    = os.path.join(os.environ["APPDATA"], "MetaQuotes", "Terminal", "Common", "Files")
OUT_BRK   = os.path.join(COMMON, "kl_custom_bars.csv")
OUT_RENKO = os.path.join(COMMON, "kl_renko_bars.csv")
ALIVE     = os.path.join(COMMON, "kl_feed_alive.json")

HDR = ["time", "open", "high", "low", "close", "tick_volume", "spread", "real_volume"]


def connect():
    if not mt5.initialize(path=TERMINAL):
        raise SystemExit(f"initialize failed: {mt5.last_error()}")
    a = mt5.account_info()
    if a is None or a.login != LOGIN:
        mt5.shutdown()
        raise SystemExit(f"WRONG ACCOUNT {a.login if a else None}, expected {LOGIN}")


def write_atomic(path, rows):
    """Write via a temp file and swap it in, so a reader never sees half a file.

    The swap can fail with WinError 5 when the MQL5 service happens to have the
    target open: Windows refuses to replace a file another process is reading.
    That is a race, not a fault, and the next attempt a few milliseconds later
    almost always wins - so retry briefly and give up quietly if not, because the
    next poll will rewrite it anyway. Observed live 2026-08-03.
    """
    tmp = path + ".tmp"
    with open(tmp, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(HDR)
        w.writerows(rows)
    for attempt in range(10):
        try:
            os.replace(tmp, path)
            return True
        except PermissionError:
            time.sleep(0.05)
    return False                   # skipped this cycle; the next one retries


def breakout_rows(rates):
    """Closed source bars whose close broke the previous bar's range."""
    out = []
    for i, r in enumerate(rates):
        if i == 0 or r["close"] > rates[i - 1]["high"] or r["close"] < rates[i - 1]["low"]:
            out.append([int(r["time"]), r["open"], r["high"], r["low"], r["close"],
                        int(r["tick_volume"]), int(r["spread"]), 0])
    return out


def renko_rows(rates, last_price, brick, reversal=REVERSAL):
    """Renko bricks off closed-bar closes, extended with the live price.

    REVERSAL is the classic fix for bricks stacking at the same level. With
    reversal=1 price only has to travel one brick to flip direction, so a market
    ticking either side of a boundary prints up-down-up-down over the same two
    prices - visual noise with no information in it. With reversal=2 a change of
    direction needs TWO bricks of movement, so that oscillation never prints.
    Measured on this data: 601 direction flips at 1x, 320 at 2x - 47% fewer.

    On a reversal the new brick opens at the previous brick's OPEN rather than
    its close. That is the standard construction and it is what produces Renko's
    offset staircase at turning points.

    Each brick gets its source bar's time plus a one-second offset per brick in
    that bar: MT5 silently drops duplicate timestamps, so bricks completing
    together would vanish without this.
    """
    out = []
    anchor_open = anchor_close = float(rates[0]["open"])
    d = 0                                   # last direction: +1 up, -1 down, 0 none

    def emit(t, n, up):
        nonlocal anchor_open, anchor_close, d
        reversing = (d == 1 and not up) or (d == -1 and up)
        base = anchor_open if reversing else anchor_close
        cl = base + brick if up else base - brick
        out.append([t + n, base, max(base, cl), min(base, cl), cl, 0, 0, 0])
        anchor_open, anchor_close, d = base, cl, (1 if up else -1)

    def step(px, t, n):
        """Emit every brick this price completes. Returns bricks emitted."""
        made = 0
        while True:
            up_gap = (anchor_open if d == -1 else anchor_close) + brick * (reversal if d == -1 else 1)
            dn_gap = (anchor_open if d == 1 else anchor_close) - brick * (reversal if d == 1 else 1)
            if px >= up_gap:
                emit(t, n + made, True)
            elif px <= dn_gap:
                emit(t, n + made, False)
            else:
                return made
            made += 1

    for r in rates:
        step(float(r["close"]), int(r["time"]), 0)

    # live tail: bricks completed since the last closed bar
    if last_price is not None and out:
        step(float(last_price), int(out[-1][0]) + 1, 0)
    return out


def main():
    connect()
    print(f"live feed up: {SYMBOL} -> breakout + renko({BRICK:g}pt), poll {POLL}s", flush=True)
    last_counts = (0, 0)
    while True:
        try:
            # FIXED start, never a rolling window. copy_rates_from_pos slides its
            # window forward as time passes, which moves rates[0] and therefore
            # moves the Renko ANCHOR - every brick boundary then shifts and the
            # whole history silently redraws. Observed 2026-08-03: the brick count
            # fell 1430 -> 1415 with no new bricks, which is that bug.
            now = datetime.utcnow()
            r_brk   = mt5.copy_rates_range(SYMBOL, SRC_TF_BRK,   ANCHOR_FROM, now)
            r_renko = mt5.copy_rates_range(SYMBOL, SRC_TF_RENKO, ANCHOR_FROM, now)
            tick = mt5.symbol_info_tick(SYMBOL)
            if r_brk is None or not len(r_brk) or r_renko is None or not len(r_renko):
                time.sleep(POLL); continue

            # Drop the still-forming last bar of each: its close is not final, and
            # both rules key off the close, so acting early would repaint.
            closed  = r_brk[:-1]   if len(r_brk) > 1   else r_brk
            closed_r = r_renko[:-1] if len(r_renko) > 1 else r_renko

            brk = breakout_rows(closed)
            # No provisional brick from the live bid. A brick built from the bid
            # can fail to reappear once the bar actually closes below the
            # threshold, and MT5 has no way to retract one already pushed - so it
            # would sit there permanently as a brick that never really happened.
            # Bricks confirm on closes only; the KLRenkoLive indicator is what
            # shows live movement between them.
            rnk = renko_rows(closed_r, None, BRICK)

            write_atomic(OUT_BRK, brk)
            write_atomic(OUT_RENKO, rnk)

            with open(ALIVE, "w", encoding="utf-8") as f:
                f.write('{"alive_utc": "%s", "breakout": %d, "renko": %d, "bid": %s}'
                        % (datetime.utcnow().isoformat(), len(brk), len(rnk),
                           tick.bid if tick else "null"))

            if (len(brk), len(rnk)) != last_counts:
                print(f"{datetime.now():%H:%M:%S}  breakout {len(brk)}  renko {len(rnk)}"
                      f"  bid {tick.bid if tick else '?'}", flush=True)
                last_counts = (len(brk), len(rnk))
        except Exception as e:
            print(f"{datetime.now():%H:%M:%S}  ERROR {type(e).__name__}: {e}", flush=True)
        time.sleep(POLL)


if __name__ == "__main__":
    main()
