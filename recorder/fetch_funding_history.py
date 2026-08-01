"""Download 6.6 years of hourly perpetual-funding history and matching candles.

The recorders started 2026-07-30 and need thirty days before they say anything. This
does not - Deribit serves the whole history of what longs paid shorts, hour by hour,
back to 2020. That is the single deepest participant-behaviour series reachable from
here without a paid feed.

WHY FUNDING IS THE RIGHT FIRST TEST of "is one side forced or trapped":
A perpetual swap has no expiry, so an hourly payment keeps it pinned to spot. When
funding is strongly positive, longs are paying shorts to stay long - the crowd is on
the long side and bleeding for it. Strongly negative, the reverse. Unlike anything
derived from candles, this is not a transformation of price: it is a direct readout
of what one side is willing to pay, which is exactly the question the OHLC work could
not answer.

Two instruments, because a finding on one is a coincidence:
    BTC-PERPETUAL   the one we actually trade a proxy of
    ETH-PERPETUAL   the independent replication

Everything is cached to CSV so the tests never re-hit the network.
"""
import urllib.request, json, time, csv, os, sys

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
INSTRUMENTS = ["BTC-PERPETUAL", "ETH-PERPETUAL"]
CHUNK_D = 30            # funding: 30-day windows
CANDLE_D = 55           # candles: ~1440 hourly bars per request


def get(url, tries=4, timeout=30):
    last = None
    for k in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode())
        except Exception as e:
            last = e
            time.sleep(1.5 * (k + 1))
    raise last


def day(ms):
    return time.strftime("%Y-%m-%d", time.gmtime(ms / 1000))


def fetch_funding(inst):
    """Walk backwards in 30-day windows until the exchange runs out of history."""
    end, rows, empty = int(time.time() * 1000), {}, 0
    for _ in range(90):
        start = end - CHUNK_D * 86400000
        d = get("https://www.deribit.com/api/v2/public/get_funding_rate_history"
                "?instrument_name=%s&start_timestamp=%d&end_timestamp=%d"
                % (inst, start, end)).get("result") or []
        if not d:
            empty += 1
            if empty >= 2:
                break
        else:
            empty = 0
            for r in d:
                rows[r["timestamp"]] = r
        end = start
        sys.stdout.write("\r    funding %-14s %6d rows, back to %s" % (inst, len(rows), day(end)))
        sys.stdout.flush()
        time.sleep(0.08)
    print()
    return rows


def fetch_candles(inst, oldest_ms):
    """Hourly OHLC back to wherever the funding history starts."""
    end, out = int(time.time() * 1000), {}
    while end > oldest_ms:
        start = end - CANDLE_D * 86400000
        r = get("https://www.deribit.com/api/v2/public/get_tradingview_chart_data"
                "?instrument_name=%s&start_timestamp=%d&end_timestamp=%d&resolution=60"
                % (inst, start, end)).get("result") or {}
        ticks = r.get("ticks") or []
        if not ticks:
            break
        for i, t in enumerate(ticks):
            out[t] = (r["open"][i], r["high"][i], r["low"][i], r["close"][i], r["volume"][i])
        end = start
        sys.stdout.write("\r    candles %-14s %6d bars, back to %s" % (inst, len(out), day(end)))
        sys.stdout.flush()
        time.sleep(0.08)
    print()
    return out


os.makedirs(DATA, exist_ok=True)
for inst in INSTRUMENTS:
    print("%s" % inst)
    fund = fetch_funding(inst)
    if not fund:
        print("    no funding history - skipped\n"); continue
    oldest = min(fund)
    cand = fetch_candles(inst, oldest)

    # Join on the hour. Funding stamps land on the hour, so an exact key match works
    # for the vast majority; anything unmatched is dropped rather than interpolated.
    path = os.path.join(DATA, "hist_%s.csv" % inst.replace("-", "_"))
    keys = sorted(set(fund) & set(cand))
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["ts", "utc", "open", "high", "low", "close", "volume",
                    "interest_1h", "interest_8h", "index_price"])
        for k in keys:
            o, h, l, c, v = cand[k]
            f = fund[k]
            w.writerow([k, time.strftime("%Y-%m-%dT%H:%M", time.gmtime(k / 1000)),
                        o, h, l, c, v, f["interest_1h"], f["interest_8h"], f["index_price"]])
    span = (max(keys) - min(keys)) / 86400000 / 365.25 if keys else 0
    print("    -> %s  %d joined hours, %s to %s (%.1f years)\n"
          % (os.path.basename(path), len(keys), day(min(keys)), day(max(keys)), span))
