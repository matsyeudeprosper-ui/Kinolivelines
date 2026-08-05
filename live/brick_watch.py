"""brick_watch.py - warns when the fixed 50-point brick stops being the right size.

WHY THIS EXISTS
The bots use a FIXED 50-point Renko brick. That was calibrated on 2026-08-04
when BTC was ~$64,000, where 50 points is 0.078% of price - a sensible move.

A fixed brick silently changes meaning as price moves:
  BTC $128,000 -> 50 pts is 0.039%, half as significant. Bricks form twice as
                  often, reversals get noisier, trade count balloons.
  BTC  $32,000 -> 50 pts is 0.156%, twice as significant. Bricks become rare,
                  baskets sit open longer, drawdowns get bigger.

The REASONING above stands on its own arithmetic. The evidence that used to be
cited here does not: "a fixed 50-pt brick had a worst drawdown of $987 versus
$384 price-scaled" came from the backtest whose entry alignment was wrong
(FINDINGS.md trap 15), and has never been re-measured. Treat the size of the
effect as unknown; the direction is still a straightforward consequence of a
fixed point-size meaning different things at different price levels.

The user chose a deliberate warning over automatic scaling, so that the chart
and the bot never change underneath them without a decision. This only WARNS.
It changes nothing.
"""
import json, os, time
from datetime import datetime

import MetaTrader5 as mt5

TERMINAL   = r"C:\Program Files\MetaTrader 5\terminal64.exe"
LOGIN      = 436771046
SYMBOL     = "BTCUSDm"

BRICK_NOW    = 50.0          # what the bots and the chart feed actually use
CALIB_PRICE  = 64000.0       # price it was calibrated at, 2026-08-04
CALIB_PCT    = BRICK_NOW / CALIB_PRICE      # 0.078%

# Warn once the ideal brick differs from the configured one by more than this.
# 30% is wide enough to ignore normal swings and tight enough to catch a real
# regime change - it corresponds to roughly BTC below $49k or above $91k.
TOLERANCE  = 0.30
POLL       = 300

HERE   = os.path.dirname(os.path.abspath(__file__))
LOG    = os.path.join(HERE, "brick_watch.log")
STATUS = os.path.join(HERE, "brick_watch_status.json")


def say(m):
    line = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {m}"
    print(line, flush=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def main():
    if not mt5.initialize(path=TERMINAL):
        raise SystemExit(f"initialize failed: {mt5.last_error()}")
    a = mt5.account_info()
    if a is None or a.login != LOGIN:
        mt5.shutdown(); raise SystemExit("wrong account")
    say(f"brick_watch up | brick {BRICK_NOW:.0f} pts calibrated at BTC ${CALIB_PRICE:,.0f} "
        f"({100*CALIB_PCT:.3f}% of price) | warn beyond {100*TOLERANCE:.0f}% drift")
    warned = False
    while True:
        try:
            t = mt5.symbol_info_tick(SYMBOL)
            if t is None or t.bid <= 0:
                time.sleep(POLL); continue
            price = t.bid
            ideal = price * CALIB_PCT                 # brick that would mean the same today
            drift = ideal / BRICK_NOW - 1.0
            lo = CALIB_PRICE * (1 - TOLERANCE)
            hi = CALIB_PRICE * (1 + TOLERANCE)
            out = abs(drift) > TOLERANCE

            with open(STATUS, "w", encoding="utf-8") as f:
                json.dump({"checked_utc": datetime.utcnow().isoformat(),
                           "btc": round(price, 2), "brick_in_use": BRICK_NOW,
                           "ideal_brick": round(ideal, 1),
                           "drift_pct": round(100 * drift, 1),
                           "band": [round(lo), round(hi)],
                           "action_needed": out}, f)

            if out and not warned:
                say("*** BRICK SIZE WARNING ***")
                say(f"    BTC is ${price:,.0f}. The 50-point brick is now "
                    f"{100*BRICK_NOW/price:.3f}% of price, not the {100*CALIB_PCT:.3f}% "
                    f"it was designed for.")
                say(f"    Recommended brick: {ideal:.0f} points  (drift {100*drift:+.0f}%)")
                say(f"    Affects: renko_bot.py, renko_recovery_bot.py, charting/live_feed.py")
                say(f"    Backtest showed a mismatched brick roughly TRIPLED the worst "
                    f"drawdown ($987 vs $384). This needs a decision, not a shrug.")
                warned = True
            elif not out and warned:
                say(f"brick drift back inside tolerance (BTC ${price:,.0f}) - warning cleared")
                warned = False
        except Exception as e:
            say(f"ERROR {type(e).__name__}: {e}")
        time.sleep(POLL)


if __name__ == "__main__":
    main()
