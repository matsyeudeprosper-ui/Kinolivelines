"""Mirror a KinoliveLines order onto account 134499778 with the direction flipped.

THIS TOUCHES REAL MONEY. Account 134499778 sits on Exness-MT5Real9 with trade_mode 2.
Every guard below exists because of that and none of them should be relaxed.

WHY IT IS A SEPARATE FILE. act.py refuses any account whose trade_mode is not 0, and
that refusal protects the demo loop from a misconfiguration - it is consulted by the
daemon, by GPT-5 on failover, and by any future session. Removing it to allow one live
experiment would strip that protection from everything. So the live path lives here,
with a HARD whitelist of exactly one account number, and act.py keeps its guard intact.

WHAT MIRRORING DOES TO THE ARITHMETIC, recorded so nobody has to rediscover it:
the two accounts are exact mirrors, so precisely one of them wins on every trade.

    price reaches the target   ->  main +$1.00, mirror -$2.00   = -$1.00
    price reaches the stop     ->  main -$2.00, mirror +$1.00   = -$1.00

There is no third outcome. The pair loses $1.00 every time, because the winning side
collects $1 while the losing side pays $2. Each account independently loses one spread
per trade, so running two of them loses two spreads instead of one. Mirroring cannot
offset the loss; it doubles it. The user was shown this and chose to proceed on a $42.70
balance, which funds roughly eleven days at the observed trade rate.

THE FLIP. A mirror must trigger at the SAME price as the original, so the order type
changes as well as the side:

    BUY_LIMIT  @ E  (rests below)  ->  SELL_STOP  @ E  (rests below)
    SELL_LIMIT @ E  (rests above)  ->  BUY_STOP   @ E  (rests above)
    BUY_STOP   @ E                 ->  SELL_LIMIT @ E
    SELL_STOP  @ E                 ->  BUY_LIMIT  @ E

Stop and target are reflected through the entry: new = 2E - old. For a BUY at E with
SL E-40 and TP E+20 that gives a SELL at E with SL E+40 and TP E-20, which is the
mirror image and keeps the same $2 risk and $1 reward.

  python mirror.py pend BUY_LIMIT 63006 62966 63026 0.05 "reason"
  python mirror.py cancel <ticket> "reason"
"""
import MetaTrader5 as mt5, sys, os, csv
from datetime import datetime

TERMINAL = r"C:\Projects\MT5-KinoliveTrader\terminal64.exe"
MIRROR_LOGIN = 134499778          # the ONLY account this file may ever touch
FORBIDDEN = {436771046}           # the demo loop's account - never mirror onto itself
SYM = "BTCUSDm"
MAX_LOTS = 0.05
LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mirror_decisions.csv")

FLIP = {"BUY_LIMIT": "SELL_STOP", "SELL_LIMIT": "BUY_STOP",
        "BUY_STOP": "SELL_LIMIT", "SELL_STOP": "BUY_LIMIT"}
TYPES = {"BUY_LIMIT": mt5.ORDER_TYPE_BUY_LIMIT, "SELL_LIMIT": mt5.ORDER_TYPE_SELL_LIMIT,
         "BUY_STOP": mt5.ORDER_TYPE_BUY_STOP, "SELL_STOP": mt5.ORDER_TYPE_SELL_STOP}


def log(action, detail, reason):
    new = not os.path.exists(LOG) or os.path.getsize(LOG) == 0
    with open(LOG, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["time", "action", "detail", "reason", "account"])
        w.writerow([datetime.now().isoformat(timespec="seconds"), action, detail,
                    reason, MIRROR_LOGIN])


def connect():
    if not mt5.initialize(path=TERMINAL):
        raise SystemExit("mirror: initialize failed %s" % (mt5.last_error(),))
    a = mt5.account_info()
    if a is None:
        mt5.shutdown(); raise SystemExit("mirror: no account info")
    # The whitelist is the whole safety model here. An account that is not exactly
    # 134499778 gets nothing, whether it is real, demo, or the main loop's own.
    if a.login != MIRROR_LOGIN:
        mt5.shutdown()
        raise SystemExit("mirror: REFUSING - terminal is on %d, whitelist is %d"
                         % (a.login, MIRROR_LOGIN))
    if a.login in FORBIDDEN:
        mt5.shutdown(); raise SystemExit("mirror: REFUSING - that is the demo loop account")
    return a


cmd = sys.argv[1] if len(sys.argv) > 1 else ""
acc = connect()
mt5.symbol_select(SYM, True)
tick = mt5.symbol_info_tick(SYM)
print("mirror: account %d (%s) balance %.2f  bid %.2f ask %.2f"
      % (acc.login, acc.server, acc.balance, tick.bid, tick.ask))

if cmd == "pend":
    otype, price, sl, tp, lots, reason = (sys.argv[2].upper(), float(sys.argv[3]),
                                          float(sys.argv[4]), float(sys.argv[5]),
                                          float(sys.argv[6]), sys.argv[7])
    if otype not in FLIP:
        mt5.shutdown(); raise SystemExit("mirror: unknown order type %s" % otype)
    if lots > MAX_LOTS:
        mt5.shutdown(); raise SystemExit("mirror: %s lots over cap %s" % (lots, MAX_LOTS))

    m_type = FLIP[otype]
    m_sl, m_tp = 2 * price - sl, 2 * price - tp        # reflect through the entry
    is_buy = m_type.startswith("BUY")
    if is_buy and not (m_sl < price < m_tp):
        mt5.shutdown(); raise SystemExit("mirror: BUY needs sl<%s<tp, got %s/%s" % (price, m_sl, m_tp))
    if not is_buy and not (m_tp < price < m_sl):
        mt5.shutdown(); raise SystemExit("mirror: SELL needs tp<%s<sl, got %s/%s" % (price, m_tp, m_sl))

    # the mirrored type must still rest on a legal side of THIS terminal's market
    legal = {"BUY_LIMIT": price < tick.ask, "SELL_LIMIT": price > tick.bid,
             "BUY_STOP": price > tick.ask, "SELL_STOP": price < tick.bid}[m_type]
    if not legal:
        log("FAILED:SIDE", "%s @ %s vs bid %s ask %s" % (m_type, price, tick.bid, tick.ask), reason)
        mt5.shutdown()
        raise SystemExit("mirror: %s @ %s is on the wrong side of this market" % (m_type, price))

    risk = abs(price - m_sl) * lots
    rew = abs(m_tp - price) * lots
    print("mirror: %s -> %s @ %s  SL %s  TP %s  |  risk $%.2f  reward $%.2f"
          % (otype, m_type, price, m_sl, m_tp, risk, rew))
    r = mt5.order_send({"action": mt5.TRADE_ACTION_PENDING, "symbol": SYM, "volume": lots,
                        "type": TYPES[m_type], "price": price, "sl": m_sl, "tp": m_tp,
                        "type_time": mt5.ORDER_TIME_GTC, "comment": "KL-mirror"})
    ok = r.retcode in (mt5.TRADE_RETCODE_DONE, mt5.TRADE_RETCODE_PLACED)
    print("mirror: retcode %s %s -> %s" % (r.retcode, r.comment, "OK" if ok else "FAILED"))
    log("MIRROR_PEND" if ok else "FAILED:MIRROR_PEND",
        "ticket %s %s %s @ %s SL %s TP %s (flipped from %s)"
        % (getattr(r, "order", "?"), m_type, lots, price, m_sl, m_tp, otype), reason)

elif cmd == "cancel":
    ticket, reason = int(sys.argv[2]), sys.argv[3]
    r = mt5.order_send({"action": mt5.TRADE_ACTION_REMOVE, "order": ticket})
    ok = r.retcode in (mt5.TRADE_RETCODE_DONE, mt5.TRADE_RETCODE_PLACED)
    print("mirror: cancel #%d -> %s" % (ticket, "OK" if ok else "FAILED"))
    log("MIRROR_CANCEL" if ok else "FAILED:MIRROR_CANCEL", "#%d" % ticket, reason)

else:
    print(__doc__)
mt5.shutdown()
