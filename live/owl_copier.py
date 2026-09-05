"""owl_copier.py <uid> - mirror the master's OWL trades to ONE account.

ONE CODEBASE FOR ALL ACCOUNTS (user decision 2026-09-05): no generated
copies, no drift. Launch with the user's id; credentials + terminal come
from owl_nest_users.json at runtime. Works for demos and reals alike.

Every second:
  - read owl_master_positions.json (written by owl_master_publisher.py)
  - honor the user's own pause file (owl_trading_pause_<uid>.json):
    paused = open NOTHING new; existing copies keep mirroring SL/TP and
    closes so protection never stops
  - lot scale = clamp(own_balance / master_balance, 0, 3.0);
    lot = max(0.01, round(master_lot * scale, 2))
  - diff master positions vs our copies (comment "OWLCP-<master ticket>"):
      new master ticket        -> open a copy, set its SL/TP
      SL/TP changed (locks!)   -> modify the copy
      volume reduced (partial) -> partial-close the copy pro rata
      master ticket gone       -> close the copy at market
Safety: wrong-account refusal, master file older than 30s = do nothing
new (stale = blind), only OWL-* master positions ever arrive here.
"""
import json
import os
import sys
import time
import MetaTrader5 as mt5

DIR = r"C:\Projects\KinoliveLines\live"
USERS = os.path.join(DIR, "owl_nest_users.json")
MASTER = os.path.join(DIR, "owl_master_positions.json")
SYMBOL = None       # resolved per account - Exness names the pair
                    # BTCUSDm on Standard and BTCUSD on Pro accounts
SCALE_CAP = 3.0

uid = sys.argv[1]
u = next(x for x in json.load(open(USERS, encoding="utf-8"))
         if x["id"] == uid)
LOGIN = int(u.get("mt5_login") or u["login"])
LOG = os.path.join(DIR, f"owl_copier_{uid}.log")
PAUSE = os.path.join(DIR, f"owl_trading_pause_{uid}.json")


def say(m):
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(f"{time.strftime('%Y-%m-%dT%H:%M:%S')} {m}\n")


def paused():
    try:
        return bool(json.load(open(PAUSE)).get("paused"))
    except Exception:
        return False


def connect():
    kw = {"path": u["terminal"]}
    if u.get("mt5_login"):
        kw.update(login=LOGIN, password=u.get("mt5_password", ""),
                  server=u.get("mt5_server", ""))
    if not mt5.initialize(**kw):
        return False
    ai = mt5.account_info()
    if ai is None or ai.login != LOGIN:
        say(f"WRONG ACCOUNT {ai.login if ai else None}, want {LOGIN}")
        mt5.shutdown()
        return False
    # resolve THIS account's BTC symbol once: fresh terminals have no
    # Market Watch selection, and the name differs by account class
    # (BTCUSDm vs BTCUSD - found on luc 09-05)
    global SYMBOL
    if SYMBOL is None:
        for cand in (u.get("symbol"), "BTCUSDm", "BTCUSD"):
            if (cand and mt5.symbol_select(cand, True)
                    and mt5.symbol_info_tick(cand)):
                SYMBOL = cand
                say(f"symbol resolved: {SYMBOL}")
                break
        if SYMBOL is None:
            say("NO BTC symbol tradable on this account")
            return False
    return True


def send(req, what):
    r = mt5.order_send(req)
    ok = r is not None and r.retcode == mt5.TRADE_RETCODE_DONE
    say(f"{what}: {'OK' if ok else f'FAILED rc={r.retcode if r else None}'}")
    return ok


say(f"copier starting for {uid} (account {LOGIN})")
last_mvol = {}      # master volume last seen per copy - partial closes
                    # trigger ONLY on a real master reduction, never on
                    # balance/scale drift
seen = set()        # master tickets we have already copied once
missing_since = {}  # copy vanished while master still open: wait 20s
                    # before re-opening - the copy usually just hit its
                    # own SL a beat before the master's exit reaches the
                    # feed (luc pilot 09-05: churn cost -0.21)
_last_mtime = 0.0
while True:
    # event-push (2026-09-05): watch the feed file's mtime at 10Hz and
    # act only on change - the publisher heartbeats every 5s, so grace
    # timers and staleness still get evaluated regularly.
    time.sleep(0.1)
    try:
        _mt = os.stat(MASTER).st_mtime
    except Exception:
        continue
    if _mt == _last_mtime:
        continue
    _last_mtime = _mt
    try:
        try:
            m = json.load(open(MASTER))
        except Exception:
            continue
        stale = time.time() - float(m.get("t", 0)) > 30
        if not connect():
            time.sleep(5)
            continue
        ai = mt5.account_info()
        scale = 1.0
        if m.get("balance"):
            scale = min(SCALE_CAP, max(0.0, ai.balance
                                       / float(m["balance"])))
        mine = {p.comment: p for p in
                (mt5.positions_get(symbol=SYMBOL) or [])
                if (p.comment or "").startswith("OWLCP-")}
        want = {f"OWLCP-{p['ticket']}": p for p in m["positions"]}
        tick = mt5.symbol_info_tick(SYMBOL)
        if tick is None:
            continue
        # 1) close copies whose master is gone
        for cmt, p in list(mine.items()):
            if cmt not in want and not stale:
                send({"action": mt5.TRADE_ACTION_DEAL,
                      "position": p.ticket, "symbol": SYMBOL,
                      "volume": p.volume,
                      "type": (mt5.ORDER_TYPE_SELL
                               if p.type == mt5.POSITION_TYPE_BUY
                               else mt5.ORDER_TYPE_BUY),
                      "price": (tick.bid
                                if p.type == mt5.POSITION_TYPE_BUY
                                else tick.ask),
                      "deviation": 100, "comment": cmt,
                      "type_filling": mt5.ORDER_FILLING_IOC},
                     f"close {cmt} (master closed)")
        for cmt, mp in want.items():
            lot = max(0.01, round(mp["volume"] * scale, 2))
            p = mine.get(cmt)
            if p is None:
                # 2) open missing copy (unless paused or stale feed)
                if paused() or stale:
                    missing_since.pop(cmt, None)
                    continue
                if cmt in seen:
                    t0m = missing_since.setdefault(cmt, time.time())
                    if time.time() - t0m < 20:
                        continue
                missing_since.pop(cmt, None)
                seen.add(cmt)
                d = mp["dir"]
                if send({"action": mt5.TRADE_ACTION_DEAL,
                         "symbol": SYMBOL, "volume": lot,
                         "type": (mt5.ORDER_TYPE_BUY if d == 1
                                  else mt5.ORDER_TYPE_SELL),
                         "price": (tick.ask if d == 1 else tick.bid),
                         "deviation": 100, "comment": cmt,
                         "type_filling": mt5.ORDER_FILLING_IOC},
                        f"open {cmt} {lot} lots (scale {scale:.2f})"):
                    time.sleep(0.5)
                    p2 = next((x for x in
                               (mt5.positions_get(symbol=SYMBOL) or [])
                               if x.comment == cmt), None)
                    if p2 is not None and (mp["sl"] or mp["tp"]):
                        send({"action": mt5.TRADE_ACTION_SLTP,
                              "position": p2.ticket, "symbol": SYMBOL,
                              "sl": mp["sl"], "tp": mp["tp"]},
                             f"set SL/TP {cmt}")
                continue
            # 3) mirror SL/TP changes (locks, partial-TP moves)
            if (abs((p.sl or 0) - (mp["sl"] or 0)) > 0.5
                    or abs((p.tp or 0) - (mp["tp"] or 0)) > 0.5):
                send({"action": mt5.TRADE_ACTION_SLTP,
                      "position": p.ticket, "symbol": SYMBOL,
                      "sl": mp["sl"], "tp": mp["tp"]},
                     f"modify SL/TP {cmt}")
            # 4) mirror partial closes pro rata (master reduced volume)
            if cmt not in last_mvol:
                last_mvol[cmt] = mp["volume"]
            if mp["volume"] < last_mvol[cmt] - 1e-9 and not stale:
                frac = mp["volume"] / last_mvol[cmt]
                cut = round(p.volume * (1 - frac), 2)
                if cut >= 0.01 and round(p.volume - cut, 2) >= 0.01:
                    send({"action": mt5.TRADE_ACTION_DEAL,
                          "position": p.ticket, "symbol": SYMBOL,
                          "volume": cut,
                          "type": (mt5.ORDER_TYPE_SELL
                                   if p.type == mt5.POSITION_TYPE_BUY
                                   else mt5.ORDER_TYPE_BUY),
                          "price": (tick.bid
                                    if p.type == mt5.POSITION_TYPE_BUY
                                    else tick.ask),
                          "deviation": 100, "comment": cmt,
                          "type_filling": mt5.ORDER_FILLING_IOC},
                         f"partial {cmt} -{cut}")
                last_mvol[cmt] = mp["volume"]
        for k in [k for k in last_mvol if k not in want]:
            last_mvol.pop(k, None)
    except Exception as e:
        say(f"loop error: {e}")
        time.sleep(5)
