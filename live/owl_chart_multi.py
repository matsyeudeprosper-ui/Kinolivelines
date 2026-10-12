"""owl_chart_multi.py - chart data for the other markets (owner 2026-10-12: "a way in the chart to switch
symbols, split screens included").

Runs the BTC chart feed's OWN code (owl_chart_feed.tick_once + htf_tick) once per market, each market in its
own copy of the module, so pins, sticky pullback chain and higher-timeframe ages never mix between markets:

  * OUT / HTFF / NHF / PB_CHAIN point to live/chart_multi/<SYM>*.json;
  * `mt5` is a thin stand-in that returns the market's prices multiplied by 10^(digits-2): the feed's engine
    rounds to 2 decimals (written for BTC), scaling keeps a currency's full precision. The scale and the
    digits are published in chart_multi/meta.json; the chart page divides when it writes a price.

Read only (prices from the feed's demo terminal). The BTC feed (owl_chart_feed.py, owl_chart_btc.json) is
untouched and keeps running on its own.
    python owl_chart_multi.py
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
OUTD = os.path.join(DIR, "chart_multi")
os.makedirs(OUTD, exist_ok=True)
LOG = os.path.join(OUTD, "multi.log")
SYMS = [("XAUUSD", "Or", "Gold"), ("XAGUSD", "Argent", "Silver"), ("USOIL", "Pétrole US", "US oil"),
        ("US30", "Dow Jones", "Dow Jones"), ("USTEC", "Nasdaq 100", "Nasdaq 100"), ("US500", "S&P 500", "S&P 500"),
        ("DE30", "DAX", "DAX"), ("UK100", "FTSE 100", "FTSE 100"), ("JP225", "Nikkei 225", "Nikkei 225"),
        ("EURUSD", "Euro / Dollar", "Euro / Dollar"), ("GBPUSD", "Livre / Dollar", "Pound / Dollar"),
        ("USDJPY", "Dollar / Yen", "Dollar / Yen")]
CYCLE_S = 10


def log(m):
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ ") + m + "\n")
    except Exception:
        pass


class ScaledMT5(types.ModuleType):
    """mt5 for one market: prices multiplied by `s`, everything else passed through"""

    def __init__(self, s):
        super().__init__("mt5_scaled")
        self._s = float(s)

    def __getattr__(self, k):
        return getattr(mt5, k)

    def copy_rates_from_pos(self, *a, **k):
        R = mt5.copy_rates_from_pos(*a, **k)
        if R is None or self._s == 1.0:
            return R
        R = R.copy()
        for f in ("open", "high", "low", "close"):
            R[f] = R[f] * self._s
        return R

    def symbol_info_tick(self, sym):
        t = mt5.symbol_info_tick(sym)
        if t is None or self._s == 1.0:
            return t
        return types.SimpleNamespace(bid=t.bid * self._s, ask=t.ask * self._s, last=t.last * self._s,
                                     time=t.time, time_msc=t.time_msc, volume=t.volume)


def instance(sym, scale):
    p = os.path.join(DIR, "owl_chart_feed.py")
    spec = importlib.util.spec_from_file_location("ocf_" + sym, p)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    m.SYMBOL = sym
    m.OUT = os.path.join(OUTD, sym + ".json")
    m.HTFF = os.path.join(OUTD, sym + "_htf.json")
    m.NHF = os.path.join(OUTD, sym + "_nerv.json")
    m.PB_CHAIN = os.path.join(OUTD, sym + "_pbchain.json")
    m.mt5 = ScaledMT5(scale)
    return m


def main():
    first = instance(SYMS[0][0], 1.0)
    first.mt5 = mt5
    assert first.connect(), "no terminal"
    meta, inst = {}, {}
    for sym, fr, en in SYMS:
        info = mt5.symbol_info(sym)
        if info is None:
            log("%s: not on this terminal" % sym)
            continue
        mt5.symbol_select(sym, True)
        s = 10 ** max(0, int(info.digits) - 2)
        inst[sym] = instance(sym, s)
        meta[sym] = {"name_fr": fr, "name_en": en, "digits": int(info.digits), "scale": s}
        try:
            inst[sym].pb_catch_up()
        except Exception as e:
            log("%s: pullback catch-up skipped %r" % (sym, e))
    json.dump({"updated": int(time.time()), "symbols": meta}, open(os.path.join(OUTD, "meta.json"), "w", encoding="utf-8"))
    log("multi feed up: %d markets" % len(inst))
    while True:
        t0 = time.time()
        for sym, m in inst.items():
            try:
                m.tick_once()
            except Exception as e:
                log("%s error %r" % (sym, e))
        time.sleep(max(2.0, CYCLE_S - (time.time() - t0)))


if __name__ == "__main__":
    main()
