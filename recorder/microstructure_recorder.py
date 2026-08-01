"""Record the two things that need high-frequency capture, side by side.

Twelve entry ideas built on BTC's own OHLC came back empty. Both datasets here are
information that is NOT in that feed, and neither can be backfilled - the history
only exists if something is writing it down now.

1. BROKER LAG.  Exness quotes BTCUSDm themselves; the price is DERIVED from real
   exchange prices rather than being the market. If their feed trails the real
   market even briefly, that is exploitable without predicting anything - it is a
   microstructure question, not a forecasting one. Measuring it needs both feeds
   sampled together, close in time, which is exactly what this does.

   Be clear about the prior: a systematic, persistent lag would be arbitraged and
   the broker would fix it. What is plausible is transient dislocation during fast
   moves. That is why the file records the raw pair on every tick rather than a
   summary - the interesting moments are rare and would be averaged away.

2. ORDER BOOK IMBALANCE.  How much size rests on the bid versus the ask at the top
   of the real exchange's book. A genuine short-horizon predictor in most markets,
   and completely absent from an OHLC feed. OKX serves the live book but NO
   history, so again the only route is to start writing.

DESIGN
  * 2-second poll: fast enough that a lag of a few seconds is visible, slow enough
    to stay well inside OKX rate limits over weeks of running.
  * MT5 and OKX are read as close together as possible and BOTH timestamps are
    stored, so the sampling gap itself can be measured rather than assumed.
  * Never dies on a network error - it has to survive unattended for weeks.
  * Appends only. Rotates daily so no single file becomes unwieldy.
"""
import csv
import json
import os
import time
import urllib.request
from datetime import datetime, timezone

import MetaTrader5 as mt5

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
ALIVE = os.path.join(DATA, "micro_alive.json")
TERMINAL = r"C:\Program Files\MetaTrader 5\terminal64.exe"
SYM = "BTCUSDm"
POLL = 2.0
UA = {"User-Agent": "Mozilla/5.0 (research)"}

COLS = ["t_local", "mt5_ms", "mt5_bid", "mt5_ask",
        "okx_ms", "okx_last", "okx_bid", "okx_ask",
        "bid_sz1", "ask_sz1", "bid_sz5", "ask_sz5", "fetch_ms"]


def get(url, timeout=6):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def okx_book():
    """Top-of-book plus 5-level depth. Returns dict or None; never raises."""
    try:
        d = get("https://www.okx.com/api/v5/market/books?instId=BTC-USDT&sz=5")
        if str(d.get("code")) != "0" or not d.get("data"):
            return None
        b = d["data"][0]
        bids, asks = b.get("bids", []), b.get("asks", [])
        if not bids or not asks:
            return None
        return {
            "ts": int(b["ts"]),
            "bid": float(bids[0][0]), "ask": float(asks[0][0]),
            "bid_sz1": float(bids[0][1]), "ask_sz1": float(asks[0][1]),
            "bid_sz5": sum(float(x[1]) for x in bids[:5]),
            "ask_sz5": sum(float(x[1]) for x in asks[:5]),
        }
    except Exception:
        return None


def connect():
    """Pin the terminal AND verify the symbol - two MT5 instances run on this box."""
    while True:
        if mt5.initialize(path=TERMINAL) and mt5.symbol_select(SYM, True):
            return
        time.sleep(10)


def path_for(day):
    return os.path.join(DATA, "micro_%s_%s.csv" % (SYM, day))


def main():
    os.makedirs(DATA, exist_ok=True)
    connect()
    print("microstructure recorder up: %s vs OKX BTC-USDT, %.0fs poll" % (SYM, POLL), flush=True)

    day = None
    fh = None
    written = 0
    try:
        while True:
            try:
                t0 = time.time()
                book = okx_book()
                tick = mt5.symbol_info_tick(SYM)
                fetch_ms = (time.time() - t0) * 1000

                if tick is None:
                    mt5.shutdown(); connect(); time.sleep(POLL); continue

                today = datetime.now(timezone.utc).strftime("%Y%m%d")
                if today != day:
                    if fh:
                        fh.close()
                    p = path_for(today)
                    new = not os.path.exists(p) or os.path.getsize(p) == 0
                    fh = open(p, "a", newline="", encoding="utf-8")
                    w = csv.writer(fh)
                    if new:
                        w.writerow(COLS)
                    day = today

                mid_okx = (book["bid"] + book["ask"]) / 2 if book else ""
                csv.writer(fh).writerow([
                    datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
                    int(tick.time_msc), tick.bid, tick.ask,
                    book["ts"] if book else "", mid_okx,
                    book["bid"] if book else "", book["ask"] if book else "",
                    book["bid_sz1"] if book else "", book["ask_sz1"] if book else "",
                    book["bid_sz5"] if book else "", book["ask_sz5"] if book else "",
                    round(fetch_ms, 1),
                ])
                fh.flush()
                written += 1

                if written % 300 == 0:                       # ~every 10 minutes
                    lag = ""
                    if book:
                        lag = "  mt5-okx price gap %+.2f" % (
                            (tick.bid + tick.ask) / 2 - mid_okx)
                    print("%s  %d rows%s" % (datetime.now().strftime("%H:%M:%S"), written, lag),
                          flush=True)

                with open(ALIVE, "w", encoding="utf-8") as f:
                    json.dump({"alive_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                               "rows_this_run": written, "file": path_for(day)}, f)
            except Exception as e:
                try:
                    print("poll error %s: %s" % (type(e).__name__, str(e)[:90]), flush=True)
                except Exception:
                    pass
            time.sleep(POLL)
    finally:
        if fh:
            fh.close()
        mt5.shutdown()


if __name__ == "__main__":
    main()
