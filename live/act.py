"""Guarded actions on the BTCUSDm demo account. Every path verifies the
account, re-reads state after acting, and logs the decision with its reason.

  python act.py pend  BUY_LIMIT 64700 64600 64900 0.01 "reason"
  python act.py sltp  <ticket> <sl> <tp> "reason"
  python act.py close <ticket> "reason"
  python act.py cancel <order_ticket> "reason"
  python act.py note  NO_ACTION|WATCH "detail" "reason"
"""
import MetaTrader5 as mt5, sys, os, csv
from datetime import datetime

TERMINAL = r"C:\Program Files\MetaTrader 5\terminal64.exe"
LOGIN    = 436771046
SYM      = "BTCUSDm"
MAX_LOTS = 0.05                     # hard ceiling; nothing larger ever goes out
LOG      = os.path.join(os.path.dirname(os.path.abspath(__file__)), "decisions.csv")

ORDER_TYPES = {"BUY_LIMIT": mt5.ORDER_TYPE_BUY_LIMIT, "SELL_LIMIT": mt5.ORDER_TYPE_SELL_LIMIT,
               "BUY_STOP":  mt5.ORDER_TYPE_BUY_STOP,  "SELL_STOP":  mt5.ORDER_TYPE_SELL_STOP}

def log(action, detail, reason):
    """Append the decision, stamped with whoever ordered it.

    act.py runs as a SEPARATE process, so it cannot see brain.py's in-memory
    provider. brain.run_act() passes it through the environment instead. A bare
    hand-run of act.py has no stamp and is recorded as 'manual', which is the
    honest answer - it was a human decision, not an API one.

    This must stay in step with brain.DECISION_COLS. When the provider columns
    were added to brain.py alone, act.py kept writing 4 columns into a 6 column
    file, so every real ORDER - the rows that matter most - came out with no
    attribution while the no_action rows around them had it."""
    prov = os.environ.get("KL_DECIDER_PROVIDER") or "manual"
    mdl = os.environ.get("KL_DECIDER_MODEL") or "manual"
    new = not os.path.exists(LOG) or os.path.getsize(LOG) == 0
    with open(LOG, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new: w.writerow(["time", "action", "detail", "reason", "provider", "model"])
        w.writerow([datetime.now().isoformat(timespec="seconds"), action, detail, reason,
                    prov, mdl])

def connect():
    if not mt5.initialize(path=TERMINAL):
        raise SystemExit(f"initialize failed: {mt5.last_error()}")
    a = mt5.account_info()
    if a.login != LOGIN:
        mt5.shutdown(); raise SystemExit(f"WRONG ACCOUNT {a.login}, expected {LOGIN}")
    if a.trade_mode != 0:
        mt5.shutdown(); raise SystemExit("NOT A DEMO ACCOUNT - refusing to trade")
    return a

def send(req, what):
    print(f"sending: {req}")
    r = mt5.order_send(req)
    ok = r.retcode in (mt5.TRADE_RETCODE_DONE, mt5.TRADE_RETCODE_PLACED)
    print(f"retcode {r.retcode}  {r.comment}  ->  {'OK' if ok else 'FAILED'}")
    if not ok: print(f"last_error {mt5.last_error()}")
    return ok, r

cmd = sys.argv[1] if len(sys.argv) > 1 else ""
acc = connect()
tick = mt5.symbol_info_tick(SYM)
print(f"account {acc.login} DEMO  equity {acc.equity:,.2f}   bid {tick.bid} ask {tick.ask}")

if cmd == "pend":
    otype, price, sl, tp, lots, reason = (sys.argv[2], float(sys.argv[3]), float(sys.argv[4]),
                                          float(sys.argv[5]), float(sys.argv[6]), sys.argv[7])
    if lots > MAX_LOTS: mt5.shutdown(); raise SystemExit(f"lots {lots} over cap {MAX_LOTS}")
    if otype not in ORDER_TYPES: mt5.shutdown(); raise SystemExit(f"bad type {otype}")
    is_buy = otype.startswith("BUY")
    # stop and target must straddle the entry on the correct sides
    if is_buy and not (sl < price < tp): mt5.shutdown(); raise SystemExit(f"BUY needs sl<{price}<tp")
    if not is_buy and not (tp < price < sl): mt5.shutdown(); raise SystemExit(f"SELL needs tp<{price}<sl")

    # The entry must be on the side of the market its order type can actually
    # rest on. A limit waits for a BETTER price, a stop waits for a WORSE one, so
    # each has exactly one legal side and the broker rejects the rest with an
    # opaque "10015 Invalid price". On 2026-07-31 06:07 a SELL_LIMIT was sent at
    # 63,886.75 while bid was 63,894.55 - price had already risen through the
    # resistance, so the level was BEHIND the market and could never be sold into.
    # Catching it here turns a bare broker rejection into a message that says what
    # to do instead, which matters because a model told only "FAILED" may retry.
    side_rule = {
        "BUY_LIMIT":  (price < tick.ask, f"BUY_LIMIT must rest BELOW ask {tick.ask}"),
        "SELL_LIMIT": (price > tick.bid, f"SELL_LIMIT must rest ABOVE bid {tick.bid}"),
        "BUY_STOP":   (price > tick.ask, f"BUY_STOP must rest ABOVE ask {tick.ask}"),
        "SELL_STOP":  (price < tick.bid, f"SELL_STOP must rest BELOW bid {tick.bid}"),
    }[otype]
    if not side_rule[0]:
        alt = ("BUY_STOP" if otype == "BUY_LIMIT" else "SELL_STOP" if otype == "SELL_LIMIT"
               else "BUY_LIMIT" if otype == "BUY_STOP" else "SELL_LIMIT")
        msg = (f"REJECTED: {side_rule[1]}, but you sent {price}. Price has already "
               f"passed through that level, so it is behind the market and this order "
               f"can never rest there. Either use a {alt} if you still want that "
               f"direction, pick a level price has not yet reached, or take no trade. "
               f"Do NOT resend the same price - it will fail again.")
        log(f"FAILED:{otype}", f"@ {price} SL {sl} TP {tp} (wrong side of market)", reason)
        print(msg); mt5.shutdown(); raise SystemExit(msg)

    # Brokers also enforce a minimum distance from market for pending orders.
    si = mt5.symbol_info(SYM)
    stops_pts = (si.trade_stops_level or 0) * si.point if si else 0
    if stops_pts and abs(price - (tick.ask if is_buy else tick.bid)) < stops_pts:
        msg = (f"REJECTED: entry {price} is inside the broker's minimum pending "
               f"distance of {stops_pts:.2f} from market. Move it further out or take no trade.")
        log(f"FAILED:{otype}", f"@ {price} (inside {stops_pts:.2f} stops level)", reason)
        print(msg); mt5.shutdown(); raise SystemExit(msg)
    risk, rew = abs(price-sl), abs(tp-price)
    print(f"risk {risk:,.2f}px = ${risk*lots:,.2f} ({risk*lots/acc.equity*100:.2f}% eq) | "
          f"reward {rew:,.2f}px = ${rew*lots:,.2f} | R:R {rew/risk:.2f}:1")
    ok, r = send({"action": mt5.TRADE_ACTION_PENDING, "symbol": SYM, "volume": lots,
                  "type": ORDER_TYPES[otype], "price": price, "sl": sl, "tp": tp,
                  "type_time": mt5.ORDER_TIME_GTC, "comment": "KL-auto"}, "pending")
    # Log the attempt either way. Logging only successes lost the reasoning behind
    # every rejected order - on 2026-07-31 a broker-rejected SELL_LIMIT left no row
    # in decisions.csv at all, so the trade record silently omitted a decision that
    # was actually made. A failure is part of the record.
    if ok:
        log("PEND", f"{otype} {lots} @ {price} SL {sl} TP {tp} R:R {rew/risk:.2f}", reason)
        print(f"\nresting orders now: {mt5.orders_total()}")
    else:
        log("FAILED:PEND", f"{otype} {lots} @ {price} SL {sl} TP {tp} "
                           f"retcode {getattr(r, 'retcode', '?')}", reason)

elif cmd == "sltp":
    ticket, sl, tp, reason = int(sys.argv[2]), float(sys.argv[3]), float(sys.argv[4]), sys.argv[5]
    pos = mt5.positions_get(ticket=ticket)
    if not pos: mt5.shutdown(); raise SystemExit(f"position {ticket} not found")
    p = pos[0]
    if p.type == 0 and not (sl < tick.bid): mt5.shutdown(); raise SystemExit("BUY sl must be below bid")
    if p.type == 1 and not (sl > tick.ask): mt5.shutdown(); raise SystemExit("SELL sl must be above ask")
    ok, r = send({"action": mt5.TRADE_ACTION_SLTP, "position": ticket,
                  "symbol": SYM, "sl": sl, "tp": tp}, "sltp")
    if ok:
        v = mt5.positions_get(ticket=ticket)[0]
        print(f"CONFIRMED #{v.ticket} SL {v.sl} TP {v.tp} P&L {v.profit:+.2f}")
        log("SLTP", f"#{ticket} SL {v.sl} TP {v.tp}", reason)

elif cmd == "close":
    ticket, reason = int(sys.argv[2]), sys.argv[3]
    pos = mt5.positions_get(ticket=ticket)
    if not pos: mt5.shutdown(); raise SystemExit(f"position {ticket} not found")
    p = pos[0]
    ok, r = send({"action": mt5.TRADE_ACTION_DEAL, "position": ticket, "symbol": SYM,
                  "volume": p.volume,
                  "type": mt5.ORDER_TYPE_SELL if p.type == 0 else mt5.ORDER_TYPE_BUY,
                  "price": tick.bid if p.type == 0 else tick.ask,
                  "deviation": 20, "comment": "KL-close"}, "close")
    if ok:
        log("CLOSE", f"#{ticket} @ {r.price} pnl {p.profit:+.2f}", reason)
        print(f"closed. open positions now: {mt5.positions_total()}")

elif cmd == "cancel":
    ticket, reason = int(sys.argv[2]), sys.argv[3]
    ok, r = send({"action": mt5.TRADE_ACTION_REMOVE, "order": ticket}, "cancel")
    if ok:
        log("CANCEL", f"#{ticket}", reason)
        print(f"resting orders now: {mt5.orders_total()}")
elif cmd == "note":
    # Deciding NOT to trade is a decision and belongs in the record. Without this
    # the journal only ever showed the trades taken, which makes every later
    # "was skipping right?" question unanswerable - the skipped setups left no
    # trace, and the provider attribution on them was lost too.
    action = sys.argv[2].upper()
    if action not in ("NO_ACTION", "WATCH"):
        raise SystemExit("note action must be NO_ACTION or WATCH")
    log(action, sys.argv[3], sys.argv[4])
    print(f"logged {action}")
else:
    print(__doc__)
mt5.shutdown()
