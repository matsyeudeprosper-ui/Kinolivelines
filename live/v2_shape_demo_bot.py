"""v2_shape_demo_bot.py - V2 research bots "Turtle" and "Rabbit", DEMO ONLY.

Deployed 2026-08-19 as the forward-validation step of the V2 research track
(see memory: kinolivelines-tailguard-v2-research). Runs on the DEMO account
436771046 ONLY - hard-refuses any other account or a real (non-demo)
account. Same entry signal as V1 (M1 50pt/2-brick reversal), but the V2
shapes found in the 2026-08-19 shape research:

  TURTLE (magic 770510): TP 1% / SL 0.5% of entry price, entries only when
    the last-24h high-low range is < 2.5% of price, up to 5 concurrent
    0.05-lot positions. Backtest character: small steady income (~$24/mo),
    positive 6 of 7 years incl. 2021, worst dip ~$2.2k, max single loss ~$16.

  RABBIT (magic 770511): TP 4% / SL 2%, range gate < 4%, up to 10 concurrent
    0.05-lot positions. Backtest character: ~$400/mo in the 2024-26 regime
    but LOST ~$5.9k across 2021-23 - era-dependent, lumpy months, worst
    slide ~$8k. On demo precisely to see which regime we're in now.

Both are UNVALIDATED FORWARD - that's the whole point of this demo run.
Broker-side TP/SL bracket per position, no recovery/basket/martingale.

Run:  pythonw v2_shape_demo_bot.py turtle
      pythonw v2_shape_demo_bot.py rabbit
"""
import json, os, sys, time
from datetime import datetime, timedelta

import MetaTrader5 as mt5

TERMINAL = r"C:\Program Files\MetaTrader 5\terminal64.exe"   # the DEMO install
LOGIN    = 436771046                                          # DEMO account
SYMBOL   = "BTCUSDm"
LOTS     = 0.05
BRICK    = 50.0
REVERSAL = 2
POLL     = 20
FRESH_MIN = 6
MAX_FAILS = 10
RANGE_BARS = 1440   # 24h of closed M1 bars for the regime gate

PROFILES = {
    "turtle": dict(MAGIC=770510, TP_PCT=0.01,  SL_PCT=0.005, GATE_PCT=2.5, MAX_POS=5),
    "rabbit": dict(MAGIC=770511, TP_PCT=0.04,  SL_PCT=0.02,  GATE_PCT=4.0, MAX_POS=10),
}

if len(sys.argv) < 2 or sys.argv[1] not in PROFILES:
    raise SystemExit("usage: v2_shape_demo_bot.py turtle|rabbit")
NAME = sys.argv[1]
P = PROFILES[NAME]

HERE   = os.path.dirname(os.path.abspath(__file__))
LOG    = os.path.join(HERE, f"v2_{NAME}_demo.log")
ALIVE  = os.path.join(HERE, f"v2_{NAME}_demo_alive.json")
STATE  = os.path.join(HERE, f"v2_{NAME}_demo_state.json")
JOURNAL = os.path.join(HERE, f"v2_{NAME}_demo_journal.csv")


def say(m):
    line = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {m}"
    print(line, flush=True)
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def check_account():
    """DEMO account 436771046 only, verified on EVERY loop. trade_mode 0 =
    demo. Anything else (wrong login, or a REAL account) -> refuse. This bot
    must never be able to touch real money."""
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
        return {"last_brick": 0, "deploy_utc": datetime.utcnow().isoformat(),
                "deploy_epoch": int(time.time()), "realized_cum": 0.0,
                "last_deal_time": 0, "wins": 0, "losses": 0}


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
    return [p for p in ps if p.magic == P["MAGIC"]]


def open_one(direction, tp_pct, sl_pct):
    tick = mt5.symbol_info_tick(SYMBOL)
    if tick is None:
        return False
    buy = (direction == 1)
    price = tick.ask if buy else tick.bid
    tp = price * (1 + tp_pct) if buy else price * (1 - tp_pct)
    sl = price * (1 - sl_pct) if buy else price * (1 + sl_pct)
    req = {"action": mt5.TRADE_ACTION_DEAL, "symbol": SYMBOL, "volume": LOTS,
           "type": mt5.ORDER_TYPE_BUY if buy else mt5.ORDER_TYPE_SELL,
           "price": price, "tp": tp, "sl": sl,
           "deviation": 30, "magic": P["MAGIC"], "comment": f"V2-{NAME}",
           "type_time": mt5.ORDER_TIME_GTC}
    say(f"OPEN {'BUY' if buy else 'SELL'} {LOTS} @ {price:.2f} TP {tp:.2f} SL {sl:.2f}")
    r = mt5.order_send(req)
    ok = r is not None and r.retcode in (mt5.TRADE_RETCODE_DONE, mt5.TRADE_RETCODE_PLACED)
    say(f"  retcode {getattr(r,'retcode','?')} -> {'OK' if ok else 'FAILED'}")
    return ok


def harvest_closed_deals(st):
    """Pick up newly closed deals for this magic, log them, update realized
    P&L and win/loss counts."""
    frm = datetime.utcfromtimestamp(max(st.get("deploy_epoch", 0) - 60,
                                        st.get("last_deal_time", 0)))
    deals = mt5.history_deals_get(frm, datetime.utcnow() + timedelta(hours=1))
    if not deals:
        return
    new = [d for d in deals if d.magic == P["MAGIC"] and d.entry == 1
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
                say(f"CLOSED #{d.position_id}  {pnl:+.2f}  (running total {st['realized_cum']:+.2f}, "
                    f"W{st.get('wins',0)}/L{st.get('losses',0)})")
    except Exception as exc:
        say(f"JOURNAL WRITE FAILED: {exc}")
    save_state(st)


def main():
    acc = connect()
    say("=" * 70)
    say(f"V2 '{NAME.upper()}' DEMO BOT UP - account {acc.login} {acc.server} (DEMO) "
        f"balance {acc.balance:.2f} {acc.currency}")
    say(f"shape: TP {100*P['TP_PCT']:g}% / SL {100*P['SL_PCT']:g}% of entry price, "
        f"entries only when 24h range < {P['GATE_PCT']:g}% of price, "
        f"up to {P['MAX_POS']} concurrent positions of {LOTS} lots, magic {P['MAGIC']}")
    say("Forward validation of the 2026-08-19 V2 backtest shapes - see memory "
        "kinolivelines-tailguard-v2-research. UNVALIDATED FORWARD; demo only.")
    say("=" * 70)

    st = load_state()
    save_state(st)
    fails = 0
    while True:
        try:
            rates = mt5.copy_rates_from_pos(SYMBOL, mt5.TIMEFRAME_M1, 0, RANGE_BARS + 600)
            if rates is None or len(rates) < RANGE_BARS + 2:
                fails += 1
                say(f"no/short bars ({fails}/{MAX_FAILS}) last_error {mt5.last_error()}")
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

            closed = rates[:-1]                      # decisions on CLOSED bars only
            win = closed[-RANGE_BARS:]
            rng = float(win["high"].max() - win["low"].min())
            last_close = float(closed[-1]["close"])
            rng_pct = 100.0 * rng / last_close
            gate_ok = rng_pct < P["GATE_PCT"]

            bricks = build_bricks(closed)
            rev = last_reversal(bricks)
            ps = mine()
            if ps is None:
                time.sleep(POLL); continue

            harvest_closed_deals(st)

            if rev and rev["time"] > st.get("last_brick", 0):
                age = (datetime.utcnow() - datetime.utcfromtimestamp(rev["time"])).total_seconds() / 60
                if age > FRESH_MIN:
                    say(f"skip signal: stale ({age:.1f}min old)")
                elif not gate_ok:
                    say(f"skip signal: range gate blocked (24h range {rng_pct:.2f}% >= {P['GATE_PCT']:g}%)")
                elif len(ps) >= P["MAX_POS"]:
                    say(f"skip signal: all {P['MAX_POS']} slots in use")
                else:
                    open_one(rev["dir"], P["TP_PCT"], P["SL_PCT"])
                st["last_brick"] = rev["time"]
                save_state(st)

            with open(ALIVE, "w", encoding="utf-8") as f:
                json.dump({"alive_utc": datetime.utcnow().isoformat(),
                           "bot": f"v2-{NAME}", "magic": P["MAGIC"],
                           "positions": len(ps), "max_pos": P["MAX_POS"],
                           "lots": LOTS,
                           "tp_pct": P["TP_PCT"], "sl_pct": P["SL_PCT"],
                           "gate_pct": P["GATE_PCT"],
                           "range24_pct": round(rng_pct, 3),
                           "gate_open": gate_ok,
                           "realized_cum": st.get("realized_cum", 0.0),
                           "wins": st.get("wins", 0), "losses": st.get("losses", 0),
                           "equity": acc.equity, "balance": acc.balance}, f)
        except Exception as e:
            say(f"ERROR {type(e).__name__}: {e}")
        time.sleep(POLL)


if __name__ == "__main__":
    main()
