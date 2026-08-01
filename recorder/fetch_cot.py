"""Download CFTC positioning history and matching daily prices.

This is the dataset for the question the price work could not answer: does knowing
WHO holds the position tell you anything that the price chart does not?

The CFTC has published, every week since 1986, how many contracts each class of
trader holds in every US futures market:
    NON-COMMERCIAL   large speculators - funds, CTAs. The crowd whose extremes people
                     watch. This is the "positioning" everyone means.
    COMMERCIAL       hedgers - miners, refiners, banks. Usually the other side.
    NON-REPORTABLE   everyone too small to report. Retail, roughly.

Why this beats the crypto funding data: it covers metals, equity indices, currencies
and energy - five asset classes that do NOT all move together. Crypto could never
give real replication because BTC and ETH are one bet. This can.

TWO TRAPS HANDLED HERE, both of which would manufacture an edge:

  LOOKAHEAD. The report is dated Tuesday but not published until Friday 15:30 ET.
  Anyone aligning Tuesday's positioning to Tuesday's price is trading on information
  that did not exist for three more days. Every row here carries `usable_from`, the
  FOLLOWING Friday - and the study keys off that, never off the report date.

  CONTRACT SIZE DRIFT. Raw contract counts are not comparable across decades - open
  interest in gold today dwarfs 1986. Everything is stored as a share of open
  interest, so a 40-year percentile rank means something.

Prices come from Yahoo as daily OHLC. Where a futures contract exists it is preferred,
since that is what the positioning is actually in; otherwise the cash index stands in.
The yen is stored INVERTED, because CFTC measures yen futures (dollars per yen) while
the quote feed gives USDJPY (yen per dollar) - failing to flip it would reverse the
sign of every yen result.
"""
import urllib.request, urllib.parse, ssl, json, csv, os, time, datetime as dt

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
COT_RES = "6dca-aqww"                       # legacy futures-only, 1986 ->

try:
    import certifi
    CTX = ssl.create_default_context(cafile=certifi.where())
except Exception:
    CTX = ssl._create_unverified_context()

# label, candidate COT market-name prefixes, yahoo ticker, invert?
#
# CFTC renamed several contracts to "Consolidated" versions around Feb 2022, so the
# obvious old name simply stops dead there. Splicing the old and new series together
# would be worse than losing the years: raw position counts jump at the join, and a
# trailing percentile rank would read that jump as a positioning extreme for three
# years afterwards - a fake signal manufactured by bookkeeping.
#
# So each market lists candidates and the fetcher picks the longest SINGLE continuous
# series that still reports in 2026. No splices, no discontinuities.
MARKETS = [
    ("gold",    ["GOLD - COMMODITY EXCHANGE"],                                  "GC=F",     False),
    ("silver",  ["SILVER - COMMODITY EXCHANGE"],                                "SI=F",     False),
    ("nikkei",  ["NIKKEI STOCK AVERAGE YEN DENOM",
                 "NIKKEI STOCK AVERAGE - CHICAGO"],                             "^N225",    False),
    ("dow",     ["DJIA Consolidated", "DJIA x $5",
                 "DOW JONES INDUSTRIAL AVG- x $5"],                             "^DJI",     False),
    ("nasdaq",  ["NASDAQ-100 Consolidated", "NASDAQ MINI",
                 "NASDAQ-100 STOCK INDEX (MINI)"],                              "^NDX",     False),
    ("sp500",   ["S&P 500 Consolidated", "E-MINI S&P 500 - CHICAGO",
                 "E-MINI S&P 500 STOCK INDEX"],                                 "^GSPC",    False),
    ("bitcoin", ["BITCOIN - CHICAGO MERCANTILE"],                               "BTC-USD",  False),
    ("eurusd",  ["EURO FX - CHICAGO MERCANTILE"],                               "EURUSD=X", False),
    ("yen",     ["JAPANESE YEN - CHICAGO MERCANTILE"],                          "JPY=X",    True),
    ("crude",   ["WTI-PHYSICAL - NEW YORK",
                 "CRUDE OIL, LIGHT SWEET - NEW YORK"],                          "CL=F",     False),
]
MIN_END = "2026-01-01"          # a series must still be reported to be usable

# HOLDOUT SET - markets deliberately NOT looked at during discovery.
#
# The reversal-at-extremes result was found on the list above: metals, equity indices,
# major FX and crypto. Validating it there again would prove nothing. These are grains,
# oilseeds, softs, livestock, industrial metals and secondary currencies - different
# exchanges, different participants, different reasons for anyone to be positioned at
# all. If crowding genuinely changes how a market behaves, it should not care that the
# crowd is in soybeans rather than gold.
#
# Nothing here gets tuned. Same rank window, same extreme definition, same horizon.
HOLDOUT = [
    ("corn",         ["CORN - CHICAGO BOARD OF TRADE"],            "ZC=F",     False),
    ("soybeans",     ["SOYBEANS - CHICAGO BOARD OF TRADE"],        "ZS=F",     False),
    ("soybean_meal", ["SOYBEAN MEAL - CHICAGO BOARD OF TRADE"],    "ZM=F",     False),
    ("soybean_oil",  ["SOYBEAN OIL - CHICAGO BOARD OF TRADE"],     "ZL=F",     False),
    ("oats",         ["OATS - CHICAGO BOARD OF TRADE"],            "ZO=F",     False),
    ("rough_rice",   ["ROUGH RICE - CHICAGO BOARD OF TRADE"],      "ZR=F",     False),
    ("cocoa",        ["COCOA - ICE FUTURES U.S."],                 "CC=F",     False),
    ("coffee",       ["COFFEE C - ICE FUTURES U.S."],              "KC=F",     False),
    ("cotton",       ["COTTON NO. 2 - ICE FUTURES U.S."],          "CT=F",     False),
    ("sugar",        ["SUGAR NO. 11 - ICE FUTURES U.S."],          "SB=F",     False),
    ("orange_juice", ["FRZN CONCENTRATED ORANGE JUICE"],           "OJ=F",     False),
    ("live_cattle",  ["LIVE CATTLE - CHICAGO MERCANTILE"],         "LE=F",     False),
    ("feeder_cattle",["FEEDER CATTLE - CHICAGO MERCANTILE"],       "GF=F",     False),
    ("lean_hogs",    ["LEAN HOGS - CHICAGO MERCANTILE"],           "HE=F",     False),
    ("platinum",     ["PLATINUM - NEW YORK MERCANTILE"],           "PL=F",     False),
    ("palladium",    ["PALLADIUM - NEW YORK MERCANTILE"],          "PA=F",     False),
    ("aud",          ["AUSTRALIAN DOLLAR - CHICAGO MERCANTILE"],   "AUDUSD=X", False),
    ("cad",          ["CANADIAN DOLLAR - CHICAGO MERCANTILE"],     "CAD=X",    True),
    ("chf",          ["SWISS FRANC - CHICAGO MERCANTILE"],         "CHF=X",    True),
    ("mxn",          ["MEXICAN PESO - CHICAGO MERCANTILE"],        "MXN=X",    True),
]

# `python fetch_cot.py holdout` writes the holdout files instead of the discovery ones.
import sys as _sys
IS_HOLDOUT = len(_sys.argv) > 1 and _sys.argv[1].lower() == "holdout"
if IS_HOLDOUT:
    MARKETS = HOLDOUT

FIELDS = ["report_date_as_yyyy_mm_dd", "market_and_exchange_names", "open_interest_all",
          "noncomm_positions_long_all", "noncomm_positions_short_all",
          "noncomm_postions_spread_all", "comm_positions_long_all",
          "comm_positions_short_all", "nonrept_positions_long_all",
          "nonrept_positions_short_all"]


def get(url, tries=4, timeout=90):
    last = None
    for k in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=timeout, context=CTX) as r:
                return json.loads(r.read().decode())
        except Exception as e:
            last = e
            time.sleep(1.5 * (k + 1))
    raise last


def next_friday(d):
    """Publication day: the Friday of the report week (report date is a Tuesday)."""
    return d + dt.timedelta(days=(4 - d.weekday()) % 7 or 7 if d.weekday() > 4 else (4 - d.weekday()))


def fetch_cot(prefix):
    rows, off = [], 0
    while True:
        u = ("https://publicreporting.cftc.gov/resource/%s.json?" % COT_RES +
             urllib.parse.urlencode({
                 "$select": ",".join(FIELDS),
                 "$where": "starts_with(market_and_exchange_names, '%s')" % prefix.replace("'", "''"),
                 "$order": "report_date_as_yyyy_mm_dd ASC",
                 "$limit": 5000, "$offset": off}))
        batch = get(u)
        rows += batch
        if len(batch) < 5000:
            break
        off += 5000
    return rows


def fetch_prices(ticker, invert):
    u = ("https://query1.finance.yahoo.com/v8/finance/chart/%s"
         "?period1=0&period2=%d&interval=1d" % (ticker, int(time.time())))
    res = (get(u).get("chart") or {}).get("result") or []
    if not res:
        return []
    r0 = res[0]
    ts = r0.get("timestamp") or []
    q = (r0.get("indicators", {}).get("quote") or [{}])[0]
    o, h, l, c = (q.get("open"), q.get("high"), q.get("low"), q.get("close"))
    out = []
    for i, t in enumerate(ts):
        vals = (o[i], h[i], l[i], c[i])
        if any(v is None or v <= 0 for v in vals):
            continue
        oo, hh, ll, cc = vals
        if invert:                       # 1/x flips highs and lows
            oo, hh, ll, cc = 1 / oo, 1 / ll, 1 / hh, 1 / cc
        out.append((dt.date.fromtimestamp(t).isoformat(), oo, hh, ll, cc))
    return out


os.makedirs(DATA, exist_ok=True)
_sfx = "_holdout" if IS_HOLDOUT else ""
cot_path = os.path.join(DATA, "cot_positioning%s.csv" % _sfx)
px_path = os.path.join(DATA, "cot_prices%s.csv" % _sfx)

with open(cot_path, "w", newline="", encoding="utf-8") as fc, \
     open(px_path, "w", newline="", encoding="utf-8") as fp:
    wc, wp = csv.writer(fc), csv.writer(fp)
    wc.writerow(["market", "report_date", "usable_from", "open_interest",
                 "nc_long", "nc_short", "nc_spread", "c_long", "c_short",
                 "nr_long", "nr_short"])
    wp.writerow(["market", "date", "open", "high", "low", "close"])

    for label, prefixes, ticker, invert in MARKETS:
        rows, chosen = [], None
        for pref in prefixes:
            try:
                cand = fetch_cot(pref)
            except Exception as e:
                print("%-9s COT FAIL on '%s' %s" % (label, pref, type(e).__name__)); continue
            if not cand:
                continue
            last = cand[-1]["report_date_as_yyyy_mm_dd"][:10]
            # must still be reported now, and we want the longest such series
            if last >= MIN_END and len(cand) > len(rows):
                rows, chosen = cand, pref
        if not rows:
            print("%-9s no series still reporting in 2026 - skipped" % label); continue
        n = 0
        for r in rows:
            try:
                d = dt.date.fromisoformat(r["report_date_as_yyyy_mm_dd"][:10])
                # publication is the Friday of that same week
                pub = d + dt.timedelta(days=(4 - d.weekday()) % 7)
                wc.writerow([label, d.isoformat(), pub.isoformat(),
                             r.get("open_interest_all", ""),
                             r.get("noncomm_positions_long_all", ""),
                             r.get("noncomm_positions_short_all", ""),
                             r.get("noncomm_postions_spread_all", ""),
                             r.get("comm_positions_long_all", ""),
                             r.get("comm_positions_short_all", ""),
                             r.get("nonrept_positions_long_all", ""),
                             r.get("nonrept_positions_short_all", "")])
                n += 1
            except Exception:
                pass
        try:
            px = fetch_prices(ticker, invert)
        except Exception as e:
            px = []
            print("%-9s price FAIL %s" % (label, type(e).__name__))
        for row in px:
            wp.writerow([label] + list(row))
        span = "%s..%s" % (rows[0]["report_date_as_yyyy_mm_dd"][:10],
                           rows[-1]["report_date_as_yyyy_mm_dd"][:10])
        print("%-9s COT %4d wks %s | price %5d days %s%s\n%-9s   using '%s'"
              % (label, n, span, len(px),
                 "%s..%s" % (px[0][0], px[-1][0]) if px else "-",
                 "  [INVERTED]" if invert else "", "", chosen))
        time.sleep(0.4)

print("\n-> %s\n-> %s" % (cot_path, px_path))
