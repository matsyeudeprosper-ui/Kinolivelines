"""2026-11-01 (owner: "normally 1:1; if that trade hits its stop-loss, immediately the reverse trade on the next BOS at 1:2"):
the light checks of robots/robot_after.py and of every place that reads it (no bench, no MT5):
    python test_robot_after.py
The bench run of the owner's rule (a stop-out followed by the reverse 2R trade, and the old robots unchanged) is
study/robot_after_check.py (heavier: run it through study/when_free.py)."""
import json, os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import robot_after as RA
import robot_lot as L
import robot_dsl as D
import robot_live as RL

# 1. the history names: last_dir / last_hit_sl, and older callers unchanged
H = L.History(200)
assert H.names()["last_dir"] == 0 and H.names()["last_hit_sl"] == 0 and H.last_trade is None
H.add(-2.0)                                            # an older caller: pnl only
assert H.names()["last_dir"] == 0 and H.names()["last_pnl"] == -2.0
H.add(-1.5, d=-1, hit_sl=True, t=100.0)
assert H.names()["last_dir"] == -1 and H.names()["last_hit_sl"] == 1 and H.last_trade["tc"] == 100.0
assert L.lot("0.02 if last_hit_sl else 0.01", H.names()) == 0.02

# 2. the target formula: validated, described, priced
ok, ex = D.validate("exit", {"target": "2 if last_hit_sl else 1", "choch": False})
assert ok and ex["target"] == "2 if last_hit_sl else 1", ex
assert not D.validate("exit", {"target": "__import__('os')"})[0]
assert D.validate("exit", {"target": 1.0})[1]["target"] == 1.0                 # numbers as before
assert RL.tp_for({"exit": ex}, 1, 100.0, 10.0, 0.8, V=H.names()) == 120.0      # after a stop-out: 2R
assert RL.tp_for({"exit": ex}, -1, 100.0, 10.0, 0.8) == 90.0                    # no history: 1R
assert RL.tp_for({"exit": {"target": 1.5}}, 1, 100.0, 10.0, 0.8) == 115.0       # a number: unchanged

# 3. the after-loss block: validated, pending only right after a NORMAL trade's stop-out, the trade's own rules
ok, al = RA.validate({"entry": {"event": "any"}, "stop": {"kind": "protected", "buffer": 0}, "direction": "reverse", "target": 2}, D.validate)
assert ok, al
assert not RA.validate({"entry": {"event": "nope"}}, D.validate)[0]
assert not RA.validate({"entry": {"event": "any"}, "direction": "up"}, D.validate)[0]
assert RA.pending(al, {"d": -1, "hit_sl": True, "pnl": -1.0, "al": False, "tc": 0}) == 1      # stopped SELL -> a BUY
assert RA.pending(al, {"d": 1, "hit_sl": True, "pnl": -1.0, "al": False, "tc": 0}) == -1      # stopped BUY -> a SELL
assert RA.pending(al, {"d": 1, "hit_sl": True, "pnl": -1.0, "al": True, "tc": 0}) is None     # the reversal closed: normal
assert RA.pending(al, {"d": 1, "hit_sl": False, "pnl": 2.0, "al": False, "tc": 0}) is None    # a win: normal
normal = {"entry": {"event": "formula", "buy": "close < open @ M15 and close > open", "sell": "close > open @ M15 and close < open"},
          "stop": {"kind": "formula", "buy": "lowest(low, 10)", "sell": "highest(high, 10)"},
          "exit": {"target": 1.0, "choch": False, "time_min": None, "breakeven_at": None}, "after_loss": al}
r2 = RA.rules_for(normal, al)
assert r2["entry"] == {"event": "any"} and r2["stop"]["kind"] == "protected" and r2["exit"]["target"] == 2.0 and "after_loss" not in r2
assert RL.entry_ok(r2, "FLIP-BOS")[0] and RL.entry_ok(r2, "BOS")[0] and not RL.entry_ok(normal, "BOS")[0]
assert RL.tp_for(r2, 1, 100.0, 10.0, 0.8) == 120.0 and RL.tp_for(normal, 1, 100.0, 10.0, 0.8) == 110.0
assert RL.uses_formulas(normal) and not RL.uses_formulas({"after_loss": {"entry": {"event": "any"}}})

# 4. robots.json form (piece ids) -> rules, as the bench (robot_runner.arm_for) and the desk (robot_package) read it
P = {p["id"]: p for p in json.load(open(os.path.join(HERE, "robots.json"), encoding="utf-8"))["pieces"]}
fr = RA.from_parts({"entry": "p-toute-cassure-bos-ou-cho", "stop": "point-protege", "direction": "reverse", "target": 2.0}, P)
assert fr["entry"] == {"event": "any"} and fr["stop"]["kind"] == "protected" and fr["target"] == 2.0, fr
assert RA.from_parts({"entry": "cassure-tendance"}, P)["entry"] == {"event": "any"}          # the Owl's break entry = every break
assert RA.from_parts(None, P) is None and RA.from_parts({"entry": "no-such-piece"}, P) is None

# 5. the builder builds the owner's rule (never refuses it), and the demonstrations read it
import robot_chat as C
import robot_demo as RD
owl = {"entry": "cassure-tendance", "filters": ["tendance-fond", "orage", "mouvement"], "stop": "point-protege",
       "exit": "objectif-08r", "recovery": "rattrapage-limite", "money": "base"}
raw = {"robot": {"name": "Ma methode + retournement", "market": "BTCUSD", "entry": {"use": "p-bougie-du-haut-puis-boug"},
                 "filters": [], "stop": {"use": "p-stop-derriere-la-zone"}, "exit": {"use": "objectif-1r"},
                 "recovery": {"use": "rattrapage-limite"}, "money": {"use": "simple", "lot": "0.01"},
                 "after_loss": {"entry": {"rule": {"event": "any"}, "name": "cassure", "plain": "la cassure"},
                                "stop": {"use": "point-protege"}, "direction": "reverse", "target": 2}}}
pieces = list(P.values())
ans, probs = C.clean(raw, pieces, owl, None)
assert not probs and ans["robot"]["after_loss"]["target"] == 2.0 and ans["robot"]["after_loss"]["direction"] == "reverse", (probs, ans["robot"])
assert C.view(ans["robot"], pieces)["after_loss"]["plain_en"].startswith("When a trade hits its stop")
rules, rr = RD.rules_of(ans["robot"], pieces)
assert rules["after_loss"]["entry"] == {"event": "any"} and rules["after_loss"]["stop"] == {"kind": "protected"}
kept, _ = C.clean({"robot": dict(raw["robot"], after_loss="-")}, pieces, owl, ans["robot"])     # left out: kept
assert kept["robot"]["after_loss"] == ans["robot"]["after_loss"]
assert "after_loss" not in C.clean({"robot": dict(raw["robot"], after_loss=None)}, pieces, owl, ans["robot"])[0]["robot"]
raw_fx = {"robot": dict(raw["robot"], exit={"rule": {"target": "2 if last_hit_sl else 1", "choch": False}, "name": "1R / 2R", "plain": "x"})}
assert C.clean(raw_fx, pieces, owl, None)[1] == []
assert "RULES ON THE LAST TRADE'S RESULT" in C.SYSTEM and "never tell a member it cannot" in C.SYSTEM

# 6. 2026-11-02 (owner: "after a stop-out, the reverse trade on a 1-minute candle that CLOSES fully beyond the stop just
# hit; if that close never comes, a new breakout in the first direction is a second entry"): stop_close + alt
OWN = {"entry": {"event": "stop_close", "buffer": 0}, "stop": None, "direction": "reverse",
       "alt": {"entry": {"event": "bos"}, "direction": "same"}}
ok, own = RA.validate(OWN, D.validate)
assert ok and own["entry"] == {"event": "stop_close", "buffer": 0.0} and own["alt"]["direction"] == "same", own
assert own["alt"]["entry"] == {"event": "bos"} and own["alt"]["stop"] is None and own["alt"]["target"] is None
assert "alt" not in RA.validate({"entry": {"event": "any"}}, D.validate)[1]                    # old blocks: same shape
assert not RA.validate(dict(OWN, entry={"event": "stop_close", "buffer": -1}), D.validate)[0]
assert not RA.validate(dict(OWN, entry={"event": "stop_close", "order": {"type": "limit", "buy": "close", "sell": "close"}}), D.validate)[0]
assert not RA.validate(dict(OWN, alt={"entry": {"event": "nope"}}), D.validate)[0]
assert not RA.validate(dict(OWN, alt={"entry": {"event": "bos"}, "direction": "up"}), D.validate)[0]
assert not RA.validate(dict(OWN, alt="bos"), D.validate)[0]
assert "minute" in D.describe("entry", own["entry"])[1] and "stop" in D.describe("entry", own["entry"])[0]
# the history keeps the stopped trade's exact stop
H2 = L.History(200)
H2.add(-3.0, d=1, hit_sl=True, t=1000.0, sl=99.5, e=105.0)
assert H2.last_trade["sl"] == 99.5 and H2.last_trade["e"] == 105.0
H2.add(1.0)
assert H2.last_trade["sl"] is None                                           # older callers: unknown, not a stale value
last = {"d": 1, "hit_sl": True, "pnl": -3.0, "al": False, "tc": 1000.0, "sl": 99.5, "e": 105.0}   # a BUY stopped at 99.5
B = RA.branches(own, last, now=1000)
(m, ms), (a, as_) = B
assert ms == -1 and as_ == 1                                                 # main: SELL (reverse); alt: BUY (same)
# minute after minute: neither fires until a close below 99.5 - then the SELL, at that close
closes = [(1020, 100.4), (1080, 99.9), (1140, 99.5), (1200, 99.4)]
fired = [(t, RA.trigger(m, ms, last, "minute", close=c, t_close=t)) for t, c in closes]
assert fired == [(1020, 0), (1080, 0), (1140, 0), (1200, -1)], fired
# a SELL break (not the alt's side) and a CHoCH up (not a BOS) do nothing; a BUY BOS fires the alt first
assert RA.trigger(a, as_, last, "bos", d=-1, t_close=1080) == 0 and RA.trigger(a, as_, last, "choch", d=1, t_close=1080) == 0
assert RA.trigger(a, as_, last, "bos", d=1, t_close=1080) == 1
# a stopped SELL: the close must be ABOVE its stop
lastS = dict(last, d=-1, sl=120.0, e=110.0)
(m2, s2), (a2, t2) = RA.branches(own, lastS, now=1000)
assert s2 == 1 and t2 == -1 and RA.trigger(m2, s2, lastS, "minute", close=120.01, t_close=1020) == 1
assert RA.trigger(m2, s2, lastS, "minute", close=119.99, t_close=1020) == 0
# the buffer
ownb = RA.validate(dict(OWN, entry={"event": "stop_close", "buffer": 2}), D.validate)[1]
mb, sb = RA.branches(ownb, last)[0]
assert RA.trigger(mb, sb, last, "minute", close=98.0, t_close=1020) == 0 and RA.trigger(mb, sb, last, "minute", close=97.4, t_close=1020) == -1
# neither fires until expire_min: then back to normal
ownx = dict(own, expire_min=60)
assert RA.branches(ownx, last, now=1000 + 59 * 60) is not None and RA.branches(ownx, last, now=1000 + 61 * 60) is None
# the after-loss trade closed (whichever branch took it, whatever its result): back to normal
assert RA.branches(own, dict(last, al=True, hit_sl=True, pnl=-1.0)) is None and RA.branches(own, dict(last, al=True, pnl=4.0)) is None
assert RA.branches(own, dict(last, hit_sl=False, pnl=2.0)) is None             # a win: normal
# the same candle: the bench's order (sell side first, then the 1-minute candle, then the buy side)
assert RA.first_of([(1, "main", "alt-buy"), (0, "close", "close-sell")]) == "close-sell"
# robots.json form with the alt branch, and the desk's candle memory
PX = dict(P, **{"x-sc": {"id": "x-sc", "type": "entry", "rule": {"event": "stop_close", "buffer": 0.0}},
                "x-bos": {"id": "x-bos", "type": "entry", "rule": {"event": "bos"}}})
fp = RA.from_parts({"entry": "x-sc", "direction": "reverse", "alt": {"entry": "x-bos", "direction": "same"}}, PX)
assert fp["entry"]["event"] == "stop_close" and fp["alt"] == {"entry": {"event": "bos"}, "stop": None, "direction": "same", "target": None}, fp
assert RA.from_parts({"entry": "x-sc", "alt": {"entry": "no-such"}}, PX) is None
assert "alt" not in RA.from_parts({"entry": "x-sc"}, PX)
assert RL.uses_formulas({"after_loss": fp}) and RL.uses_formulas({"after_loss": {"entry": {"event": "any"}, "alt": {"entry": {"event": "formula", "buy": "close > open", "sell": None}}}})
assert RA.rules_for(normal, fp["alt"])["entry"] == {"event": "bos"}
# the builder builds it (and never as the normal entry), the page says it in plain words
raw_own = {"robot": dict(raw["robot"], after_loss={"entry": {"rule": {"event": "stop_close", "buffer": 0}, "name": "Cloture au-dela du stop"},
                                                   "stop": None, "direction": "reverse",
                                                   "alt": {"entry": {"rule": {"event": "bos"}, "name": "Cassure"}, "direction": "same"}})}
ans2, probs2 = C.clean(raw_own, pieces, owl, None)
assert not probs2, probs2
alc = ans2["robot"]["after_loss"]
assert alc["entry"]["rule"] == {"event": "stop_close", "buffer": 0.0} and alc["alt"]["direction"] == "same" and alc["alt"]["entry"]["rule"] == {"event": "bos"}
vw = C.view(ans2["robot"], pieces)["after_loss"]
assert "clôture au-delà du stop touché" in vw["plain_fr"] and "whichever happens first" in vw["plain_en"] and vw["alt"]["direction"] == "same", vw
assert C.clean({"robot": dict(raw["robot"], entry={"rule": {"event": "stop_close"}, "name": "x"})}, pieces, owl, None)[1]
assert "stop_close" in C.SYSTEM and '"alt"' in C.SYSTEM
assert RD._signals({"entry": {"event": "stop_close"}}, None, {"d": [1], "flip": [False], "slp": [1.0]}, None) == []
print("ok")
