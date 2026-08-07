"""Build a filtered bar series and hand it to MT5 as a CUSTOM SYMBOL.

The rule (user's, 2026-08-03): keep a candle only if it CLOSES OUTSIDE the
previous candle's range - close > previous high, or close < previous low.
Candles that close back inside the previous candle's range are dropped.

Python does the maths and writes a CSV; KLCustomChart.mq5 reads it and pushes
the bars into a custom symbol. That split exists because the MetaTrader5 Python
package has NO CustomSymbolCreate - custom symbols are MQL5-only. It is the same
pattern as mirror_publisher.py -> KLMirror.mq5.

TWO MODES, because "previous candle" is ambiguous once you start dropping bars:

  original  compare against the previous bar of the ORIGINAL series.
            A straight mask over the real chart: every surviving candle is one
            that broke its immediate predecessor's range. Kept bars can sit
            inside each other, because the bar they broke may itself be gone.

  chain     compare against the previous SURVIVING bar.
            Self-referential, so each kept candle closes beyond the range of the
            one drawn before it - a strict breakout chain, closer in spirit to
            Renko. Always keeps fewer bars.

Run with --mode to pick; the script reports both counts either way so the
difference is visible before you choose.
"""
import argparse, csv, os, sys
from datetime import datetime

import MetaTrader5 as mt5

TERMINAL = r"C:\Program Files\MetaTrader 5\terminal64.exe"
LOGIN    = 436771046
SYMBOL   = "BTCUSDm"

# The MT5 COMMON folder is shared by every terminal on the machine, so the MQL5
# side can read this from whichever terminal you run it on.
COMMON = os.path.join(os.environ["APPDATA"], "MetaQuotes", "Terminal", "Common", "Files")
OUT       = os.path.join(COMMON, "kl_custom_bars.csv")
OUT_RENKO = os.path.join(COMMON, "kl_renko_bars.csv")

TF = {"M1": mt5.TIMEFRAME_M1, "M5": mt5.TIMEFRAME_M5, "M15": mt5.TIMEFRAME_M15,
      "M30": mt5.TIMEFRAME_M30, "H1": mt5.TIMEFRAME_H1, "H4": mt5.TIMEFRAME_H4}


def connect():
    """Pinned path AND verified login - trap 1 in RESTORE.md. Two terminals run
    on this box and a bare initialize() attaches to whichever it likes."""
    if not mt5.initialize(path=TERMINAL):
        raise SystemExit(f"initialize failed: {mt5.last_error()}")
    a = mt5.account_info()
    if a is None or a.login != LOGIN:
        mt5.shutdown()
        raise SystemExit(f"WRONG ACCOUNT {a.login if a else None}, expected {LOGIN}")
    return a


def build_renko(rates, brick):
    """Classic fixed-brick Renko. Bricks have no wicks: open = anchor,
    close = anchor +/- brick.

    THE TIMESTAMP TRAP. A Renko brick has no natural time, and a fast bar can
    complete several at once - but MT5 rejects a rates array whose times are not
    strictly increasing, and silently keeps only one of any duplicates. So each
    brick takes its source bar's time plus a one-second offset per brick within
    that bar. Source bars are >= 60s apart, so the offsets cannot collide with
    the next bar as long as fewer than 60 bricks complete in one bar - at a
    50-point brick that would need a 3,000-point candle.
    """
    out = []
    anchor = float(rates[0]["open"])
    for r in rates:
        t, c = int(r["time"]), float(r["close"])
        n_in_bar = 0
        while c >= anchor + brick or c <= anchor - brick:
            up = c >= anchor + brick
            o = anchor
            cl = anchor + brick if up else anchor - brick
            out.append({"time": t + n_in_bar, "open": o,
                        "high": max(o, cl), "low": min(o, cl), "close": cl,
                        "tick_volume": int(r["tick_volume"]),
                        "spread": int(r["spread"]), "real_volume": 0})
            anchor = cl
            n_in_bar += 1
    return out


def apply_filter(rates, mode):
    """Return the subset of bars that close outside the reference bar's range."""
    kept = []
    ref = None                       # the bar each candidate is measured against
    for i, r in enumerate(rates):
        if i == 0:
            kept.append(r)           # anchor: nothing to break yet
            ref = r
            continue
        prev = ref if mode == "chain" else rates[i - 1]
        if r["close"] > prev["high"] or r["close"] < prev["low"]:
            kept.append(r)
            ref = r                  # only matters in chain mode
        elif mode == "original":
            ref = r                  # unused, kept for symmetry
    return kept


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tf", default="M5", choices=list(TF))
    ap.add_argument("--bars", type=int, default=5000, help="source bars to pull")
    # chain is what the RUNNING feed uses (live_feed.py compares each close to
    # the last KEPT bar). Defaulting this builder to "original" meant a manual
    # rebuild silently produced a different series from the one the live chart
    # accumulates - same name, different rule.
    ap.add_argument("--mode", default="chain", choices=["original", "chain"])
    ap.add_argument("--renko", type=float, default=0,
                    help="brick size in points; builds Renko instead of the breakout filter")
    a = ap.parse_args()

    connect()
    # Oversized requests return NOTHING rather than truncating (trap 4), so step
    # down until the terminal actually answers.
    rates = None
    for n in (a.bars, 5000, 2000, 1000, 500):
        rates = mt5.copy_rates_from_pos(SYMBOL, TF[a.tf], 0, n)
        if rates is not None and len(rates):
            break
    mt5.shutdown()
    if rates is None or not len(rates):
        raise SystemExit("no rates returned for " + SYMBOL)

    print(f"source        {len(rates)} {a.tf} bars  "
          f"{datetime.utcfromtimestamp(rates[0]['time'])} -> "
          f"{datetime.utcfromtimestamp(rates[-1]['time'])}")

    if a.renko:
        kept = build_renko(rates, a.renko)
        out_path = OUT_RENKO
        print(f"  renko {a.renko:g}pt bricks -> {len(kept)} bricks")
    else:
        both = {m: apply_filter(rates, m) for m in ("original", "chain")}
        kept = both[a.mode]
        out_path = OUT
        for m, k in both.items():
            mark = " <- selected" if m == a.mode else ""
            print(f"  mode {m:<9} keeps {len(k):5d}  ({100*len(k)/len(rates):.1f}%){mark}")

    times = [int(b["time"]) for b in kept]
    if any(times[i] <= times[i - 1] for i in range(1, len(times))):
        raise SystemExit("BUG: timestamps are not strictly increasing - MT5 would drop bars")

    os.makedirs(COMMON, exist_ok=True)
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["time", "open", "high", "low", "close", "tick_volume", "spread", "real_volume"])
        for r in kept:
            w.writerow([int(r["time"]), r["open"], r["high"], r["low"], r["close"],
                        int(r["tick_volume"]), int(r["spread"]), int(r["real_volume"])])
    print(f"\nwrote {len(kept)} bars -> {out_path}")
    print("Now run the KLCustomChart script in MetaTrader (Navigator > Scripts).")


if __name__ == "__main__":
    main()
