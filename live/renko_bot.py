"""renko_bot.py - trades the Renko REVERSAL rule on the DEMO account.

THE RULE (user's, 2026-08-04, after backtesting 25 geometries):
    A reversal brick is the first brick in the opposite direction to the one
    before it. On a reversal UP brick -> BUY. On a reversal DOWN brick -> SELL.
    Take profit 5 bricks (250 pts), stop loss 3 bricks (150 pts).
    ONE trade at a time.

WHAT THE BACKTEST SAID, recorded here so nobody reads live results as proof of
something they are not. Over 45 days and 849 trades this setting returned
+1.71 points per trade - but the same 25-cell search run on SHUFFLED data, with
any real pattern destroyed, produced +0.91 on the identical cell. The standard
error is about 6.7 points, so +1.71 is a quarter of one SE from zero. This is
being run forward to find out whether that is anything at all. Treat it as a
measurement, not a strategy with a known edge.

Slippage is the thing most likely to sink it: observed 0.3 to 4.9 points on live
stops today, averaging ~3.8, which is more than twice the backtested gain.

SAFETY
  - refuses any account that is not 436771046 AND not a demo (trade_mode 0)
  - 0.01 lots, hard capped
  - one position at a time, checked against the broker before every entry
  - its own magic number, so it can never touch a position it did not open
  - only acts on a reversal detected in the last FRESH_MIN minutes, so a restart
    cannot fire on a stale signal
"""
import json, os, time
from datetime import datetime, timedelta

import MetaTrader5 as mt5

TERMINAL   = r"C:\Program Files\MetaTrader 5\terminal64.exe"
LOGIN      = 436771046
SYMBOL     = "BTCUSDm"
LOTS       = 0.01
MAGIC      = 770404                 # distinct from the old loop's orders
BRICK      = 50.0
REVERSAL   = 2                      # bricks needed to turn
TP_BRICKS  = 5
SL_BRICKS  = 3
POLL       = 20                     # seconds
FRESH_MIN  = 6                      # ignore a reversal older than this
ANCHOR     = datetime(2026, 7, 17)  # fixed, so brick boundaries never shift

HERE  = os.path.dirname(os.path.abspath(__file__))
LOG   = os.path.join(HERE, "renko_bot.log")
ALIVE = os.path.join(HERE, "renko_bot_alive.json")
STATE = os.path.join(HERE, "renko_bot_state.json")


def say(msg):
    line = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}"
    print(line, flush=True)
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def connect():
    """Pin the path AND verify the account. Two terminals run on this box and a
    bare initialize() attaches to whichever it likes - trap 1 in RESTORE.md."""
    if not mt5.initialize(path=TERMINAL):
        raise SystemExit(f"initialize failed: {mt5.last_error()}")
    a = mt5.account_info()
    if a is None or a.login != LOGIN:
        mt5.shutdown()
        raise SystemExit(f"WRONG ACCOUNT {a.login if a else None}, expected {LOGIN}")
    if a.trade_mode != 0:
        mt5.shutdown()
        raise SystemExit("NOT A DEMO ACCOUNT - refusing to trade")
    return a


def build_bricks(rates):
    """Same construction as charting/live_feed.py: 50-point bricks, 2-brick
    reversal, built from CLOSED bar closes so nothing ever repaints."""
    out = []
    ao = ac = float(rates[0]["open"])
    d = 0
    for r in rates:
        t, c = int(r["time"]), float(r["close"])
        while True:
            up_g = (ao if d == -1 else ac) + BRICK * (REVERSAL if d == -1 else 1)
            dn_g = (ao if d == 1 else ac) - BRICK * (REVERSAL if d == 1 else 1)
            if c >= up_g:
                base = ao if d == -1 else ac
                ao, ac, d = base, base + BRICK, 1
            elif c <= dn_g:
                base = ao if d == 1 else ac
                ao, ac, d = base, base - BRICK, -1
            else:
                break
            out.append({"time": t, "dir": d, "close": ac})
    return out


def last_reversal(bricks):
    """The most recent brick whose direction differs from the one before it."""
    for k in range(len(bricks) - 1, 0, -1):
        if bricks[k]["dir"] != bricks[k - 1]["dir"]:
            return bricks[k]
    return None


def our_positions():
    return [p for p in (mt5.positions_get(symbol=SYMBOL) or []) if p.magic == MAGIC]


def load_state():
    try:
        with open(STATE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"last_traded_brick": 0}


def save_state(s):
    try:
        with open(STATE, "w", encoding="utf-8") as f:
            json.dump(s, f)
    except Exception:
        pass


def enter(direction, ref_price):
    """Market order with stop and target attached before it can move."""
    tick = mt5.symbol_info_tick(SYMBOL)
    if tick is None:
        say("no tick - skipping entry")
        return False
    buy = (direction == 1)
    price = tick.ask if buy else tick.bid
    tp = price + BRICK * TP_BRICKS if buy else price - BRICK * TP_BRICKS
    sl = price - BRICK * SL_BRICKS if buy else price + BRICK * SL_BRICKS
    req = {"action": mt5.TRADE_ACTION_DEAL, "symbol": SYMBOL, "volume": LOTS,
           "type": mt5.ORDER_TYPE_BUY if buy else mt5.ORDER_TYPE_SELL,
           "price": price, "sl": sl, "tp": tp, "deviation": 30,
           "magic": MAGIC, "comment": "KL-renko-rev",
           "type_time": mt5.ORDER_TIME_GTC}
    say(f"ENTER {'BUY' if buy else 'SELL'} {LOTS} @ {price:.2f}  SL {sl:.2f}  TP {tp:.2f}"
        f"  (reversal brick close {ref_price:.2f})")
    r = mt5.order_send(req)
    # Success is the RETCODE, never formatted text - trap 6 in RESTORE.md, where
    # matching on a string reported every fill as FAILED and caused re-sends.
    ok = r is not None and r.retcode in (mt5.TRADE_RETCODE_DONE, mt5.TRADE_RETCODE_PLACED)
    say(f"  retcode {getattr(r, 'retcode', '?')} {getattr(r, 'comment', '')} -> "
        f"{'OK' if ok else 'FAILED'}")
    if not ok:
        say(f"  last_error {mt5.last_error()}")
    return ok


def main():
    acc = connect()
    say(f"renko_bot up | {SYMBOL} | account {acc.login} DEMO | equity {acc.equity:.2f}")
    say(f"rule: reversal brick -> market entry, TP {TP_BRICKS} bricks "
        f"({BRICK*TP_BRICKS:.0f}pt), SL {SL_BRICKS} bricks ({BRICK*SL_BRICKS:.0f}pt), "
        f"one at a time, {LOTS} lots, magic {MAGIC}")
    state = load_state()
    while True:
        try:
            rates = mt5.copy_rates_range(SYMBOL, mt5.TIMEFRAME_M1, ANCHOR, datetime.utcnow())
            if rates is None or len(rates) < 2:
                time.sleep(POLL); continue
            closed = rates[:-1]                      # never act on a forming bar
            bricks = build_bricks(closed)
            rev = last_reversal(bricks)
            pos = our_positions()

            if rev and not pos:
                age_min = (datetime.utcnow() - datetime.utcfromtimestamp(rev["time"])).total_seconds() / 60
                if rev["time"] > state.get("last_traded_brick", 0) and age_min <= FRESH_MIN:
                    # Count only OUR positions, by magic. This used to check
                    # positions_total() == 0, which was right when this was the
                    # only bot on the account - but renko_recovery_bot.py now runs
                    # alongside it and holds baskets for hours, which would have
                    # made this one stand down permanently and silently.
                    # Each bot manages only what it opened; neither can touch the
                    # other's positions because every close is addressed by ticket.
                    if not our_positions():
                        if enter(rev["dir"], rev["close"]):
                            state["last_traded_brick"] = rev["time"]
                            save_state(state)
                    else:
                        say("our own position still open - standing down")
                elif rev["time"] > state.get("last_traded_brick", 0):
                    # Seen but too old: record it so we do not fire on it later.
                    say(f"reversal at {datetime.utcfromtimestamp(rev['time'])} is "
                        f"{age_min:.0f} min old (limit {FRESH_MIN}) - skipping")
                    state["last_traded_brick"] = rev["time"]
                    save_state(state)

            with open(ALIVE, "w", encoding="utf-8") as f:
                json.dump({"alive_utc": datetime.utcnow().isoformat(),
                           "bricks": len(bricks),
                           "last_reversal_utc": datetime.utcfromtimestamp(rev["time"]).isoformat() if rev else None,
                           "last_reversal_dir": rev["dir"] if rev else None,
                           "open_positions": len(pos),
                           "equity": mt5.account_info().equity}, f)
        except Exception as e:
            say(f"ERROR {type(e).__name__}: {e}")
        time.sleep(POLL)


if __name__ == "__main__":
    main()
