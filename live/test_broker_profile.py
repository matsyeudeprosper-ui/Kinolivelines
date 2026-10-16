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
sys.exit(1 if fails else 0)
