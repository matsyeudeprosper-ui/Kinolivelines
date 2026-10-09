"""Regression cases for study/delayed_entry_ticks.replay (ChatGPT review 13).
    python -m pytest live/lab/test_delayed_entry_ticks.py -q
Synthetic quotes; buy setups unless stated: stop 90, target 108, midpoint 100.3 (review-13 geometry)."""
import sys, numpy as np
sys.path.insert(0, r"C:\Projects\KinoliveLines\study")
from delayed_entry_ticks import replay, clean_quotes

END = 10 ** 12


def arr(rows):
    tm = np.array([r[0] for r in rows], dtype=np.int64); bid = np.array([r[1] for r in rows], dtype=float); ask = np.array([r[2] for r in rows], dtype=float)
    return tm, bid, ask


def test_review13_case1_gap_after_fill_is_counted():
    # eligibility at 61,000 ms; first quote at 61,000; next quote 60 s later through the stop
    TM, B, A = arr([(61_000, 100.0, 100.2), (121_000, 89.0, 89.2)])
    # immediate arm: trigger at 61,000, execution at >= 62,000 -> the 121,000 tick (gap 60 s counted BEFORE evaluation)
    r = replay(TM, B, A, 1, 0, 90.0, 108.0, 100.3, False, END)
    assert r["max_gap_ms"] >= 60_000 and r["resolved"] is False
    # delayed arm: ask 100.2 <= 100.3 triggers at 61,000; execution tick 121,000 has bid 89 <= stop -> rejected (stop printed)
    r = replay(TM, B, A, 1, 0, 90.0, 108.0, 100.3, True, END)
    assert r["kind"] in ("reject_invalid_stop", "reject_after_stop_print") and r["max_gap_ms"] >= 60_000


def test_review13_case2_breached_stop_at_fill_is_rejected_for_both_arms():
    TM, B, A = arr([(61_000, 89.0, 89.2), (62_000, 89.0, 89.2), (63_000, 110.0, 110.2)])
    r = replay(TM, B, A, 1, 0, 90.0, 108.0, 100.3, False, END)
    assert r["kind"] == "reject_invalid_stop", r            # no winner conjured from a breached stop
    r = replay(TM, B, A, 1, 0, 90.0, 108.0, 100.3, True, END)
    assert r["kind"] == "reject_after_stop_print", r


def test_wait_to_first_quote_counts_as_coverage():
    TM, B, A = arr([(200_000, 100.0, 100.2), (201_000, 100.0, 100.2), (202_000, 109.0, 109.2)])
    r = replay(TM, B, A, 1, 0, 90.0, 108.0, 100.3, False, END)
    assert r["kind"] == "fill" and r["win"] and r["max_gap_ms"] >= 139_000 and r["resolved"] is False


def test_horizon_open_at_end_marked_not_resolved_with_later_prices():
    TM, B, A = arr([(61_000, 100.0, 100.2), (62_000, 100.0, 100.2), (63_000, 101.0, 101.2), (70_000, 120.0, 120.2)])
    r = replay(TM, B, A, 1, 0, 90.0, 108.0, 100.3, False, end_ms=65_000)
    assert r["kind"] == "open_at_end" and r["mark_px"] == 101.0 and r["mark_msc"] == 63_000


def test_horizon_pending_at_end_for_delayed():
    TM, B, A = arr([(61_000, 105.0, 105.2), (62_000, 105.0, 105.2), (70_000, 100.0, 100.2)])
    r = replay(TM, B, A, 1, 0, 90.0, 108.0, 100.3, True, end_ms=65_000)
    assert r["kind"] == "pending_at_end"


def test_delayed_fill_uses_execution_quote_not_the_line():
    TM, B, A = arr([(61_000, 101.0, 101.2), (61_500, 100.0, 100.2), (62_600, 99.5, 99.8), (63_000, 109.0, 109.2)])
    r = replay(TM, B, A, 1, 0, 90.0, 108.0, 100.3, True, END)
    assert r["kind"] == "fill" and r["fill_px"] == 99.8 and r["trigger_msc"] == 61_500 and r["win"]


def test_missed_winner_before_trigger():
    TM, B, A = arr([(61_000, 105.0, 105.2), (62_000, 108.5, 108.7), (63_000, 100.0, 100.2)])
    r = replay(TM, B, A, 1, 0, 90.0, 108.0, 100.3, True, END)
    assert r["kind"] == "missed_win"


def test_sell_mirror_and_same_tick_stop_priority():
    # sell: stop 110, target 92, midpoint 99.7; fill then a tick through both -> loss (stop priority)
    TM, B, A = arr([(61_000, 99.0, 99.2), (61_500, 99.8, 100.0), (62_600, 100.0, 100.2), (63_000, 91.0, 111.0)])
    r = replay(TM, B, A, -1, 0, 110.0, 92.0, 99.7, True, END)
    assert r["kind"] == "fill" and r["fill_px"] == 100.0 and r["win"] is False


def test_invalid_quotes_dropped():
    TM, B, A = arr([(1, 0.0, 1.0), (2, 100.0, 99.0), (3, 100.0, 100.2), (4, float("nan"), 1.0)])
    t, b, a, n = clean_quotes(TM, B, A)
    assert n == 3 and len(t) == 1 and t[0] == 3
