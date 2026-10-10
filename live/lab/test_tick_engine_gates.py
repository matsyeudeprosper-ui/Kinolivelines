"""Regression cases for the gate ORDER of the matrix / Compte / pullback arms (ChatGPT review 16):
ordinary gates with their state updates first, the arm's late hook immediately before the setup.
    python live/lab/test_tick_engine_gates.py        (plain runner)"""
import sys, numpy as np
sys.path.insert(0, r"C:\Projects\KinoliveLines\study")
import tick_engine as E
from tick_engine_matrix import PolicyArm
from tick_engine_compte import GatedArm
H = E.H
POL = {"entry": "immediate", "allowance": "current", "cap": "on"}


def cfg(**over):
    base = {"lot": 0.02, "balance": 0.0, "scale_lot": 0, "scale_daily": 0, "scale_ref": 200.0, "day_cap": 0.0, "rr": 0.8, "bullets": 3, "k_streak": 2,
            "kill_net": 0.0, "storm": 1.85, "movement": 1, "nerv_gate": False, "n_cont": 1, "debt_gate": 1, "min_balance": 0.0, "risk_fit": 0.0,
            "hard_cap_pct": 0.0, "jar": False, "drag": 0.0, "limits_live": 1}
    base.update(over); return H.cfg_strict(base)


class WeakStates:
    """a Compte source that is always weak and informative (trend -1, no CHoCH up)"""
    def at(self, t_ms): return {"global": {"trend": -1, "choch": 0, "status": "ok", "valid": True, "informative": True, "n": 50},
                                "buy": {"trend": -1, "choch": 0, "status": "ok", "valid": True, "informative": True, "n": 25},
                                "sell": {"trend": -1, "choch": 0, "status": "ok", "valid": True, "informative": True, "n": 25}, "last_close_ms": t_ms - 1000}


def opp(t, d=1, slp=90.0, flip=False, awake=True, lvl=100.0):
    return {"t": t, "i": 0, "d": d, "slp": slp, "cl": 100.0, "flip": flip, "awake": awake, "nv": 1.0, "mv2": None, "i_fire": False, "lvl": lvl, "weekday": 0, "hour": 0, "minute": 0}


def arr(rows):
    return (np.array([r[0] for r in rows], dtype=np.int64), np.array([r[1] for r in rows], dtype=float), np.array([r[2] for r in rows], dtype=float))


def test_asleep_signal_is_refused_by_the_ordinary_gate_not_by_compte():
    TM, B, A = arr([(61_000, 100.0, 100.2)])
    g = GatedArm("global_pause", cfg(), {}, "global", WeakStates()); n0 = PolicyArm("no_pause", cfg(), POL, {})
    for arm in (g, n0): arm.signal(opp(0, awake=False), 0, TM, B, A)
    assert n0.n["not_awake"] == 1 and g.n["not_awake"] == 1
    assert g.n["eligible_for_gate"] == 0 and g.n["paused"] == 0 and g.n["signals"] == 1


def test_paused_flip_in_debt_still_updates_flip_and_allowance_state():
    TM, B, A = arr([(61_000, 100.0, 100.2)])
    g = GatedArm("global_pause", cfg(), {}, "global", WeakStates()); g.pk = 5.0      # in debt
    g.signal(opp(0, flip=True), 0, TM, B, A)
    assert g.n["eligible_for_gate"] == 1 and g.n["paused"] == 1 and g.pend is None and g.order is None
    assert g.last_flip_t == 0 and g.cont_left == 1, (g.last_flip_t, g.cont_left)   # the flip re-armed the allowance even though the entry was paused


def test_later_continuation_consumes_the_allowance_then_is_paused():
    TM, B, A = arr([(61_000, 100.0, 100.2), (121_000, 100.0, 100.2)])
    g = GatedArm("global_pause", cfg(), {}, "global", WeakStates()); g.pk = 5.0
    g.signal(opp(0, flip=True), 0, TM, B, A)
    g.signal(opp(60, flip=False, lvl=101.0), 1, TM, B, A)       # the one continuation: allowance consumed, then paused by Compte
    assert g.cont_left == 0 and g.n["paused"] == 2 and g.used_hi == 101.0
    g.signal(opp(120, flip=False, lvl=102.0), 1, TM, B, A)      # no allowance left: refused by the ordinary debt gate, not counted eligible
    assert g.n["debt_gate"] == 1 and g.n["eligible_for_gate"] == 2


def test_ordinary_dedupe_refusal_is_not_eligible_for_the_gate():
    TM, B, A = arr([(61_000, 100.0, 100.2), (121_000, 100.0, 100.2)])
    g = GatedArm("global_pause", cfg(), {}, "global", WeakStates())
    g.signal(opp(0, flip=False, lvl=100.0), 0, TM, B, A)        # first use of the level: eligible, paused
    g.signal(opp(60, flip=False, lvl=100.0), 1, TM, B, A)       # same level again: dedupe refusal BEFORE the gate
    assert g.n["dedupe"] == 1 and g.n["eligible_for_gate"] == 1 and g.n["paused"] == 1


def test_no_pause_arm_creates_the_order_after_the_same_gates():
    TM, B, A = arr([(61_000, 100.0, 100.2)])
    n0 = GatedArm("no_pause", cfg(), {}, "none", WeakStates())
    n0.signal(opp(0, flip=True), 0, TM, B, A)
    assert n0.n["eligible_for_gate"] == 1 and n0.order is not None and n0.n["orders"] == 1


if __name__ == "__main__":
    import traceback
    ok = fail = 0
    for name in sorted(n for n in dir() if n.startswith("test_")):
        try: globals()[name](); ok += 1; print("PASS", name)
        except Exception as e: fail += 1; print("FAIL", name, "->", repr(e)[:300]); traceback.print_exc(limit=2)
    print("passed", ok, "failed", fail); sys.exit(1 if fail else 0)
