"""Fetch OKX funding-rate history for the perps already in the daily panel.

Carry is a different KIND of edge from everything tested so far. Every previous attempt
tried to predict direction. Carry does not predict anything - it collects a payment that
exists whether or not the price moves, in exchange for holding a risk somebody else wants
off their book. On a perpetual swap that payment is the funding rate, paid every 8 hours
between longs and shorts.

The catch, and the whole reason this needs testing rather than assuming: funding is
positive precisely when everyone wants to be long. Shorting to collect it means standing
in front of the crowd. The money question is whether the funding collected exceeds the
price move that goes against you. That is what the test measures, not the funding alone -
quoting an annualised funding yield without the price leg is the classic way to make a
carry trade look free when it is not.

Funding pays every 8 hours, so a year is ~1,095 payments. Two years is fetched, which is
enough to include both a strong bull phase and a drawdown.
"""
import json, os, time, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "okx_funding.json")
PERIODS = 2200                                  # ~2 years of 8-hourly funding


def get(url, tries=4):
    for a in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "kl-research/1.0"})
            with urllib.request.urlopen(req, timeout=25) as r:
                return json.loads(r.read().decode())
        except Exception:
            if a == tries - 1:
                return None
            time.sleep(1.2 * (a + 1))
    return None


daily = json.load(open(os.path.join(HERE, "okx_daily.json")))
insts = list(daily.keys())
print("fetching funding for %d perps (~%d periods each)\n" % (len(insts), PERIODS))

out = {}
for n, inst in enumerate(insts, 1):
    rows, before = [], ""
    while len(rows) < PERIODS:
        url = ("https://www.okx.com/api/v5/public/funding-rate-history"
               "?instId=%s&limit=100%s" % (inst, ("&after=" + before) if before else ""))
        j = get(url)
        if not j or j.get("code") != "0" or not j.get("data"):
            break
        batch = j["data"]                       # newest first
        rows.extend(batch)
        before = batch[-1]["fundingTime"]
        time.sleep(0.12)
        if len(batch) < 100:
            break
    if len(rows) >= 300:
        out[inst] = [[r["fundingTime"], r["fundingRate"]] for r in rows]
    if n % 10 == 0 or n == len(insts):
        print("   %d/%d done, %d usable" % (n, len(insts), len(out)))

json.dump(out, open(OUT, "w"))
lens = sorted(len(v) for v in out.values())
print("\nsaved %d instruments" % len(out))
if lens:
    print("funding periods: min %d, median %d, max %d"
          % (lens[0], lens[len(lens)//2], lens[-1]))
    print("(8-hourly, so median is about %.1f years)" % (lens[len(lens)//2] / 1095))
