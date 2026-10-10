"""Compte state controller - pinned origin, full precision (ChatGPT brief
2026-10-09, task 3; review 3 fixes). Analytics only: nothing live reads it.

Input: the ordered outcomes (money, full precision) of one reference series.
Output per outcome: the structure state the SAME engine as the price chart
gives, with these differences from the display / eq_state / tracker path:

  * no rounding before the engine (build() rounds to 2 dp; this keeps the
    full value and uses an explicit tolerance for the filter comparisons);
  * the cold-start window order (all, 120, 80, 50, 30, 20 kept candles) is
    used ONCE: when a direction first appears the window's first candle is
    pinned as the origin and every later outcome is processed from that
    origin - no re-slicing to a shorter window to find a direction;
  * bad input (missing, non-numeric, NaN/inf, a flagged gap) LATCHES the
    controller as invalid BEFORE any mutation: n, cum and kept keep the last
    valid financial state, the reason and the last valid event are recorded,
    and only reset() + a complete validated replay clears it.

Tolerance: the silence filter compares money with TOL = 1e-9 dollars; the
engine's own comparisons (owl_chart_feed.engine) are strict floats. So the
state is invariant to a positive rescale of the whole series only up to that
tolerance - documented, not claimed exact for every scale.

Deterministic: feeding outcomes one by one gives the same state as feeding
the whole prefix to a fresh controller (check_determinism)."""
import math, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from owl_chart_feed import engine   # noqa: E402  (the price chart's engine, unchanged)

VERSION = "compte-ctl-2"
WINDOWS = ("all", 120, 80, 50, 30, 20)
TOL = 1e-9


class CompteController:
    def __init__(self):
        self.reset()

    def reset(self):
        """Explicit recovery: the caller must replay a complete, validated
        sequence after this. Nothing else clears an invalid latch."""
        self.n = 0                 # valid outcomes fed
        self.cum = 0.0
        self.kept = []             # [n, o, h, l, c, dir] full precision
        self.ref_h = self.ref_l = None
        self.origin = None         # index into kept, pinned once
        self.origin_window = None
        self.invalid = None        # {"reason", "at_n", "last_valid_event"}
        self.last_event = None
        self.state = self._empty("no_data")
        self.transitions = []      # (n, old_trend, new_trend, new_marks, why)

    @staticmethod
    def _empty(status):
        return {"version": VERSION, "status": status, "trend": 0, "choch": 0,
                "next_bos": None, "invalid": None, "origin": None,
                "origin_window": None, "n": 0, "kept": 0, "marks": 0, "reason": None}

    def _latch(self, reason):
        if self.invalid is None:
            self.invalid = {"reason": reason, "at_n": self.n, "last_valid_event": self.last_event}
        self.state = dict(self.state, status="invalid", reason=self.invalid["reason"])
        return self.state

    def feed(self, p, valid=True, event=None):
        """One closed outcome. Returns the state. Once invalid, every call
        returns the latched invalid state and mutates nothing."""
        if self.invalid is not None:
            return self.state
        if not valid:
            return self._latch("flagged_gap")
        if p is None or isinstance(p, bool):
            return self._latch("missing_or_non_numeric")
        try:
            v = float(p)
        except (TypeError, ValueError):
            return self._latch("missing_or_non_numeric")
        if not math.isfinite(v):
            return self._latch("non_finite_input")
        c = self.cum + v
        if not math.isfinite(c):
            return self._latch("non_finite_cumulative")
        # --- validated: mutate ---
        self.n += 1
        self.last_event = event if event is not None else self.n
        o = self.cum; self.cum = c
        h, l = max(o, c), min(o, c)
        if self.ref_h is None or c > self.ref_h + TOL or c < self.ref_l - TOL:
            self.kept.append([self.n, o, h, l, c, 1 if c >= o else -1])
            self.ref_h, self.ref_l = h, l
        return self._compute()

    def _run(self, cands):
        bk = []
        out = engine(cands, brk_out=bk)
        return out, bk

    def _compute(self):
        old = self.state
        if len(self.kept) < 3:
            self.state = dict(self._empty("warming"), n=self.n, kept=len(self.kept)); return self.state
        if self.origin is None:
            for w in WINDOWS:
                start = 0 if w == "all" else max(0, len(self.kept) - w)
                out, bk = self._run(self.kept[start:])
                if out[2]:
                    self.origin, self.origin_window = start, w
                    break
            if self.origin is None:
                self.state = dict(self._empty("no_direction"), n=self.n, kept=len(self.kept)); return self.state
        out, bk = self._run(self.kept[self.origin:])
        (dots, marks, trend, choch, nxt, inv, *_rest) = out
        self.state = {"version": VERSION, "status": "ok", "trend": trend, "choch": choch,
                      "next_bos": nxt, "invalid": inv, "origin": self.origin,
                      "origin_window": self.origin_window, "n": self.n,
                      "kept": len(self.kept), "marks": len(marks), "reason": None}
        if old.get("trend") != trend:
            new_marks = len(marks) - (old.get("marks") or 0)
            self.transitions.append((self.n, old.get("trend"), trend, new_marks,
                                     "bootstrap" if old.get("status") != "ok" else ("mark" if new_marks > 0 else "no_mark")))
        return self.state


def run(outcomes):
    c = CompteController()
    for p in outcomes:
        c.feed(p)
    return c


def check_determinism(outcomes):
    """Incremental == from-scratch at every prefix (restart safety)."""
    inc = CompteController(); bad = 0
    for i, p in enumerate(outcomes):
        a = dict(inc.feed(p)); b = dict(run(outcomes[:i + 1]).state)
        if a != b:
            bad += 1
    return bad
