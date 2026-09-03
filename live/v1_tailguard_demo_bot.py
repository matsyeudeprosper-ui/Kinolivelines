"""v1_tailguard_demo_bot.py - V1 "Tail Guard" moved to the DEMO account.

History: V1 ran on the REAL account 134499778 from 2026-08-14 until
2026-08-19, when a BTC surge to ~$68.4k margin-stopped the underfunded
account ($120.64 balance vs a ~$1,370-wide SL) and wiped it to $0 - the
exact risk warned about at every startup. At the user's instruction
("bring down v1 to demo account") the live process was stopped the same
day and V1 continues here on DEMO 436771046, unchanged rules, for
continued forward observation alongside the V2 Turtle/Rabbit demo bots.

Rules (exactly the last live configuration):
  - Entry: M1 50pt/2-brick reversal, ONE position at a time (cap=1).
  - TP: 100 points ($5.00 at 0.05 lots), broker-side.
  - SL: relative 40% of entry price (deployed 2026-08-17), broker-side,
    with the Breakeven Ratchet on top (deployed 2026-08-18): once banked
    realized profit since deploy >= 30% of the current trade's default SL
    width, the SL tightens to min(banked, default width).
  - No recovery, no basket, no daily limit.

Run:  pythonw v1_tailguard_demo_bot.py
"""
import json, os, sys, time
from datetime import datetime, timedelta

import MetaTrader5 as mt5

TERMINAL = r"C:\Program Files\MetaTrader 5\terminal64.exe"   # the DEMO install
LOGIN    = 436771046                                          # DEMO account
SYMBOL   = "BTCUSDm"
LOTS     = 0.05
MAGIC    = 770512            # new magic - distinct from every other bot
BRICK    = 50.0
REVERSAL = 2
TP_PTS   = 100.0
RELATIVE_SL_PCT = 0.40
RATCHET_TRIGGER_FRAC = 0.30
RATCHET_CAP_FRAC = 1.00
POLL     = 20
FRESH_MIN = 6
MAX_FAILS = 10

HERE    = os.path.dirname(os.path.abspath(__file__))
LOG     = os.path.join(HERE, "v1_tailguard_demo.log")
ALIVE   = os.path.join(HERE, "v1_tailguard_demo_alive.json")
STATE   = os.path.join(HERE, "v1_tailguard_demo_state.json")
JOURNAL = os.path.join(HERE, "v1_tailguard_demo_journal.csv")


def say(m):
    line = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {m}"
    print(line, flush=True)
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def check_account():
    """DEMO 436771046 only, verified every loop - must never touch real money."""
    a = mt5.account_info()
    if a is None:
        return None
    if a.login != LOGIN:
        say(f"*** WRONG ACCOUNT {a.login}, expected DEMO {LOGIN} - REFUSING ***")
        return False
    if a.trade_mode != 0:
        say(f"*** NOT A DEMO ACCOUNT (trade_mode={a.trade_mode}) - REFUSING ***")
        return False
    return a


def connect():
    if not mt5.initialize(path=TERMINAL):
        raise SystemExit(f"initialize failed: {mt5.last_error()}")
    a = check_account()
    if not a:
        mt5.shutdown(); raise SystemExit("account check failed at startup")
    return a


def build_bricks(rates):
    out = []
    ao = ac = float(rates[0]["open"]); d = 0
    for r in rates:
        t, c = int(r["time"]), float(r["close"])
        while True:
            up = (ao if d == -1 else ac) + BRICK * (REVERSAL if d == -1 else 1)
            dn = (ao if d == 1 else ac) - BRICK * (REVERSAL if d == 1 else 1)
            if c >= up:
                base = ao if d == -1 else ac; ao, ac, d = base, base + BRICK, 1
            elif c <= dn:
                base = ao if d == 1 else ac; ao, ac, d = base, base - BRICK, -1
            else:
                break
            out.append({"time": t, "dir": d, "close": ac})
    return out


def last_reversal(b):
    for k in range(len(b) - 1, 0, -1):
        if b[k]["dir"] != b[k - 1]["dir"]:
            return dict(b[k])
    return None


def load_state():
    try:
        with open(STATE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"last_brick": 0, "deploy_epoch": int(time.time()),
                "realized_cum": 0.0, "last_deal_time": 0, "wins": 0, "losses": 0}


def save_state(s):
    try:
        tmp = STATE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(s, f); f.flush(); os.fsync(f.fileno())
        os.replace(tmp, STATE)
    except Exception as exc:
        say(f"STATE SAVE FAILED: {exc}")


def mine():
    ps = mt5.positions_get(symbol=SYMBOL)
    if ps is None:
        return None
    return [p for p in ps if p.magic == MAGIC]


def effective_sl_pts(st, price):
    """Relative 40% default + Breakeven Ratchet (trigger 30%, cap 100%) -
    identical formula to the last live V1 configuration."""
    default_sl_usd = price * RELATIVE_SL_PCT * LOTS
    trigger = RATCHET_TRIGGER_FRAC * default_sl_usd
    cum = st.get("realized_cum", 0.0)
    if cum >= trigger:
        sl_usd = min(max(cum, 0.0), RATCHET_CAP_FRAC * default_sl_usd)
        return sl_usd / LOTS, True
    return price * RELATIVE_SL_PCT, False


def open_one(direction, sl_pts):
    tick = mt5.symbol_info_tick(SYMBOL)
    if tick is None:
        return False
    buy = (direction == 1)
    price = tick.ask if buy else tick.bid
    tp = price + TP_PTS if buy else price - TP_PTS
    sl = price - sl_pts if buy else price + sl_pts
    req = {"action": mt5.TRADE_ACTION_DEAL, "symbol": SYMBOL, "volume": LOTS,
           "type": mt5.ORDER_TYPE_BUY if buy else mt5.ORDER_TYPE_SELL,
           "price": price, "tp": tp, "sl": sl,
           "deviation": 30, "magic": MAGIC, "comment": "V1-TailGuard-demo",
           "type_time": mt5.ORDER_TIME_GTC}
    say(f"OPEN {'BUY' if buy else 'SELL'} {LOTS} @ {price:.2f} TP {tp:.2f} SL {sl:.2f}")
    r = mt5.order_send(req)
    ok = r is not None and r.retcode in (mt5.TRADE_RETCODE_DONE, mt5.TRADE_RETCODE_PLACED)
    say(f"  retcode {getattr(r,'retcode','?')} -> {'OK' if ok else 'FAILED'}")
    return ok


def harvest_closed_deals(st):
    frm = datetime.utcfromtimestamp(max(st.get("deploy_epoch", 0) - 60,
                                        st.get("last_deal_time", 0)))
    deals = mt5.history_deals_get(frm, datetime.utcnow() + timedelta(hours=1))
    if not deals:
        return
    new = [d for d in deals if d.magic == MAGIC and d.entry == 1
           and d.time > st.get("last_deal_time", 0)]
    if not new:
        return
    new_file = not os.path.exists(JOURNAL)
    try:
        with open(JOURNAL, "a", encoding="utf-8", newline="") as f:
            if new_file:
                f.write("close_time_utc,position_id,profit_usd\n")
            for d in sorted(new, key=lambda x: x.time):
                pnl = d.profit + d.swap + d.commission + getattr(d, "fee", 0.0)
                st["realized_cum"] = round(st.get("realized_cum", 0.0) + pnl, 2)
                if pnl >= 0: st["wins"] = st.get("wins", 0) + 1
                else: st["losses"] = st.get("losses", 0) + 1
                st["last_deal_time"] = max(st.get("last_deal_time", 0), int(d.time))
                f.write(f"{datetime.utcfromtimestamp(d.time).isoformat()},{d.position_id},{pnl:.2f}\n")
                say(f"CLOSED #{d.position_id}  {pnl:+.2f}  (banked {st['realized_cum']:+.2f}, "
                    f"W{st.get('wins',0)}/L{st.get('losses',0)})")
    except Exception as exc:
        say(f"JOURNAL WRITE FAILED: {exc}")
    save_state(st)


def main():
    acc = connect()
    say("=" * 70)
    say(f"V1 'TAIL GUARD' DEMO BOT UP - account {acc.login} {acc.server} (DEMO) "
        f"balance {acc.balance:.2f} {acc.currency}")
    say(f"rules: M1 brick 50pt/2rev, cap=1, TP {TP_PTS:.0f}pts (${TP_PTS*LOTS:.2f}), "
        f"SL relative {100*RELATIVE_SL_PCT:.0f}% of price + Breakeven Ratchet "
        f"(trigger {100*RATCHET_TRIGGER_FRAC:.0f}%, cap {100*RATCHET_CAP_FRAC:.0f}%), magic {MAGIC}")
    say("Moved here from the REAL account 2026-08-19 after that account was "
        "margin-stopped to $0 by the BTC surge - see the module docstring. "
        "realized_cum starts fresh at $0.00 on demo.")
    say("=" * 70)
    st = load_state()
    save_state(st)
    fails = 0
    while True:
        try:
            rates = mt5.copy_rates_from_pos(SYMBOL, mt5.TIMEFRAME_M1, 0, 3000)
            if rates is None or len(rates) < 2:
                fails += 1
                say(f"no bars ({fails}/{MAX_FAILS}) last_error {mt5.last_error()}")
                if fails >= MAX_FAILS:
                    say("TERMINAL UNREACHABLE - exiting for the watchdog")
                    mt5.shutdown(); sys.exit(1)
                time.sleep(POLL); continue
            acc = check_account()
            if acc is False:
                say("halting - wrong/non-demo account."); mt5.shutdown(); sys.exit(2)
            if acc is None:
                fails += 1
                if fails >= MAX_FAILS:
                    mt5.shutdown(); sys.exit(1)
                time.sleep(POLL); continue
            fails = 0

            bricks = build_bricks(rates[:-1])
            rev = last_reversal(bricks)
            ps = mine()
            if ps is None:
                time.sleep(POLL); continue

            harvest_closed_deals(st)

            if rev and rev["time"] > st.get("last_brick", 0):
                age = (datetime.utcnow() - datetime.utcfromtimestamp(rev["time"])).total_seconds() / 60
                if age > FRESH_MIN:
                    say(f"skip signal: stale ({age:.1f}min old)")
                elif ps:
                    say("skip signal: already in a position (cap=1)")
                else:
                    tick = mt5.symbol_info_tick(SYMBOL)
                    if tick is not None:
                        price_now = tick.ask if rev["dir"] == 1 else tick.bid
                        sl_pts, ratchet_on = effective_sl_pts(st, price_now)
                        say(f"SL SIZING {'RATCHET ACTIVE' if ratchet_on else 'relative 40%'}: "
                            f"{sl_pts:.1f}pts (${sl_pts*LOTS:.2f}) @ {price_now:.2f}  "
                            f"banked=${st.get('realized_cum', 0.0):.2f}")
                        open_one(rev["dir"], sl_pts)
                st["last_brick"] = rev["time"]
                save_state(st)

            _px = float(rates[-1]["close"])
            _sl_pts, _ratchet_on = effective_sl_pts(st, _px)
            with open(ALIVE, "w", encoding="utf-8") as f:
                json.dump({"alive_utc": datetime.utcnow().isoformat(),
                           "bot": "v1-tailguard-demo", "magic": MAGIC,
                           "positions": len(ps), "lots": LOTS,
                           "tp_usd": round(TP_PTS * LOTS, 2),
                           "sl_mode": "relative_pct_of_price+ratchet",
                           "current_sl_usd": round(_sl_pts * LOTS, 2),
                           "ratchet_active": _ratchet_on,
                           "realized_cum": st.get("realized_cum", 0.0),
                           "wins": st.get("wins", 0), "losses": st.get("losses", 0),
                           "equity": acc.equity, "balance": acc.balance}, f)
        except Exception as e:
            say(f"ERROR {type(e).__name__}: {e}")
        time.sleep(POLL)


if __name__ == "__main__":
    main()
