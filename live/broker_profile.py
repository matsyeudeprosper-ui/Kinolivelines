"""broker_profile.py - the broker readiness check (owner 2026-10-16, multi-broker go-live item 1).

Reads one account's broker facts with light MetaTrader5 calls (no history) and checks them against what the bots
ASSUME today. A failed blocking check means real money would be traded on a wrong assumption; it names the
upgrade (review/MULTI_BROKER_GO_LIVE.md items 2-7) that removes it. Trading is not activated while any blocking
check fails (owl_app_server activate route).

    profile(mt5)            -> dict of facts (the worker calls it every 6 h; nest_data/<uid>.broker.json)
    checks(prof)            -> [{"k", "ok", "block", "fr", "en", "fix"}], pure - unit-tested in test_broker_profile.py
    ready(prof)             -> (bool, [failed blocking keys])
"""
import time

KNOWN_BTC = ("BTCUSD", "BTCUSDm")        # the names the bots resolve today
EXNESS_FEED = "exness"                   # every bot reads ONE chart feed built from an Exness account
S_MIN_DIST = 10.0                        # the bots' minimum stop on Bitcoin, in price points ($)
FILL_IOC, FILL_FOK = 2, 1                # SYMBOL_FILLING_* flags in symbol_info.filling_mode
HEDGING = 2                              # ACCOUNT_MARGIN_MODE_RETAIL_HEDGING


def find_btc(symbols):
    """the account's Bitcoin-vs-dollar symbol among symbol_info rows (name / description / path), or None"""
    best, score = None, 0
    for s in symbols:
        name = str(getattr(s, "name", "") or "").upper()
        desc = str(getattr(s, "description", "") or "").upper()
        path = str(getattr(s, "path", "") or "").upper()
        if int(getattr(s, "trade_mode", 0) or 0) == 0:
            continue
        ccy = str(getattr(s, "currency_profit", "") or "").upper()
        sc = 0
        if name.startswith("BTCUSD") or name.startswith("XBTUSD"):
            sc += 3
        if "BITCOIN" in desc and ("DOLLAR" in desc or "USD" in desc):
            sc += 2
        if name == "BITCOIN" and ccy == "USD":          # FOREX.com (pilot 2026-10-16): symbol "Bitcoin", quoted in USD
            sc += 3
        if "CRYPTO" in path:
            sc += 1
        if "BTC" in name and ("EUR" in name or "JPY" in name or "GBP" in name or "ETH" in name):
            sc = 0
        if sc > score or (sc == score and best is not None and len(name) < len(str(best.name))):
            best, score = s, sc
    return best if score >= 3 else None


# 2026-10-17 (owner: "are we assuming the user will trade only BTC?"): the nest's other markets, so the sign-up probe
# and the member's broker profile say which of them exist at THIS broker. Real money is Bitcoin-only today; a market
# robot or a market that qualifies later will be refused on an account whose broker lacks it (owl_app_server).
NEST_MARKETS = [
    ("XAUUSD", "Or", "Gold", ("XAUUSD", "GOLD"), ("GOLD",)),
    ("USTEC", "Nasdaq 100", "Nasdaq 100", ("USTEC", "NAS100", "US100", "NDX100", "USTECH", "NASDAQ"), ("NASDAQ", "NAS 100", "US TECH")),
    ("US30", "Dow Jones", "Dow Jones", ("US30", "DJ30", "DOW", "DJI30", "WS30"), ("DOW", "WALL STREET")),
    ("USOIL", "Pétrole US", "US oil", ("USOIL", "WTI", "XTIUSD", "CRUDEOIL", "OILUSD", "USCRUDE", "CL"), ("WTI", "CRUDE")),
]


def find_market(symbols, key):
    """the account's symbol for one nest market (name prefixes first, then the description), or None"""
    spec = next((m for m in NEST_MARKETS if m[0] == key), None)
    if spec is None:
        return None
    _, _, _, names, words = spec
    best, score = None, 0
    for s in symbols:
        if int(getattr(s, "trade_mode", 0) or 0) == 0:
            continue
        name = str(getattr(s, "name", "") or "").upper()
        desc = str(getattr(s, "description", "") or "").upper()
        base = name.rstrip("M").rstrip(".").rstrip("_")
        sc = 0
        if name in names or base in names:
            sc += 3
        elif any(name.startswith(n) for n in names):
            sc += 2
        elif any(w in name for w in words):              # FOREX.com-style "US Tech 100", "Gold"
            sc += 2
        if any(w in desc for w in words):
            sc += 1
        if key == "XAUUSD" and ("EUR" in name or "GBP" in name or "AUD" in name or "XAG" in name):
            sc = 0
        if sc > score or (sc == score and best is not None and len(name) < len(str(best.name))):
            best, score = s, sc
    return best if score >= 2 else None


def markets(mt5, symbols=None):
    """{key: {name, spread, contract, digits} | None} for every nest market"""
    syms = symbols if symbols is not None else (mt5.symbols_get() or [])
    out = {}
    for key, fr, en, _, _ in NEST_MARKETS:
        s = find_market(syms, key)
        if s is None:
            out[key] = None
            continue
        try:
            si = mt5.symbol_info(s.name)
            out[key] = {"name": si.name, "spread": int(si.spread or 0), "point": si.point, "contract": si.trade_contract_size,
                        "digits": si.digits, "vol_min": si.volume_min, "ccy_profit": si.currency_profit}
        except Exception:
            out[key] = {"name": getattr(s, "name", "?")}
    return out


def profile(mt5):
    ai = mt5.account_info()
    if ai is None:
        return None
    _syms = mt5.symbols_get() or []
    btc = find_btc(_syms)
    out = {"login": ai.login, "server": ai.server, "company": getattr(ai, "company", ""), "currency": ai.currency,
           "leverage": ai.leverage, "margin_mode": int(getattr(ai, "margin_mode", -1)), "checked_at": int(time.time())}
    try:
        out["markets"] = markets(mt5, _syms)
    except Exception:
        out["markets"] = {}
    if btc is None:
        out["btc"] = None
        return out
    si = mt5.symbol_info(btc.name)
    tk = mt5.symbol_info_tick(btc.name)
    off_h = None
    if tk is not None and getattr(tk, "time", 0):
        off_h = round((int(tk.time) - time.time()) / 3600.0)        # broker server time - UTC, whole hours
    out["btc"] = {"name": si.name, "description": si.description, "path": si.path, "digits": si.digits, "point": si.point,
                  "contract": si.trade_contract_size, "tick_size": si.trade_tick_size, "tick_value": si.trade_tick_value,
                  "vol_min": si.volume_min, "vol_step": si.volume_step, "vol_max": si.volume_max,
                  "filling_mode": int(si.filling_mode), "stops_level": int(si.trade_stops_level), "freeze_level": int(si.trade_freeze_level),
                  "trade_mode": int(si.trade_mode), "spread": int(si.spread or 0), "ccy_profit": si.currency_profit,
                  "clock_offset_h": off_h}
    return out


def checks(p):
    """pure: facts -> the readiness list"""
    C = []

    def add(k, ok, block, fr, en, fix):
        C.append({"k": k, "ok": bool(ok), "block": bool(block), "fr": fr, "en": en, "fix": fix})

    if not p:
        add("account", False, True, "Compte illisible pour l'instant", "Account not readable yet", "attendre la connexion")
        return C
    b = p.get("btc")
    add("btc_found", b is not None, True, "Bitcoin trouvé chez ce courtier" if b else "Pas de Bitcoin chez ce courtier",
        "Bitcoin found at this broker" if b else "No Bitcoin at this broker", "item 2")
    if b is None:
        return C
    add("btc_name", b["name"] in KNOWN_BTC, True, "Nom du Bitcoin connu des robots (%s)" % b["name"],
        "Bitcoin name known to the robots (%s)" % b["name"], "item 2 - symbol finder")
    usd_pt = (float(b["tick_value"]) / float(b["tick_size"])) if b.get("tick_size") else 0.0
    add("contract", abs(float(b["contract"]) - 1.0) < 1e-9 and abs(usd_pt - 1.0) < 1e-6, True,
        "1 lot = 1 BTC, 1 $ par point (contrat %s, %.4g $/point)" % (b["contract"], usd_pt),
        "1 lot = 1 BTC, $1 per point (contract %s, %.4g $/point)" % (b["contract"], usd_pt), "item 3 - contract sizing")
    add("lots", float(b["vol_min"]) <= 0.01 + 1e-9 and float(b["vol_step"]) <= 0.01 + 1e-9, True,
        "Lot minimum %s, pas %s" % (b["vol_min"], b["vol_step"]), "Minimum lot %s, step %s" % (b["vol_min"], b["vol_step"]), "item 3 - contract sizing")
    add("fill", int(b["filling_mode"]) & FILL_IOC, True, "Type d'exécution accepté par le robot" if int(b["filling_mode"]) & FILL_IOC else "Type d'exécution refusé (IOC absent)",
        "Order fill type accepted" if int(b["filling_mode"]) & FILL_IOC else "Order fill type refused (no IOC)", "item 5 - fill type")
    stop_pts = float(b["stops_level"]) * float(b["point"])
    add("stops", stop_pts <= S_MIN_DIST, True, "Distance minimale du stop %.2f (robot : %.0f)" % (stop_pts, S_MIN_DIST),
        "Minimum stop distance %.2f (robot: %.0f)" % (stop_pts, S_MIN_DIST), "item 5 - stop rules")
    off = b.get("clock_offset_h")
    add("clock", off == 0, True, "Horloge du courtier en UTC" if off == 0 else "Horloge du courtier décalée (%s h)" % off,
        "Broker clock on UTC" if off == 0 else "Broker clock offset (%s h)" % off, "item 4 - broker clock")
    add("currency", str(p.get("currency")).upper() == "USD", True, "Compte en dollars" if str(p.get("currency")).upper() == "USD" else "Compte en %s" % p.get("currency"),
        "Dollar account" if str(p.get("currency")).upper() == "USD" else "Account in %s" % p.get("currency"), "item 6 - account currency")
    add("hedging", p.get("margin_mode") == HEDGING, True, "Positions séparées autorisées (couverture)" if p.get("margin_mode") == HEDGING else "Compte en mode net (une seule position)",
        "Separate positions allowed (hedging)" if p.get("margin_mode") == HEDGING else "Netting account (one position only)", "bot logic - adds need hedging")
    feed = EXNESS_FEED in str(p.get("server", "")).lower() or EXNESS_FEED in str(p.get("company", "")).lower()
    if not feed:
        # 2026-10-16 item 7: a per-broker feed (owl_chart_broker.py -> chart_broker/<key>.json) that is alive counts
        try:
            import broker_book as _BB
            feed = _BB.feed_fresh(p.get("server", ""))
        except Exception:
            feed = False
    add("feed", feed, True, "Signaux lus sur les prix de ce courtier" if feed else "Signaux lus sur les prix Exness, pas ceux de ce courtier",
        "Signals read on this broker's prices" if feed else "Signals read on Exness prices, not this broker's", "item 7 - per-broker feed")
    add("commission", True, False, "Commission par lot : à vérifier", "Commission per lot: to verify", "item 10")
    return C


def ready(p):
    bad = [c["k"] for c in checks(p) if c["block"] and not c["ok"]]
    return (not bad), bad


# ---- items 2, 4, 5 (2026-10-16): the three broker differences a bot meets at a non-Exness broker ----
def pick_fill(flags, IOC=2, FOK=1, RETURN=0):
    """item 5 - the order fill type this symbol accepts: IOC when allowed (the bots' habit), else FOK, else RETURN.
    flags = symbol_info.filling_mode (bit 1 FOK, bit 2 IOC). Values default to the MetaTrader5 constants."""
    f = int(flags or 0)
    if f & FILL_IOC:
        return IOC
    if f & FILL_FOK:
        return FOK
    return RETURN


def clock_offset_s(mt5, symbol):
    """item 4 - broker server time minus UTC, in whole hours, as seconds (Exness 0; many brokers +7200/+10800).
    Measured on the symbol's last tick: the tick is never more than a few minutes old on a 24/7 market."""
    try:
        tk = mt5.symbol_info_tick(symbol)
        if tk is None or not getattr(tk, "time", 0):
            return 0
        return int(round((int(tk.time) - time.time()) / 3600.0)) * 3600
    except Exception:
        return 0


def deals_utc(mt5, frm, to, off_s):
    """item 4 - history_deals_get with UTC datetimes in and UTC deal times out, whatever the broker's clock:
    the window is shifted INTO broker time for the query, each deal's time shifted BACK by the same offset."""
    import datetime as _dt
    sh = _dt.timedelta(seconds=int(off_s or 0))
    ds = mt5.history_deals_get(frm + sh, to + sh) or []
    if not off_s:
        return list(ds)
    return [d._replace(time=int(d.time) - int(off_s), time_msc=int(getattr(d, "time_msc", d.time * 1000)) - int(off_s) * 1000) for d in ds]
