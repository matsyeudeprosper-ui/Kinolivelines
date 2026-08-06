"""Start a NEW cycle while an existing basket is still open.

Right now rule 7 says no new first trade until both the first trade and its
hedge are closed. That is what stops the bot trading while a basket is working.
This tests removing it: allow up to N cycles running side by side.

Each cycle is fully independent - its own first trade, its own hedge, its own
drawdown reference, its own exit. They do not net against each other. That is
the point of the test: more of the signal gets traded, at the cost of holding
more risk at once.

This is also the exact difference that made two earlier scripts disagree by $220
on the same 27 months. One waited for the basket to empty and one did not, and
I had not noticed. Testing it properly instead.

MAX POSITIONS = 2 x concurrent cycles, so cycles=4 can hold 8 positions.

Invariants on every run:
  - open positions never exceed 2 x max_cycles
  - no single cycle can gain more than about $60 (two legs at 0.01 lots)
"""
import numpy as np
import MetaTrader5 as mt5
from datetime import datetime

SPREAD, BRICK, REV = 10.0, 50.0, 2
TP, TRIG, PT, START = 250.0, 150.0, 0.01, 1000.0
REWARD, HSL = 1.5, 1.0

mt5.initialize(path=r"C:\Program Files\MetaTrader 5\terminal64.exe")
DATA = {"M1": mt5.copy_rates_from_pos("BTCUSDm", mt5.TIMEFRAME_M1, 0, 80000),
        "M15": mt5.copy_rates_from_pos("BTCUSDm", mt5.TIMEFRAME_M15, 0, 80000)}
mt5.shutdown()


class Cycle:
    __slots__ = ("f_px", "f_long", "f_open", "h_px", "h_long", "h_tp", "h_sl",
                 "h_open", "hedged", "rec", "banked")

    def __init__(self, px, long_):
        self.f_px, self.f_long, self.f_open = px, long_, True
        self.h_px = self.h_long = self.h_tp = self.h_sl = None
        self.h_open = False; self.hedged = False; self.rec = False
        self.banked = 0.0

    def floating(self, px):
        t = 0.0
        if self.f_open:
            t += ((px - self.f_px) if self.f_long else (self.f_px - px - SPREAD)) * PT
        if self.h_open:
            t += ((px - self.h_px) if self.h_long else (self.h_px - px - SPREAD)) * PT
        return t

    def n_open(self):
        return int(self.f_open) + int(self.h_open)


def run(R, a, max_cycles):
    o, h, l, c = (R[k][a:].astype(float) for k in ("open", "high", "low", "close"))
    N = len(c)
    ao = ac = float(o[0]); d = 0; pd_ = 0
    bal = START
    live = []                       # open cycles
    pending = []                    # (kind, cycle_or_None, long, tp, sl)
    peak = START; mdd = 0.0; lo = START; eq = START
    opened = 0; hedges = 0; won = 0; stop = 0
    results = []; max_open = 0
    for j in range(N):
        # ---- fills --------------------------------------------------------
        for kind, cy, L, ptp, psl in pending:
            px = o[j] + SPREAD if L else o[j]
            if kind == "first":
                live.append(Cycle(px, L)); opened += 1
            else:
                cy.h_px, cy.h_long, cy.h_tp, cy.h_sl = px, L, ptp, psl
                cy.h_open = True; cy.hedged = True
                opened += 1; hedges += 1
        pending = []
        tot_open = sum(x.n_open() for x in live)
        max_open = max(max_open, tot_open)
        if tot_open > 2 * max_cycles:
            raise AssertionError(f"{tot_open} positions with max_cycles={max_cycles}")

        # ---- bricks -------------------------------------------------------
        ci = c[j]
        while True:
            u = (ao if d == -1 else ac) + BRICK * (REV if d == -1 else 1)
            n_ = (ao if d == 1 else ac) - BRICK * (REV if d == 1 else 1)
            if ci >= u:
                base = ao if d == -1 else ac; ao, ac, d = base, base + BRICK, 1
            elif ci <= n_:
                base = ao if d == 1 else ac; ao, ac, d = base, base - BRICK, -1
            else:
                break
            if pd_ and d != pd_ and j + 1 < N and not pending:
                want = (d == 1)
                # a hedge for the OLDEST cycle that wants one takes priority
                target = None
                for cy in live:
                    if cy.rec and not cy.hedged and cy.f_open and want != cy.f_long:
                        target = cy; break
                if target is not None:
                    dn = max(((target.f_px - c[j]) if target.f_long
                              else (c[j] - target.f_px)), BRICK)
                    pending.append(("hedge", target, want, REWARD * dn, HSL * dn))
                elif len(live) < max_cycles:
                    pending.append(("first", None, want, TP, 0.0))
            pd_ = d

        # ---- manage each cycle --------------------------------------------
        done = []
        for cy in live:
            if cy.f_open:
                if (h[j] >= cy.f_px + TP) if cy.f_long else (l[j] <= cy.f_px - TP - SPREAD):
                    bal += TP * PT; cy.banked += TP * PT; cy.f_open = False
            if cy.h_open:
                hitT = (h[j] >= cy.h_px + cy.h_tp) if cy.h_long else (l[j] <= cy.h_px - cy.h_tp - SPREAD)
                hitS = (l[j] <= cy.h_px - cy.h_sl) if cy.h_long else (h[j] >= cy.h_px + cy.h_sl + SPREAD)
                if hitS:
                    bal -= cy.h_sl * PT; cy.banked -= cy.h_sl * PT
                    cy.h_open = False; stop += 1
                    if cy.f_open:                       # rule 5, close the pair
                        p = ((c[j] - cy.f_px) if cy.f_long else (cy.f_px - c[j] - SPREAD)) * PT
                        bal += p; cy.banked += p; cy.f_open = False
                elif hitT:
                    bal += cy.h_tp * PT; cy.banked += cy.h_tp * PT
                    cy.h_open = False; won += 1
                    if cy.f_open:
                        p = ((c[j] - cy.f_px) if cy.f_long else (cy.f_px - c[j] - SPREAD)) * PT
                        bal += p; cy.banked += p; cy.f_open = False
            if cy.f_open and not cy.rec:
                if (l[j] <= cy.f_px - TRIG) if cy.f_long else (h[j] >= cy.f_px + TRIG + SPREAD):
                    cy.rec = True
            # back to zero with both open
            if cy.rec and cy.n_open() and (cy.banked + cy.floating(c[j])) >= 0:
                p = cy.floating(c[j]); bal += p; cy.banked += p
                cy.f_open = cy.h_open = False
            if cy.n_open() == 0:
                done.append(cy)
        for cy in done:
            results.append(cy.banked); live.remove(cy)

        eq = bal + sum(x.floating(c[j]) for x in live)
        peak = max(peak, eq); mdd = max(mdd, peak - eq); lo = min(lo, eq)
        if eq <= 0:
            return dict(eq=0.0, dead=True, mdd=mdd, lo=0.0, opened=opened,
                        hedges=hedges, won=won, stop=stop, max_open=max_open,
                        results=results)
    return dict(eq=eq, dead=False, mdd=mdd, lo=lo, opened=opened, hedges=hedges,
                won=won, stop=stop, max_open=max_open, results=results)


ANCH = [0, 3, 9, 21, 45, 90]
for tf in ("M1", "M15"):
    R = DATA[tf]
    mon = (R["time"][-1] - R["time"][0]) / 86400 / 30.4
    print("=" * 82)
    print(f"{tf}   {mon:.1f} months   how many cycles may run at once")
    print("=" * 82)
    print(f"{'cycles':<9}{'mean final':>12}{'lowest':>10}{'worst dd':>10}"
          f"{'trades/mo':>11}{'max open':>10}{'hit%':>8}{'invariants':>12}")
    for mc in (1, 2, 3, 5, 10):
        out = []
        bad = False
        for a in ANCH:
            z = run(R, a, mc)
            out.append(z)
            if z["results"] and max(z["results"]) > 60.0:
                bad = True
        eqs = np.array([x["eq"] for x in out])
        th = sum(x["hedges"] for x in out); w = sum(x["won"] for x in out)
        print(f"{mc:<9}{eqs.mean():>12.2f}{np.mean([x['lo'] for x in out]):>10.2f}"
              f"{np.mean([x['mdd'] for x in out]):>10.2f}"
              f"{np.mean([x['opened'] for x in out])/mon:>11.0f}"
              f"{max(x['max_open'] for x in out):>10}"
              f"{100*w/max(1,th):>7.1f}%{('FAIL' if bad else 'pass'):>12}")
    print()
