"""The REVIEW-12 replay (commit 654222c), kept verbatim for the before/after comparison asked in review 13.
Globals TM, BID, ASK, GAP_NEXT, LATENCY_MS must be set by the caller (v1 used the raw concatenated days, no END bound)."""
import bisect
import numpy as np
LATENCY_MS = 1000
TM = BID = ASK = GAP_NEXT = None
def replay(d, t_signal, e0, sl, tp, mid, delayed):
    """returns dict(kind, fill_msc, fill_px, exit_msc, exit_px, win, gap) - kind in
    fill / missed_win / stop_first / no_fill_end / unresolved_gap"""
    start = int((t_signal + 60) * 1000 + LATENCY_MS)
    i = bisect.bisect_left(TM, start)
    n = len(TM)
    # phase 1: wait for the fill (delayed: the midpoint; baseline: the first tick)
    j = i
    fill = None
    mg = 0          # the largest tick gap (ms) met on the path to resolution
    while j < n:
        b, a = BID[j], ASK[j]
        if delayed:
            if d == 1:
                if b >= tp: return {"kind": "missed_win", "t": int(TM[j]), "max_gap_ms": mg}
                if b <= sl: return {"kind": "stop_first", "t": int(TM[j]), "max_gap_ms": mg}
                if a <= mid: fill = (j, a); break
            else:
                if a <= tp: return {"kind": "missed_win", "t": int(TM[j]), "max_gap_ms": mg}
                if a >= sl: return {"kind": "stop_first", "t": int(TM[j]), "max_gap_ms": mg}
                if b >= mid: fill = (j, b); break
        else:
            fill = (j, a if d == 1 else b); break
        mg = max(mg, int(GAP_NEXT[j]))
        j += 1
    if fill is None:
        return {"kind": "no_fill_end"}
    fj, fpx = fill
    # phase 2: first barrier after the fill, exact tick order, executable side
    k = fj + 1
    while k < n:
        b, a = BID[k], ASK[k]
        if d == 1:
            if b <= sl: return {"kind": "fill", "fill_msc": int(TM[fj]), "fill_px": float(fpx), "exit_msc": int(TM[k]), "exit_px": float(b), "win": False, "max_gap_ms": mg}
            if b >= tp: return {"kind": "fill", "fill_msc": int(TM[fj]), "fill_px": float(fpx), "exit_msc": int(TM[k]), "exit_px": float(b), "win": True, "max_gap_ms": mg}
        else:
            if a >= sl: return {"kind": "fill", "fill_msc": int(TM[fj]), "fill_px": float(fpx), "exit_msc": int(TM[k]), "exit_px": float(a), "win": False, "max_gap_ms": mg}
            if a <= tp: return {"kind": "fill", "fill_msc": int(TM[fj]), "fill_px": float(fpx), "exit_msc": int(TM[k]), "exit_px": float(a), "win": True, "max_gap_ms": mg}
        mg = max(mg, int(GAP_NEXT[k]))
        k += 1
    return {"kind": "unresolved_end", "fill_msc": int(TM[fj]), "fill_px": float(fpx), "max_gap_ms": mg}


