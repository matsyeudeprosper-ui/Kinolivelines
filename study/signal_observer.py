"""signal_observer.py - record EVERY renko reversal, including rejected ones.

The point (GPT review, 2026-08-07): a journal that only contains opened trades
cannot say whether a filter correctly avoided bad trades. So this records every
reversal the brick series produces, whether or not any bot acted on it, plus
the exact context at signal time - and fills in what happened NEXT (MFE/MAE at
1h and 4h) once that future has occurred.

The "50-point shadow rule" is GPT's candidate entry filter: accept a signal
only if price has travelled <= 50 pts beyond the reversal brick's close by the
time the signal is known. It gates NOTHING here - the accepted flag is just
another column, so accepted and rejected populations can be compared on equal
footing later.

READ ONLY. No order_send anywhere. Separate CSV per run direction of enquiry:
one row per reversal, updated in place when horizons mature.
"""
import csv
import json
import os
import sys
import time
from datetime import datetime, timedelta

import numpy as np
import MetaTrader5 as mt5

TERMINAL = r"C:\Program Files\MetaTrader 5\terminal64.exe"   # demo: same symbol feed
LOGIN = 436771046
SYMBOL = "BTCUSDm"
BRICK, REVERSAL = 50.0, 2
ANCHOR = datetime(2026, 7, 17)          # the bots' anchor - same brick series
FILTER_PTS = 50.0                        # GPT's shadow acceptance rule
POLL = 20
HORIZONS = (60, 240)                     # minutes; MFE/MAE filled in later

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "signal_observer.csv")
STATE = os.path.join(HERE, "signal_observer_state.json")
ALIVE = os.path.join(HERE, "signal_observer_alive.json")
LOG = os.path.join(HERE, "signal_observer.log")

COLS = ["signal_utc", "known_utc", "age_seconds", "side",
        "rev_brick_close", "bid", "ask", "spread",
        "dist_beyond_brick", "accepted_50pt", "hh_ll_pass", "d4_pass",
        "prev_run_bricks", "mins_since_prev_reversal",
        "atr_m1_14", "session",
        "mfe60_pts", "mae60_pts", "mfe240_pts", "mae240_pts"]


def say(m):
    line = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {m}"
    print(line, flush=True)
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def session_of(h):
    return ("asia" if h < 7 else "europe" if h < 13 else "us" if h < 21 else "late")


def bricks_and_reversals(rates):
    """The exact brick loop the bots and engine use, on CLOSED bars, returning
    every brick (time, dir) so run lengths and reversal gaps are computable."""
    o = rates["open"].astype(float)
    c = rates["close"].astype(float)
    tm = rates["time"].astype(np.int64)
    ao = ac = float(o[0])
    d = 0
    out = []
    for j in range(len(c)):
        ci = c[j]
        while True:
            up = (ao if d == -1 else ac) + BRICK * (REVERSAL if d == -1 else 1)
            dn = (ao if d == 1 else ac) - BRICK * (REVERSAL if d == 1 else 1)
            if ci >= up:
                base = ao if d == -1 else ac
                ao, ac, d = base, base + BRICK, 1
            elif ci <= dn:
                base = ao if d == 1 else ac
                ao, ac, d = base, base - BRICK, -1
            else:
                break
            out.append((int(tm[j]), d, ac))
    revs = []
    for i in range(1, len(out)):
        if out[i][1] != out[i - 1][1]:
            run = 1
            k = i - 2
            while k >= 0 and out[k][1] == out[i - 1][1]:
                run += 1
                k -= 1
            prev_rev_t = revs[-1]["time"] if revs else None
            revs.append(dict(time=out[i][0], dir=out[i][1], close=out[i][2],
                             prev_run=run,
                             mins_prev=((out[i][0] - prev_rev_t) / 60.0
                                        if prev_rev_t else None)))
    return revs


def atr14(rates):
    h = rates["high"].astype(float)
    l = rates["low"].astype(float)
    c = rates["close"].astype(float)
    pc = np.concatenate([[c[0]], c[:-1]])
    tr = np.maximum(h - l, np.maximum(np.abs(h - pc), np.abs(l - pc)))
    a = np.full(len(tr), np.nan)
    if len(tr) > 14:
        a[13] = tr[:14].mean()
        for i in range(14, len(tr)):
            a[i] = (a[i - 1] * 13 + tr[i]) / 14.0
    return a


def d4_pass_of(side, hi_, lo_, j):
    """SPEC_HHLL_VARIANTS D4, the validation near-miss on M1 (missed the 2SE
    bar by $1): last two CONFIRMED 5-bar swing lows rising -> BUY pass; last
    two confirmed swing highs falling -> SELL pass. Strict fractals (unique
    extreme in the 5-bar window); pivot i is known only from bar i+2, so only
    i <= j-2 counts - same no-lookahead rule as the backtest."""
    arr = lo_ if side == "BUY" else hi_
    vals = []
    i = j - 2
    stop = max(2, j - 3000)
    while i >= stop and len(vals) < 2:
        w = arr[i - 2:i + 3]
        if side == "BUY":
            if arr[i] == w.min() and (w == arr[i]).sum() == 1:
                vals.append(arr[i])
        else:
            if arr[i] == w.max() and (w == arr[i]).sum() == 1:
                vals.append(arr[i])
        i -= 1
    if len(vals) < 2:
        return ""
    v1, v0 = vals[0], vals[1]          # vals[0] = most recent pivot
    if side == "BUY":
        return "yes" if v1 > v0 else "no"
    return "yes" if v1 < v0 else "no"


def load_rows():
    if not os.path.exists(OUT):
        return []
    with open(OUT, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def write_rows(rows):
    tmp = OUT + ".tmp"
    with open(tmp, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLS)
        w.writeheader()
        w.writerows(rows)
    os.replace(tmp, OUT)


def fill_horizons(rows, rates):
    """MFE/MAE in the SIGNAL direction, from the recorded entry-side price,
    over each horizon - only once the horizon has fully elapsed. Filled from
    M1 highs/lows, so the same one-bar caveat as the journal applies."""
    tm = rates["time"].astype(np.int64)
    hi = rates["high"].astype(float)
    lo = rates["low"].astype(float)
    now = int(datetime.utcnow().timestamp())
    changed = 0
    for r in rows:
        sig = int(datetime.strptime(r["signal_utc"], "%Y-%m-%d %H:%M:%S").timestamp())
        px = float(r["ask"] if r["side"] == "BUY" else r["bid"])
        for mins in HORIZONS:
            key = f"mfe{mins}_pts"
            if r[key] != "":
                continue
            if now < sig + mins * 60 + 120:
                continue                      # future not fully known yet
            a = int(np.searchsorted(tm, sig, side="right"))
            b = int(np.searchsorted(tm, sig + mins * 60, side="right"))
            if b <= a:
                continue
            if r["side"] == "BUY":
                mfe, mae = float(np.max(hi[a:b]) - px), float(px - np.min(lo[a:b]))
            else:
                mfe, mae = float(px - np.min(lo[a:b])), float(np.max(hi[a:b]) - px)
            r[key] = f"{mfe:.2f}"
            r[f"mae{mins}_pts"] = f"{mae:.2f}"
            changed += 1
    return changed


def main():
    say(f"signal observer up | every reversal recorded, acted on or not | "
        f"shadow filter {FILTER_PTS:.0f} pts | POLL {POLL}s | READ ONLY")
    try:
        st = json.load(open(STATE))
    except Exception:
        st = {"last_rev": 0}
    fails = 0
    forward_only_pending = (st["last_rev"] == 0)
    # FORWARD-ONLY. The first run once backfilled 404 historical reversals
    # stamped with the CURRENT bid/ask - a signal's context exists only at
    # signal time, so those rows were junk. On a fresh state, skip everything
    # that already happened and record from now.
    while True:
        try:
            if not mt5.initialize(path=TERMINAL):
                fails += 1
                time.sleep(POLL)
                continue
            acc = mt5.account_info()
            if acc is None or acc.login != LOGIN:
                mt5.shutdown()
                fails += 1
                time.sleep(POLL)
                continue
            rates = mt5.copy_rates_range(SYMBOL, mt5.TIMEFRAME_M1, ANCHOR,
                                         datetime.utcnow())
            tick = mt5.symbol_info_tick(SYMBOL)
            mt5.shutdown()
            if rates is None or len(rates) < 20 or tick is None:
                fails += 1
                time.sleep(POLL)
                continue
            fails = 0

            closed = rates[:-1]                 # forming bar excluded, as the bots do
            revs = bricks_and_reversals(closed)
            if forward_only_pending and revs:
                st["last_rev"] = revs[-1]["time"]
                json.dump(st, open(STATE, "w"))
                forward_only_pending = False
                say(f"fresh state: skipping {len(revs)} historical reversals, "
                    f"recording forward from here")
            atr = atr14(closed)
            tmc = closed["time"].astype(np.int64)
            rows = load_rows()
            existing = {r["signal_utc"] for r in rows}
            now = datetime.utcnow()

            for rv in revs:
                if rv["time"] <= st["last_rev"]:
                    continue
                sig_utc = datetime.utcfromtimestamp(rv["time"]).strftime("%Y-%m-%d %H:%M:%S")
                if sig_utc in existing:
                    continue
                side = "BUY" if rv["dir"] == 1 else "SELL"
                px = tick.ask if side == "BUY" else tick.bid
                beyond = (px - rv["close"]) if side == "BUY" else (rv["close"] - px)
                age = (now - datetime.utcfromtimestamp(rv["time"])).total_seconds()
                j = int(np.searchsorted(tmc, rv["time"], side="right")) - 1
                a_ = atr[j] if 0 <= j < len(atr) and not np.isnan(atr[j]) else ""
                # SPEC_HHLL_ENTRY, recorded on every live signal: do the last 3
                # closed M1 bars agree with the trade's direction?
                hh = ""
                if j >= 2:
                    hi_, lo_ = closed["high"], closed["low"]
                    if side == "BUY":
                        hh = "yes" if hi_[j] > hi_[j-1] > hi_[j-2] else "no"
                    else:
                        hh = "yes" if lo_[j] < lo_[j-1] < lo_[j-2] else "no"
                rows.append({
                    "signal_utc": sig_utc,
                    "known_utc": now.strftime("%Y-%m-%d %H:%M:%S"),
                    "age_seconds": f"{age:.0f}",
                    "side": side,
                    "rev_brick_close": f"{rv['close']:.2f}",
                    "bid": f"{tick.bid:.2f}", "ask": f"{tick.ask:.2f}",
                    "spread": f"{tick.ask - tick.bid:.2f}",
                    "dist_beyond_brick": f"{beyond:.2f}",
                    "accepted_50pt": "yes" if beyond <= FILTER_PTS else "no",
                    "hh_ll_pass": hh,
                    "d4_pass": (d4_pass_of(side, closed["high"].astype(float),
                                           closed["low"].astype(float), j)
                                if j >= 4 else ""),
                    "prev_run_bricks": rv["prev_run"],
                    "mins_since_prev_reversal": (f"{rv['mins_prev']:.1f}"
                                                 if rv["mins_prev"] else ""),
                    "atr_m1_14": f"{a_:.2f}" if a_ != "" else "",
                    "session": session_of(now.hour),
                    "mfe60_pts": "", "mae60_pts": "",
                    "mfe240_pts": "", "mae240_pts": "",
                })
                st["last_rev"] = rv["time"]
                say(f"reversal {side} @ {rv['close']:.2f} | beyond {beyond:+.0f} pts "
                    f"| age {age:.0f}s | 50pt filter: "
                    f"{'ACCEPT' if beyond <= FILTER_PTS else 'reject'}")

            filled = fill_horizons(rows, closed)
            write_rows(rows)
            json.dump(st, open(STATE, "w"))
            json.dump(dict(alive_utc=datetime.utcnow().isoformat(),
                           rows=len(rows), filled_this_pass=filled),
                      open(ALIVE, "w"))
        except Exception as e:
            say(f"ERROR {type(e).__name__}: {e}")
            try:
                mt5.shutdown()
            except Exception:
                pass
            fails += 1
        if fails >= 30:
            say("30 consecutive failures - exiting for the watchdog")
            sys.exit(1)
        time.sleep(POLL)


if __name__ == "__main__":
    main()
