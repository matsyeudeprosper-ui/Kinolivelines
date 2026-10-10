"""The pullback gate's decision table (owner 2026-10-10, trend following).
    python live/lab/test_pb_gate.py
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from pb_gate import pb_gate


def run():
    T = pb_gate
    # trend mode: with the structure AND beyond the last BOS
    assert T("trend", 1, 100.0, 1, last_bos=90.0) == (True, "beyond_last_bos")
    assert T("trend", -1, 80.0, -1, last_bos=90.0) == (True, "beyond_last_bos")
    # the wrong side of the last BOS = paused (buy below it / sell above it), the level itself included
    assert T("trend", 1, 85.0, 1, last_bos=90.0) == (False, "paused_wrong_side")
    assert T("trend", 1, 90.0, 1, last_bos=90.0) == (False, "paused_wrong_side")
    assert T("trend", -1, 95.0, -1, last_bos=90.0) == (False, "paused_wrong_side")
    # against the structure: refused, and the CHoCH exception no longer opens it
    assert T("trend", -1, 100.0, 1, choch=-1, choch_lvl=120.0, last_bos=90.0) == (False, "against_structure")
    # price reclaims the level -> continuation resumes
    assert T("trend", 1, 90.5, 1, last_bos=90.0) == (True, "beyond_last_bos")
    # no pullback structure / no last BOS known -> PAUSE (no permissive fallback); older modes unchanged
    assert T("trend", 1, 100.0, 0) == (False, "no_structure")
    assert T("trend", 1, 100.0, 1, last_bos=None) == (False, "no_last_bos")
    assert T("choch", 1, 100.0, 0) == (True, "no_structure")
    assert T("strict", 1, 100.0, 0) == (True, "no_structure")
    # the morning rule, kept for the replay
    assert T("choch", -1, 100.0, 1, choch=-1, choch_lvl=110.0) == (True, "choch_exception")
    assert T("choch", -1, 115.0, 1, choch=-1, choch_lvl=110.0) == (False, "against_structure")
    assert T("choch", 1, 100.0, 1) == (True, "with_structure")
    assert T("strict", -1, 100.0, 1, choch=-1, choch_lvl=110.0) == (False, "against_structure")
    assert T("off", -1, 100.0, 1) == (True, "off")
    print("test_pb_gate: 16 ok")


if __name__ == "__main__":
    run()
