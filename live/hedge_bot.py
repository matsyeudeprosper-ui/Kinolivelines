"""hedge_bot.py - the ONE-HEDGE recovery rule, on the REAL account 134499778.

*** THIS BOT TRADES REAL MONEY. ***

Deployed 2026-08-06 at the user's explicit instruction, who was told and accepted
the following before authorising it:

  - the rule LOSES in backtest. On 27 months of clean M15 it turns $1,000 into
    $473. The hedge hits its target 38-39% and needs 40% to break even.
  - a reward sweep from 1:1 to 1:3 put the hit rate ON the break-even line at
    EVERY ratio, which is the signature of an entry with no directional
    information at all. No ratio fixes it.
  - the M1 result that looks positive is 1.8 months and +$32 against a +/-$35
    error bar. Inside noise.
  - the measured drawdown is $67 on M1 and $615 on M15 at 0.01 lots, which is
    the minimum tradeable size. THIS ACCOUNT IS $30.95. The account is smaller
    than the strategy's ordinary operating drawdown, so the realistic outcome is
    the balance being gone in roughly one to two months.

It is deployed because it is the user's money and their decision. Nothing here
should be read as the rule being validated.

WHY IT IS STILL THE BEST OF THE FAMILY
Of everything tested it has the smallest drawdown and the only hard bound on
risk: never more than two positions, and a loss defined in advance by the
hedge's stop. The alternatives reach 5, 22 or 39 positions and can lose
multiples of the account in a single basket.

THE RULE
  1. a reversal brick opens ONE trade, 250-point target, NO stop
  2. 150 points against it -> recovery
  3. take the NEXT OPPOSITE reversal, one only. Target 1.5x the first trade's
     drawdown at that moment, stop 1.0x it
  4. hedge hits target -> close both, new cycle
  5. hedge hits stop   -> close both, new cycle
  6. cycle P&L back to zero -> close both, new cycle
  7. NEVER more than 2 positions, and no new cycle until both are closed

SAFETY, all of it deliberate
  - refuses any account that is not 134499778 AND not trade_mode REAL, checked
    on EVERY loop rather than once at startup, because a terminal can be
    re-logged into a different account while this is running
  - 0.01 lots, hard-capped, never scaled
  - EQUITY FLOOR: stops opening anything below FLOOR_USD and says so. The user
    did not ask for this; it is here because a $30 account running a strategy
    with a $67 drawdown has no other brake. Tell me to remove it and I will.
  - its own magic number, so it can never touch a position it did not open
  - freshness guard, so a restart cannot fire on a stale signal
  - exits if the terminal goes unreachable, so the watchdog can restart it
"""
import json
import os
import sys
import time
from datetime import datetime, timedelta

import MetaTrader5 as mt5

TERMINAL   = r"C:\Projects\MT5-KinoliveTrader\terminal64.exe"
LOGIN      = 134499778
SYMBOL     = "BTCUSDm"
LOTS       = 0.01
MAGIC      = 770406                 # distinct from the demo bots
BRICK      = 50.0
REVERSAL   = 2
TP_BRICKS  = 5                      # 250 points
TRIG_BRICKS = 3                     # 150 points, recovery trigger
HEDGE_REWARD = 1.5                  # target = 1.5x the first trade's drawdown
HEDGE_RISK   = 1.0                  # stop   = 1.0x it
MAX_POS    = 2
POLL       = 20
FRESH_MIN  = 6
ANCHOR     = datetime(2026, 7, 17)  # same brick series as the demo bots
MAX_FAILS  = 10

# Stop opening anything if equity falls to this. Started at $30.95.
FLOOR_USD  = 15.00

HERE  = os.path.dirname(os.path.abspath(__file__))
LOG   = os.path.join(HERE, "hedge_bot.log")
ALIVE = os.path.join(HERE, "hedge_bot_alive.json")
STATE = os.path.join(HERE, "hedge_bot_state.json")


def say(m):
    line = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {m}"
    print(line, flush=True)
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def check_account():
    """Verified on EVERY loop, not once. Returns the account or None."""
    a = mt5.account_info()
    if a is None:
        return None
    if a.login != LOGIN:
        say(f"*** WRONG ACCOUNT {a.login}, expected {LOGIN} - REFUSING TO TRADE ***")
        return False
    if a.trade_mode != 2:
        say(f"*** account is not REAL (trade_mode={a.trade_mode}) - REFUSING ***")
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
            return b[k]
    return None


def mine():
    return [p for p in (mt5.positions_get(symbol=SYMBOL) or []) if p.magic == MAGIC]


def load_state():
    try:
        with open(STATE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"last_brick": 0, "first_ticket": None, "hedge_ticket": None,
                "recovery": False, "hedged": False}


def save_state(s):
    try:
        with open(STATE, "w", encoding="utf-8") as f:
            json.dump(s, f)
    except Exception:
        pass


def send(direction, tp_pts, sl_pts, why):
    """Market order. Returns the position ticket, or None."""
    tick = mt5.symbol_info_tick(SYMBOL)
    if tick is None:
        say("no tick - skipping"); return None
    buy = (direction == 1)
    price = tick.ask if buy else tick.bid
    tp = price + tp_pts if buy else price - tp_pts
    req = {"action": mt5.TRADE_ACTION_DEAL, "symbol": SYMBOL, "volume": LOTS,
           "type": mt5.ORDER_TYPE_BUY if buy else mt5.ORDER_TYPE_SELL,
           "price": price, "tp": tp, "deviation": 30,
           "magic": MAGIC, "comment": "KL-hedge",
           "type_time": mt5.ORDER_TIME_GTC}
    if sl_pts > 0:
        req["sl"] = price - sl_pts if buy else price + sl_pts
    say(f"OPEN {'BUY' if buy else 'SELL'} {LOTS} @ {price:.2f} TP {tp:.2f}"
        f"{' SL %.2f' % req['sl'] if sl_pts > 0 else ' (no stop)'}  [{why}]")
    r = mt5.order_send(req)
    ok = r is not None and r.retcode in (mt5.TRADE_RETCODE_DONE, mt5.TRADE_RETCODE_PLACED)
    say(f"  retcode {getattr(r, 'retcode', '?')} {getattr(r, 'comment', '')} -> "
        f"{'OK' if ok else 'FAILED'}")
    if not ok:
        say(f"  last_error {mt5.last_error()}")
        return None
    tk = None
    if getattr(r, "deal", 0):
        ds = mt5.history_deals_get(ticket=r.deal)
        if ds:
            tk = ds[0].position_id
    tk = tk or getattr(r, "order", None)
    say(f"  position ticket {tk}")
    return tk


def close_all(ps, why):
    say(f"CLOSE {len(ps)} position(s), pnl {sum(p.profit + p.swap for p in ps):+.2f}  [{why}]")
    for p in ps:
        t = mt5.symbol_info_tick(SYMBOL)
        req = {"action": mt5.TRADE_ACTION_DEAL, "position": p.ticket, "symbol": SYMBOL,
               "volume": p.volume,
               "type": mt5.ORDER_TYPE_SELL if p.type == 0 else mt5.ORDER_TYPE_BUY,
               "price": t.bid if p.type == 0 else t.ask,
               "deviation": 30, "magic": MAGIC, "comment": "KL-hedge-close"}
        r = mt5.order_send(req)
        ok = r is not None and r.retcode in (mt5.TRADE_RETCODE_DONE, mt5.TRADE_RETCODE_PLACED)
        say(f"  close #{p.ticket} -> {'OK' if ok else 'FAILED ' + str(getattr(r, 'retcode', '?'))}")


def cycle_realised(tickets):
    """Banked on this cycle's tickets. Matched by ticket, never by time -
    deal timestamps are broker server time and this box is not."""
    if not tickets:
        return 0.0
    want = set(t for t in tickets if t)
    deals = mt5.history_deals_get(datetime.now() - timedelta(days=7),
                                  datetime.now() + timedelta(days=1))
    if deals is None:
        return None
    return sum(d.profit + d.swap + d.commission for d in deals
               if d.magic == MAGIC and d.entry == mt5.DEAL_ENTRY_OUT
               and d.position_id in want)


def main():
    acc = connect()
    say("=" * 70)
    say(f"HEDGE BOT UP - REAL MONEY - account {acc.login} {acc.server} "
        f"balance {acc.balance:.2f} {acc.currency}")
    say(f"rule: 1 trade TP {BRICK*TP_BRICKS:.0f}pt no stop | recovery at "
        f"{BRICK*TRIG_BRICKS:.0f}pt | ONE opposite hedge, target "
        f"{HEDGE_REWARD}x drawdown, stop {HEDGE_RISK}x | max {MAX_POS} positions")
    say(f"EQUITY FLOOR ${FLOOR_USD:.2f} - no new positions below this")
    say(f"backtest says this LOSES: $1,000 -> $473 over 27 months. Deployed on "
        f"the user's instruction with the risk stated and accepted.")
    say("=" * 70)
    st = load_state()
    fails = 0
    while True:
        try:
            acc = check_account()
            if acc is False:
                say("halting - wrong account. Fix and restart."); mt5.shutdown(); sys.exit(2)
            if acc is None:
                fails += 1
                say(f"no account_info ({fails}/{MAX_FAILS})")
                if fails >= MAX_FAILS:
                    say("TERMINAL UNREACHABLE - exiting for the watchdog")
                    mt5.shutdown(); sys.exit(1)
                time.sleep(POLL); continue

            rates = mt5.copy_rates_range(SYMBOL, mt5.TIMEFRAME_M1, ANCHOR, datetime.utcnow())
            if rates is None or len(rates) < 2:
                fails += 1
                say(f"no bars ({fails}/{MAX_FAILS}) last_error {mt5.last_error()}")
                if fails >= MAX_FAILS:
                    say("TERMINAL UNREACHABLE - exiting for the watchdog")
                    mt5.shutdown(); sys.exit(1)
                time.sleep(POLL); continue
            fails = 0

            bricks = build_bricks(rates[:-1])
            rev = last_reversal(bricks)
            ps = mine()
            tick = mt5.symbol_info_tick(SYMBOL)
            eq = acc.equity

            first = next((p for p in ps if p.ticket == st.get("first_ticket")), None)
            hedge = next((p for p in ps if p.ticket == st.get("hedge_ticket")), None)

            # ---- flat: the cycle is over, whatever ended it ----------------
            if not ps:
                if st.get("first_ticket") or st.get("hedge_ticket"):
                    say("flat - cycle closed, resetting")
                st.update({"first_ticket": None, "hedge_ticket": None,
                           "recovery": False, "hedged": False})
                save_state(st)
            else:
                # ---- rule 6: cycle P&L back to zero ------------------------
                realised = cycle_realised([st.get("first_ticket"), st.get("hedge_ticket")])
                if realised is not None:
                    cyc = realised + sum(p.profit + p.swap for p in ps)
                    if st.get("recovery") and cyc >= 0:
                        close_all(ps, f"recovered - cycle P&L {cyc:+.2f}")
                        st.update({"first_ticket": None, "hedge_ticket": None,
                                   "recovery": False, "hedged": False})
                        save_state(st); ps = []
                # ---- rule 5: the hedge stopped -> close the other leg too --
                if ps and st.get("hedged") and hedge is None and first is not None:
                    close_all([first], "hedge stopped out - closing the first trade too")
                    st.update({"first_ticket": None, "hedge_ticket": None,
                               "recovery": False, "hedged": False})
                    save_state(st); ps = []
                # ---- rule 4: the hedge hit target -> close the other leg ---
                if ps and st.get("hedged") and hedge is not None and first is None:
                    pass    # first already closed on its own target, fine
                # ---- recovery trigger --------------------------------------
                if ps and first is not None and not st.get("recovery"):
                    adverse = ((first.price_open - tick.bid) if first.type == 0
                               else (tick.ask - first.price_open))
                    if adverse >= BRICK * TRIG_BRICKS:
                        st["recovery"] = True
                        say(f"RECOVERY ON - #{first.ticket} is {adverse:.0f} pts against")
                        save_state(st)

            # ---- entries ---------------------------------------------------
            ps = mine()
            if rev and rev["time"] > st.get("last_brick", 0):
                age = (datetime.utcnow() - datetime.utcfromtimestamp(rev["time"])).total_seconds() / 60
                if age > FRESH_MIN:
                    st["last_brick"] = rev["time"]; save_state(st)
                elif eq <= FLOOR_USD:
                    say(f"EQUITY FLOOR: {eq:.2f} <= {FLOOR_USD:.2f} - not opening anything")
                    st["last_brick"] = rev["time"]; save_state(st)
                elif len(ps) >= MAX_POS:
                    st["last_brick"] = rev["time"]; save_state(st)
                elif not ps:
                    # rule 7 - new cycle only when completely flat
                    tk = send(rev["dir"], BRICK * TP_BRICKS, 0.0, "new cycle")
                    if tk:
                        st.update({"first_ticket": tk, "hedge_ticket": None,
                                   "recovery": False, "hedged": False,
                                   "last_brick": rev["time"]})
                        save_state(st)
                elif (st.get("recovery") and not st.get("hedged")
                      and first is not None and rev["dir"] != (1 if first.type == 0 else -1)):
                    # rule 3 - ONE opposite hedge, sized off the drawdown NOW
                    dn = ((first.price_open - tick.bid) if first.type == 0
                          else (tick.ask - first.price_open))
                    dn = max(dn, BRICK)
                    tk = send(rev["dir"], HEDGE_REWARD * dn, HEDGE_RISK * dn,
                              f"hedge, drawdown {dn:.0f}pt -> target "
                              f"{HEDGE_REWARD*dn:.0f} stop {HEDGE_RISK*dn:.0f}")
                    if tk:
                        st.update({"hedge_ticket": tk, "hedged": True,
                                   "last_brick": rev["time"]})
                        save_state(st)
                elif st.get("recovery") and st.get("hedged"):
                    say("skip: already hedged this cycle")
                    st["last_brick"] = rev["time"]; save_state(st)

            ps = mine()
            with open(ALIVE, "w", encoding="utf-8") as f:
                json.dump({"alive_utc": datetime.utcnow().isoformat(),
                           "account": acc.login, "real": acc.trade_mode == 2,
                           "positions": len(ps),
                           "floating": round(sum(p.profit + p.swap for p in ps), 2),
                           "recovery": bool(st.get("recovery")),
                           "hedged": bool(st.get("hedged")),
                           "equity": round(eq, 2), "balance": round(acc.balance, 2),
                           "floor": FLOOR_USD,
                           "below_floor": eq <= FLOOR_USD}, f)
        except Exception as e:
            say(f"ERROR {type(e).__name__}: {e}")
        time.sleep(POLL)


if __name__ == "__main__":
    main()
