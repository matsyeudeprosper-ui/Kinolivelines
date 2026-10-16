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


def profile(mt5):
    ai = mt5.account_info()
    if ai is None:
        return None
    btc = find_btc(mt5.symbols_get() or [])
    out = {"login": ai.login, "server": ai.server, "company": getattr(ai, "company", ""), "currency": ai.currency,
           "leverage": ai.leverage, "margin_mode": int(getattr(ai, "margin_mode", -1)), "checked_at": int(time.time())}
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
    add("feed", feed, True, "Signaux lus sur les prix de ce courtier" if feed else "Signaux lus sur les prix Exness, pas ceux de ce courtier",
        "Signals read on this broker's prices" if feed else "Signals read on Exness prices, not this broker's", "item 7 - per-broker feed")
    add("commission", True, False, "Commission par lot : à vérifier", "Commission per lot: to verify", "item 10")
    return C


def ready(p):
    bad = [c["k"] for c in checks(p) if c["block"] and not c["ok"]]
    return (not bad), bad
