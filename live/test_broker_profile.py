"""unit tests for broker_profile.checks / find_btc - fake brokers, no MT5.   python live/test_broker_profile.py"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import broker_profile as BP


class S:
    def __init__(self, **k):
        self.__dict__.update(k)


EXNESS_PRO = {"login": 1, "server": "Exness-MT5Real30", "company": "Exness Technologies Ltd", "currency": "USD", "leverage": 2000, "margin_mode": 2,
              "btc": {"name": "BTCUSD", "contract": 1.0, "tick_size": 0.01, "tick_value": 0.01, "vol_min": 0.01, "vol_step": 0.01, "filling_mode": 3,
                      "stops_level": 0, "point": 0.01, "clock_offset_h": 0}}
fails = 0


def expect(name, prof, want_ready, want_bad=()):
    global fails
    ok, bad = BP.ready(prof)
    good = ok == want_ready and set(bad) == set(want_bad)
    fails += not good
    print(("ok  " if good else "FAIL") + " %-38s ready=%s bad=%s" % (name, ok, bad))


expect("Exness Pro (today's accounts)", EXNESS_PRO, True)
p = {**EXNESS_PRO, "server": "ICMarketsSC-Demo", "company": "Raw Trading Ltd",
     "btc": {**EXNESS_PRO["btc"], "name": "BTCUSD.", "contract": 1.0, "clock_offset_h": 3, "filling_mode": 1}}
expect("IC Markets-like (name, clock, FOK, feed)", p, False, ("btc_name", "clock", "fill", "feed"))
p = {**EXNESS_PRO, "currency": "EUR", "margin_mode": 0}
expect("EUR netting account", p, False, ("currency", "hedging"))
p = {**EXNESS_PRO, "btc": {**EXNESS_PRO["btc"], "contract": 0.01, "tick_value": 0.0001, "vol_min": 0.1}}
expect("micro contract, min lot 0.1", p, False, ("contract", "lots"))
p = {**EXNESS_PRO, "btc": {**EXNESS_PRO["btc"], "stops_level": 2000}}
expect("broker min stop 20 $ > robot 10", p, False, ("stops",))
expect("no Bitcoin", {**EXNESS_PRO, "btc": None}, False, ("btc_found",))
expect("unreadable account", None, False, ("account",))

syms = [S(name="BTCEUR", description="Bitcoin vs Euro", path="Crypto\\BTCEUR", trade_mode=4),
        S(name="ETHUSD", description="Ethereum vs US Dollar", path="Crypto\\ETHUSD", trade_mode=4),
        S(name="BTCUSD.r", description="Bitcoin vs US Dollar", path="Crypto\\BTCUSD.r", trade_mode=4),
        S(name="BTCUSD", description="Bitcoin vs US Dollar", path="Crypto\\BTCUSD", trade_mode=0)]
b = BP.find_btc(syms)
good = b is not None and b.name == "BTCUSD.r"
fails += not good
print(("ok  " if good else "FAIL") + " find_btc skips disabled / EUR / ETH -> %s" % (b.name if b else None))
# FOREX.com (pilot 2026-10-16): the symbol is just "Bitcoin", quoted in USD; "Bitcoin Cash" must not win
syms = [S(name="Bitcoin Cash", description="Bitcoin Cash", path="CFD\\Cryptocurrencies\\Bitcoin Cash", trade_mode=4, currency_profit="USD"),
        S(name="Ethereum", description="Ethereum", path="CFD\\Cryptocurrencies\\Ethereum", trade_mode=4, currency_profit="USD"),
        S(name="Bitcoin", description="Bitcoin", path="CFD\\Cryptocurrencies\\Bitcoin", trade_mode=4, currency_profit="USD")]
b = BP.find_btc(syms)
good = b is not None and b.name == "Bitcoin"
fails += not good
print(("ok  " if good else "FAIL") + " find_btc finds FOREX.com's 'Bitcoin' -> %s" % (b.name if b else None))

# items 2/4/5 helpers (2026-10-16)
good = BP.pick_fill(3) == 2 and BP.pick_fill(1) == 1 and BP.pick_fill(2) == 2 and BP.pick_fill(0) == 0 and BP.pick_fill(1, IOC="IOC", FOK="FOK") == "FOK"
fails += not good
print(("ok  " if good else "FAIL") + " pick_fill: Exness(3)->IOC, FOREX.com(1)->FOK, 0->RETURN")
import datetime as _dt, time as _tm
from collections import namedtuple
Deal = namedtuple("Deal", "ticket time time_msc magic entry")
Tick = namedtuple("Tick", "time bid ask")


class FakeMT5:
    """broker clock UTC+3: tick times and deal times are 10800 s ahead of UTC"""
    def __init__(self):
        self.off = 10800; self.calls = []
    def symbol_info_tick(self, s):
        return Tick(int(_tm.time()) + self.off - 40, 1.0, 1.1)
    def history_deals_get(self, a, b):
        self.calls.append((a, b))
        return [Deal(1, int(a.timestamp()) + 60, (int(a.timestamp()) + 60) * 1000, 9, 1)]


fm = FakeMT5()
off = BP.clock_offset_s(fm, "Bitcoin")
frm = _dt.datetime(2026, 10, 16, 8, 0, tzinfo=_dt.timezone.utc); to = _dt.datetime(2026, 10, 16, 9, 0, tzinfo=_dt.timezone.utc)
ds = BP.deals_utc(fm, frm, to, off)
good = off == 10800 and fm.calls[0][0] == frm + _dt.timedelta(seconds=10800) and ds[0].time == int(frm.timestamp()) + 60 and ds[0].time_msc == (int(frm.timestamp()) + 60) * 1000
fails += not good
print(("ok  " if good else "FAIL") + " clock_offset_s measures +3 h; deals_utc shifts the window in and the deal times back (off=%s, deal=%s)" % (off, ds[0].time - int(frm.timestamp())))
fm.off = 0
good = BP.clock_offset_s(fm, "BTCUSD") == 0 and BP.deals_utc(fm, frm, to, 0)[0].time == int(frm.timestamp()) + 60
fails += not good
print(("ok  " if good else "FAIL") + " Exness: offset 0, deals untouched")
# (the market tests below continue; the exit is at the end)

# 2026-10-17 (owner: "are we assuming the user will trade only BTC?"): the nest's other markets at a broker
mk = [S(name="XAUUSDm", description="Gold vs US Dollar", path="Metals/XAUUSDm", trade_mode=4),
      S(name="XAUEUR", description="Gold vs Euro", path="Metals/XAUEUR", trade_mode=4),
      S(name="USTECm", description="US Tech 100 Index", path="Indices/USTECm", trade_mode=4),
      S(name="US30m", description="US Wall Street 30 Index", path="Indices/US30m", trade_mode=4),
      S(name="USOILm", description="US Crude Oil", path="Energies/USOILm", trade_mode=4),
      S(name="NAS100", description="Nasdaq 100", path="Indices/NAS100", trade_mode=0)]
for key, want in (("XAUUSD", "XAUUSDm"), ("USTEC", "USTECm"), ("US30", "US30m"), ("USOIL", "USOILm")):
    got = BP.find_market(mk, key); good = got is not None and got.name == want
    fails += not good; print(("ok  " if good else "FAIL") + " market %-7s -> %s" % (key, got.name if got else None))
got = BP.find_market([S(name="XAUEUR", description="Gold vs Euro", path="", trade_mode=4)], "XAUUSD")
fails += got is not None; print(("ok  " if got is None else "FAIL") + " gold in euro is not the nest's gold")
got = BP.find_market([S(name="NAS100", description="Nasdaq 100", path="", trade_mode=0)], "USTEC")
fails += got is not None; print(("ok  " if got is None else "FAIL") + " a symbol that cannot be traded does not count")
fx = [S(name="Bitcoin", description="Bitcoin", path="CFD/Cryptocurrencies", trade_mode=4), S(name="US Tech 100", description="US Tech 100", path="CFD/Indices", trade_mode=4),
      S(name="Gold", description="Gold Spot", path="CFD/Metals", trade_mode=4)]
got = BP.find_market(fx, "XAUUSD"); good = got is not None and got.name == "Gold"
fails += not good; print(("ok  " if good else "FAIL") + " FOREX.com-style 'Gold' found by name")
got = BP.find_market(fx, "USTEC"); good = got is not None and got.name == "US Tech 100"
fails += not good; print(("ok  " if good else "FAIL") + " FOREX.com-style 'US Tech 100' found by description")
print("\nfails:", fails); sys.exit(1 if fails else 0)
