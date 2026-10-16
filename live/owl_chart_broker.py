"""owl_chart_broker.py - the Bitcoin chart feed read on ANOTHER broker's prices (owner 2026-10-16, go-live item 7:
"signals depend on the broker's price... we should be connected to the brokers to get the right price").

One process per broker, on the pattern of owl_chart_multi.py: the BTC feed's OWN code (owl_chart_feed) runs in its
own module copy, connected to a price-only account at that broker, with every output under live/chart_broker/:
    <key>.json  <key>_htf.json  <key>_nerv.json  <key>_pbchain.json   (+ meta.json: key -> server, symbol, updated)
The Exness feed (owl_chart_feed.py -> owl_chart_btc.json) is untouched. Readers pick the file by the member's
broker key (broker_book.key_of). Feed account, in order: owl_secrets.json "feed_<key>" or "pilot_<key>" (a demo
the owner opened), else the first nest member on that broker (prices only - nothing is sent).
    python owl_chart_broker.py forexcomglobal
"""
import importlib.util
import json
import os
import sys
import time
import types
from datetime import datetime, timezone

import MetaTrader5 as mt5

DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, DIR)
import broker_book as BB
import broker_profile as BP

OUTD = os.path.join(DIR, "chart_broker")
os.makedirs(OUTD, exist_ok=True)
CYCLE_S = 10


def log(key, m):
    try:
        with open(os.path.join(OUTD, key + ".log"), "a", encoding="utf-8") as f:
            f.write(datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ ") + m + "\n")
    except Exception:
        pass


def feed_accounts(key):
    """[(terminal, login, password, server-or-address)] for this broker: the owner's demo first, members after"""
    out = []
    sec = BB._load(os.path.join(DIR, "owl_secrets.json"), {})
    for k, P in sec.items():                 # any pilot_* / feed_* entry whose server belongs to this broker
        if isinstance(P, dict) and P.get("terminal") and P.get("server") and BB.key_of(P["server"]) == key:
            out.append((P["terminal"], int(P["login"]), P["password"], P.get("server_addr") or P["server"]))
    try:
        for u in json.load(open(os.path.join(DIR, "owl_nest_users.json"), encoding="utf-8")):
            if BB.key_of(u.get("mt5_server")) == key and u.get("terminal") and u.get("mt5_login") and os.path.exists(u["terminal"]):
                out.append((u["terminal"], int(u["mt5_login"]), u.get("mt5_password") or "", u.get("mt5_server_addr") or u["mt5_server"]))
    except Exception:
        pass
    return out


class ShiftedMT5(types.ModuleType):
    """mt5 for one broker: candle and tick times brought back to UTC (item 4 - FOREX.com's clock is UTC+3, and the
    feed, the chart and the bots compare candle times with the real clock); everything else passed through"""

    def __init__(self):
        super().__init__("mt5_shifted")
        self.off = 0

    def __getattr__(self, k):
        return getattr(mt5, k)

    def copy_rates_from_pos(self, *a, **k):
        R = mt5.copy_rates_from_pos(*a, **k)
        if R is None or not self.off:
            return R
        R = R.copy(); R["time"] = R["time"] - self.off
        return R

    def symbol_info_tick(self, sym):
        t = mt5.symbol_info_tick(sym)
        if t is None or not self.off:
            return t
        return types.SimpleNamespace(bid=t.bid, ask=t.ask, last=t.last, time=t.time - self.off,
                                     time_msc=t.time_msc - self.off * 1000, volume=t.volume)


def instance(key, symbol, accounts):
    p = os.path.join(DIR, "owl_chart_feed.py")
    spec = importlib.util.spec_from_file_location("ocf_broker_" + key, p)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    m.SYMBOL = symbol
    m.OUT = os.path.join(OUTD, key + ".json")
    m.HTFF = os.path.join(OUTD, key + "_htf.json")
    m.NHF = os.path.join(OUTD, key + "_nerv.json")
    m.PB_CHAIN = os.path.join(OUTD, key + "_pbchain.json")
    m.TERMINAL, m.LOGIN, m.PASSWORD, m.SERVER = accounts[0][0], accounts[0][1], accounts[0][2], accounts[0][3]
    m.candle_sources = lambda: [(t, l, s, pw) for t, l, pw, s in accounts]      # this broker's accounts only
    m.mt5 = ShiftedMT5()
    return m


def main(key):
    accounts = feed_accounts(key)
    assert accounts, "no feed account for broker %s (owl_secrets feed_%s / pilot_%s, or a member there)" % (key, key, key)
    page = next((v for k, v in BB.book().items() if BB.key_of(v.get("server")) == key), None) or {}
    symbol = ((page.get("btc") or {}).get("name")) or "BTCUSD"
    m = instance(key, symbol, accounts)
    assert m.connect(), "no terminal at %s could serve %s candles" % (key, symbol)
    ai = m.mt5.account_info()
    if m.mt5.symbol_info(symbol) is None:
        b = BP.find_btc(m.mt5.symbols_get() or [])
        assert b is not None, "no Bitcoin symbol at %s" % key
        symbol = b.name; m.SYMBOL = symbol
    m.mt5.symbol_select(symbol, True)
    off = BP.clock_offset_s(mt5, symbol)
    m.mt5.off = off                                   # from here every candle and tick time the feed sees is UTC
    log(key, "broker feed up: %s (%s) symbol %s clock UTC%+.0f h" % (ai.server if ai else "?", ai.company if ai else "?", symbol, off / 3600))
    try:
        m.pb_catch_up()
    except Exception as e:
        log(key, "pullback catch-up skipped %r" % (e,))
    last_fix = 0.0
    while True:
        t0 = time.time()
        try:
            m.tick_once()
        except Exception as e:
            log(key, "error %r" % (e,))
        try:
            meta = BB._load(os.path.join(OUTD, "meta.json"), {}) or {}
            meta[key] = {"server": ai.server if ai else "", "company": ai.company if ai else "", "symbol": symbol, "clock_offset_s": off, "updated": int(time.time())}
            BB._save(os.path.join(OUTD, "meta.json"), meta)
        except Exception:
            pass
        try:
            age = time.time() - os.path.getmtime(m.OUT)
        except OSError:
            age = 1e9
        if age > 120 and time.time() - last_fix > 300:          # same self-heal as the Exness and market feeds
            last_fix = time.time()
            ok = m.connect()
            m.mt5.symbol_select(symbol, True)
            log(key, "file stale (%.0f s) - reconnect %s" % (age, "ok" if ok else "FAILED"))
        time.sleep(max(2.0, CYCLE_S - (time.time() - t0)))


if __name__ == "__main__":
    main(BB.key_of(sys.argv[1]) if "-" in sys.argv[1] else sys.argv[1].lower())
