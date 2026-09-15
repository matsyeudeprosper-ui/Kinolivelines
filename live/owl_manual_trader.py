"""owl_manual_trader.py - assisted manual trading on the LIVE account
(owner 2026-09-15, after the auto BOS bot was stopped on 223995441).

It NEVER opens a trade on its own. What it does:
  - runs the same Struct engine on M1 so the chart and the alerts use the
    exact structure the bot used;
  - pushes a notification on every CHoCH so the owner can decide;
  - keeps the debt / war-chest ledger AUTOMATIC by replaying every closed
    deal on the account, manual closes included, so the lot size the chart
    preloads always reflects the real debt;
  - publishes manual_state.json (trend, choch, debt, chest, net, lot rule)
    for the chart page;
  - executes an order dropped in manual_order.json by the chart, after
    validating it, and writes the outcome to manual_order_result.json.

Kill line: the ledger is reported but NOTHING is closed automatically.
The owner is the decision maker now.
"""
import json
import os
import time
from datetime import datetime, timedelta, timezone

import MetaTrader5 as mt5

import structure_bos_bot as B          # Struct engine + constants

import sys as _sys

DIR = os.path.dirname(os.path.abspath(__file__))
# 2026-09-15 (owner): any account in "manual" or "semi" mode gets its own
# instance; full-automation accounts never run one. Usage:
#   python owl_manual_trader.py <nest-user-id>      (default: bos)
UID = _sys.argv[1] if len(_sys.argv) > 1 else "bos"
_U = [x for x in json.load(open(os.path.join(DIR, "owl_nest_users.json"),
                                encoding="utf-8")) if x.get("id") == UID]
if not _U:
    raise SystemExit(f"unknown nest user {UID}")
_U = _U[0]
if _U.get("mode") not in ("manual", "semi"):
    raise SystemExit(f"{UID} is not in manual/semi mode - nothing to run")
TERMINAL = _U["terminal"]
LOGIN = int(_U.get("mt5_login") or _U["login"])
SERVER = _U.get("mt5_server", "Exness-MT5Real30")
PASSWORD = _U.get("mt5_password") or None
SYMBOL = "BTCUSD"
MAGIC = 909102                      # manual orders (909101 = the retired bot)
COMMENT = "KL-MAN"
ERA_START = datetime(2026, 9, 8, 19, 0)
BASE_LOT = 0.02
MAX_EXTRA = 3
CHEST_CAP = 10.0
LOT_MIN, LOT_MAX = 0.01, 0.10
REQ = os.path.join(DIR, f"manual_order_{UID}.json")
RES = os.path.join(DIR, f"manual_order_result_{UID}.json")
STATE = os.path.join(DIR, f"manual_state_{UID}.json")
VPEND = os.path.join(DIR, f"manual_pending_{UID}.json")
VPEND_MAX_H = 24                    # a forgotten order expires
LOG = os.path.join(DIR, f"owl_manual_trader_{UID}.log")
SEED_BARS = 3000
REQ_MAX_AGE = 180                   # a request older than this is stale


def say(m):
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(f"{datetime.now(timezone.utc).isoformat()} {m}\n")


def push(title, body):
    try:
        import owl_push_notifier as P
        P.send_all(title, body, kind="instant", only_uid=UID)
        say(f"PUSH {title} | {body}")
    except Exception as e:
        say(f"push failed: {type(e).__name__}: {e}")


def rebuild_ledger():
    """Replay every closed deal since the era start. Self-healing: manual
    closes, app closes and bot closes all land in the same books."""
    ds = mt5.history_deals_get(ERA_START, datetime.utcnow() + timedelta(days=1)) or []
    closes = sorted([d for d in ds if d.entry == 1 and d.symbol == SYMBOL],
                    key=lambda d: d.time)
    banked = peak = chest = 0.0
    for d in closes:
        pnl = d.profit + d.swap + d.commission
        banked = round(banked + pnl, 2)
        if pnl < 0 and d.volume > BASE_LOT + 0.001:
            chest = round(max(0.0, chest + pnl * (1.0 - BASE_LOT / d.volume)), 2)
        if banked > peak:
            chest = round(min(CHEST_CAP, chest + banked - peak), 2)
            peak = banked
    debt = round(max(0.0, peak - banked), 2)
    return dict(banked=banked, peak=peak, debt=debt, chest=chest,
                trades=len(closes))


LOT_STEP = 0.01


def counter_lot():
    """Owner 2026-09-15: a trade against the structure rides half the BASE
    lot and never carries war-chest bullets. Returned value, and whether
    such a trade is possible at all: if halving cannot produce something
    strictly smaller than the base lot, counter-trend is forbidden."""
    half = int((BASE_LOT / 2) / LOT_STEP) * LOT_STEP
    half = round(max(LOT_MIN, half), 2)
    return half, (half < BASE_LOT - 1e-9)


def lot_for(dist, led):
    """The lot the debt system would use for a stop this far away."""
    lot = BASE_LOT
    bullets = 0
    if led["debt"] > 0.5 and dist > 0:
        risk001 = dist * 0.01
        bullets = min(MAX_EXTRA, int(led["chest"] // max(risk001, 0.01)))
        lot = round(BASE_LOT + bullets * 0.01, 2)
    return max(LOT_MIN, min(LOT_MAX, lot)), bullets


def open_positions():
    return [p for p in (mt5.positions_get(symbol=SYMBOL) or [])]


def pending_orders():
    return [o for o in (mt5.orders_get(symbol=SYMBOL) or []) if o.magic == MAGIC]


PEND = {(1, True): mt5.ORDER_TYPE_BUY_STOP, (1, False): mt5.ORDER_TYPE_BUY_LIMIT,
        (-1, True): mt5.ORDER_TYPE_SELL_STOP, (-1, False): mt5.ORDER_TYPE_SELL_LIMIT}
PEND_NAME = {(1, True): "BUY STOP", (1, False): "BUY LIMIT",
             (-1, True): "SELL STOP", (-1, False): "SELL LIMIT"}


def load_vpend():
    try:
        return json.load(open(VPEND, encoding="utf-8"))
    except Exception:
        return None


def save_vpend(v):
    if v is None:
        try:
            os.remove(VPEND)
        except Exception:
            pass
    else:
        json.dump(v, open(VPEND, "w"))


def place_pending(d, entry, sl, tp, tick, led, trend=0):
    """Owner 2026-09-15: a programmed entry must NOT fire on a touch. MT5's
    native pending orders trigger on price, so we hold the order here and
    send it at market only once a completed M1 candle CLOSES beyond the
    line, on the far side from where price sat when it was programmed."""
    mkt = tick.ask if d == 1 else tick.bid
    if d == 1 and not (sl < entry < tp):
        return False, "achat: il faut SL < entree < TP"
    if d == -1 and not (tp < entry < sl):
        return False, "vente: il faut TP < entree < SL"
    dist = abs(entry - sl)
    if dist <= B.S_MIN_DIST:
        return False, f"stop trop proche ({dist:.0f} pts)"
    stop_side = (entry > mkt) if d == 1 else (entry < mkt)
    info = mt5.symbol_info(SYMBOL)
    gap = (info.trade_stops_level * info.point) if info else 0.0
    if abs(entry - mkt) <= max(gap, B.S_MIN_DIST):
        return False, f"entree trop pres du marche ({abs(entry-mkt):.0f} pts)"
    cancel_pending()                     # one programmed entry at a time
    name = PEND_NAME[(d, stop_side)]
    against = (trend != 0 and d != trend)
    lot, bullets = lot_for(dist, led)
    if against:
        half, ok = counter_lot()
        if not ok:
            return False, "contre-tendance impossible a cette taille de lot"
        lot, bullets = half, 0
        # owner 2026-09-15: only a trade AGAINST the structure has to be
        # confirmed by a close. With the trend, a touch is enough.
        need = 1 if entry > mkt else -1
        save_vpend(dict(d=d, entry=round(entry, 2), sl=round(sl, 2),
                        tp=round(tp, 2), need=need, kind=name,
                        placed=time.time(), trend=trend))
        say(f"{name} ARME (contre-tendance) {lot} @ {entry:.2f} "
            f"SL {sl:.2f} TP {tp:.2f} - attend une cloture M1 "
            f"{'au-dessus' if need == 1 else 'en dessous'}")
        push(f"{name} arme", f"contre-tendance a {entry:.0f}, se declenche "
                             f"sur cloture M1")
        return True, dict(kind=name, lot=lot, price=entry, sl=sl, tp=tp,
                          risk=round(dist * lot, 2), armed=True)
    # with the trend: a real broker order, triggered on touch
    r = mt5.order_send({
        "action": mt5.TRADE_ACTION_PENDING, "symbol": SYMBOL, "volume": lot,
        "type": PEND[(d, stop_side)], "price": round(entry, 2),
        "sl": round(sl, 2), "tp": round(tp, 2), "deviation": 200,
        "magic": MAGIC, "comment": COMMENT,
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_RETURN})
    if r is None or r.retcode != mt5.TRADE_RETCODE_DONE:
        return False, f"broker: {getattr(r, 'retcode', '?')} {getattr(r, 'comment', '')}"
    say(f"{name} {lot} @ {entry:.2f} SL {sl:.2f} TP {tp:.2f} "
        f"(risque ${dist * lot:.2f}, {bullets} balle(s), au contact)")
    push(f"{name} programme", f"{lot} lot a {entry:.0f}, au contact")
    return True, dict(kind=name, lot=lot, price=entry, sl=sl, tp=tp,
                      risk=round(dist * lot, 2), bullets=bullets)


def vpend_check(close_px, led):
    """Called on each completed M1 bar. Fires the armed entry at market
    when the candle closes beyond the line."""
    v = load_vpend()
    if not v:
        return
    if (time.time() - v["placed"]) / 3600 > VPEND_MAX_H:
        save_vpend(None)
        say(f"{v['kind']} expire apres {VPEND_MAX_H} h sans declenchement")
        push("Ordre expire", f"{v['kind']} a {v['entry']:.0f} annule")
        return
    if open_positions():
        return
    beyond = (close_px > v["entry"]) if v["need"] == 1 else (close_px < v["entry"])
    if not beyond:
        return
    tick = mt5.symbol_info_tick(SYMBOL)
    if tick is None:
        return
    d = v["d"]
    px = tick.ask if d == 1 else tick.bid
    dist = abs(px - v["sl"])
    if dist <= B.S_MIN_DIST:
        save_vpend(None)
        say(f"{v['kind']} annule: la cloture laisse un stop de {dist:.0f} pts")
        return
    lot, bullets = lot_for(dist, led)
    if v.get("trend") and d != v["trend"]:
        half, ok = counter_lot()
        if not ok:
            save_vpend(None)
            return
        lot, bullets = half, 0
    r = mt5.order_send({
        "action": mt5.TRADE_ACTION_DEAL, "symbol": SYMBOL, "volume": lot,
        "type": mt5.ORDER_TYPE_BUY if d == 1 else mt5.ORDER_TYPE_SELL,
        "price": px, "sl": v["sl"], "tp": v["tp"], "deviation": 200,
        "magic": MAGIC, "comment": COMMENT,
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC})
    save_vpend(None)
    if r is None or r.retcode != mt5.TRADE_RETCODE_DONE:
        say(f"{v['kind']} declenche mais refuse: {getattr(r, 'retcode', '?')}")
        push("Declenchement refuse", str(getattr(r, "comment", "")))
        return
    say(f"{v['kind']} DECLENCHE sur cloture {close_px:.2f}: {lot} @ {r.price:.2f} "
        f"SL {v['sl']:.2f} TP {v['tp']:.2f} (risque ${dist * lot:.2f})")
    push(f"{v['kind']} declenche",
         f"{lot} lot a {r.price:.0f}, risque ${dist * lot:.2f}")


def cancel_pending(ticket=None):
    n = 0
    if load_vpend() is not None:
        save_vpend(None)
        n += 1
        say("entree programmee annulee")
    for o in pending_orders():
        if ticket and o.ticket != ticket:
            continue
        r = mt5.order_send({"action": mt5.TRADE_ACTION_REMOVE, "order": o.ticket})
        if r is not None and r.retcode == mt5.TRADE_RETCODE_DONE:
            n += 1
            say(f"ordre en attente {o.ticket} annule")
    return n


def execute(req, led, trend=0):
    """Validate and place the order the chart asked for."""
    if req.get("cancel"):
        n = cancel_pending(int(req["cancel"]) if req["cancel"] != 1 else None)
        return (n > 0), (f"{n} ordre(s) annule(s)" if n else "rien a annuler")
    d = int(req.get("d", 0))
    sl = float(req.get("sl", 0))
    tp = float(req.get("tp", 0))
    entry = float(req.get("entry", 0) or 0)
    if d not in (1, -1) or sl <= 0 or tp <= 0:
        return False, "requete invalide"
    if time.time() - float(req.get("ts", 0)) > REQ_MAX_AGE:
        return False, "requete perimee"
    if open_positions():
        return False, "une position est deja ouverte"
    tick = mt5.symbol_info_tick(SYMBOL)
    if tick is None:
        return False, "pas de cotation"
    if entry > 0:
        return place_pending(d, entry, sl, tp, tick, led, trend)
    px = tick.ask if d == 1 else tick.bid
    if d == 1 and not (sl < px < tp):
        return False, f"achat: il faut SL < {px:.2f} < TP"
    if d == -1 and not (tp < px < sl):
        return False, f"vente: il faut TP < {px:.2f} < SL"
    dist = abs(px - sl)
    if dist <= B.S_MIN_DIST:
        return False, f"stop trop proche ({dist:.0f} pts)"
    lot, bullets = lot_for(dist, led)
    against = (trend != 0 and d != trend)
    if against:
        half, ok = counter_lot()
        if not ok:
            return False, "contre-tendance impossible a cette taille de lot"
        lot, bullets = half, 0
    elif req.get("lot"):                    # the chart may pin a lot
        lot = max(LOT_MIN, min(LOT_MAX, round(float(req["lot"]), 2)))
    r = mt5.order_send({
        "action": mt5.TRADE_ACTION_DEAL, "symbol": SYMBOL, "volume": lot,
        "type": mt5.ORDER_TYPE_BUY if d == 1 else mt5.ORDER_TYPE_SELL,
        "price": px, "sl": round(sl, 2), "tp": round(tp, 2),
        "deviation": 200, "magic": MAGIC, "comment": COMMENT,
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC})
    if r is None or r.retcode != mt5.TRADE_RETCODE_DONE:
        return False, f"broker: {getattr(r, 'retcode', '?')} {getattr(r, 'comment', '')}"
    risk = dist * lot
    say(f"ORDRE MANUEL {'ACHAT' if d == 1 else 'VENTE'} {lot} @ {r.price:.2f} "
        f"SL {sl:.2f} TP {tp:.2f} (risque ${risk:.2f}, {bullets} balle(s), "
        f"dette ${led['debt']:.2f}"
        + (", CONTRE-TENDANCE demi-lot" if against else "") + ")")
    push("Ordre place", f"{'Achat' if d == 1 else 'Vente'} {lot} lot a "
                        f"{r.price:.0f}, risque ${risk:.2f}")
    return True, dict(lot=lot, price=r.price, sl=sl, tp=tp, risk=round(risk, 2),
                      bullets=bullets)


def main():
    assert mt5.initialize(path=TERMINAL, login=LOGIN,
                          password=PASSWORD or B.PASSWORD,
                          server=SERVER, timeout=60000), "MT5 init failed"
    ai = mt5.account_info()
    led = rebuild_ledger()
    say(f"MANUAL TRADER [{UID}] up on {ai.login} balance {ai.balance:.2f} | "
        f"net {led['banked']:+.2f} dette {led['debt']:.2f} chest {led['chest']:.2f} "
        f"({led['trades']} trades) - AUCUNE entree automatique")
    eng = B.Struct()
    R = mt5.copy_rates_from_pos(SYMBOL, mt5.TIMEFRAME_M1, 1, SEED_BARS)
    for r in (R if R is not None else []):
        eng.step(int(r["time"]), float(r["open"]), float(r["high"]),
                 float(r["low"]), float(r["close"]))
    last_bar = int(R[-1]["time"]) if R is not None and len(R) else 0
    last_choch = eng.choch
    last_led = 0.0
    say(f"moteur amorce: tendance {eng.trend} choch {eng.choch}")
    while True:
        time.sleep(min(60.0 - (time.time() % 60.0) + 0.2, 1.0))
        try:
            # ---- order request from the chart
            if os.path.exists(REQ):
                try:
                    req = json.load(open(REQ, encoding="utf-8"))
                except Exception as e:
                    req = None
                    say(f"requete illisible: {e}")
                os.remove(REQ)
                if req:
                    led = rebuild_ledger()
                    ok, info = execute(req, led, eng.trend)
                    json.dump({"ok": ok, "info": info,
                               "t": time.time()}, open(RES, "w"))
                    if not ok:
                        say(f"ordre refuse: {info}")
                        push("Ordre refuse", str(info))
            # ---- new closed bar: structure + CHoCH alert
            kb = mt5.copy_rates_from_pos(SYMBOL, mt5.TIMEFRAME_M1, 1, 2)
            if kb is not None and len(kb) >= 1:
                bar = kb[-1]
                bt = int(bar["time"])
                if bt != last_bar:
                    last_bar = bt
                    prev_trend = eng.trend
                    eng.step(bt, float(bar["open"]), float(bar["high"]),
                             float(bar["low"]), float(bar["close"]))
                    if eng.choch != 0 and eng.choch != last_choch:
                        side = "haussier" if eng.choch == 1 else "baissier"
                        px = float(bar["close"])
                        say(f"CHoCH {side} a {px:.2f}")
                        push(f"CHoCH {side}",
                             f"Changement de caractere a {px:.0f}. "
                             f"A toi de decider.")
                    vpend_check(float(bar["close"]), rebuild_ledger())
                    last_choch = eng.choch
                    if eng.trend != prev_trend and eng.trend != 0:
                        say(f"FLIP: tendance {'haussiere' if eng.trend == 1 else 'baissiere'}")
            # ---- publish state for the chart (every 10 s)
            if time.time() - last_led >= 10:
                last_led = time.time()
                led = rebuild_ledger()
                tick = mt5.symbol_info_tick(SYMBOL)
                pos = open_positions()
                ai = mt5.account_info()
                json.dump({
                    "acct": LOGIN, "balance": round(ai.balance, 2),
                    "equity": round(ai.equity, 2),
                    "net": led["banked"], "peak": led["peak"],
                    "debt": led["debt"], "chest": led["chest"],
                    "trades": led["trades"],
                    "base_lot": BASE_LOT, "max_extra": MAX_EXTRA,
                    "counter_lot": counter_lot()[0],
                    "counter_ok": counter_lot()[1],
                    "lot_min": LOT_MIN, "lot_max": LOT_MAX,
                    "s_min_dist": B.S_MIN_DIST,
                    "trend": eng.trend, "choch": eng.choch,
                    "px": round(float(tick.bid), 2) if tick else None,
                    "spread": round(float(tick.ask - tick.bid), 2) if tick else None,
                    "open": [{"lot": p.volume, "d": 1 if p.type == 0 else -1,
                              "e": p.price_open, "sl": p.sl, "tp": p.tp,
                              "pl": round(p.profit, 2)} for p in pos],
                    "pending": ([{
                        "ticket": 1, "lot": counter_lot()[0],
                        "e": _vp["entry"], "sl": _vp["sl"], "tp": _vp["tp"],
                        "kind": _vp["kind"], "armed": True,
                        "need": _vp["need"]}] if (_vp := load_vpend()) else
                        [{"ticket": o.ticket, "lot": o.volume_current,
                          "e": o.price_open, "sl": o.sl, "tp": o.tp,
                          "armed": False,
                          "kind": PEND_NAME.get(
                              (1 if o.type in (2, 4) else -1,
                               o.type in (4, 5)), "EN ATTENTE")}
                         for o in pending_orders()]),
                    "updated": int(time.time()),
                }, open(STATE, "w"))
        except Exception as e:
            say(f"ERROR {type(e).__name__}: {e}")
            time.sleep(15)


if __name__ == "__main__":
    main()
