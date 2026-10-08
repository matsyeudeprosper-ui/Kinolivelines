"""owl_nest_worker.py <user_id> - OwlNest stats worker for ONE user.

Connects (read-only) to the user's MT5 terminal, computes the nest stats
every 5s and writes them to nest_data/<user_id>.json for the web server.

User record fields (owl_nest_users.json):
  id, name, token          - identity
  terminal                 - path to the user's terminal64.exe
  login                    - expected account number (safety check)
  mt5_login/mt5_password/mt5_server - OPTIONAL explicit login (use the
                             INVESTOR password for family accounts =
                             read-only by construction)
  era_start                - stats begin here (ISO datetime)
  symbol                   - default BTCUSDm
  bot_only                 - true: count only OWL-* opened positions
"""
import json, os, sys, time
from datetime import datetime, timezone, timedelta
import MetaTrader5 as mt5

DIR = r"C:\Projects\KinoliveLines\live"
USERS = os.path.join(DIR, "owl_nest_users.json")
OUT = os.path.join(DIR, "nest_data")
os.makedirs(OUT, exist_ok=True)

uid = sys.argv[1]
u = next(x for x in json.load(open(USERS, encoding="utf-8"))
         if x["id"] == uid)
ERA = datetime.fromisoformat(u["era_start"])
if ERA.tzinfo is None:
    ERA = ERA.replace(tzinfo=timezone.utc)
SYMBOL = u.get("symbol", "BTCUSDm")
BOT_ONLY = bool(u.get("bot_only"))
OUTP = os.path.join(OUT, uid + ".json")

_ddhist = []


def init():
    if u.get("mt5_login"):
        return mt5.initialize(path=u["terminal"],
                              login=int(u["mt5_login"]),
                              password=u.get("mt5_password", ""),
                              server=u.get("mt5_server", ""))
    return mt5.initialize(path=u["terminal"])


def out_deals(frm, to):
    frm = max(frm, ERA)
    alld = mt5.history_deals_get(ERA, to) or []
    ins = [d for d in alld if d.entry == mt5.DEAL_ENTRY_IN]
    if BOT_ONLY:
        keep = {d.position_id for d in ins
                if (d.comment or "").startswith(("OWL-", "KL-"))}
    else:
        keep = {d.position_id for d in ins}
    outs = [d for d in alld if d.entry == mt5.DEAL_ENTRY_OUT
            and d.position_id in keep
            and datetime.fromtimestamp(d.time, tz=timezone.utc) >= frm]
    ins_map = {d.position_id: d for d in ins if d.position_id in keep}
    return outs, ins_map


def compute():
    ai = mt5.account_info()
    if ai is None:
        return {"error": "no account info"}
    if u.get("login") and ai.login != int(u["login"]):
        return {"error": f"wrong account {ai.login}"}
    utcnow = datetime.now(timezone.utc)
    midnight = utcnow.replace(hour=0, minute=0, second=0, microsecond=0)
    monday = midnight - timedelta(days=midnight.weekday())
    week_ago = utcnow - timedelta(days=7)
    horizon = utcnow + timedelta(minutes=5)
    month_start = midnight.replace(day=1)
    val = lambda d: d.profit + d.commission + d.swap
    d30_start = utcnow - timedelta(days=30)
    m3_start = (month_start - timedelta(days=62)).replace(day=1)   # 3 months
    base_from = min(month_start, monday, week_ago, d30_start, m3_start)
    alldeals, ins_map = out_deals(base_from, horizon)
    alldeals = sorted(alldeals, key=lambda d: d.time)
    _since = lambda t0: [d for d in alldeals
                         if d.time >= t0.timestamp()]
    today = sum(val(d) for d in _since(midnight))
    week = sum(val(d) for d in _since(monday))
    mdeals = _since(month_start)
    month = sum(val(d) for d in mdeals)
    d7 = _since(week_ago)
    cum = peak = dd = 0.0
    curve = []
    for d in d7:
        cum += d.profit + d.commission + d.swap
        peak = max(peak, cum)
        dd = max(dd, peak - cum)
        curve.append(round(cum, 2))
    open_pos = mt5.positions_get(symbol=SYMBOL) or []
    if BOT_ONLY:
        # 2026-09-08: KL- covers the new bot family (KL-BOS,
        # KL-FRESH) - their trades were invisible with OWL- only
        floating = sum(p.profit + p.swap for p in open_pos
                       if (p.comment or "").startswith(
                           ("OWL-", "KL-")))
    else:
        floating = ai.equity - ai.balance
    dd = max(dd, peak - (cum + floating))
    _ddhist.append((time.time(), dd))
    while _ddhist and time.time() - _ddhist[0][0] > 7 * 86400:
        _ddhist.pop(0)
    dd = max(x[1] for x in _ddhist)
    if BOT_ONLY:
        _shown = [p for p in open_pos
                  if (p.comment or "").startswith(("OWL-", "KL-"))]
    else:
        _shown = list(open_pos)
    def _bullets(comment, vol):
        """Structure-bot trades that carry chest bullets: the 50%%
        adds (KL-*-ADD) and entries above the 0.02 base (fighters).
        KL-SNIPER runs a flat 0.06 - never a bullet trade."""
        c = comment or ""
        if not c.startswith(("KL-BOS", "KL-HALF")):
            return False
        return "-ADD" in c or vol > 0.021
    open_list = [{"d": ("A" if p.type == mt5.POSITION_TYPE_BUY else "V"),
                  "lot": p.volume,
                  "pl": round(p.profit + p.swap, 2),
                  "e": p.price_open, "sl": p.sl, "tp": p.tp,
                  "cur": p.price_current,
                  "k": ("s" if ((p.comment or "").startswith("OWL-recov")
                               or _bullets(p.comment, p.volume))
                        else "p")} for p in _shown]
    te = mt5.symbol_info_tick("EURUSDm")
    eur = round(te.bid, 5) if te and te.bid > 0 else None
    def _tkind(d):
        ic = getattr(ins_map.get(d.position_id), "comment", "") or ""
        oc = d.comment or ""
        if "partial" in oc:
            return "partiel"
        if ic.startswith("OWL-recov"):
            return "soldat"
        if _bullets(ic, d.volume):
            return "soldat"
        return "page"
    def _trow(d):
        _in = ins_map.get(d.position_id)
        return {"w": datetime.fromtimestamp(d.time, tz=timezone.utc)
                .strftime("%d/%m %H:%M"),
                "p": round(d.profit + d.commission + d.swap, 2),
                "k": _tkind(d), "lot": d.volume,
                "dir": ("A" if _in is not None
                        and _in.type == mt5.DEAL_TYPE_BUY else "V"),
                "ep": round(_in.price, 2) if _in is not None else None,
                "xp": round(d.price, 2),
                # 2026-10-01: journal rows are keyed on position_id
                # (the bot writes ticket=d.position_id), so carrying
                # it here lets the app attach the multi-timeframe
                # snapshot by an exact match, not a guess on time.
                "pid": d.position_id,
                "dur": (round((d.time - _in.time) / 60)
                        if _in is not None else None)}
    trades = [_trow(d) for d in d7[-30:]][::-1]
    d30 = _since(d30_start)
    _c30 = 0.0
    curve30 = []
    for d in d30:
        _c30 += val(d)
        curve30.append(round(_c30, 2))
    if len(curve30) > 300:
        _stp = len(curve30) / 300.0
        curve30 = [curve30[int(i * _stp)] for i in range(300)]
    # daily strip: one line per UTC day over the last 7 days
    _wd = ["lun", "mar", "mer", "jeu", "ven", "sam", "dim"]
    _dm = {}
    for d in d7:
        _dt = datetime.fromtimestamp(d.time, tz=timezone.utc)
        _k = _dt.strftime("%Y-%m-%d")
        if _k not in _dm:
            _dm[_k] = [_dt, 0.0]
        _dm[_k][1] += d.profit + d.commission + d.swap
    days = [{"d": f"{_wd[v[0].weekday()]} {v[0].strftime('%d/%m')}",
             "p": round(v[1], 2)}
            for _k, v in sorted(_dm.items(), reverse=True)]
    # per-day trade lists (last 7 days) keyed by the strip label, so
    # the app can expand a day on tap
    _dtr = {}
    for d in d7:
        _dt = datetime.fromtimestamp(d.time, tz=timezone.utc)
        _lbl = f"{_wd[_dt.weekday()]} {_dt.strftime('%d/%m')}"
        _dtr.setdefault(_lbl, []).append(
            {"t": _dt.strftime("%H:%M"), "p": round(val(d), 2)})
    for _k in _dtr:
        _dtr[_k] = _dtr[_k][-15:]
    # whole-month day P&L for the calendar heat-map
    _mm = {}
    for d in mdeals:
        _k = (datetime.fromtimestamp(d.time, tz=timezone.utc)
              .strftime("%Y-%m-%d"))
        _mm[_k] = _mm.get(_k, 0.0) + val(d)
    month_days = [{"d": k, "p": round(v, 2)}
                  for k, v in sorted(_mm.items())]
    # 2026-09-27: the app can browse the previous months' calendars
    _m3 = {}
    for d in _since(m3_start):
        _dt = datetime.fromtimestamp(d.time, tz=timezone.utc)
        _m3.setdefault(_dt.strftime("%Y-%m"), {})
        _k = _dt.strftime("%Y-%m-%d")
        _m3[_dt.strftime("%Y-%m")][_k] = _m3[_dt.strftime("%Y-%m")].get(_k, 0.0) + val(d)
    months = {ym: [{"d": k, "p": round(v, 2)} for k, v in sorted(dd.items())]
              for ym, dd in _m3.items()}
    # monthly report figures: trades, wins, longest winning streak
    _ms = {}
    for d in _since(m3_start):
        _ym = datetime.fromtimestamp(d.time, tz=timezone.utc).strftime("%Y-%m")
        st = _ms.setdefault(_ym, {"n": 0, "won": 0, "streak": 0, "_cur": 0})
        st["n"] += 1
        if val(d) > 0.005:
            st["won"] += 1
            st["_cur"] += 1
            st["streak"] = max(st["streak"], st["_cur"])
        elif val(d) < -0.005:
            st["_cur"] = 0
    month_stats = {k: {"n": v["n"], "won": v["won"], "streak": v["streak"]}
                   for k, v in _ms.items()}
    # 2026-09-27: "Depuis le debut" - the whole era of this member
    _alls, _ = out_deals(ERA, horizon)
    _alls = sorted(_alls, key=lambda d: d.time)
    _bm = {}
    for d in _alls:
        _k = datetime.fromtimestamp(d.time, tz=timezone.utc).strftime("%Y-%m")
        _bm[_k] = _bm.get(_k, 0.0) + val(d)
    _best = max(_bm.items(), key=lambda kv: kv[1]) if _bm else None
    since_start = {
        "first": (datetime.fromtimestamp(_alls[0].time, tz=timezone.utc)
                  .strftime("%Y-%m-%d") if _alls else None),
        "era": ERA.strftime("%Y-%m-%d"),
        "days": max(0, (utcnow - ERA).days),
        "n": len(_alls),
        "won": sum(1 for d in _alls if val(d) > 0.005),
        "net": round(sum(val(d) for d in _alls), 2),
        "best_month": ({"ym": _best[0], "p": round(_best[1], 2)} if _best else None),
    }
    # 2026-10-08 (owner): the progression as a filtered candle chart. One
    # candle per closed deal since the era start (open = cumulative result
    # before it, close = after), then the SAME silence filter and structure
    # engine as the price chart. The app server strips the structure for
    # everyone but the admin. Its own try: never costs the stats.
    eqc = None
    try:
        from owl_chart_feed import build as _fbuild, engine as _feng
        _raw, _cum, _lt = [], 0.0, 0
        for d in _alls:
            _t = max(int(d.time), _lt + 1); _lt = _t
            _o = _cum; _cum += val(d)
            _raw.append({"time": _t, "open": _o, "high": max(_o, _cum),
                         "low": min(_o, _cum), "close": _cum})
        _kept = _fbuild(_raw)
        if len(_kept) >= 3:
            # cold start: the engine needs two dots of one kind from its
            # first candle; like the chart's internal structure, try the
            # whole history then shorter tails, first direction wins
            for _w in (len(_kept), 120, 80, 50, 30, 20):
                _bk = []
                (_dots, _marks, _tr, _ch, _nx, _iv, _nxt_t, _iv_t, _dr,
                 _fl, _fl_t, _fd) = _feng(_kept[-_w:], brk_out=_bk)
                if _tr:
                    break
            if _tr:
                _dots = [x for x in _dots if x[2] == _tr]
            eqc = {"candles": _kept[-300:], "n_trades": len(_raw),
                   # the true current total (hidden trades + open trade),
                   # which the last SHOWN candle may not be
                   "now": round(_cum + floating, 2),
                   "live": ([int(utcnow.timestamp()), round(_cum, 2),
                             round(max(_cum, _cum + floating), 2),
                             round(min(_cum, _cum + floating), 2),
                             round(_cum + floating, 2)]
                            if abs(floating) > 0.004 else None),
                   "dots": _dots, "marks": _marks,
                   "breaks": [[x[0], x[1], round(x[2], 2)] for x in _bk][-12:],
                   "trend": _tr, "choch": _ch, "bos_dir": _dr,
                   "next_bos": round(_nx, 2) if _nx else None,
                   "invalid": round(_iv, 2) if _iv else None,
                   "next_bos_t": _nxt_t, "invalid_t": _iv_t,
                   "flip_bos": round(_fl, 2) if _fl else None,
                   "flip_bos_t": _fl_t, "flip_bos_dir": _fd}
        elif _kept:
            eqc = {"candles": _kept, "n_trades": len(_raw), "live": None,
                   "now": round(_cum + floating, 2)}
    except Exception as _e:
        eqc = {"err": f"{type(_e).__name__}: {_e}"}
    return {
        "name": u.get("name", uid),
        "acct": ai.login,
        "srv": ai.server,
        "real": ai.trade_mode == mt5.ACCOUNT_TRADE_MODE_REAL,
        "eurusd": eur,
        "balance": round(ai.balance, 2),
        "equity": round(ai.equity, 2),
        "today": round(today, 2),
        "week": round(week, 2),
        "month": round(month, 2),
        "max_dd_7d": round(dd, 2),
        "open_positions": len(open_list),
        "open_list": open_list,
        "trades": trades,
        "days": days,
        "day_trades": _dtr,
        "month_days": month_days,
        "months": months,
        "month_stats": month_stats,
        "since_start": since_start,
        "curve": curve[-120:],
        "curve30": curve30,
        # 2026-10-08: the curves are one point per TRADE, so the app cannot
        # derive their first date from their length - send it
        "curve_from": int(d7[-120:][0].time) if d7 else None,
        "curve30_from": int(d30[0].time) if d30 else None,
        "eqc": eqc,
        "updated_utc": utcnow.isoformat(timespec="seconds"),
    }


WEALTH_OUT = os.path.join(OUT, uid + ".wealth.json")
LAB_WEALTH = os.path.join(DIR, "lab", "wealth")
_wealth_t = 0.0


def wealth():
    """2026-10-08 (owner): the Patrimoine money centre. Every closed trade of
    the era and every deposit / withdrawal, kept APART so results are never
    moved by cash. The page computes the charts; this only gathers facts.
    Also copied to lab/wealth/<uid>.json for the chercheur."""
    ai = mt5.account_info()
    if ai is None:
        return None
    now = datetime.now(timezone.utc)
    horizon = now + timedelta(minutes=5)
    alld = sorted(mt5.history_deals_get(ERA, horizon) or [], key=lambda d: d.time)
    outs, ins_map = out_deals(ERA, horizon)
    outs = sorted(outs, key=lambda d: d.time)
    mine = {d.ticket for d in outs}
    trades = []
    for d in outs:
        _in = ins_map.get(d.position_id)
        trades.append([int(d.time), round(d.profit + d.commission + d.swap, 2),
                       round(d.volume, 2),
                       1 if (_in is not None and _in.type == mt5.DEAL_TYPE_BUY) else -1,
                       (round((d.time - _in.time) / 60) if _in is not None else None)])
    flows = [[int(d.time), round(d.profit, 2), (d.comment or "")[:40]]
             for d in alld if d.type == mt5.DEAL_TYPE_BALANCE]
    # anything else that moved the balance (hand trades on a bot-only
    # account, fees): needed to rebuild the balance before each trade
    others = [[int(d.time), round(d.profit + d.commission + d.swap, 2)]
              for d in alld
              if d.type != mt5.DEAL_TYPE_BALANCE and d.ticket not in mine
              and abs(d.profit + d.commission + d.swap) > 0.004]
    total = (sum(x[1] for x in trades) + sum(x[1] for x in flows)
             + sum(x[1] for x in others))
    return {"uid": uid, "name": u.get("name", uid), "era": ERA.isoformat(),
            "currency": ai.currency, "balance": round(ai.balance, 2),
            "equity": round(ai.equity, 2),
            "bal_start": round(ai.balance - total, 2),
            "trades": trades, "flows": flows, "others": others,
            "updated": int(time.time())}


_authfails = 0
while True:
    try:
        # account deleted from the app (2026-09-05)? stop cleanly - the
        # manager only respawns users still in the file
        if not any(x.get("id") == uid for x in
                   json.load(open(USERS, encoding="utf-8"))):
            try:
                os.remove(OUTP)
            except Exception:
                pass
            sys.exit(0)
    except SystemExit:
        raise
    except Exception:
        pass
    try:
        if not init():
            _authfails += 1
            data = {"error": "mt5 init failed"}
            if _authfails >= 6:
                # 6 straight login failures = bad credentials; the
                # manager cleans up this attempt (2026-09-06)
                data["auth_failed"] = True
        else:
            _authfails = 0
            data = compute()
            # the money centre's facts, once a minute (its own try: never
            # costs the 5-second stats)
            if time.time() - _wealth_t > 60:
                try:
                    _w = wealth()
                    if _w:
                        for _p in (WEALTH_OUT, os.path.join(LAB_WEALTH, uid + ".json")):
                            os.makedirs(os.path.dirname(_p), exist_ok=True)
                            json.dump(_w, open(_p + ".tmp", "w"))
                            os.replace(_p + ".tmp", _p)
                    _wealth_t = time.time()
                except Exception:
                    _wealth_t = time.time()
    except Exception as e:
        data = {"error": str(e)}
    data.setdefault("updated_utc",
                    datetime.now(timezone.utc).isoformat(timespec="seconds"))
    try:
        tmp = OUTP + ".tmp"
        json.dump(data, open(tmp, "w"))
        os.replace(tmp, OUTP)
    except Exception:
        pass
    time.sleep(5)
