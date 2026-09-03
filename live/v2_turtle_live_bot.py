"""v2_turtle_live_bot.py - V2 "Turtle" on the LIVE account 134499778. REAL MONEY.

Deployed 2026-08-19 at the user's explicit instruction: "we will deploy
turtle on the live account, I'll invest 100 dollars ... if it gets wiped
out that is fine, I understand the risk. but ideally a system that auto
trails the floor."

The shape (same as the demo Turtle, which stays running for comparison):
  - Entry: M1 50pt/2-brick reversal, only when the last-24h high-low range
    is < 2.5% of price (quiet-market gate - the measured edge lives there).
  - TP 1% / SL 0.5% of entry price, broker-side bracket.
  - Up to 5 concurrent positions.
  - LOTS = 0.01 (broker minimum) - NOT the demo's 0.05: with ~$100 of
    capital, 0.05-lot turtle's ordinary bad days (-$263 in backtest) would
    be instantly fatal. At 0.01 everything is 1/5: max single loss ~$3.4,
    worst backtest dip ~$440, expected ~$5/mo. $100 gives it a real chance,
    not a guarantee - the worst historical stretch would still have
    overwhelmed it. User explicitly accepts this.

THE TRAILING FLOOR (user's request):
  - Inactive until equity PEAK >= FLOOR_ARM ($200 = deposit doubled).
  - Once armed: floor = peak_equity - FLOOR_GIVEBACK ($100), trailing up
    only. If equity <= floor: close every Turtle position, halt entries
    permanently, and say so loudly in log + alive.json. Manual reset:
    delete the 'floor_tripped' key from the state file and restart.
  - Guarantees once armed: the original $100 can never be lost again, and
    at most $100 of any new peak can be given back.

Idle guard: below $20 balance the bot never sends orders (no retcode-10019
spam like the 2026-08-19 wipeout morning) - it just waits for the deposit.

Run:  pythonw v2_turtle_live_bot.py
"""
import json, os, sys, time
from datetime import datetime, timedelta

import MetaTrader5 as mt5

TERMINAL = r"C:\Projects\MT5-KinoliveTrader\terminal64.exe"   # the LIVE install
LOGIN    = 134499778
SYMBOL   = "BTCUSDm"
LOTS     = 0.01
MAGIC    = 770513
BRICK    = 50.0
REVERSAL = 2
TP_PCT   = 0.01
SL_PCT   = 0.005
GATE_PCT = 2.5
MAX_POS  = 5
POLL     = 20
FRESH_MIN = 6
MAX_FAILS = 10
RANGE_BARS = 1440
MIN_BALANCE = 20.0
MAX_SPREAD_PTS = 15.0   # spread guard added 2026-08-19: the backtested edge
                        # dies above ~20pts of spread (+$24/mo at 10pts ->
                        # +$3/mo at 20pts -> negative at 30pts). Skip any
                        # entry when the live spread exceeds this. Uniform
                        # cost-control, applies to every entry identically.
FLOOR_ARM = 200.0
FLOOR_GIVEBACK = 100.0

HERE    = os.path.dirname(os.path.abspath(__file__))
LOG     = os.path.join(HERE, "v2_turtle_live.log")
ALIVE   = os.path.join(HERE, "v2_turtle_live_alive.json")
STATE   = os.path.join(HERE, "v2_turtle_live_state.json")
JOURNAL = os.path.join(HERE, "v2_turtle_live_journal.csv")


def say(m):
    line = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {m}"
    print(line, flush=True)
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def check_account():
    """REAL account 134499778 only, verified every loop (trade_mode 2 = real)."""
    a = mt5.account_info()
    if a is None:
        return None
    if a.login != LOGIN:
        say(f"*** WRONG ACCOUNT {a.login}, expected {LOGIN} - REFUSING TO TRADE ***")
        return False
    if a.trade_mode != 2:
        say(f"*** not a REAL account (trade_mode={a.trade_mode}) - REFUSING ***")
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
                "realized_cum": 0.0, "last_deal_time": 0, "wins": 0, "losses": 0,
                "peak_equity": 0.0, "floor_tripped": False}


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


def close_position(p, why):
    tick = mt5.symbol_info_tick(SYMBOL)
    if tick is None:
        return False
    price = tick.bid if p.type == 0 else tick.ask
    req = {"action": mt5.TRADE_ACTION_DEAL, "position": p.ticket, "symbol": SYMBOL,
           "volume": p.volume,
           "type": mt5.ORDER_TYPE_SELL if p.type == 0 else mt5.ORDER_TYPE_BUY,
           "price": price, "deviation": 30, "magic": MAGIC,
           "comment": "Turtle-floor-close"}
    r = mt5.order_send(req)
    ok = r is not None and r.retcode in (mt5.TRADE_RETCODE_DONE, mt5.TRADE_RETCODE_PLACED)
    say(f"FLOOR CLOSE #{p.ticket} -> {'OK' if ok else 'FAILED ' + str(getattr(r,'retcode','?'))}  [{why}]")
    return ok


def open_one(direction):
    tick = mt5.symbol_info_tick(SYMBOL)
    if tick is None:
        return False
    buy = (direction == 1)
    price = tick.ask if buy else tick.bid
    tp = price * (1 + TP_PCT) if buy else price * (1 - TP_PCT)
    sl = price * (1 - SL_PCT) if buy else price * (1 + SL_PCT)
    req = {"action": mt5.TRADE_ACTION_DEAL, "symbol": SYMBOL, "volume": LOTS,
           "type": mt5.ORDER_TYPE_BUY if buy else mt5.ORDER_TYPE_SELL,
           "price": price, "tp": tp, "sl": sl,
           "deviation": 30, "magic": MAGIC, "comment": "V2-turtle-live",
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
                say(f"CLOSED #{d.position_id}  {pnl:+.2f}  (total {st['realized_cum']:+.2f}, "
                    f"W{st.get('wins',0)}/L{st.get('losses',0)})")
    except Exception as exc:
        say(f"JOURNAL WRITE FAILED: {exc}")
    save_state(st)


def main():
    acc = connect()
    say("=" * 70)
    say(f"V2 'TURTLE' LIVE BOT UP - REAL MONEY - account {acc.login} {acc.server} "
        f"balance {acc.balance:.2f} {acc.currency}")
    say(f"shape: TP {100*TP_PCT:g}% / SL {100*SL_PCT:g}%, quiet gate < {GATE_PCT:g}%, "
        f"up to {MAX_POS} positions of {LOTS} lots (broker minimum - sized for ~$100 capital), "
        f"magic {MAGIC}")
    say(f"TRAILING FLOOR: off until equity peak >= ${FLOOR_ARM:.0f} (deposit doubled); then "
        f"floor = peak - ${FLOOR_GIVEBACK:.0f}, trailing up only. Touch it -> close all, halt.")
    say(f"idle guard: no orders while balance < ${MIN_BALANCE:.0f} (waiting for the deposit).")
    say("*** UNVALIDATED FORWARD. User's explicit instruction and risk acceptance "
        "2026-08-19: '$100 test... if it gets wiped out that is fine'. ***")
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
                say("halting - wrong/non-real account."); mt5.shutdown(); sys.exit(2)
            if acc is None:
                fails += 1
                if fails >= MAX_FAILS:
                    mt5.shutdown(); sys.exit(1)
                time.sleep(POLL); continue
            fails = 0

            closed = rates[:-1]
            win = closed[-RANGE_BARS:]
            rng_pct = 100.0 * float(win["high"].max() - win["low"].min()) / float(closed[-1]["close"])
            gate_ok = rng_pct < GATE_PCT

            ps = mine()
            if ps is None:
                time.sleep(POLL); continue

            harvest_closed_deals(st)

            # ---- trailing floor ----
            st["peak_equity"] = max(st.get("peak_equity", 0.0), acc.equity)
            floor_armed = st["peak_equity"] >= FLOOR_ARM
            floor = st["peak_equity"] - FLOOR_GIVEBACK if floor_armed else None
            if floor_armed and not st.get("floor_tripped") and acc.equity <= floor:
                say(f"*** TRAILING FLOOR HIT: equity {acc.equity:.2f} <= floor {floor:.2f} "
                    f"(peak {st['peak_equity']:.2f}). Closing all and HALTING. ***")
                for p in ps:
                    close_position(p, "trailing floor hit")
                st["floor_tripped"] = True
                save_state(st)

            can_trade = (not st.get("floor_tripped")) and acc.balance >= MIN_BALANCE

            bricks = build_bricks(closed)
            rev = last_reversal(bricks)
            if rev and rev["time"] > st.get("last_brick", 0):
                age = (datetime.utcnow() - datetime.utcfromtimestamp(rev["time"])).total_seconds() / 60
                if st.get("floor_tripped"):
                    say("skip signal: TRAILING FLOOR tripped - halted until manual reset")
                elif acc.balance < MIN_BALANCE:
                    say(f"skip signal: balance ${acc.balance:.2f} below ${MIN_BALANCE:.0f} - waiting for deposit")
                elif age > FRESH_MIN:
                    say(f"skip signal: stale ({age:.1f}min old)")
                elif not gate_ok:
                    say(f"skip signal: range gate blocked (24h range {rng_pct:.2f}% >= {GATE_PCT:g}%)")
                elif len(ps) >= MAX_POS:
                    say(f"skip signal: all {MAX_POS} slots in use")
                else:
                    tick = mt5.symbol_info_tick(SYMBOL)
                    spread = (tick.ask - tick.bid) if tick else 999.0
                    if spread > MAX_SPREAD_PTS:
                        say(f"skip signal: spread guard ({spread:.1f}pts > {MAX_SPREAD_PTS:g}pts)")
                    else:
                        open_one(rev["dir"])
                st["last_brick"] = rev["time"]
                save_state(st)

            with open(ALIVE, "w", encoding="utf-8") as f:
                json.dump({"alive_utc": datetime.utcnow().isoformat(),
                           "bot": "v2-turtle-LIVE", "magic": MAGIC,
                           "positions": len(ps), "max_pos": MAX_POS, "lots": LOTS,
                           "tp_pct": TP_PCT, "sl_pct": SL_PCT, "gate_pct": GATE_PCT,
                           "range24_pct": round(rng_pct, 3), "gate_open": gate_ok,
                           "realized_cum": st.get("realized_cum", 0.0),
                           "wins": st.get("wins", 0), "losses": st.get("losses", 0),
                           "peak_equity": round(st.get("peak_equity", 0.0), 2),
                           "floor_armed": floor_armed,
                           "floor": round(floor, 2) if floor is not None else None,
                           "floor_tripped": st.get("floor_tripped", False),
                           "waiting_for_deposit": acc.balance < MIN_BALANCE,
                           "equity": acc.equity, "balance": acc.balance}, f)
        except Exception as e:
            say(f"ERROR {type(e).__name__}: {e}")
        time.sleep(POLL)


if __name__ == "__main__":
    main()
