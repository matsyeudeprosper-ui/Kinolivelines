"""owl_panic.py <user_id> [--armed] - ADMIN EMERGENCY STOP for ONE account.

Owner 2026-09-18: "an emergency stop/end current trades option, only for
admin... as an admin I can switch between accounts, I should be able to
cancel trades in any account".

What it does, in this order:
  1. writes owl_trading_pause_<uid>.json  -> the account's bots stop
     opening ANYTHING new. This happens FIRST on purpose: closing without
     pausing just lets the bot re-enter a second later.
  2. cancels every pending order on the account
  3. closes every open position at market
  4. writes owl_panic_result_<uid>.json and prints the same JSON

It closes EVERY position, not only the ones a bot opened - an emergency
stop that leaves hand trades running is not an emergency stop. Every
failure is reported with the broker's retcode; nothing fails silently.

Safety: the account number is checked against the user record BEFORE any
order is sent, and the terminal's logged-in account is never switched. A
mismatch refuses and closes nothing.

Without --armed it is a DRY RUN: it reports what it would close.
"""
import json
import os
import sys
import time
from datetime import datetime, timezone

import MetaTrader5 as mt5

DIR = os.path.dirname(os.path.abspath(__file__))
USERS = os.path.join(DIR, "owl_nest_users.json")
RETRY_CODES = (10004, 10021, 10020)     # requote, no prices, timeout


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def finish(uid, out):
    out["t"] = now()
    p = os.path.join(DIR, f"owl_panic_result_{uid}.json")
    tmp = p + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(out, f)
        os.replace(tmp, p)
    except Exception:
        pass
    print(json.dumps(out))
    try:
        mt5.shutdown()
    except Exception:
        pass
    sys.exit(0 if out.get("ok") else 1)


def main():
    if len(sys.argv) < 2:
        print(json.dumps({"ok": False, "err": "usage: owl_panic.py <uid> [--armed]"}))
        sys.exit(2)
    uid = sys.argv[1]
    armed = "--armed" in sys.argv[2:]
    out = {"ok": False, "uid": uid, "armed": armed,
           "paused": False, "orders": [], "positions": []}

    try:
        u = next(x for x in json.load(open(USERS, encoding="utf-8"))
                 if x.get("id") == uid)
    except Exception:
        finish(uid, dict(out, err=f"compte inconnu: {uid}"))

    want = int(u.get("mt5_login") or u.get("login") or 0)
    term = u.get("terminal")
    if not want or not term or not os.path.exists(term):
        finish(uid, dict(out, err="terminal ou numero de compte manquant"))

    # 1. PAUSE FIRST - a close without a pause is undone by the next tick.
    if armed:
        try:
            pf = os.path.join(DIR, f"owl_trading_pause_{uid}.json")
            tmp = pf + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"paused": True, "by": "panic",
                           "note": "arret d'urgence admin", "t": time.time()}, f)
            os.replace(tmp, pf)
            out["paused"] = True
        except Exception as e:
            out["pause_err"] = str(e)

    # attach WITHOUT switching the terminal's account
    ok = mt5.initialize(path=term)
    ai = mt5.account_info() if ok else None
    if ai is None and u.get("mt5_password"):
        mt5.shutdown()
        ok = mt5.initialize(path=term, login=want,
                            password=u["mt5_password"],
                            server=u.get("mt5_server"))
        ai = mt5.account_info() if ok else None
    if ai is None:
        finish(uid, dict(out, err=f"connexion MT5 impossible ({mt5.last_error()})"))
    if int(ai.login) != want:
        finish(uid, dict(out, err=f"MAUVAIS COMPTE: terminal sur {ai.login}, "
                                  f"attendu {want} - rien ferme"))
    out["acct"] = int(ai.login)
    out["equity"] = round(ai.equity, 2)

    # 2. pending orders
    for o in (mt5.orders_get() or []):
        row = {"ticket": o.ticket, "symbol": o.symbol,
               "lot": o.volume_current, "price": o.price_open}
        if not armed:
            row["would"] = "annuler"
        else:
            r = mt5.order_send({"action": mt5.TRADE_ACTION_REMOVE,
                                "order": o.ticket})
            row["done"] = bool(r and r.retcode == mt5.TRADE_RETCODE_DONE)
            row["retcode"] = getattr(r, "retcode", None)
            if not row["done"]:
                row["err"] = getattr(r, "comment", "")
        out["orders"].append(row)

    # 3. open positions - every one, whatever opened it
    for p in (mt5.positions_get() or []):
        row = {"ticket": p.ticket, "symbol": p.symbol, "lot": p.volume,
               "magic": p.magic, "pl": round(p.profit + p.swap, 2)}
        if not armed:
            row["would"] = "fermer"
            out["positions"].append(row)
            continue
        buy = p.type == mt5.ORDER_TYPE_BUY
        done = False
        for attempt in (1, 2):
            tick = mt5.symbol_info_tick(p.symbol)
            if tick is None:
                row["err"] = "pas de cotation"
                break
            r = mt5.order_send({
                "action": mt5.TRADE_ACTION_DEAL, "symbol": p.symbol,
                "volume": p.volume, "position": p.ticket,
                "type": mt5.ORDER_TYPE_SELL if buy else mt5.ORDER_TYPE_BUY,
                "price": tick.bid if buy else tick.ask,
                "deviation": 500, "magic": p.magic,
                "comment": "ADMIN-PANIC",
                "type_time": mt5.ORDER_TIME_GTC,
                "type_filling": mt5.ORDER_FILLING_IOC})
            rc = getattr(r, "retcode", None)
            row["retcode"] = rc
            if r is not None and rc == mt5.TRADE_RETCODE_DONE:
                done = True
                row["price"] = r.price
                break
            row["err"] = getattr(r, "comment", "") or str(mt5.last_error())
            if rc not in RETRY_CODES or attempt == 2:
                break
            time.sleep(0.4)
        row["done"] = done
        out["positions"].append(row)

    left = len(mt5.positions_get() or []) if armed else None
    out["left"] = left
    out["closed"] = sum(1 for x in out["positions"] if x.get("done"))
    out["cancelled"] = sum(1 for x in out["orders"] if x.get("done"))
    out["failed"] = sum(1 for x in out["positions"] + out["orders"]
                        if armed and not x.get("done"))
    out["ok"] = (out["failed"] == 0) if armed else True
    finish(uid, out)


if __name__ == "__main__":
    main()
