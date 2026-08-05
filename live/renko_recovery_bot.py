"""renko_recovery_bot.py - the CAPPED RECOVERY design, on the DEMO account.

THE RULE (user's design + the cap that makes it survive)
  1. a reversal brick opens ONE trade, take profit 5 bricks (250 pts)
  2. wins  -> banked, new cycle
  3. price goes 3 bricks (150 pts) against it -> do NOT close. Enter RECOVERY.
  4. in recovery, each new reversal adds another 0.01 lot, up to MAX_BASKET
  5. equity back to where the cycle started -> close everything, new cycle
  6. basket would exceed MAX_BASKET -> close everything at a loss, new cycle

Step 6 is the difference between living and dying. Without it the same design
ran 5.2 years and then died: recovery succeeded 743 times out of 744, and the
single failure took the whole account. Capped at 4, recovery succeeded 3,626
times and was force-closed for a small loss 266 times - those 266 losses are
what buys the survival.

BACKTEST, 7.6 years of H1, recorded here so live results are read honestly:
  $1,000 -> $3,631 (+263%), 83% of months profitable, max drawdown $384,
  equity never fell below the starting $1,000. Median month only +$9 - this
  grows slowly by compounding, it does not earn much month to month.
  Every cap from 2 to 12 survived and profited (+131% to +263%), so this is a
  broad plateau rather than one tuned setting - unlike the TP/SL search, where
  the best cell was matched by shuffled data.
  H1 bricks are coarser than the M1 this bot uses, so live trade counts and
  timing will differ. The risk SHAPE is what was tested, not the exact return.

NO BROKER STOP LOSS. Positions carry a take profit but no stop, because the
exit logic lives here. If this process dies while holding a basket, those
positions sit unmanaged until it restarts. That is the main operational risk
and the reason for the heartbeat file.

2026-08-05 FIX - "recovered" used to mean the wrong thing.
Rule 5 says close when the money is back to where the cycle started. The
original code tested mt5.account_info().equity, which is the WHOLE ACCOUNT -
including renko_bot.py's positions and its realised wins and losses. The two
bots share account 436771046, so the other bot's P&L decided this bot's exits.
It happened live on 2026-08-04: this bot's basket was -$1.13, the plain bot
banked +$2.46 at 19:05, account equity touched the target, and the basket was
closed at a LOSS while the rule said it should close at zero or better.
The reverse is the dangerous case - when the plain bot is losing, the target
becomes unreachable and this bot holds its basket LONGER than the rule allows,
adding positions toward the cap. The backtest never saw any of this because the
simulation had only one strategy in it.
Now the cycle is measured from THIS BOT'S OWN money only: every position opened
in the cycle is tracked by ticket, and cycle P&L = realised on those tickets +
floating on the ones still open. Nothing else on the account can move it.
"""
import json, os, time
from datetime import datetime, timedelta

import MetaTrader5 as mt5

TERMINAL    = r"C:\Program Files\MetaTrader 5\terminal64.exe"
LOGIN       = 436771046
SYMBOL      = "BTCUSDm"
LOTS        = 0.01
MAGIC       = 770405            # distinct from renko_bot's 770404
BRICK       = 50.0
REVERSAL    = 2
TP_BRICKS   = 5
SL_BRICKS   = 3                 # a TRIGGER level, not a broker stop
MAX_BASKET  = 4
POLL        = 20
FRESH_MIN   = 6
ANCHOR      = datetime(2026, 7, 17)

HERE  = os.path.dirname(os.path.abspath(__file__))
LOG   = os.path.join(HERE, "renko_recovery.log")
ALIVE = os.path.join(HERE, "renko_recovery_alive.json")
STATE = os.path.join(HERE, "renko_recovery_state.json")


def say(m):
    line = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {m}"
    print(line, flush=True)
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def connect():
    if not mt5.initialize(path=TERMINAL):
        raise SystemExit(f"initialize failed: {mt5.last_error()}")
    a = mt5.account_info()
    if a is None or a.login != LOGIN:
        mt5.shutdown(); raise SystemExit(f"WRONG ACCOUNT {a.login if a else None}")
    if a.trade_mode != 0:
        mt5.shutdown(); raise SystemExit("NOT A DEMO ACCOUNT - refusing to trade")
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


def basket_pnl(ps):
    return sum(p.profit + p.swap for p in ps)


def cycle_realised(tickets):
    """Money already banked on THIS cycle's positions - the ones that hit their
    own take profit and left, plus anything closed by hand.

    Matched by position ticket, never by time. Deal timestamps are in BROKER
    server time while datetime.now() here is box time, and comparing the two
    silently drops or double-counts deals whenever the offset is not zero.
    The window below only has to be wide enough to contain the cycle."""
    if not tickets:
        return 0.0
    want = set(tickets)
    deals = mt5.history_deals_get(datetime.now() - timedelta(days=7),
                                  datetime.now() + timedelta(days=1))
    if deals is None:
        return None                     # unknown - caller must not act on it
    return sum(d.profit + d.swap + d.commission for d in deals
               if d.magic == MAGIC and d.entry == mt5.DEAL_ENTRY_OUT
               and d.position_id in want)


def load_state():
    try:
        with open(STATE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"last_brick": 0, "recovery": False, "cycle_equity": None,
                "cycle_tickets": []}


def save_state(s):
    try:
        with open(STATE, "w", encoding="utf-8") as f:
            json.dump(s, f)
    except Exception:
        pass


def open_one(direction, why):
    """Returns the POSITION ticket on success, None on failure. The ticket is
    what ties the position to this cycle, so a failure to resolve it has to be
    treated as a failure to open - an untracked position would sit outside the
    cycle P&L and never be counted."""
    tick = mt5.symbol_info_tick(SYMBOL)
    if tick is None:
        return None
    buy = (direction == 1)
    price = tick.ask if buy else tick.bid
    tp = price + BRICK * TP_BRICKS if buy else price - BRICK * TP_BRICKS
    req = {"action": mt5.TRADE_ACTION_DEAL, "symbol": SYMBOL, "volume": LOTS,
           "type": mt5.ORDER_TYPE_BUY if buy else mt5.ORDER_TYPE_SELL,
           "price": price, "tp": tp,           # NO sl - the exit logic is here
           "deviation": 30, "magic": MAGIC, "comment": "KL-recov",
           "type_time": mt5.ORDER_TIME_GTC}
    say(f"OPEN {'BUY' if buy else 'SELL'} {LOTS} @ {price:.2f} TP {tp:.2f}  [{why}]")
    r = mt5.order_send(req)
    ok = r is not None and r.retcode in (mt5.TRADE_RETCODE_DONE, mt5.TRADE_RETCODE_PLACED)
    say(f"  retcode {getattr(r,'retcode','?')} -> {'OK' if ok else 'FAILED'}")
    if not ok:
        return None
    ticket = None
    if getattr(r, "deal", 0):
        ds = mt5.history_deals_get(ticket=r.deal)
        if ds:
            ticket = ds[0].position_id
    if ticket is None:
        ticket = getattr(r, "order", None) or None   # market fills reuse the id
    if ticket is None:
        say("  WARNING could not resolve position ticket - not tracked in cycle")
    else:
        say(f"  position ticket {ticket}")
    return ticket


def close_all(ps, why):
    say(f"CLOSE BASKET of {len(ps)}  pnl {basket_pnl(ps):+.2f}  [{why}]")
    for p in ps:
        t = mt5.symbol_info_tick(SYMBOL)
        req = {"action": mt5.TRADE_ACTION_DEAL, "position": p.ticket, "symbol": SYMBOL,
               "volume": p.volume,
               "type": mt5.ORDER_TYPE_SELL if p.type == 0 else mt5.ORDER_TYPE_BUY,
               "price": t.bid if p.type == 0 else t.ask,
               "deviation": 30, "magic": MAGIC, "comment": "KL-recov-close"}
        r = mt5.order_send(req)
        ok = r is not None and r.retcode in (mt5.TRADE_RETCODE_DONE, mt5.TRADE_RETCODE_PLACED)
        say(f"  close #{p.ticket} -> {'OK' if ok else 'FAILED ' + str(getattr(r,'retcode','?'))}")


def main():
    acc = connect()
    say(f"recovery bot up | {SYMBOL} | {acc.login} DEMO | equity {acc.equity:.2f}")
    say(f"rule: TP {TP_BRICKS} bricks, recovery at {SL_BRICKS} bricks, "
        f"MAX BASKET {MAX_BASKET}, {LOTS} lots, magic {MAGIC}")
    say("exit: OWN cycle P&L back to 0.00 (realised on this cycle's tickets + "
        "floating). Account equity is no longer used - the other bot's P&L "
        "used to move it.")
    st = load_state()
    while True:
        try:
            rates = mt5.copy_rates_range(SYMBOL, mt5.TIMEFRAME_M1, ANCHOR, datetime.utcnow())
            if rates is None or len(rates) < 2:
                time.sleep(POLL); continue
            bricks = build_bricks(rates[:-1])
            rev = last_reversal(bricks)
            ps = mine()
            eq = mt5.account_info().equity

            # This bot's own cycle P&L: banked on this cycle's tickets, plus
            # what is still floating. NOT account equity - see the 2026-08-05
            # note at the top of this file.
            tickets = st.get("cycle_tickets") or []
            if ps and not tickets:
                # Restarted holding positions with no ticket list (state file
                # lost or pre-fix). Adopt what is open so the cycle is at least
                # measurable; anything banked before the restart is gone from
                # the count, so say so rather than pretend the number is clean.
                tickets = [p.ticket for p in ps]
                st["cycle_tickets"] = tickets
                say(f"adopted {len(tickets)} untracked position(s) into the cycle "
                    f"- realised P&L before this restart is not counted")
                save_state(st)
            realised = cycle_realised(tickets)
            cyc = None if realised is None else realised + basket_pnl(ps)

            if not ps:
                # flat: this is where a new cycle begins
                st["recovery"] = False
                st["cycle_equity"] = eq
                st["cycle_tickets"] = []
                save_state(st)
            else:
                # has anything gone SL_BRICKS against us? -> recovery
                if not st.get("recovery"):
                    tick = mt5.symbol_info_tick(SYMBOL)
                    for p in ps:
                        adverse = (p.price_open - tick.bid) if p.type == 0 else (tick.ask - p.price_open)
                        if adverse >= BRICK * SL_BRICKS:
                            st["recovery"] = True
                            shown = "unknown" if cyc is None else f"{cyc:+.2f}"
                            say(f"RECOVERY ON - #{p.ticket} is {adverse:.0f} pts "
                                f"against; own cycle P&L {shown}, recovering to 0.00")
                            save_state(st); break
                # exit conditions. cyc is None only when the deal history could
                # not be read - hold rather than guess, the next poll retries.
                if st.get("recovery") and cyc is not None and cyc >= 0:
                    close_all(ps, f"recovered - own cycle P&L {cyc:+.2f} "
                                  f"(realised {realised:+.2f} + floating {basket_pnl(ps):+.2f})")
                    st["recovery"] = False; st["cycle_equity"] = None
                    st["cycle_tickets"] = []; save_state(st)
                    ps = []
                elif len(ps) > MAX_BASKET:
                    close_all(ps, f"basket cap {MAX_BASKET} exceeded - taking the loss"
                                  + (f", cycle P&L {cyc:+.2f}" if cyc is not None else ""))
                    st["recovery"] = False; st["cycle_equity"] = None
                    st["cycle_tickets"] = []; save_state(st)
                    ps = []

            # entries: one when flat, more only while recovering
            if rev and rev["time"] > st.get("last_brick", 0):
                age = (datetime.utcnow() - datetime.utcfromtimestamp(rev["time"])).total_seconds() / 60
                if age <= FRESH_MIN:
                    ps = mine()
                    if not ps:
                        # a new cycle starts with an empty ticket list, so its
                        # P&L begins at exactly zero
                        st["cycle_tickets"] = []
                        tk = open_one(rev["dir"], "new cycle")
                        if tk:
                            st["last_brick"] = rev["time"]; st["cycle_equity"] = eq
                            st["cycle_tickets"] = [tk]
                    elif st.get("recovery") and len(ps) <= MAX_BASKET:
                        tk = open_one(rev["dir"], f"recovery add #{len(ps)+1}")
                        if tk:
                            st["last_brick"] = rev["time"]
                            st["cycle_tickets"] = (st.get("cycle_tickets") or []) + [tk]
                    save_state(st)
                else:
                    st["last_brick"] = rev["time"]; save_state(st)

            ps = mine()
            realised = cycle_realised(st.get("cycle_tickets") or [])
            cyc = None if realised is None else realised + basket_pnl(ps)
            with open(ALIVE, "w", encoding="utf-8") as f:
                json.dump({"alive_utc": datetime.utcnow().isoformat(),
                           "positions": len(ps), "basket_pnl": round(basket_pnl(ps), 2),
                           "recovery": bool(st.get("recovery")),
                           "cycle_pnl": None if cyc is None else round(cyc, 2),
                           "cycle_realised": None if realised is None else round(realised, 2),
                           "cycle_tickets": len(st.get("cycle_tickets") or []),
                           "cycle_equity": st.get("cycle_equity"),
                           "equity": eq}, f)
        except Exception as e:
            say(f"ERROR {type(e).__name__}: {e}")
        time.sleep(POLL)


if __name__ == "__main__":
    main()
