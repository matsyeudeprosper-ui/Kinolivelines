"""h1_opposite_bot.py (owner 2026-11-20) - real account 223985697 (nest id "kino", "Mike"), BTCUSD 0.01.

The owner's rules, exactly:
  1. At the start of every new hour (the H1 candle just closed), open a trade OPPOSITE to that candle:
     closed bullish -> SELL, closed bearish -> BUY (a flat candle: nothing).
  2. No stop-loss. Take-profit = +1 $ on the trade.
  3. Exit against us on an M1 CLOSE beyond the closed H1 candle: a SELL closes when an M1 candle closes above that
     candle's HIGH; a BUY closes when an M1 candle closes below its LOW.
  4. At the next H1 open the trade still open is closed (win or loss) and the next one starts.

Only positions with this bot's MAGIC are ever touched. Log: live/h1_opposite_bot.log, state: live/h1_opposite_state.json
(survives a restart: a restart mid-hour keeps managing the open trade and waits for the next hour to open a new one).
Started by boot_all.ps1 (also while VALERE_ONLY.flag exists - owner 11-20: this bot auto-restarts).
"""
import json
import os
import sys
import time

import MetaTrader5 as mt5

HERE = os.path.dirname(os.path.abspath(__file__))
LOG = os.path.join(HERE, "h1_opposite_bot.log")
STATE = os.path.join(HERE, "h1_opposite_state.json")
NEST_ID = "kino"
SYMBOL = "BTCUSD"
VOLUME = 0.01
TP_USD = 1.0
MAGIC = 2026112001
COMMENT = "H1opp"


def say(m):
    line = time.strftime("%Y-%m-%d %H:%M:%S UTC ", time.gmtime()) + m
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass
    print(line, flush=True)


def load_state():
    try:
        return json.load(open(STATE, encoding="utf-8"))
    except Exception:
        return {}


def save_state(s):
    tmp = STATE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(s, f, indent=1)
    os.replace(tmp, STATE)


def account():
    users = json.load(open(os.path.join(HERE, "owl_nest_users.json"), encoding="utf-8"))
    u = next(x for x in users if x.get("id") == NEST_ID)
    return u["terminal"], int(u["mt5_login"]), u["mt5_password"], u["mt5_server"]


def connect():
    term, login, pw, server = account()
    if not mt5.initialize(path=term, login=login, password=pw, server=server, timeout=60000):
        raise RuntimeError("MT5 init failed: %s" % (mt5.last_error(),))
    ai = mt5.account_info()
    if not ai or ai.login != login:
        raise RuntimeError("wrong account %s" % (ai,))
    if not mt5.symbol_select(SYMBOL, True):
        raise RuntimeError("symbol %s not available" % SYMBOL)
    say("connected %s %s balance %.2f" % (ai.login, ai.server, ai.balance))


def my_positions():
    return [p for p in (mt5.positions_get(symbol=SYMBOL) or []) if p.magic == MAGIC]


def fillings():
    info = mt5.symbol_info(SYMBOL)
    fm = int(getattr(info, "filling_mode", 0) or 0)
    out = []
    if fm & 1:
        out.append(mt5.ORDER_FILLING_FOK)
    if fm & 2:
        out.append(mt5.ORDER_FILLING_IOC)
    out.append(mt5.ORDER_FILLING_RETURN)
    return out


def send(req):
    last = None
    for f in fillings():
        req["type_filling"] = f
        r = mt5.order_send(req)
        last = r
        if r is not None and r.retcode in (mt5.TRADE_RETCODE_DONE, mt5.TRADE_RETCODE_PLACED):
            return r
        if r is not None and r.retcode != mt5.TRADE_RETCODE_INVALID_FILL:
            break
    return last


def close(p, why):
    tick = mt5.symbol_info_tick(SYMBOL)
    buy = p.type == mt5.POSITION_TYPE_BUY
    r = send({"action": mt5.TRADE_ACTION_DEAL, "symbol": SYMBOL, "volume": p.volume, "position": p.ticket,
              "type": mt5.ORDER_TYPE_SELL if buy else mt5.ORDER_TYPE_BUY, "price": tick.bid if buy else tick.ask,
              "deviation": 200, "magic": MAGIC, "comment": COMMENT})
    ok = r is not None and r.retcode == mt5.TRADE_RETCODE_DONE
    say("CLOSE %s #%d (%s) profit %.2f -> %s" % ("BUY" if buy else "SELL", p.ticket, why, p.profit,
                                                  "ok" if ok else "FAILED %s" % (r and (r.retcode, r.comment),)))
    return ok


def tp_price(side, entry):
    """the price where this trade makes +TP_USD (the broker's own profit formula)"""
    otype = mt5.ORDER_TYPE_BUY if side == "BUY" else mt5.ORDER_TYPE_SELL
    one = mt5.order_calc_profit(otype, SYMBOL, VOLUME, entry, entry + (1.0 if side == "BUY" else -1.0))
    per_point = abs(one or 0) or (mt5.symbol_info(SYMBOL).trade_contract_size * VOLUME)
    dist = TP_USD / per_point
    info = mt5.symbol_info(SYMBOL)
    return round(entry + dist if side == "BUY" else entry - dist, info.digits)


def open_trade(side, bar_t):
    tick = mt5.symbol_info_tick(SYMBOL)
    entry = tick.ask if side == "BUY" else tick.bid
    tp = tp_price(side, entry)
    r = send({"action": mt5.TRADE_ACTION_DEAL, "symbol": SYMBOL, "volume": VOLUME,
              "type": mt5.ORDER_TYPE_BUY if side == "BUY" else mt5.ORDER_TYPE_SELL, "price": entry, "tp": tp,
              "deviation": 200, "magic": MAGIC, "comment": COMMENT})
    ok = r is not None and r.retcode == mt5.TRADE_RETCODE_DONE
    say("OPEN %s %.2f %s at %.2f tp %.2f (no SL) for bar %s -> %s" % (
        side, VOLUME, SYMBOL, entry, tp, time.strftime("%H:%M", time.gmtime(bar_t)),
        "ok #%s" % r.order if ok else "FAILED %s" % (r and (r.retcode, r.comment),)))
    return ok


def main():
    connect()
    s = load_state()
    say("start - state %s" % json.dumps(s))
    last_m1 = 0
    while True:
        try:
            h1 = mt5.copy_rates_from_pos(SYMBOL, mt5.TIMEFRAME_H1, 0, 2)
            if h1 is None or len(h1) < 2:
                time.sleep(2)
                continue
            cur_t, closed = int(h1[1]["time"]), h1[0]
            if s.get("bar") is None:
                s["bar"] = cur_t                      # first start: wait for the next hour (never open mid-hour)
                save_state(s)
                say("waiting for the next H1 open (current bar %s)" % time.strftime("%H:%M", time.gmtime(cur_t)))
            if cur_t != s.get("bar"):
                # rule 4: the next H1 open closes whatever is still open
                for p in my_positions():
                    close(p, "new hour")
                o, c, hi, lo = float(closed["open"]), float(closed["close"]), float(closed["high"]), float(closed["low"])
                s.update({"bar": cur_t, "high": hi, "low": lo, "side": None})
                if c > o:
                    s["side"] = "SELL"
                elif c < o:
                    s["side"] = "BUY"
                say("H1 closed %s O %.2f H %.2f L %.2f C %.2f -> %s" % (
                    time.strftime("%H:%M", time.gmtime(int(closed["time"]))), o, hi, lo, c, s["side"] or "flat, no trade"))
                if s["side"]:
                    open_trade(s["side"], cur_t)
                save_state(s)
            # rule 3: an M1 close beyond the closed H1 candle, against the trade
            m1 = mt5.copy_rates_from_pos(SYMBOL, mt5.TIMEFRAME_M1, 1, 1)
            if m1 is not None and len(m1) and int(m1[0]["time"]) != last_m1:
                last_m1 = int(m1[0]["time"])
                mc = float(m1[0]["close"])
                for p in my_positions():
                    if p.type == mt5.POSITION_TYPE_SELL and s.get("high") is not None and mc > float(s["high"]):
                        close(p, "M1 closed %.2f above H1 high %.2f" % (mc, s["high"]))
                    elif p.type == mt5.POSITION_TYPE_BUY and s.get("low") is not None and mc < float(s["low"]):
                        close(p, "M1 closed %.2f below H1 low %.2f" % (mc, s["low"]))
            time.sleep(1)
        except Exception as e:
            say("ERROR %s - reconnecting in 20 s" % str(e)[:200])
            time.sleep(20)
            try:
                mt5.shutdown()
                connect()
            except Exception as e2:
                say("reconnect failed: %s" % str(e2)[:200])


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--check":
        connect()
        print("positions on account:", [(p.ticket, p.symbol, p.magic, p.volume, round(p.profit, 2)) for p in (mt5.positions_get() or [])])
        t = mt5.symbol_info_tick(SYMBOL)
        print("bid/ask", t.bid, t.ask, "TP for SELL at bid:", tp_price("SELL", t.bid), "BUY at ask:", tp_price("BUY", t.ask))
        mt5.shutdown()
    else:
        main()
