"""Record crypto derivatives data that MT5 does not carry.

Every entry idea tested on 2026-07-31 used BTC's own OHLC and came back empty -
twelve of them. The one direction not exhausted is information the price chart
does not contain: how much leverage is in the system, what it costs to hold, and
which way the crowd is positioned.

That data exists free, but only shallowly. Binance and Bybit return 451/403 from
this server (geo-blocked). OKX is reachable and its 5-minute endpoints hold just
2 DAYS of history, which is far too little to test - at ~700 observations the
error bar is wider than any effect measured all night.

So the fix is time, not cleverness: capture it now at 5-minute granularity and in
a month there are ~8,600 observations instead of 700. This process is the only
thing standing between "untestable" and "testable" on that idea.

WHAT IS CAPTURED (OKX, BTC contracts, plus Deribit funding as a second source)
  open_interest    total contracts outstanding - how much leverage exists
  contract_volume  turnover alongside it
  long_short       ratio of accounts long vs short - crowd positioning
  taker_buy/sell   aggressive buying vs selling - who is hitting the market
  funding_okx      cost of holding a long, 8-hourly
  funding_deribit  independent second read on the same thing

DESIGN NOTES
  * Never crashes on a network error. A recorder that dies silently is worse than
    no recorder, and this one has to survive unattended for weeks.
  * Deduplicates on the API's own timestamp, so a restart or an overlapping poll
    cannot double-write rows - the price recorder was corrupted that way once.
  * Appends only. The file is the asset; nothing here rewrites history.
"""
import csv
import json
import os
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "data", "derivs_BTC.csv")
LIQ = os.path.join(HERE, "data", "liquidations_BTC.csv")
ALIVE = os.path.join(HERE, "data", "derivs_alive.json")
POLL = 300                      # 5 minutes, matching the finest OKX granularity
LIQ_POLL = 60                   # see LIQUIDATIONS below - cascades outrun a 5-min poll
UA = {"User-Agent": "Mozilla/5.0 (research)"}

COLS = ["ts_utc", "ts_ms", "open_interest", "contract_volume", "long_short",
        "taker_buy", "taker_sell", "funding_okx", "funding_deribit"]

# LIQUIDATIONS - added 2026-08-01, in their own file and on their own clock.
#
# Two reasons they are not columns in derivs_BTC.csv: they are events rather than a
# value sampled every five minutes, and there can be dozens in a single minute or none
# for an hour. Forcing them into the wide row would either lose events or pad the file
# with blanks.
#
# They are polled every 60s rather than every 300s because the endpoint returns at most
# 100 recent events. Liquidations matter precisely during cascades - which is exactly
# when more than 100 can occur inside five minutes, so a slow poll would silently drop
# the observations the whole dataset exists to capture.
#
# This is the field the earlier research could not test at all: forced selling is
# non-informational price pressure, the cleanest available candidate for a move that
# must revert. Recording starts now so the clock is already running when there is
# enough of it to analyse.
LIQ_COLS = ["ts_utc", "ts_ms", "instId", "side", "posSide", "sz", "bkPx"]


def get(url, timeout=20):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def okx_latest(path, ncols):
    """Newest row of an OKX rubik series. Returns (ts_ms, values) or None."""
    try:
        d = get("https://www.okx.com" + path)
        if str(d.get("code")) != "0":
            return None
        rows = d.get("data") or []
        if not rows:
            return None
        row = max(rows, key=lambda r: int(r[0]))       # newest by timestamp
        return int(row[0]), [float(x) for x in row[1:1 + ncols]]
    except Exception:
        return None


def funding_okx():
    try:
        d = get("https://www.okx.com/api/v5/public/funding-rate?instId=BTC-USDT-SWAP")
        if str(d.get("code")) != "0" or not d.get("data"):
            return None
        return float(d["data"][0]["fundingRate"])
    except Exception:
        return None


def funding_deribit():
    try:
        d = get("https://www.deribit.com/api/v2/public/get_funding_rate_value"
                "?instrument_name=BTC-PERPETUAL"
                "&start_timestamp=%d&end_timestamp=%d"
                % (int(time.time() * 1000) - 3600000, int(time.time() * 1000)))
        return float(d.get("result")) if d.get("result") is not None else None
    except Exception:
        return None


def liquidations():
    """Recent forced liquidations on BTC-USDT swaps, flattened to one row per event."""
    out = []
    try:
        d = get("https://www.okx.com/api/v5/public/liquidation-orders"
                "?instType=SWAP&uly=BTC-USDT&state=filled&limit=100")
        if str(d.get("code")) != "0":
            return out
        for inst in d.get("data") or []:
            iid = inst.get("instId") or inst.get("uly") or "BTC-USDT-SWAP"
            for ev in inst.get("details") or []:
                try:
                    ts = int(ev.get("ts") or ev.get("time"))
                except (TypeError, ValueError):
                    continue
                out.append([
                    datetime.fromtimestamp(ts / 1000, timezone.utc).isoformat(timespec="milliseconds"),
                    ts, iid, ev.get("side", ""), ev.get("posSide", ""),
                    ev.get("sz", ""), ev.get("bkPx", "")])
    except Exception:
        pass
    return out


def seen_liquidations():
    """Composite keys already stored, so repeated polls cannot duplicate an event."""
    if not os.path.exists(LIQ):
        return set()
    try:
        with open(LIQ, newline="", encoding="utf-8") as f:
            return {"%s|%s|%s|%s" % (r.get("ts_ms"), r.get("side"), r.get("sz"),
                                     r.get("bkPx")) for r in csv.DictReader(f)}
    except Exception:
        return set()


def seen_timestamps():
    """Existing ts_ms values, so a restart cannot duplicate rows."""
    if not os.path.exists(OUT):
        return set()
    try:
        with open(OUT, newline="", encoding="utf-8") as f:
            return {r["ts_ms"] for r in csv.DictReader(f) if r.get("ts_ms")}
    except Exception:
        return set()


def main():
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    if not os.path.exists(OUT) or os.path.getsize(OUT) == 0:
        with open(OUT, "w", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow(COLS)
    if not os.path.exists(LIQ) or os.path.getsize(LIQ) == 0:
        with open(LIQ, "w", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow(LIQ_COLS)
    seen = seen_timestamps()
    liq_seen = seen_liquidations()
    print("derivs recorder up. %d derivs rows, %d liquidations already stored. "
          "derivs every %ds, liquidations every %ds"
          % (len(seen), len(liq_seen), POLL, LIQ_POLL), flush=True)

    liq_total = len(liq_seen)
    next_derivs = 0.0
    while True:
        try:
            # ---- liquidations, on the fast clock ----
            fresh = 0
            for row in liquidations():
                k = "%s|%s|%s|%s" % (row[1], row[3], row[5], row[6])
                if k in liq_seen:
                    continue
                liq_seen.add(k)
                with open(LIQ, "a", newline="", encoding="utf-8") as f:
                    csv.writer(f).writerow(row)
                fresh += 1
            if fresh:
                liq_total += fresh
                if liq_total % 50 < fresh:          # occasional progress note only
                    print("%s  %d liquidations stored"
                          % (datetime.now(timezone.utc).isoformat(timespec="seconds"),
                             liq_total), flush=True)
            # keep the dedup set from growing without bound over a long run
            if len(liq_seen) > 200000:
                liq_seen = set(list(liq_seen)[-100000:])

            if time.time() < next_derivs:
                with open(ALIVE, "w", encoding="utf-8") as f:
                    json.dump({"alive_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                               "rows": len(seen), "liquidations": liq_total}, f)
                time.sleep(LIQ_POLL)
                continue
            next_derivs = time.time() + POLL
            oi = okx_latest("/api/v5/rubik/stat/contracts/open-interest-volume?ccy=BTC&period=5m", 2)
            ls = okx_latest("/api/v5/rubik/stat/contracts/long-short-account-ratio?ccy=BTC&period=5m", 1)
            tv = okx_latest("/api/v5/rubik/stat/taker-volume?ccy=BTC&instType=CONTRACTS&period=5m", 2)

            if oi:
                ts_ms, (open_int, vol) = oi
                key = str(ts_ms)
                if key not in seen:
                    row = [datetime.fromtimestamp(ts_ms / 1000, timezone.utc).isoformat(timespec="seconds"),
                           key, open_int, vol,
                           ls[1][0] if ls else "",
                           tv[1][0] if tv else "", tv[1][1] if tv else "",
                           funding_okx() or "", funding_deribit() or ""]
                    with open(OUT, "a", newline="", encoding="utf-8") as f:
                        csv.writer(f).writerow(row)
                    seen.add(key)
                    if len(seen) % 12 == 0:            # hourly-ish progress note
                        print("%s  %d rows stored" % (row[0], len(seen)), flush=True)

            with open(ALIVE, "w", encoding="utf-8") as f:
                json.dump({"alive_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                           "rows": len(seen), "liquidations": liq_total}, f)
        except Exception as e:
            # never die: an unattended recorder that stops is worse than no recorder
            try:
                print("poll error %s: %s" % (type(e).__name__, str(e)[:90]), flush=True)
            except Exception:
                pass
        time.sleep(LIQ_POLL)


if __name__ == "__main__":
    main()
