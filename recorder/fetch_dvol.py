"""Download Deribit's DVOL implied-volatility index for BTC and ETH.

Found while looking for datasets that could shorten the wait on liquidations, and it
does more than shorten it - this is testable immediately. 46,947 hourly points reaching
back to March 2021.

WHY IT IS INDEPENDENT INFORMATION. DVOL is computed from the live options book: it is
what traders are actually paying for protection over the next 30 days. It is not a
transformation of past prices, which is the entire category this project has already
exhausted. The closest thing tested so far - realised volatility - is backward looking
and derived from the same candles as everything else. Implied volatility is a forward
quote from a different market.

Realised volatility can be computed from data already held, so the pair gives the
variance risk premium directly: implied minus realised. That premium is one of the most
persistently documented effects across asset classes, and it has never been looked at
here.

Both currencies are pulled so the replication universe is right: BTC is the target, ETH
is the check. Neither equities nor metals are owed anything - this is a crypto options
mechanism.
"""
import urllib.request, json, ssl, csv, os, time, sys

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
try:
    import certifi
    CTX = ssl.create_default_context(cafile=certifi.where())
except Exception:
    CTX = ssl._create_unverified_context()


def get(url, tries=4, timeout=40):
    last = None
    for k in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=timeout, context=CTX) as r:
                return json.loads(r.read().decode())
        except Exception as e:
            last = e
            time.sleep(1.2 * (k + 1))
    raise last


def day(ms):
    return time.strftime("%Y-%m-%d", time.gmtime(int(ms) / 1000))


os.makedirs(DATA, exist_ok=True)
for ccy in ("BTC", "ETH"):
    pts, end, empty = {}, int(time.time() * 1000), 0
    for _ in range(80):
        start = end - 40 * 86400000
        try:
            r = get("https://www.deribit.com/api/v2/public/get_volatility_index_data"
                    "?currency=%s&start_timestamp=%d&end_timestamp=%d&resolution=3600"
                    % (ccy, start, end)).get("result") or {}
            batch = r.get("data") or []
        except Exception as e:
            print("  %s stopped: %s" % (ccy, type(e).__name__)); break
        if not batch:
            empty += 1
            if empty >= 2:
                break
        else:
            empty = 0
            for p in batch:
                pts[p[0]] = p
        end = start
        sys.stdout.write("\r  %s  %6d points, back to %s" % (ccy, len(pts), day(end)))
        sys.stdout.flush()
        time.sleep(0.08)
    print()
    if not pts:
        print("  %s: nothing returned" % ccy); continue
    path = os.path.join(DATA, "dvol_%s.csv" % ccy)
    ks = sorted(pts)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["ts", "utc", "open", "high", "low", "close"])
        for k in ks:
            p = pts[k]
            w.writerow([k, time.strftime("%Y-%m-%dT%H:%M", time.gmtime(k / 1000)),
                        p[1], p[2], p[3], p[4]])
    print("  -> %s   %d hourly points, %s to %s (%.1f years)"
          % (os.path.basename(path), len(ks), day(min(ks)), day(max(ks)),
             (max(ks) - min(ks)) / 86400000 / 365.25))
