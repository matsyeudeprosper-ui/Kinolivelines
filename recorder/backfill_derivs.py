"""Backfill the derivatives recorder with the 30 days OKX already has.

The recorder started 2026-07-30 from nothing and needs ~30 days before its series are
long enough to test. But OKX publishes 30 days of HOURLY history for the same numbers
it is polling live. Ignoring that throws away a free month.

This writes the history into a separate hourly file rather than into derivs_BTC.csv,
because the two are not the same measurement: the live recorder samples every 5 minutes
and this is hourly. Mixing resolutions in one file would quietly corrupt any test that
assumes a fixed sampling interval.

Series pulled (each at the deepest period OKX will serve):
    open interest + contract volume    the crowding level and how much changed hands
    long/short account ratio           how many accounts sit on each side
    taker buy/sell volume              aggressive buying against aggressive selling -
                                       the closest thing here to order-flow imbalance
    funding rate                       already have 7.3 years from Deribit; this is
                                       the OKX cross-check

Run it again any time - it re-reads the whole window and rewrites the file, so there
are no duplicate rows and no partial-write states to reason about.
"""
import urllib.request, json, time, csv, os

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
OUT = os.path.join(DATA, "derivs_BTC_hourly.csv")
CCY = "BTC"
INST = "BTC-USDT-SWAP"


def get(url, tries=4, timeout=25):
    last = None
    for k in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode())
        except Exception as e:
            last = e
            time.sleep(1.2 * (k + 1))
    raise last


def rubik(path, extra, period="1H"):
    """Rubik stats keyed by ms timestamp -> tuple of the numeric columns.

    The endpoint returns one page (~360 rows) starting at `begin`, NOT everything up
    to now - so a single call with begin=-45d silently returns only the oldest two
    weeks and looks complete. Walk `begin` forward until the pages stop advancing.
    """
    out = {}
    beg = int((time.time() - 45 * 86400) * 1000)
    now = int(time.time() * 1000)
    for _ in range(20):
        url = ("https://www.okx.com/api/v5/rubik/stat/%s?%s&period=%s&begin=%d"
               % (path, extra, period, beg))
        rows = get(url).get("data") or []
        if not rows:
            break
        newest = beg
        for row in rows:
            try:
                ts = int(row[0])
                out[ts] = tuple(float(x) for x in row[1:])
                newest = max(newest, ts)
            except (ValueError, IndexError):
                pass
        if newest <= beg or newest >= now - 3600000:
            break
        beg = newest + 1                      # next page starts after this one
        time.sleep(0.15)
    return out


print("pulling OKX hourly history (deepest the endpoint serves)")
series = {}
for label, path, extra in [
    ("oi_vol",  "contracts/open-interest-volume",      "ccy=%s" % CCY),
    ("ls",      "contracts/long-short-account-ratio",  "ccy=%s" % CCY),
    ("taker",   "taker-volume",                        "ccy=%s&instType=CONTRACTS" % CCY),
]:
    try:
        series[label] = rubik(path, extra)
        ks = series[label]
        if ks:
            print("  %-8s %4d hours  %s -> %s" % (
                label, len(ks),
                time.strftime("%m-%d %H:%M", time.gmtime(min(ks) / 1000)),
                time.strftime("%m-%d %H:%M", time.gmtime(max(ks) / 1000))))
        else:
            print("  %-8s empty" % label)
    except Exception as e:
        print("  %-8s FAIL %s" % (label, type(e).__name__))
        series[label] = {}
    time.sleep(0.2)

# funding is 8-hourly; carry the most recent value forward onto each hour
fund = {}
try:
    for r in get("https://www.okx.com/api/v5/public/funding-rate-history"
                 "?instId=%s&limit=100" % INST).get("data") or []:
        fund[int(r["fundingTime"])] = float(r["fundingRate"])
    print("  %-8s %4d settlements" % ("funding", len(fund)))
except Exception as e:
    print("  %-8s FAIL %s" % ("funding", type(e).__name__))

fkeys = sorted(fund)


def funding_at(ts):
    """Most recent settlement at or before ts - never a future one."""
    lo, hi = 0, len(fkeys) - 1
    best = None
    while lo <= hi:
        m = (lo + hi) // 2
        if fkeys[m] <= ts:
            best = fkeys[m]; lo = m + 1
        else:
            hi = m - 1
    return fund[best] if best is not None else ""


keys = sorted(series.get("oi_vol", {}))
if not keys:
    print("\nno open-interest history returned - nothing written")
else:
    os.makedirs(DATA, exist_ok=True)
    with open(OUT, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["ts_utc", "ts_ms", "open_interest", "contract_volume",
                    "long_short", "taker_buy", "taker_sell", "funding_okx"])
        wrote = 0
        for k in keys:
            oi = series["oi_vol"][k]
            ls = series.get("ls", {}).get(k, ("",))
            tk = series.get("taker", {}).get(k, ("", ""))
            w.writerow([time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime(k / 1000)), k,
                        oi[0], oi[1] if len(oi) > 1 else "",
                        ls[0], tk[0], tk[1] if len(tk) > 1 else "", funding_at(k)])
            wrote += 1
    days = (max(keys) - min(keys)) / 86400000
    print("\n-> %s" % OUT)
    print("   %d hourly rows, %.1f days, %s to %s"
          % (wrote, days,
             time.strftime("%Y-%m-%d", time.gmtime(min(keys) / 1000)),
             time.strftime("%Y-%m-%d", time.gmtime(max(keys) / 1000))))
    have = {k: sum(1 for x in series.get(k, {}) if x in series["oi_vol"]) for k in ("ls", "taker")}
    print("   coverage: long/short %d/%d hours, taker %d/%d hours"
          % (have["ls"], wrote, have["taker"], wrote))
