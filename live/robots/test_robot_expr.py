"""tests of the formula language (python test_robot_expr.py): refusals, values, no look-ahead on bigger charts"""
import numpy as np
import robot_expr as X

BAD = ["__import__('os')", "close.__class__", "open('x')", "lambda: 1", "[1,2]", "'a'", "close[0]", "x = 1",
       "ema(close, n)", "ema(close, 0)", "ema(close, 9999)", "close @ H2", "(close @ H1) @ H4", "foo(close)",
       "close if 1 else 2", "close ** 2", "close % 2", "True", "getattr(close, 'x')", "ema(close, 5.5)", "a" * 500]
for b in BAD:
    ok, why = X.is_ok(b)
    assert not ok, b
print("refused", len(BAD), "bad formulas")
GOOD = ["close > ema(close, 50) @ H1 and rsi(close, 14) < 30", "cross_up(ema(close, 9), ema(close, 21))",
        "close - 1.5 * atr(14)", "not (hour >= 22) and london", "bos_up and trend == 1", "close > pdh",
        "macd(close, 12, 26) > macd_signal(close, 12, 26, 9)", "close < bb_low(close, 20, 2)", "rising(close, 3) && volume > sma(volume, 20)"]
for g in GOOD:
    ok, why = X.is_ok(g); assert ok, (g, why)
print("accepted", len(GOOD), "good formulas")

# synthetic minutes: 3 days, price = minute index
n = 3 * 1440; t0 = 1_700_006_400 - (1_700_006_400 % 86400)
t = t0 + 60 * np.arange(n); c = np.arange(n, dtype=float); o = c - 0.5; h = c + 1; l = c - 1; v = np.ones(n)
B = X.Bars(t, o, h, l, c, v)
for g in GOOD:
    r = X.evaluate(g, B); assert r.shape == (n,)
# the H1 close seen by a minute is the last CLOSED hour: at minute 59 of hour 0 it is hour 0's close (59), at minute 30 of hour 1 still 59
r = X.evaluate("close @ H1", B)
assert np.isnan(r[0]) and r[59] == 59 and r[60] == 59 and r[90] == 59 and r[119] == 119, (r[58:62], r[119])
# no look-ahead anywhere: changing the future never changes the past
c2 = c.copy(); c2[2000:] += 500
B2 = X.Bars(t, o, h, l, c2, v)
for g in GOOD:
    a, b = X.evaluate(g, B), X.evaluate(g, B2)
    same = (a[:2000] == b[:2000]) | (np.isnan(a[:2000]) & np.isnan(b[:2000]))
    assert same.all(), g
print("no look-ahead on", len(GOOD), "formulas")
# values
assert X.evaluate("sma(close, 3)", B)[2] == 1.0
assert X.evaluate("highest(high, 5)", B)[10] == 11.0
assert X.evaluate("pdh", B)[1440] == 1440.0      # previous day's high = last minute of day 1 (c=1439, h=1440)
assert X.evaluate("weekday", B)[0] == float(((t0 // 86400) + 3) % 7)
up = X.truth("cross_up(close, 100)", B); assert up.sum() == 1 and up[101]
rs = X.evaluate("rsi(close, 14)", B); assert rs[100] == 100.0
assert X.truth("hour == 1", B)[60] and not X.truth("hour == 1", B)[58]      # judged at the candle's close
print("ALL OK")
