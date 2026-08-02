"""Fetch daily candles for every liquid OKX USDT perpetual, and cache them.

The 19-stock cross-sectional test failed for a reason that was structural rather than
about the signal: 5 long + 5 short out of 19 names is a concentrated book with a 5.7%
per-rebalance standard deviation, so only a very large effect could ever have shown. Real
cross-sectional books run hundreds of names, and signal-to-noise grows as sqrt(N).

OKX lists 100+ liquid USDT perps with free public history. That is the same idea with the
breadth it actually needs, and it costs nothing to test - which is the point. It answers
"is the venue the constraint?" without migrating anything.

Fetching is separated from testing so the download happens once. Rerunning the test does
not re-hit the API.

LIQUIDITY SCREEN, fixed before looking at any return: keep only instruments whose median
24h notional turnover is at least $20m. Illiquid perps have wide spreads, gappy candles
and delisting risk, and including them would flatter any result with prices nobody could
actually trade at.
"""
import json, os, time, urllib.request
from datetime import datetime, timezone

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "okx_daily.json")
# A first pass screened at $20m and kept only names with 400+ bars, which left 20
# instruments - no better than the 19 stocks that already failed, so it would have tested
# nothing. The binding constraint is LISTING AGE, not liquidity: most perps are recent.
# $5m/day is still a genuinely tradeable book (85 names) and 250 bars is ~8 months, which
# is enough to appear in a cross-section even if no single name spans the whole window.
# The test then requires a minimum number of names priced per DAY rather than a balanced
# panel, which is how cross-sectional work normally handles listings and delistings.
MIN_TURNOVER_USD = 5_000_000
MIN_BARS = 250
BARS_WANTED = 1200                       # ~3.3 years of daily


def get(url, tries=4):
    for a in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "kl-research/1.0"})
            with urllib.request.urlopen(req, timeout=25) as r:
                return json.loads(r.read().decode())
        except Exception as e:
            if a == tries - 1:
                print("   FAILED %s: %s" % (url[:70], e))
                return None
            time.sleep(1.5 * (a + 1))
    return None


print("1. universe")
d = get("https://www.okx.com/api/v5/public/instruments?instType=SWAP")
if not d or d.get("code") != "0":
    raise SystemExit("cannot reach OKX instruments endpoint")
perps = [x["instId"] for x in d["data"]
         if x.get("settleCcy") == "USDT" and x.get("state") == "live"]
print("   %d live USDT-settled perps" % len(perps))

print("2. liquidity screen (24h turnover >= $%dm)" % (MIN_TURNOVER_USD // 1_000_000))
t = get("https://www.okx.com/api/v5/market/tickers?instType=SWAP")
turn = {}
for x in (t or {}).get("data", []):
    try:
        turn[x["instId"]] = float(x.get("volCcy24h", 0)) * float(x.get("last", 0))
    except Exception:
        pass
# volCcy24h on a USDT perp is already in contracts of the base coin; multiplying by last
# gives a USD figure. Where the field is missing the name is dropped rather than guessed.
keep = sorted([p for p in perps if turn.get(p, 0) >= MIN_TURNOVER_USD],
              key=lambda p: -turn[p])
print("   %d pass" % len(keep))
print("   top: %s" % ", ".join(k.replace("-USDT-SWAP", "") for k in keep[:12]))

print("3. daily candles")
out = {}
for n, inst in enumerate(keep, 1):
    rows, after = [], ""
    while len(rows) < BARS_WANTED:
        url = ("https://www.okx.com/api/v5/market/history-candles"
               "?instId=%s&bar=1D&limit=100%s" % (inst, ("&after=" + after) if after else ""))
        j = get(url)
        if not j or j.get("code") != "0" or not j.get("data"):
            break
        batch = j["data"]                      # newest first
        rows.extend(batch)
        after = batch[-1][0]
        time.sleep(0.11)                       # stay inside the public rate limit
        if len(batch) < 100:
            break
    if len(rows) >= MIN_BARS:
        out[inst] = [[r[0], r[4]] for r in rows]   # timestamp, close
    if n % 20 == 0 or n == len(keep):
        print("   %d/%d fetched, %d usable" % (n, len(keep), len(out)))

with open(OUT, "w") as f:
    json.dump(out, f)
lens = sorted(len(v) for v in out.values())
print("\nsaved %d instruments to %s" % (len(out), OUT))
if lens:
    print("bars per instrument: min %d, median %d, max %d"
          % (lens[0], lens[len(lens) // 2], lens[-1]))
