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
import math
import os
import time
from datetime import datetime, timedelta, timezone

import MetaTrader5 as mt5

import structure_bos_bot as B          # Struct engine + constants
import owl_shadow as SHADOW            # the gate's refused trades

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
# 2026-09-27: the desk serves any account in manual/semi mode, so the symbol
# and the ledger start come from the nest record (441 keeps its own era
# start so its tab/jar history does not move).
SYMBOL = _U.get("symbol") or "BTCUSD"
MAGIC = 909102                      # manual orders (909101 = the retired bot)
COMMENT = "KL-MAN"
ERA_START = datetime(2026, 9, 8, 19, 0)
if UID != "bos" and _U.get("era_start"):
    ERA_START = (datetime.fromisoformat(_U["era_start"])
                 .astimezone(timezone.utc).replace(tzinfo=None))
BASE_LOT = 0.02
MAX_EXTRA = 3
CHEST_CAP = 10.0
LOT_MIN, LOT_MAX = 0.01, 0.10
REQ = os.path.join(DIR, f"manual_order_{UID}.json")
RES = os.path.join(DIR, f"manual_order_result_{UID}.json")
STATE = os.path.join(DIR, f"manual_state_{UID}.json")


def save_json(path, obj):
    """Atomic publish. A plain json.dump(open(path,'w')) leaves the file
    truncated for a few milliseconds, and any reader landing there gets
    nothing - which made the chart's P&L badge blink out roughly once a
    minute (owner 2026-09-16). Windows can refuse the replace while a
    reader holds the handle, so retry briefly."""
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(obj, fh)
    for _ in range(12):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            time.sleep(0.05)
    try:
        os.replace(tmp, path)
    except Exception:
        pass
VPEND = os.path.join(DIR, f"manual_pending_{UID}.json")
VPEND_MAX_H = 24                    # a forgotten order expires
# Owner 2026-09-18: a line placed ON a BOS level means "trade this break
# once it CONFIRMS", not "trade the first touch of this price".
AT_BOS_TOL = 12.0      # pts: within this of a BOS level = "on the level"
RETURN_TOL = 15.0      # pts: close enough to the confirmation close to enter
EXPIRE_FRAC = 0.5      # gone this share of the reward past it = missed
LOG = os.path.join(DIR, f"owl_manual_trader_{UID}.log")
SEED_BARS = 3000
REQ_MAX_AGE = 180                   # a request older than this is stale


def say(m):
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(f"{datetime.now(timezone.utc).isoformat()} {m}\n")


def push(title, body, kind="instant"):
    try:
        import owl_push_notifier as P
        P.send_all(title, body, kind=kind, only_uid=UID)
        say(f"PUSH {title} | {body}")
    except Exception as e:
        say(f"push failed: {type(e).__name__}: {e}")


def rebuild_ledger():
    """Replay every closed deal since the era start. Self-healing: manual
    closes, app closes and bot closes all land in the same books.

    THE TAB AND THE JAR (owner 2026-09-16). The tab is the drawdown from the
    equity peak - what has been lost and not yet won back. The jar is the
    recovery money, and it takes a slice of EVERY win, not only of wins that
    make a new high. The old rule only filled it on a new high, so during a
    drawdown - exactly when recovery is wanted - it never filled at all.
    Constants are shared with the auto bot so the two cannot drift."""
    ds = mt5.history_deals_get(ERA_START, datetime.utcnow() + timedelta(days=1)) or []
    closes = sorted([d for d in ds if d.entry == 1 and d.symbol == SYMBOL],
                    key=lambda d: d.time)
    banked = peak = jar = 0.0
    for d in closes:
        pnl = d.profit + d.swap + d.commission
        if pnl > 0 and B.JAR:
            jar += B.JAR_SKIM * pnl                 # a slice of every win
        elif pnl < 0 and d.volume > BASE_LOT + 0.001:
            # the jar staked the extra lots, so it pays their share
            jar = max(0.0, jar + pnl * (1.0 - BASE_LOT / d.volume))
        banked = round(banked + pnl, 2)
        if banked > peak:
            if not B.JAR:
                jar = round(min(CHEST_CAP, jar + banked - peak), 2)
            peak = banked
        if B.JAR:
            _debt = max(0.0, peak - banked)
            jar = round(min(jar, max(B.JAR_FLOOR_CAP,
                                     B.JAR_DEBT_MULT * _debt)), 2)
    debt = round(max(0.0, peak - banked), 2)
    return dict(banked=banked, peak=peak, debt=debt, chest=jar,
                trades=len(closes))


LOT_STEP = 0.01


def day_pnl():
    """Today's REALISED profit (UTC), from the same deal history the ledger
    replays - no new state file, and it self-heals like rebuild_ledger():
    a manual close, an app close and a bot close all count the same.

    Owner 2026-09-20: "like in Valere, pause trading when profit of the day
    is >= 10". Valere gets this from the package's day_cap inside
    structure_bos_bot; 441 runs THIS desk, which had no daily cap at all -
    so the dial would have been dead data without it.
    """
    # TIMEZONE-AWARE, and this is not cosmetic: mt5.history_deals_get()
    # returns ZERO deals for a naive datetime on this terminal. Written
    # naive on 2026-09-21, which made day_pnl() always 0.00 and the daily
    # cap dead code - caught 2026-09-22 only because the app's hero banner
    # said +$16.46 while this said +$0.00. Test a gate against MT5 itself,
    # never against a monkeypatched stand-in.
    now = datetime.now(timezone.utc)
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    ds = mt5.history_deals_get(start, now + timedelta(days=1)) or []
    return round(sum(d.profit + d.swap + d.commission for d in ds
                     if d.entry == 1 and d.symbol == SYMBOL), 2)


def day_capped(led):
    """None when trading may continue, otherwise the reason.

    Same rule as the bot: the cap is a PROFIT target and is WAIVED while the
    account owes money, so a good day cannot be locked in before the tab is
    paid. It stops the ROBOT only - the owner's own yellow-line orders are
    deliberate and are never blocked by it.
    """
    if B.DAY_CAP is None:
        return None
    if (led or {}).get("debt", 0.0) > 0.5:
        return None
    got = day_pnl()
    if got < B.DAY_CAP:
        return None
    return f"objectif du jour atteint (+{got:.2f} >= {B.DAY_CAP:.2f})"


def counter_lot():
    """Owner 2026-09-15: a trade against the structure rides half the BASE
    lot and never carries war-chest bullets. Returned value, and whether
    such a trade is possible at all: if halving cannot produce something
    strictly smaller than the base lot, counter-trend is forbidden."""
    half = int((BASE_LOT / 2) / LOT_STEP) * LOT_STEP
    half = round(max(LOT_MIN, half), 2)
    return half, (half < BASE_LOT - 1e-9)


CHART = os.path.join(DIR, "owl_chart_btc.json")
# Owner 2026-09-17: on THIS account "en pause" means MANUAL - the desk takes
# no entry of its own. Switching it off means AUTO: the desk enters by
# itself, on the internal structure and the main one, under the rules that
# survived verification. The default with no file is MANUAL, because the
# safe default on a real account is to do nothing.
PAUSE_MASTER = os.path.join(DIR, "owl_trading_pause.json")
PAUSE_OWN = os.path.join(DIR, f"owl_trading_pause_{UID}.json")


def manual_mode():
    try:
        if json.load(open(PAUSE_MASTER, encoding="utf-8")).get("paused"):
            return True
    except Exception:
        pass
    try:
        return bool(json.load(open(PAUSE_OWN, encoding="utf-8"))
                    .get("paused", True))
    except Exception:
        return True


def chart():
    try:
        return json.load(open(CHART, encoding="utf-8"))
    except Exception:
        return {}


def gates(cj, need_int):
    """The entry brakes - ONE implementation, in the bot, shared by every
    account (owner 2026-09-18). This desk used to carry its own copy, and
    that is exactly how 441 and Valere ended up obeying different rules.
    Kept as a thin wrapper so the desk's call sites read the same."""
    return B.weather_gate(need_int=need_int, cj=cj)
# owner 2026-09-15: no single trade may risk more than 10% of the balance.
# The automated bot already enforces this; the manual desk does too.
MAX_RISK_PCT = 0.10


def risk_ok(dist, lot):
    """None when the trade is allowed, otherwise the refusal message."""
    ai = mt5.account_info()
    if ai is None or ai.balance <= 0:
        return None
    risk, cap = dist * lot, MAX_RISK_PCT * ai.balance
    if risk <= cap:
        return None
    return (f"risque ${risk:.2f} > {MAX_RISK_PCT:.0%} du solde "
            f"${ai.balance:.2f} (${cap:.2f}) - rapproche le SL "
            f"ou attends un solde plus gros")


def int_level(d, direction, px):
    """The internal structure's stop level for a trade in this direction:
    the protected dot while the engine holds one, otherwise the protective
    extreme of the CURRENT internal leg - the lowest low for a buy, the
    highest high for a sell, since the last dot of the other kind. The most
    recent dot is the wrong answer: it lands on a minor wiggle inside the
    leg. Dots are [time, price, kind], kind +1 low / -1 high."""
    want = 1 if direction == 1 else -1
    ok = (lambda v: bool(v) and
          (v < px - 10 if direction == 1 else v > px + 10))
    if ok(d.get("int_inv")):
        return d["int_inv"]
    dots = [x for x in (d.get("int_dots") or []) if len(x) >= 3]
    runs, prev = [], -2
    for i, x in enumerate(dots):
        if x[2] != want:
            continue
        if i == prev + 1:
            runs[-1].append(float(x[1]))
        else:
            runs.append([float(x[1])])
        prev = i
    for run in reversed(runs):            # newest leg first
        vals = [v for v in run if ok(v)]
        if vals:
            return min(vals) if want == 1 else max(vals)
    return None


def internal_trade(ref, sl, direction):
    """Owner 2026-09-16: a trade riding the INTERNAL structure carries half
    the base lot, exactly like a counter-trend trade. The stop decides which
    structure the trade belongs to: whichever level it sits nearer to, the
    internal one or the main diamond."""
    try:
        d = json.load(open(CHART, encoding="utf-8"))
    except Exception:
        return False
    main = d.get("invalid")
    inner = int_level(d, direction, ref)
    if not inner or not main:
        return False
    return abs(sl - inner) < abs(sl - main)


def lot_for(dist, led):
    """The lot the tab-and-jar system would use for a stop this far away.
    Only the LOT moves - the stop never does."""
    lot = BASE_LOT
    bullets = 0
    if led["debt"] > 0.5 and led["chest"] > 0.5 and dist > 0:
        risk001 = dist * LOT_STEP
        if B.JAR:
            # stake only part of the jar, so one bad recovery cannot disarm
            # the next; and never buy more recovery than the tab needs
            by_budget = int((led["chest"] * B.JAR_STAKE) //
                            max(risk001, 0.01))
            gain001 = B.RR * dist * LOT_STEP
            by_debt = (int(math.ceil(led["debt"] / gain001))
                       if gain001 > 0 else 0)
            bullets = max(0, min(MAX_EXTRA, by_budget, by_debt))
        else:
            bullets = min(MAX_EXTRA, int(led["chest"] // max(risk001, 0.01)))
        lot = round(BASE_LOT + bullets * LOT_STEP, 2)
    return max(LOT_MIN, min(LOT_MAX, lot)), bullets


def open_positions():
    return [p for p in (mt5.positions_get(symbol=SYMBOL) or [])]


def shadow_note(cj, d, slv, why):
    """Write down a trade the NERVOSITY brake refused, and follow it
    virtually (owner 2026-09-18). Only nervosity, and only when every
    other rule would have allowed it - otherwise it is not the
    counterfactual we are trying to measure. Places no order."""
    if not why.startswith("trop nerveux"):
        return
    try:
        # would it have passed with nervosity switched off?
        if B.weather_gate(cj=dict(cj, vol_now=0, vol_ref=1)):
            return
        tick = mt5.symbol_info_tick(SYMBOL)
        if tick is None:
            return
        e = tick.ask if d == 1 else tick.bid
        dist = abs(e - slv)
        if dist <= B.S_MIN_DIST:
            return
        SHADOW.open_trade(UID, d, e, slv, e + d * B.RR * dist, why, BASE_LOT)
    except Exception:
        pass


def kill_check(led):
    """The kill line, at last (owner 2026-09-18).

    This desk was written when a human watched every trade, so its header
    said the ledger is reported and nothing is closed automatically. That
    stopped being true the day AUTO mode went on: the robot enters by
    itself, so it must be able to stop by itself. The automated bot has
    had KILL_NET since day one; 441 was the only account trading without
    one.

    net = realised + floating, the same definition structure_bos_bot uses.
    Crossing the line closes everything, cancels the pending orders and
    switches the account back to MANUAL, so nothing re-enters. It is a
    one-way door: only the owner turns automatic back on.
    """
    if B.KILL_NET is None:
        return False
    pos = [p for p in open_positions() if p.magic == MAGIC]
    floating = sum(p.profit + p.swap for p in pos)
    net = led.get("banked", 0.0) + floating
    if net > B.KILL_NET:
        return False
    say(f"LIGNE DE MORT: net {net:.2f} <= {B.KILL_NET} "
        f"- fermeture de tout et passage en manuel")
    for p in pos:
        tick = mt5.symbol_info_tick(SYMBOL)
        if tick is None:
            continue
        buy = p.type == mt5.ORDER_TYPE_BUY
        mt5.order_send({
            "action": mt5.TRADE_ACTION_DEAL, "symbol": SYMBOL,
            "volume": p.volume, "position": p.ticket,
            "type": mt5.ORDER_TYPE_SELL if buy else mt5.ORDER_TYPE_BUY,
            "price": tick.bid if buy else tick.ask,
            "deviation": 500, "magic": MAGIC, "comment": "KILL",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC})
    cancel_pending()
    try:
        tmp = PAUSE_OWN + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"paused": True, "by": "kill",
                       "note": f"ligne de mort {B.KILL_NET}",
                       "t": time.time()}, f)
        os.replace(tmp, PAUSE_OWN)
    except Exception as e:
        say(f"LIGNE DE MORT: passage en manuel echoue: {e}")
    push("Robot arrete", f"Perte de ${abs(net):.2f} atteinte. Tout est "
                         f"ferme, le compte est repasse en manuel.")
    return True


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
        save_json(VPEND, v)


def bos_level_near(entry):
    """(name, price) of the break level this entry sits on, else None.
    Reads the chart feed - the same levels the yellow line snaps to."""
    cj = chart()
    best = None
    for key, name in (("next_bos", "BOS"), ("flip_bos", "BOS de bascule"),
                      ("int_bos", "BOS interne"),
                      ("int_flip_bos", "bascule interne")):
        v = cj.get(key)
        if v is None:
            continue
        gap = abs(float(v) - entry)
        if gap <= AT_BOS_TOL and (best is None or gap < best[2]):
            best = (name, float(v), gap)
    return (best[0], best[1]) if best else None


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
    inner = internal_trade(entry, sl, d)
    lot, bullets = lot_for(dist, led)
    if against or inner:
        half, ok = counter_lot()
        if not ok:
            why = "contre-tendance" if against else "structure interne"
            return False, why + " impossible a cette taille de lot"
        lot, bullets = half, 0
    bad = risk_ok(dist, lot)
    if bad:
        say(f"ORDRE PROGRAMME REFUSE: {bad}")
        return False, bad
    # Owner 2026-09-18: is this line sitting ON a break level? Then the
    # yellow line means "I want this trade when the BOS confirms" - not
    # necessarily at that exact price, and never on a mere touch.
    on_bos = bos_level_near(entry)
    if against or on_bos:
        need = 1 if entry > mkt else -1
        mode = "bos" if on_bos else "counter"
        save_vpend(dict(d=d, entry=round(entry, 2), sl=round(sl, 2),
                        tp=round(tp, 2), need=need, kind=name, mode=mode,
                        lvl=on_bos, placed=time.time(), trend=trend))
        why = (f"sur le niveau {on_bos[0]} {on_bos[1]:.0f}" if on_bos
               else "contre-tendance")
        say(f"{name} ARME ({why}) {lot} @ {entry:.2f} SL {sl:.2f} "
            f"TP {tp:.2f} - attend une cloture M1 "
            f"{'au-dessus' if need == 1 else 'en dessous'}")
        push(f"{name} arme", f"{why} a {entry:.0f}, se declenche sur la "
                             f"bougie de confirmation")
        return True, dict(kind=name, lot=lot, price=entry, sl=sl, tp=tp,
                          risk=round(dist * lot, 2), armed=True, mode=mode)
    # with the trend: a real broker order, triggered on touch. An internal
    # trade is NOT close-confirmed - only counter-trend is (owner 2026-09-15)
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


def vpend_check(close_px, led, bar_hi=None, bar_lo=None):
    """Called on each completed M1 bar.

    Owner 2026-09-18, for a line placed ON a break level (mode "bos"):
      1. ARMED     - wait for the CONFIRMATION candle: an M1 close beyond
                     the level in the trade's direction. A touch is not it.
      2. CONFIRMED - the close is the reference price. If the market is
                     still near it, enter now at market.
      3. RETURN    - if price has already run, do not chase: enter only
                     when a later candle comes back to that close.
      4. EXPIRED   - price has gone more than EXPIRE_FRAC of the reward
                     past the close without returning: the entry is missed
                     and the order is dropped, not filled late.
    A counter-trend line ("counter") keeps its old behaviour: fire at
    market on the first close beyond the line.
    """
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
    d = v["d"]
    tick = mt5.symbol_info_tick(SYMBOL)
    if tick is None:
        return
    px = tick.ask if d == 1 else tick.bid
    if v.get("mode") == "bos":
        conf = v.get("conf")
        if conf is None:
            beyond = ((close_px > v["entry"]) if v["need"] == 1
                      else (close_px < v["entry"]))
            if not beyond:
                return                          # still waiting to confirm
            v["conf"] = round(close_px, 2)
            v["conf_t"] = time.time()
            conf = v["conf"]
            say(f"{v['kind']} CONFIRME: cloture {close_px:.2f} au-dela de "
                f"{v['entry']:.2f} - reference {conf:.2f}")
            if abs(px - conf) > RETURN_TOL:
                save_vpend(v)
                say(f"{v['kind']} le prix est deja a {px:.2f} - attend un "
                    f"retour vers {conf:.2f}")
                push(f"{v['kind']} confirme", f"le prix est parti, attend "
                                              f"un retour vers {conf:.0f}")
                return
        else:
            # already confirmed earlier: has price come back to the close?
            hi = bar_hi if bar_hi is not None else close_px
            lo = bar_lo if bar_lo is not None else close_px
            reward = abs(v["tp"] - conf)
            gone = (px - conf) * d              # how far past, in trade dir
            if gone > EXPIRE_FRAC * reward:
                save_vpend(None)
                say(f"{v['kind']} EXPIRE: prix a {px:.2f}, "
                    f"{gone:.0f} pts au-dela de la confirmation {conf:.2f} "
                    f"({EXPIRE_FRAC:.0%} de la cible) - entree manquee")
                push("Ordre expire", f"{v['kind']}: le prix est parti trop "
                                     f"loin de {conf:.0f} sans revenir")
                return
            back = (lo <= conf + RETURN_TOL) if d == 1                 else (hi >= conf - RETURN_TOL)
            if not back:
                save_vpend(v)
                return
            say(f"{v['kind']} RETOUR sur la confirmation {conf:.2f} "
                f"(bougie {lo:.2f}-{hi:.2f}) - entree")
    else:
        beyond = ((close_px > v["entry"]) if v["need"] == 1
                  else (close_px < v["entry"]))
        if not beyond:
            return
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


def modify(req):
    """Owner 2026-09-16: move the SL/TP of a position that is already open,
    by dragging the lines on the chart. Nothing else about the position is
    touched - not the lot, not the direction."""
    pos = [p for p in open_positions() if p.magic == MAGIC]
    if not pos:
        return False, "aucune position a modifier"
    p = pos[0]
    sl, tp = float(req.get("sl", 0)), float(req.get("tp", 0))
    if sl <= 0 or tp <= 0:
        return False, "SL et TP requis"
    tick = mt5.symbol_info_tick(SYMBOL)
    if tick is None:
        return False, "pas de cotation"
    d = 1 if p.type == mt5.ORDER_TYPE_BUY else -1
    px = tick.bid if d == 1 else tick.ask
    if d == 1 and not (sl < px < tp):
        return False, f"achat: il faut SL < {px:.2f} < TP"
    if d == -1 and not (tp < px < sl):
        return False, f"vente: il faut TP < {px:.2f} < SL"
    info = mt5.symbol_info(SYMBOL)
    gap = (info.trade_stops_level * info.point) if info else 0.0
    if min(abs(px - sl), abs(px - tp)) <= max(gap, B.S_MIN_DIST):
        return False, "SL ou TP trop pres du marche"
    # the 10% rule still applies - but never block a move that REDUCES the
    # risk, or a position already over the cap could not be tightened
    new_risk = abs(p.price_open - sl) * p.volume
    old_risk = abs(p.price_open - p.sl) * p.volume if p.sl else None
    if old_risk is None or new_risk > old_risk:
        bad = risk_ok(abs(p.price_open - sl), p.volume)
        if bad:
            return False, bad
    r = mt5.order_send({"action": mt5.TRADE_ACTION_SLTP, "symbol": SYMBOL,
                        "position": p.ticket, "sl": round(sl, 2),
                        "tp": round(tp, 2), "magic": MAGIC})
    if r is None or r.retcode != mt5.TRADE_RETCODE_DONE:
        return False, f"broker: {getattr(r, 'retcode', '?')} {getattr(r, 'comment', '')}"
    say(f"POSITION MODIFIEE #{p.ticket} {p.volume} "
        f"SL {p.sl:.2f} -> {sl:.2f}  TP {p.tp:.2f} -> {tp:.2f} "
        f"(risque ${new_risk:.2f})")
    push("Position modifiee", f"SL {sl:.0f}  TP {tp:.0f}")
    return True, dict(ticket=p.ticket, lot=p.volume, sl=sl, tp=tp,
                      risk=round(new_risk, 2), modified=True)


def close_now(req):
    """Owner 2026-09-16: close the running position on demand, at market.
    The ledger replays every closing deal on the symbol, so the debt and
    the war chest follow on their own."""
    pos = [p for p in open_positions() if p.magic == MAGIC]
    if not pos:
        return False, "aucune position ouverte"
    p = pos[0]
    tick = mt5.symbol_info_tick(SYMBOL)
    if tick is None:
        return False, "pas de cotation"
    d = 1 if p.type == mt5.ORDER_TYPE_BUY else -1
    r = mt5.order_send({
        "action": mt5.TRADE_ACTION_DEAL, "symbol": SYMBOL,
        "volume": p.volume, "position": p.ticket,
        "type": mt5.ORDER_TYPE_SELL if d == 1 else mt5.ORDER_TYPE_BUY,
        "price": tick.bid if d == 1 else tick.ask,
        "deviation": 200, "magic": MAGIC, "comment": COMMENT + "-X",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC})
    if r is None or r.retcode != mt5.TRADE_RETCODE_DONE:
        return False, f"broker: {getattr(r, 'retcode', '?')} {getattr(r, 'comment', '')}"
    say(f"POSITION FERMEE A LA MAIN #{p.ticket} {p.volume} @ {r.price:.2f} "
        f"(P&L flottant ${p.profit:.2f})")
    push("Position fermee", f"{p.volume} lot a {r.price:.0f}, "
                            f"P&L ${p.profit:.2f}")
    return True, dict(ticket=p.ticket, lot=p.volume, price=r.price,
                      pl=round(p.profit, 2), closed=True)


def execute(req, led, trend=0):
    """Validate and place the order the chart asked for."""
    if (req.get("by") != "auto" and not manual_mode()
            and not (req.get("close") or req.get("modify")
                     or req.get("cancel"))):
        # owner 2026-09-17: in AUTO the desk enters on its own. A hand entry
        # here would take the one slot the robot is waiting for. Changing or
        # closing a live trade stays allowed.
        return False, "mode automatique : le robot gere les entrees"
    if req.get("close"):
        return close_now(req)
    if req.get("modify"):
        return modify(req)
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
    inner = internal_trade(px, sl, d)
    if against or inner:
        half, ok = counter_lot()
        if not ok:
            why = "contre-tendance" if against else "structure interne"
            return False, why + " impossible a cette taille de lot"
        # half once, never twice: a trade that is both stays at half
        lot, bullets = half, 0
    elif req.get("lot"):                    # the chart may pin a lot
        lot = max(LOT_MIN, min(LOT_MAX, round(float(req["lot"]), 2)))
    bad = risk_ok(dist, lot)
    if bad:
        say(f"ORDRE REFUSE: {bad}")
        return False, bad
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
        + (", CONTRE-TENDANCE demi-lot" if against
           else (", STRUCTURE INTERNE demi-lot" if inner else "")) + ")")
    push("Ordre place", f"{'Achat' if d == 1 else 'Vente'} {lot} lot a "
                        f"{r.price:.0f}, risque ${risk:.2f}")
    return True, dict(lot=lot, price=r.price, sl=sl, tp=tp, risk=round(risk, 2),
                      bullets=bullets)


def auto_enter(d, slv, why, cj):
    """Take an entry at market. Everything that can refuse it - the stop
    distance, the 10% risk rule, an open position, an armed order - already
    lives in execute(), so this only adds the rules specific to auto."""
    if open_positions():
        return
    if pending_orders() or load_vpend():
        return
    _cap = day_capped(rebuild_ledger())
    if _cap:
        say(f"AUTO refuse ({why}): {_cap}")
        return
    tick = mt5.symbol_info_tick(SYMBOL)
    if tick is None:
        return
    px = tick.ask if d == 1 else tick.bid
    dist = abs(px - slv)
    if dist <= B.S_MIN_DIST:
        say(f"AUTO refuse ({why}): stop trop proche ({dist:.0f} pts)")
        return
    tp = px + d * B.RR * dist
    req = dict(d=d, sl=round(slv, 2), tp=round(tp, 2), entry=0,
               ts=time.time(), by="auto")
    ok, info = execute(req, rebuild_ledger(), eng_trend())
    say(f"AUTO {why}: {'pris' if ok else 'refuse'} - {info}")
    if ok:
        push(f"🤖 Auto {'achat' if d == 1 else 'vente'}",
             f"{why} a {px:.0f}, stop {slv:.0f}")


_ENG = {"trend": 0, "manual": None}


def eng_trend():
    return _ENG["trend"]


def main():
    if PASSWORD or UID == "bos":
        assert mt5.initialize(path=TERMINAL, login=LOGIN,
                              password=PASSWORD or B.PASSWORD,
                              server=SERVER, timeout=60000), "MT5 init failed"
    else:
        # no password on record (Kino 778): the terminal is already logged
        # in - attach to it and refuse to run on any other account
        assert mt5.initialize(path=TERMINAL, timeout=60000), "MT5 init failed"
    ai = mt5.account_info()
    assert ai is not None and int(ai.login) == LOGIN, \
        f"terminal is on {getattr(ai, 'login', None)}, not {LOGIN} - refusing"
    led = rebuild_ledger()
    # name the package and its dials. This desk gets them INDIRECTLY, from
    # the structure_bos_bot module it imports, which resolves them once at
    # import - so the log is the only place that can show what this process
    # is really running (owner 2026-09-20).
    _br = ("aucun frein" if not (B.NERVOSITY or B.MOVEMENT)
           else "sans frein nervosite" if not B.NERVOSITY
           else "sans frein mouvement" if not B.MOVEMENT
           else "freins complets")
    say(f"MANUAL TRADER [{UID}] up on {ai.login} balance {ai.balance:.2f} | "
        f"net {led['banked']:+.2f} dette {led['debt']:.2f} chest {led['chest']:.2f} "
        f"({led['trades']} trades) | paquet {B.PACKAGE} | {_br}"
        + (f" | pause a +${B.DAY_CAP:.2f}/jour"
           f" ({'ACTIVE' if led['debt'] <= 0.5 else 'en veille: dette'})"
           if B.DAY_CAP else "")
        + " - "
        + ("MANUEL, aucune entree automatique" if manual_mode()
           else "AUTO, le bureau entre seul"))
    eng = B.Struct()
    R = mt5.copy_rates_from_pos(SYMBOL, mt5.TIMEFRAME_M1, 1, SEED_BARS)
    for r in (R if R is not None else []):
        eng.step(int(r["time"]), float(r["open"]), float(r["high"]),
                 float(r["low"]), float(r["close"]))
    last_bar = int(R[-1]["time"]) if R is not None and len(R) else 0
    last_int = chart().get("int_inv_t")
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
                    save_json(RES, {"ok": ok, "info": info,
                                    "t": time.time()})
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
                    # follow the trades the nervosity brake refused, on the
                    # raw bar (owner 2026-09-18)
                    SHADOW.settle(UID, float(bar["high"]), float(bar["low"]))
                    prev_trend = eng.trend
                    sig = eng.step(bt, float(bar["open"]), float(bar["high"]),
                                   float(bar["low"]), float(bar["close"]))
                    _c = float(bar["close"])
                    if eng.choch != 0 and eng.choch != last_choch:
                        side = "haussier" if eng.choch == 1 else "baissier"
                        say(f"CHoCH {side} a {_c:.2f}")
                        # 2026-09-27: plain words for members, no jargon
                        push("\u26a1 Le sens peut changer",
                             f"Vers le {'haut' if eng.choch == 1 else 'bas'}, autour de {_c:.0f}. "
                             "Attendez la confirmation avant d'entrer.", kind="batch")
                    vpend_check(_c, rebuild_ledger(),
                                float(bar["high"]), float(bar["low"]))
                    last_choch = eng.choch
                    _ENG["trend"] = eng.trend
                    # owner 2026-09-17: every mode change is logged and
                    # pushed. A flag that can start real trading must never
                    # move without a trace.
                    _mm = manual_mode()
                    if _mm != _ENG.get("manual"):
                        _ENG["manual"] = _mm
                        say("MODE -> " + ("MANUEL, aucune entree automatique"
                                          if _mm else "AUTO, le bureau entre seul"))
                        push("Mode " + ("manuel" if _mm else "automatique"),
                             "Le robot " + ("n'entre plus seul."
                                            if _mm else "entre seul desormais."))
                    # owner 2026-09-17: notify the two moments worth acting
                    # on, so the chart does not have to be watched. A FLIP is
                    # rare and changes the side you trade; a BOS is the
                    # actionable one and carries the stop with it.
                    flip = eng.trend != prev_trend and eng.trend != 0
                    if flip:
                        w = "haussiere" if eng.trend == 1 else "baissiere"
                        say(f"FLIP: tendance {w}")
                        _ENG["cont_used"] = False      # a new trend re-arms the one continuation
                        push("\U0001f504 Nouvelle tendance " + w,
                             f"Bascule autour de {_c:.0f}. Les prochains signaux seront des "
                             f"{'achats' if eng.trend == 1 else 'ventes'}.")
                    # ---- AUTO mode: enter on our own (owner 2026-09-17)
                    # The kill line is checked BEFORE any entry and while a
                    # position is running, so a losing trade cannot carry the
                    # account past the line unnoticed (owner 2026-09-18).
                    if not manual_mode() and kill_check(led):
                        continue
                    if not manual_mode():
                        _cj = chart()
                        # the internal structure first: its protected level
                        # moves on every break, so a change means a break
                        # just confirmed
                        _iv, _ivt = _cj.get("int_inv"), _cj.get("int_inv_t")
                        _itr = _cj.get("int_trend") or 0
                        if (_iv and _ivt and _ivt != last_int
                                and _itr and _itr == eng.trend):
                            last_int = _ivt
                            _g = gates(_cj, True)
                            if _g:
                                say(f"AUTO petite structure ignoree: {_g}")
                                shadow_note(_cj, _itr, float(_iv), _g)
                            else:
                                auto_enter(_itr, float(_iv),
                                           "petite structure", _cj)
                        elif _ivt:
                            last_int = _ivt
                        # then the main structure, on its own signal
                        if sig:
                            _g = gates(_cj, False)
                            if _g:
                                say(f"AUTO grande structure ignoree: {_g}")
                                shadow_note(_cj, int(sig[0]),
                                            float(sig[1]), _g)
                            else:
                                auto_enter(int(sig[0]), float(sig[1]),
                                           "grande structure", _cj)
                    if sig:
                        d_, slv = int(sig[0]), float(sig[1])
                        dist = abs(_c - slv)
                        led2 = rebuild_ledger()
                        lot2, bul2 = lot_for(dist, led2)
                        # a break you cannot act on is noise. Measured at 22
                        # breaks a day, so silence the ones that are already
                        # unavailable: a position open, an order armed, a
                        # stop too tight, or a risk the 10% rule refuses.
                        _blk = None
                        if open_positions():
                            _blk = "position deja ouverte"
                        elif pending_orders() or load_vpend():
                            _blk = "ordre deja programme"
                        elif dist <= B.S_MIN_DIST:
                            _blk = "stop trop proche"
                        else:
                            _blk = risk_ok(dist, lot2)
                        if _blk:
                            say(f"BOS non notifie ({_blk})")
                            sig = None
                    if sig:
                        say(f"BOS {'haussier' if d_ == 1 else 'baissier'} "
                            f"a {_c:.2f}, stop {slv:.2f}")
                        # 2026-09-27: the SIGNAL, gated exactly like the robot
                        # (weather brakes, then the recovery allowance), kept
                        # in the state for the app and the chart, pushed in
                        # the simplest format a signal consumer wants.
                        _cj2 = chart()
                        _why = gates(_cj2, False) if _cj2 else None
                        _dbt = led2["debt"] > 0.5
                        if not _why and _dbt and not flip:
                            if _ENG.get("cont_used"):
                                _why = "rattrapage : une seule continuation par tendance"
                            else:
                                _ENG["cont_used"] = True
                        _tp = round(_c + d_ * B.RR * dist, 2)
                        _ENG["signal"] = {"t": int(time.time()), "dir": d_, "e": round(_c, 2),
                                          "sl": round(slv, 2), "tp": _tp, "lot": round(lot2, 2),
                                          "bul": bul2, "kind": "flip" if flip else "cont",
                                          "ok": not _why, "why": _why or "",
                                          "expires": int(time.time()) + 1800}
                        if manual_mode() and not _why:
                            push(("\U0001f7e2 ACHAT" if d_ == 1 else "\U0001f534 VENTE") + f" {SYMBOL}",
                                 f"Entr\u00e9e ~{_c:.0f} \u00b7 stop {slv:.0f} \u00b7 cible {_tp:.0f} "
                                 f"\u00b7 lot {lot2:.2f}"
                                 + (f" (+{bul2} rattrapage)" if bul2 else "")
                                 + " \u00b7 valable 30 min")
                        elif manual_mode():
                            say(f"signal non conseille: {_why}")
            # ---- publish state for the chart (every 10 s)
            if time.time() - last_led >= 10:
                last_led = time.time()
                led = rebuild_ledger()
                tick = mt5.symbol_info_tick(SYMBOL)
                pos = open_positions()
                ai = mt5.account_info()
                save_json(STATE, {
                    "acct": LOGIN, "balance": round(ai.balance, 2),
                    "auto": not manual_mode(),
                    "rr": B.RR,          # the auto bot's target, shared
                    "jar": B.JAR, "jar_skim": B.JAR_SKIM,
                    "jar_stake": B.JAR_STAKE,
                    "jar_cap": round(max(B.JAR_FLOOR_CAP,
                                         B.JAR_DEBT_MULT * led["debt"]), 2),
                    "max_risk_pct": MAX_RISK_PCT,
                    "max_risk": round(MAX_RISK_PCT * ai.balance, 2),
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
                    "signal": (_ENG.get("signal") if _ENG.get("signal")
                               and _ENG["signal"].get("expires", 0) > time.time() else None),
                    "px": round(float(tick.bid), 2) if tick else None,
                    "spread": round(float(tick.ask - tick.bid), 2) if tick else None,
                    "open": [{"lot": p.volume, "d": 1 if p.type == 0 else -1,
                              "e": p.price_open, "sl": p.sl, "tp": p.tp,
                              "pl": round(p.profit, 2)} for p in pos],
                    "pending": ([{
                        "ticket": 1, "lot": counter_lot()[0],
                        "e": _vp["entry"], "sl": _vp["sl"], "tp": _vp["tp"],
                        "kind": _vp["kind"], "armed": True,
                        "need": _vp["need"], "mode": _vp.get("mode"),
                        "conf": _vp.get("conf"),
                        "lvl": _vp.get("lvl")}] if (_vp := load_vpend()) else
                        [{"ticket": o.ticket, "lot": o.volume_current,
                          "e": o.price_open, "sl": o.sl, "tp": o.tp,
                          "armed": False,
                          "kind": PEND_NAME.get(
                              (1 if o.type in (2, 4) else -1,
                               o.type in (4, 5)), "EN ATTENTE")}
                         for o in pending_orders()]),
                    "updated": int(time.time()),
                })
        except Exception as e:
            say(f"ERROR {type(e).__name__}: {e}")
            time.sleep(15)


if __name__ == "__main__":
    main()
