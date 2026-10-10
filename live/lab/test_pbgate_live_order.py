"""Regression cases for the LIVE gate order and the ADAPTIVE day cap in the matrix / pullback arms (GPT review of
reply 18, items 1 and 3): kill, awake, dedupe, allowance (consumed), the pullback filter, weather, day cap, geometry.
    python live/lab/test_pbgate_live_order.py        (plain runner)"""
import sys, numpy as np
sys.path.insert(0, r"C:\Projects\KinoliveLines\study"); sys.path.insert(0, r"C:\Projects\KinoliveLines\live")
import tick_engine as E
from tick_engine_matrix import PolicyArm
from tick_engine_pbgate import PbGateArm
H = E.H
POL = {"entry": "immediate", "allowance": "current", "cap": "on"}


def cfg(**over):
    base = {"lot": 0.02, "balance": 0.0, "scale_lot": 0, "scale_daily": 0, "scale_ref": 200.0, "day_cap": 0.0, "rr": 0.8, "bullets": 3, "k_streak": 2,
            "kill_net": 0.0, "storm": 1.85, "movement": 1, "nerv_gate": False, "n_cont": 1, "debt_gate": 1, "min_balance": 0.0, "risk_fit": 0.0,
            "hard_cap_pct": 0.0, "jar": False, "drag": 0.0, "limits_live": 1}
    base.update(over); return H.cfg_strict(base)


def opp(t, d=1, slp=90.0, flip=False, awake=True, lvl=100.0, nv=1.0, mv2=None):
    return {"t": t, "i": 0, "d": d, "slp": slp, "cl": 100.0, "flip": flip, "awake": awake, "nv": nv, "mv2": mv2, "i_fire": False, "lvl": lvl, "weekday": 0, "hour": 0, "minute": 0}


def arr(rows):
    return (np.array([r[0] for r in rows], dtype=np.int64), np.array([r[1] for r in rows], dtype=float), np.array([r[2] for r in rows], dtype=float))


class Arm(PbGateArm):
    def __init__(self, mode, states, order="live", cap_rule="adaptive", policy=POL, c=None):
        PolicyArm.__init__(self, "t", c or cfg(), dict(policy), {}, order=order, cap_rule=cap_rule)
        self.gmode, self.S = mode, states; self.n.update({"pb_refused": 0, "pb_choch_allowed": 0, "pb_no_state": 0})


def test_weather_refusal_consumes_the_allowance_in_live_order_but_not_in_review16():
    TM, B, A = arr([(61_000, 100.0, 100.2), (121_000, 100.0, 100.2)])
    for order, consumed in (("live", 0), ("review16", 1)):
        a = Arm("none", {}, order=order); a.pk = 5.0                       # in debt
        a.signal(opp(0, flip=True, slp=100.0), 0, TM, B, A)                  # flip re-arms the one continuation (geometry too tight: no order left behind)
        a.signal(opp(60, lvl=101.0, nv=1.0, mv2=0), 1, TM, B, A)           # continuation refused by the MOVEMENT brake
        assert a.n["weather"] == 1 and a.cont_left == consumed, (order, a.cont_left)


def test_pullback_filter_runs_after_the_allowance_and_before_weather_and_cap():
    TM, B, A = arr([(61_000, 100.0, 100.2)])
    S = {0: (-1, 0, None, 95.0)}                                           # pullback trend DOWN, last BOS 95
    a = Arm("trend", S); a.pk = 5.0
    a.signal(opp(0, d=1, flip=True, nv=1.0, mv2=0), 0, TM, B, A)           # a BUY flip: against the structure AND asleep market
    assert a.n["pb_against_structure"] == 1 and a.n["weather"] == 0        # attributed to the filter (it comes first)
    assert a.last_flip_t == 0 and a.cont_left == 1                          # the flip's state update happened before the refusal


def test_filter_pass_then_weather_refusal_then_cap_refusal_in_that_order():
    TM, B, A = arr([(61_000, 100.0, 100.2), (121_000, 100.0, 100.2), (181_000, 100.0, 100.2)])
    S = {0: (1, 0, None, 95.0), 60: (1, 0, None, 95.0), 120: (1, 0, None, 95.0)}
    a = Arm("trend", S, c=cfg(day_cap=3.0))
    a.signal(opp(0, d=1, flip=True, mv2=0), 0, TM, B, A)                   # passes the filter (buy, trend up, 100.2 > 95), refused by movement (no order)
    assert a.n["weather"] == 1 and a.n["pb_refused"] == 0
    a.day_profit = 3.5
    a.signal(opp(60, d=1, flip=True), 1, TM, B, A)                          # passes the filter, cap reached, out of debt -> cap refusal
    assert a.n["day_cap"] == 1 and a.n["cap_plain_refusals"] == 1 and a.order is None
    a.day_profit = 0.0
    a.signal(opp(120, d=1, flip=True), 2, TM, B, A)                         # everything open -> an order
    assert a.order is not None and a.n["orders"] == 1


def test_adaptive_cap_cold_start_unrestricted_then_bonus_after_three_debt_days():
    TM, B, A = arr([(61_000, 100.0, 100.2)])
    S = {0: (1, 0, None, 95.0)}
    a = Arm("trend", S, c=cfg(day_cap=3.0)); a.pk = 10.0; a.day_profit = 4.0        # in debt, above the plain cap
    a.signal(opp(0, d=1, flip=True), 0, TM, B, A)
    assert a.order is not None and a.n["cap_unrestricted_cold"] == 1 and a.n["day_cap"] == 0   # fewer than 3 debt-day samples: unrestricted
    b = Arm("trend", S, c=cfg(day_cap=3.0)); b.pk = 10.0; b.debt_day_pnls = [1.0, 2.0, 9.0]    # median 2.0 -> cap 3 + 2 = 5
    b.day_profit = 4.0; b.signal(opp(0, d=1, flip=True), 0, TM, B, A)
    assert b.order is not None and b.n["cap_bonus_passes"] == 1                                 # 4 < 5: passes thanks to the bonus
    c2 = Arm("trend", S, c=cfg(day_cap=3.0)); c2.pk = 10.0; c2.debt_day_pnls = [1.0, 2.0, 9.0]
    c2.day_profit = 5.0; c2.signal(opp(0, d=1, flip=True), 0, TM, B, A)
    assert c2.order is None and c2.n["cap_bonus_refusals"] == 1                                 # 5 >= 5: refused
    d2 = Arm("trend", S, c=cfg(day_cap=3.0)); d2.pk = 10.0; d2.debt_day_pnls = [50.0, 60.0, 70.0]  # median 60 -> bonus capped at 5 x 3 = 15 -> cap 18
    d2.day_profit = 17.9; d2.signal(opp(0, d=1, flip=True), 0, TM, B, A); assert d2.order is not None
    e2 = Arm("trend", S, c=cfg(day_cap=3.0)); e2.pk = 10.0; e2.debt_day_pnls = [50.0, 60.0, 70.0]
    e2.day_profit = 18.0; e2.signal(opp(0, d=1, flip=True), 0, TM, B, A); assert e2.order is None


def test_cap_off_never_refuses_and_waiver_rule_is_the_old_harness_mirror():
    TM, B, A = arr([(61_000, 100.0, 100.2)])
    S = {0: (1, 0, None, 95.0)}
    off = Arm("trend", S, policy={"entry": "immediate", "allowance": "current", "cap": "off"}, c=cfg(day_cap=3.0)); off.day_profit = 99.0
    off.signal(opp(0, d=1, flip=True), 0, TM, B, A); assert off.order is not None and off.n["cap_waived_off"] == 1
    w = Arm("trend", S, cap_rule="waiver", c=cfg(day_cap=3.0)); w.pk = 10.0; w.day_profit = 99.0; w.debt_day_pnls = [1.0, 1.0, 1.0]
    w.signal(opp(0, d=1, flip=True), 0, TM, B, A); assert w.order is not None and w.n["day_cap"] == 0        # waiver: no cap at all in debt


def test_day_roll_records_debt_day_pnl_only_for_days_opened_in_debt():
    a = Arm("none", {}, c=cfg(day_cap=3.0))
    a.roll(0)                                   # day 1 opens flat
    a.day_profit = 2.0; a.roll(86_400_000)      # day 2: day 1 opened flat -> not recorded
    assert a.debt_day_pnls == []
    a.pk = 10.0; a.run = 0.0                    # now in debt at this day's open? (the open was recorded at the roll above: flat)
    a.day_profit = -1.0; a.roll(2 * 86_400_000)
    assert a.debt_day_pnls == [] and a.debt_at_day_open == 10.0     # day 3 opens in debt
    a.day_profit = 4.0; a.roll(3 * 86_400_000)
    assert a.debt_day_pnls == [4.0]                                  # day 3 opened in debt -> its P&L recorded


if __name__ == "__main__":
    import traceback
    ok = fail = 0
    for name in sorted(n for n in dir() if n.startswith("test_")):
        try: globals()[name](); ok += 1; print("PASS", name)
        except Exception: fail += 1; print("FAIL", name); traceback.print_exc()
    print("%d passed, %d failed" % (ok, fail)); sys.exit(1 if fail else 0)
