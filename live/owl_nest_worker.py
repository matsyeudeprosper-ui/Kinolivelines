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
                if (d.comment or "").startswith("OWL-")}
    else:
        keep = {d.position_id for d in ins}
    return [d for d in alld if d.entry == mt5.DEAL_ENTRY_OUT
            and d.position_id in keep
            and datetime.fromtimestamp(d.time, tz=timezone.utc) >= frm]


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
    pnl = lambda ds: sum(d.profit + d.commission + d.swap for d in ds)
    today = pnl(out_deals(midnight, horizon))
    week = pnl(out_deals(monday, horizon))
    month = pnl(out_deals(month_start, horizon))
    d7 = sorted(out_deals(week_ago, horizon), key=lambda d: d.time)
    cum = peak = dd = 0.0
    curve = []
    for d in d7:
        cum += d.profit + d.commission + d.swap
        peak = max(peak, cum)
        dd = max(dd, peak - cum)
        curve.append(round(cum, 2))
    open_pos = mt5.positions_get(symbol=SYMBOL) or []
    if BOT_ONLY:
        floating = sum(p.profit + p.swap for p in open_pos
                       if (p.comment or "").startswith("OWL-"))
    else:
        floating = ai.equity - ai.balance
    dd = max(dd, peak - (cum + floating))
    _ddhist.append((time.time(), dd))
    while _ddhist and time.time() - _ddhist[0][0] > 7 * 86400:
        _ddhist.pop(0)
    dd = max(x[1] for x in _ddhist)
    if BOT_ONLY:
        _shown = [p for p in open_pos
                  if (p.comment or "").startswith("OWL-")]
    else:
        _shown = list(open_pos)
    open_list = [{"d": ("A" if p.type == mt5.POSITION_TYPE_BUY else "V"),
                  "lot": p.volume,
                  "pl": round(p.profit + p.swap, 2)} for p in _shown]
    te = mt5.symbol_info_tick("EURUSDm")
    eur = round(te.bid, 5) if te and te.bid > 0 else None
    trades = [{"w": datetime.fromtimestamp(d.time, tz=timezone.utc)
                    .strftime("%d/%m %H:%M"),
               "p": round(d.profit + d.commission + d.swap, 2)}
              for d in d7[-10:]][::-1]
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
    return {
        "name": u.get("name", uid),
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
        "curve": curve[-120:],
        "updated_utc": utcnow.isoformat(timespec="seconds"),
    }


while True:
    try:
        if not init():
            data = {"error": "mt5 init failed"}
        else:
            data = compute()
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
