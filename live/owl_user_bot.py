"""owl_user_bot.py <user_id> - a personal trading Owl for ONE OwlNest member.

Runs the frozen KINO constitution (2026-09-01) on the member's DEMO
account: KINO peak/dip-return entries, two-door recovery chains, lot
ladder, 60pt min wall, one-signal-one-trade, 3 pages max, deep-fighter
ratchet (lock 40% / bank 70%) and heal targets, risk caps scaled to the
account.

IRON SAFETY: refuses to trade unless the MT5 server name contains
"trial" or "demo". Stops itself when the member's trial expires
(closing its own positions).

Spawned/supervised by owl_nest_manager.py for users with trading=true.
"""
import json, os, sys, time
from datetime import datetime, timezone, timedelta
import numpy as np
import MetaTrader5 as mt5

DIR = r"C:\Projects\KinoliveLines\live"
USERS = os.path.join(DIR, "owl_nest_users.json")
DATA = os.path.join(DIR, "nest_data")
os.makedirs(DATA, exist_ok=True)

uid = sys.argv[1]
u = next(x for x in json.load(open(USERS, encoding="utf-8"))
         if x["id"] == uid)
SYMBOL = u.get("symbol", "BTCUSDm")
LOG = os.path.join(DATA, f"bot_{uid}.log")
STATE = os.path.join(DATA, f"bot_{uid}_state.json")

MIN_WALL = 60.0
SIG_PTS = 100.0
MAX_PAGES = 3
RATCHET_LOCK = 0.40
RATCHET_BANK = 0.70
WATCH_LIFE = 21600
PEND_LIFE = 21600


def say(m):
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(f"{datetime.now(timezone.utc).isoformat()} {m}\n")


def load_state():
    try:
        st = json.load(open(STATE))
    except Exception:
        st = {}
    st.setdefault("kino", {"up": {}, "dn": {}})
    st.setdefault("watches", [])
    st.setdefault("links", {})
    st.setdefault("last_bar", 0)
    st.setdefault("scale", None)
    return st


def save_state(st):
    json.dump(st, open(STATE, "w"))


def trial_ok():
    try:
        uu = next(x for x in json.load(open(USERS, encoding="utf-8"))
                  if x["id"] == uid)
    except Exception:
        return False
    if uu.get("plan") in ("premium", "family"):
        return True
    try:
        te = datetime.fromisoformat(uu.get("trial_end"))
        if te.tzinfo is None:
            te = te.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc) < te
    except Exception:
        return False


def connect():
    ok = mt5.initialize(path=u["terminal"], login=int(u["mt5_login"]),
                        password=u.get("mt5_password", ""),
                        server=u.get("mt5_server", ""))
    if not ok:
        return False
    ai = mt5.account_info()
    if ai is None or ai.login != int(u["login"]):
        return False
    srv = (u.get("mt5_server") or "").lower()
    if ("trial" not in srv) and ("demo" not in srv):
        if u.get("plan") != "family":
            say("SAFETY: not a demo server - trading refused forever")
            raise SystemExit(1)
    return True


def scales(st, ai):
    """Account-scaled constitution numbers, frozen at first run."""
    if st["scale"] is None:
        start = ai.balance
        base = max(0.01, min(0.10, round(start / 10000.0, 2)))
        st["scale"] = {
            "start": start,
            "base": base,
            "step": max(0.01, round(base / 2.0, 2)),
            "deep": round(base * 2, 2),
            "fighter_cap": round(0.11 * start, 2),
            "page_cap": round(0.31 * start, 2),
            "chain_floor": round(0.78 * start, 2),
            "heal_extra": round(150.0 * base, 2),
            "disc_hi": round(25.0 * base, 2),
            "disc_lo": round(50.0 * base, 2),
        }
        save_state(st)
        say(f"scales set: {st['scale']}")
    return st["scale"]


def open_mkt(direction, volume, comment):
    tick = mt5.symbol_info_tick(SYMBOL)
    if tick is None:
        return None
    return mt5.order_send({
        "action": mt5.TRADE_ACTION_DEAL, "symbol": SYMBOL,
        "volume": round(volume, 2),
        "type": mt5.ORDER_TYPE_BUY if direction == 1
        else mt5.ORDER_TYPE_SELL,
        "price": tick.ask if direction == 1 else tick.bid,
        "deviation": 50, "comment": comment,
        "type_filling": mt5.ORDER_FILLING_IOC})


def close_mkt(p, comment):
    tick = mt5.symbol_info_tick(SYMBOL)
    if tick is None:
        return None
    return mt5.order_send({
        "action": mt5.TRADE_ACTION_DEAL, "position": p.ticket,
        "symbol": SYMBOL, "volume": p.volume,
        "type": mt5.ORDER_TYPE_SELL if p.type == mt5.POSITION_TYPE_BUY
        else mt5.ORDER_TYPE_BUY,
        "price": tick.bid if p.type == mt5.POSITION_TYPE_BUY
        else tick.ask,
        "deviation": 50, "comment": comment,
        "type_filling": mt5.ORDER_FILLING_IOC})


def sltp(ticket, sl, tp):
    return mt5.order_send({"action": mt5.TRADE_ACTION_SLTP,
                           "position": ticket, "symbol": SYMBOL,
                           "sl": round(sl, 2), "tp": round(tp, 2)})


def atr14(bars):
    h, l, c = bars["high"], bars["low"], bars["close"]
    tr = np.maximum(h[1:], c[:-1]) - np.minimum(l[1:], c[:-1])
    return float(np.mean(tr[-14:])) if len(tr) >= 14 else 0.0


def same_signal(direction, px, own_open):
    for p in own_open:
        d = 1 if p.type == mt5.POSITION_TYPE_BUY else -1
        if d == direction and abs(p.price_open - px) <= SIG_PTS:
            return True
    return False


def enter(direction, lot, wall, loss, chain, st, ai, own_open, b1,
          reent=False):
    sc = st["scale"]
    if ai.balance < sc["chain_floor"] and chain is not None:
        return None, "chain floor"
    if len(own_open) >= MAX_PAGES:
        return None, "pages full"
    tick = mt5.symbol_info_tick(SYMBOL)
    if tick is None:
        return None, "no tick"
    px = tick.ask if direction == 1 else tick.bid
    dist = abs(px - wall)
    if dist < MIN_WALL:
        return None, "wall close"
    risk = dist * lot
    if risk > sc["fighter_cap"]:
        return None, "risk cap"
    if loss is not None and loss + risk >= sc["page_cap"]:
        return None, "page cap"
    if same_signal(direction, px, own_open):
        return None, "same signal"
    r = open_mkt(direction, lot,
                 "OWL-recov" if chain else "OWL-kino")
    if r is None or r.retcode != mt5.TRADE_RETCODE_DONE:
        return None, f"send fail {r.retcode if r else None}"
    body = abs(float(b1["close"][0]) - float(b1["open"][0]))
    m1b = mt5.copy_rates_from_pos(SYMBOL, mt5.TIMEFRAME_M1, 1, 120)
    a14 = atr14(m1b) if m1b is not None and len(m1b) > 20 else 0.0
    strong = a14 > 0 and body >= a14
    disc = min(sc["disc_hi"] if strong else sc["disc_lo"], 0.25 * risk)
    tp_dist = dist - disc / lot
    if lot >= sc["deep"] and loss:
        hd = (loss + sc["heal_extra"]) / lot
        if MIN_WALL < hd < tp_dist:
            tp_dist = hd
    tp = px + tp_dist if direction == 1 else px - tp_dist
    sltp(r.order, wall, tp)
    st["links"][str(r.order)] = {
        "sl": round(wall, 2), "tp": round(tp, 2), "lot": lot,
        "chain": chain or str(r.order), "loss": loss or 0.0,
        "dir": direction, "entry": px, "kino": chain is None}
    save_state(st)
    say(f"{'RE-ENTRY' if reent else 'ENTRY'}"
        f"{' chain' if chain else ''}: "
        f"{'BUY' if direction == 1 else 'SELL'} {lot} @ {px:.2f} "
        f"SL {wall:.2f} TP {tp:.2f} risk {risk:.2f}")
    return r.order, "ok"


def main():
    say(f"user Owl starting for {uid}")
    st = load_state()
    while True:
        try:
            if not connect():
                time.sleep(15)
                continue
            if not trial_ok():
                say("trial over - closing my positions and stopping")
                for p in mt5.positions_get(symbol=SYMBOL) or []:
                    if (p.comment or "").startswith("OWL-"):
                        close_mkt(p, "OWL-trial-end")
                raise SystemExit(0)
            ai = mt5.account_info()
            sc = scales(st, ai)
            positions = mt5.positions_get(symbol=SYMBOL) or []
            own = [p for p in positions
                   if (p.comment or "").startswith("OWL-")]
            own_ids = {p.ticket for p in own}
            # --- closed links -> journal + chain doors ---
            for tk in list(st["links"].keys()):
                if int(tk) in own_ids:
                    continue
                lk = st["links"].pop(tk)
                deals = mt5.history_deals_get(position=int(tk)) or []
                outs = [d for d in deals
                        if d.entry == mt5.DEAL_ENTRY_OUT]
                pnl = sum(d.profit + d.commission + d.swap
                          for d in outs)
                cm = (outs[-1].comment or "").lower() if outs else ""
                reason = ("tp" if "tp" in cm else
                          "sl" if "sl" in cm else "close")
                say(f"EXIT {tk}: {reason} {pnl:+.2f}")
                if reason == "sl":
                    st["watches"].append({
                        "dir": lk["dir"], "sl": lk["sl"],
                        "lot": lk["lot"], "trig": lk["entry"],
                        "loss": lk["loss"] + abs(pnl),
                        "chain": lk["chain"],
                        "t_sl": int(time.time())})
                    say(f"chain[{lk['chain']}] armed: two doors "
                        f"{lk['sl']:.2f} / {lk['entry']:.2f}")
                else:
                    say(f"chain[{lk['chain']}] ENDED ({reason})")
                save_state(st)
            # --- ratchet for deep fighters ---
            for p in own:
                lk = st["links"].get(str(p.ticket))
                if lk is None or p.volume < sc["deep"] or not p.tp:
                    continue
                d = 1 if p.type == mt5.POSITION_TYPE_BUY else -1
                prize = (p.tp - p.price_open) * d * p.volume
                if prize <= 0:
                    continue
                if p.profit >= RATCHET_BANK * prize:
                    r = close_mkt(p, "OWL-ratchet-bank")
                    if r and r.retcode == mt5.TRADE_RETCODE_DONE:
                        say(f"RATCHET BANK {p.ticket} {p.profit:+.2f}")
                elif (p.profit >= RATCHET_LOCK * prize
                        and not lk.get("rat")):
                    r = sltp(p.ticket, p.price_open, p.tp)
                    if r and r.retcode == mt5.TRADE_RETCODE_DONE:
                        lk["rat"] = 1
                        lk["sl"] = round(p.price_open, 2)
                        save_state(st)
                        say(f"RATCHET LOCK {p.ticket} at entry")
            # --- chain watches: two doors ---
            b1 = mt5.copy_rates_from_pos(SYMBOL, mt5.TIMEFRAME_M1, 1, 1)
            if b1 is not None and len(b1):
                cl = float(b1["close"][0])
                keep = []
                for w in st["watches"]:
                    done = False
                    if int(b1["time"][0]) + 60 > w["t_sl"]:
                        broke = (cl < w["sl"] if w["dir"] == 1
                                 else cl > w["sl"])
                        reent = (not broke
                                 and (cl > w["trig"] if w["dir"] == 1
                                      else cl < w["trig"]))
                        if broke or reent:
                            nd = w["dir"] if reent else -w["dir"]
                            nl = round(w["lot"] + sc["step"], 2)
                            legb = mt5.copy_rates_from_pos(
                                SYMBOL, mt5.TIMEFRAME_M1, 1, 90)
                            if legb is not None and len(legb):
                                wall = (float(np.max(legb["high"]))
                                        if nd == -1
                                        else float(np.min(legb["low"])))
                                tkt, why = enter(
                                    nd, nl, wall, w["loss"],
                                    w["chain"], st, ai, own, b1,
                                    reent=reent)
                                if tkt is not None:
                                    done = True
                                elif why in ("risk cap", "page cap",
                                             "chain floor"):
                                    if why != "risk cap":
                                        say(f"chain[{w['chain']}] "
                                            f"STOPPED ({why})")
                                        done = True
                    if not done and time.time() - w["t_sl"] > WATCH_LIFE:
                        say(f"chain[{w['chain']}] watch expired")
                        done = True
                    if not done:
                        keep.append(w)
                if len(keep) != len(st["watches"]):
                    st["watches"] = keep
                    save_state(st)
                # --- KINO detector (fresh pages) ---
                if int(b1["time"][0]) != st["last_bar"]:
                    kb = mt5.copy_rates_from_pos(
                        SYMBOL, mt5.TIMEFRAME_M1, 1, 2)
                    if kb is not None and len(kb) == 2:
                        st["last_bar"] = int(b1["time"][0])
                        pv, cb = kb[0], kb[1]
                        po, pc = float(pv["open"]), float(pv["close"])
                        ph, pl = float(pv["high"]), float(pv["low"])
                        co, cc = float(cb["open"]), float(cb["close"])
                        ch, clo = float(cb["high"]), float(cb["low"])
                        ks = st["kino"]
                        up, dn = ks["up"], ks["dn"]
                        now_t = int(cb["time"])
                        # one page at a time: any active page still
                        # below the deep stage blocks new pages
                        stages = ([lk["lot"] for lk in
                                   st["links"].values()]
                                  + [w["lot"] + sc["step"]
                                     for w in st["watches"]])
                        gate_open = (all(s >= sc["deep"]
                                         for s in stages)
                                     if stages else True)
                        if pc > po and cc > co and cc > ph:
                            up["leg"] = True
                            up["peak"] = ch
                            up["glow"] = clo
                        elif up.get("leg"):
                            up["peak"] = max(up.get("peak", ch), ch)
                            if cc > co:
                                up["glow"] = clo
                            elif cc < up.get("glow", -1e18):
                                up["pending"] = up["peak"]
                                up["pt"] = now_t
                                up["plow"] = clo
                                up["leg"] = False
                        if up.get("pending"):
                            up["plow"] = min(up.get("plow", clo), clo)
                            if now_t - up.get("pt", now_t) > PEND_LIFE:
                                up["pending"] = None
                            elif cc > up["pending"] and gate_open:
                                tkt, _ = enter(1, sc["base"],
                                               up.get("plow", clo),
                                               None, None, st, ai,
                                               own, b1)
                                if tkt is not None:
                                    up["pending"] = None
                        if pc < po and cc < co and cc < pl:
                            dn["leg"] = True
                            dn["dip"] = clo
                            dn["rhigh"] = ch
                        elif dn.get("leg"):
                            dn["dip"] = min(dn.get("dip", clo), clo)
                            if cc < co:
                                dn["rhigh"] = ch
                            elif cc > dn.get("rhigh", 1e18):
                                dn["pending"] = dn["dip"]
                                dn["pt"] = now_t
                                dn["phigh"] = ch
                                dn["leg"] = False
                        if dn.get("pending"):
                            dn["phigh"] = max(dn.get("phigh", ch), ch)
                            if now_t - dn.get("pt", now_t) > PEND_LIFE:
                                dn["pending"] = None
                            elif cc < dn["pending"] and gate_open:
                                tkt, _ = enter(-1, sc["base"],
                                               dn.get("phigh", ch),
                                               None, None, st, ai,
                                               own, b1)
                                if tkt is not None:
                                    dn["pending"] = None
                        save_state(st)
        except SystemExit:
            raise
        except Exception as e:
            say(f"ERROR {e}")
        time.sleep(2)


if __name__ == "__main__":
    main()
