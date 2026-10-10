"""Regression cases for study/tick_engine.Arm (ChatGPT review 14): MTM at the closing
quote, add geometry against the parent's barriers, the pending setup's stop-breach rule.
    python live/lab/test_tick_engine.py        (plain runner; pytest is not installed on the VPS)
Synthetic quotes; bar time 0 -> eligibility at 61,000 ms; buy setups: stop 90, target from rr."""
import sys, numpy as np
sys.path.insert(0, r"C:\Projects\KinoliveLines\study\frozen_entry_study")
import tick_engine as E
H = E.H


def cfg(**over):
    base = {"lot": 0.02, "balance": 0.0, "scale_lot": 0, "scale_daily": 0, "scale_ref": 200.0, "day_cap": 0.0, "rr": 0.8, "bullets": 3, "k_streak": 2,
            "kill_net": 0.0, "storm": 1.85, "movement": 1, "nerv_gate": False, "n_cont": 1, "debt_gate": 1, "min_balance": 0.0, "risk_fit": 0.0,
            "hard_cap_pct": 0.0, "jar": False, "drag": 0.0, "limits_live": 1}
    base.update(over); return H.cfg_strict(base)


def arr(rows):
    return (np.array([r[0] for r in rows], dtype=np.int64), np.array([r[1] for r in rows], dtype=float), np.array([r[2] for r in rows], dtype=float))


def opp(d=1, slp=90.0, t=0):
    return {"t": t, "i": 0, "d": d, "slp": slp, "cl": 100.0, "flip": True, "awake": True, "nv": 1.0, "mv2": None, "i_fire": False, "lvl": 100.0, "weekday": 0, "hour": 0, "minute": 0}


def drive(arm, TM, B, A, signal_at_ms=61_000, o=None):
    prev = int(TM[0])
    for k in range(len(TM)):
        t = int(TM[k]); gap = t - prev; prev = t
        arm.roll(t)
        if o is not None and t >= signal_at_ms:
            arm.signal(o, k, TM, B, A); o = None
        arm.tick(k, TM, B, A, gap)
    return arm


def test_mtm_updates_on_the_closing_quote():
    # immediate buy fills at 62,000 (ask 100.2), terminal bid 89 stops it: mtm_dd must be >= the loss at that quote
    TM, B, A = arr([(61_000, 100.0, 100.2), (62_000, 100.0, 100.2), (63_000, 89.0, 89.2)])
    arm = drive(E.Arm("baseline", cfg(), "base", {}), TM, B, A, o=opp())
    assert arm.n["fills"] == 1 and len(arm.trades) == 1 and arm.trades[0]["win"] is False
    assert arm.mtm_dd >= 0.02 * (100.2 - 89.0) - 1e-9, arm.mtm_dd


def test_due_add_rejected_when_parent_is_stopped_on_that_quote():
    # delayed arm in debt: force a pending setup by starting with pk > run (debt 5)
    arm = E.Arm("delayed", cfg(), "delayed", {}); arm.pk = 5.0; arm.run = 0.0
    TM, B, A = arr([(61_000, 100.0, 100.2),      # signal: e0 = 100.2, stop 90, dist 10.2, mid = 95.1, tp = 108.36
                    (70_000, 95.0, 95.1),        # ask <= mid -> trigger (stop 90 < bid 95: submitted); adds reserved at the fill below
                    (71_000, 95.0, 95.1),        # fill at ask 95.1; bullets reserved here (debt 5, no jar -> 3 adds), due at 72,000
                    (72_000, 89.0, 89.2)])       # bullets due: parent stop 90 >= bid 89 -> adds REJECTED; parent closes on this tick
    drive(arm, TM, B, A, o=opp())
    assert arm.n["fills"] == 1 and arm.n["adds_triggered"] == 1
    assert arm.n.get("adds_rejected_geom", 0) == 3 and arm.n["adds_filled"] == 0, arm.n
    assert len(arm.trades) == 1 and arm.trades[0]["adds"] == 0


def test_pending_cancelled_when_stop_breached_on_the_trigger_quote():
    # review-14 sequence: bid 89 / ask 89.2 (through the stop AND through the midpoint) then a rebound to 94
    arm = E.Arm("delayed", cfg(), "delayed", {}); arm.pk = 5.0
    TM, B, A = arr([(61_000, 100.0, 100.2), (70_000, 89.0, 89.2), (71_000, 94.0, 94.2), (72_000, 94.0, 94.2)])
    drive(arm, TM, B, A, o=opp())
    assert arm.n.get("cancel_stop_before_submission", 0) == 1 and arm.n["orders"] == 0 and arm.n["fills"] == 0, arm.n


def test_pending_breach_during_latency_is_a_fill_rejection():
    # trigger quote fine (bid 95 > stop 90), the execution quote 1 s later is through the stop -> REJECT_GEOM at the fill
    arm = E.Arm("delayed", cfg(), "delayed", {}); arm.pk = 5.0
    TM, B, A = arr([(61_000, 100.0, 100.2), (70_000, 95.0, 95.1), (71_000, 89.0, 89.2), (72_000, 94.0, 94.2)])
    drive(arm, TM, B, A, o=opp())
    assert arm.n["orders"] == 1 and arm.n["reject_geom"] == 1 and arm.n["fills"] == 0, arm.n


def test_pending_cancelled_when_the_breaching_quote_is_also_the_trigger():
    # (review 15: renamed - this is the cancellation case) bid 89 / ask 89.2 breaches the stop AND crosses the midpoint
    # on the same quote -> the trigger quote fails the geometry check -> cancelled, no order, no later fill at 94
    arm = E.Arm("delayed", cfg(), "delayed", {}); arm.pk = 5.0
    TM, B, A = arr([(61_000, 100.0, 100.2), (65_000, 89.0, 89.2), (66_000, 97.0, 97.2), (70_000, 94.0, 94.2), (71_000, 94.0, 94.2), (72_000, 109.0, 109.2)])
    drive(arm, TM, B, A, o=opp())
    assert arm.n.get("cancel_stop_before_submission", 0) == 1 and arm.n["fills"] == 0


def test_wide_spread_earlier_print_then_legitimate_trigger_is_counted():
    # review 15: a WIDE spread lets the bid breach the stop (89) while the ask (96) stays above the midpoint (95.1),
    # so nothing triggers; the quote rebounds above the stop, then a normal quote crosses the midpoint -> the
    # order is legitimately sent (stop below the bid at the trigger), filled, and counted apart
    arm = E.Arm("delayed", cfg(), "delayed", {}); arm.pk = 5.0
    TM, B, A = arr([(61_000, 100.0, 100.2), (65_000, 89.0, 96.0), (66_000, 97.0, 97.2), (70_000, 95.0, 95.1), (71_000, 95.0, 95.1), (72_000, 109.0, 109.2)])
    drive(arm, TM, B, A, o=opp())
    assert arm.n.get("cancel_stop_before_submission", 0) == 0
    assert arm.n.get("trigger_after_earlier_stop_print", 0) == 1 and arm.n["orders"] == 1 and arm.n["fills"] == 1, arm.n
    assert len(arm.trades) == 1 and arm.trades[0]["win"] is True


if __name__ == "__main__":
    import traceback
    ok = fail = 0
    for name in sorted(n for n in dir() if n.startswith("test_")):
        try: globals()[name](); ok += 1; print("PASS", name)
        except Exception as e: fail += 1; print("FAIL", name, "->", repr(e)[:300]); traceback.print_exc(limit=2)
    print("passed", ok, "failed", fail); sys.exit(1 if fail else 0)
