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
print("ok")
