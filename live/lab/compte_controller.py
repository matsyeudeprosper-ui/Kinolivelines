"""Compte state controller v1 - pinned origin, full precision (ChatGPT brief
2026-10-09, task 3). Analytics only: nothing live reads it yet.

Input: the ordered outcomes (money, full precision) of one reference series.
Output per outcome: the structure state the SAME engine as the price chart
gives, with these differences from the display / eq_state / tracker path:

  * no rounding before the engine (build() rounds to 2 dp; this keeps the
    full value and uses an explicit tolerance for the filter comparisons);
  * the cold-start window order (all, 120, 80, 50, 30, 20 kept candles) is
    used ONCE: when a direction first appears the window's first candle is
    pinned as the origin and every later outcome is processed from that
    origin - no re-slicing to a shorter window to find a direction;
  * missing / invalid input is a status, never a trend.

Deterministic: feeding outcomes one by one gives the same state as feeding
the whole prefix to a fresh controller (checked by check_determinism)."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from owl_chart_feed import engine   # noqa: E402  (the price chart's engine, unchanged)

VERSION = "compte-ctl-1"
WINDOWS = ("all", 120, 80, 50, 30, 20)
TOL = 1e-9


class CompteController:
    def __init__(self):
        self.n = 0                 # outcomes fed
        self.cum = 0.0
        self.kept = []             # [t, o, h, l, c, dir] full precision
        self.ref_h = self.ref_l = None
        self.origin = None         # index into kept, pinned once
        self.origin_window = None
        self.state = self._empty("no_data")
        self.transitions = []      # (n, old_trend, new_trend, new_marks, why)

    @staticmethod
    def _empty(status):
        return {"version": VERSION, "status": status, "trend": 0, "choch": 0,
                "next_bos": None, "invalid": None, "origin": None,
                "origin_window": None, "n": 0, "kept": 0, "marks": 0}

    def feed(self, p, valid=True):
        """One closed outcome. valid=False marks a gap (e.g. a history query
        that failed): the state becomes 'invalid' and stays so until the
        caller re-feeds a complete, valid series into a fresh controller."""
        if not valid:
            self.state = dict(self.state, status="invalid"); return self.state
        self.n += 1
        o = self.cum; self.cum = o + float(p); c = self.cum
        h, l = max(o, c), min(o, c)
        # the silence filter, full precision, explicit tolerance
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
                      "kept": len(self.kept), "marks": len(marks)}
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


if __name__ == "__main__":
    import random
    r = random.Random(7)
    P = [r.choice([-1.0, 0.8]) * r.choice([1.0, 2.0, 3.0]) for _ in range(160)]
    c = run(P)
    print(VERSION, "synthetic: origin", c.origin, "window", c.origin_window, "final", c.state["trend"],
          "transitions", [(t[0], t[1], t[2], t[4]) for t in c.transitions])
    print("determinism violations:", check_determinism(P))
    c2 = CompteController(); c2.feed(1.0); c2.feed(0.5, valid=False)
    print("invalid input ->", c2.state["status"])
