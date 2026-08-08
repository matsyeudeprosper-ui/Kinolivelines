"""MEASUREMENT PROBE - BOS (break of structure) retrace-and-continue.

User's claim (2026-08-08): after a renko BOS up (brick close above the last
confirmed swing high), price usually retraces some % of the leg and then
continues up. Mirror for down. This probe MEASURES it - no strategy, no P&L.

Definitions (user-confirmed):
  swings   - renko_structure's walk (brick 50, rev 2), swing = run extreme
             confirmed at reversal
  BOS up   - first up-brick close P above the last confirmed swing high,
             one event per leg (re-arms when a new swing low is confirmed)
  leg      - P minus the last confirmed swing low L (>0 required)
  race     - from the NEXT bar: does high touch P+leg before low touches
             L (=P-leg, symmetric by construction)? Drift-free base = 50%.
  retrace  - deepest dip below P (as % of leg) before the race resolves

Controls, per the traps that faked results before:
  - RANDOM control: same race distances, random start bars (seed 0) - the
    base-rate answer to "BTC just drifts up anyway"
  - ties (bar spans both barriers) scored BOTH ways; trust only stable signs
  - non-overlapping: an event starting before the previous race resolved is
    skipped, so observations are independent (trap #5)
"""
import numpy as np
import MetaTrader5 as mt5
from renko_structure import BRICK, REV


def fetch(tf, want):
    n = want
    while n > 500:
        r = mt5.copy_rates_from_pos("BTCUSDm", tf, 0, n)
        if r is not None and len(r) > 0:
            return r
        n = int(n * 0.9)
    raise RuntimeError("no data")


def extract_events(R, brick=BRICK, rev=REV):
    """one BOS event per leg, both sides"""
    o = R["open"].astype(float)
    c = R["close"].astype(float)
    ao = ac = float(o[0])
    d = 0
    sh, sl_ = [], []
    armed_up = armed_dn = True
    ev = []
    for j in range(len(c)):
        ci = c[j]
        while True:
            u = (ao if d == -1 else ac) + brick * (rev if d == -1 else 1)
            n_ = (ao if d == 1 else ac) - brick * (rev if d == 1 else 1)
            if ci >= u:
                if d == -1:
                    sl_.append(ac)
                    armed_up = True          # new leg up may BOS once
                base = ao if d == -1 else ac
                ao, ac, d = base, base + brick, 1
                if armed_up and sh and sl_ and ac > sh[-1]:
                    leg = ac - sl_[-1]
                    if leg > 0:
                        ev.append((j, +1, ac, leg))
                    armed_up = False
            elif ci <= n_:
                if d == 1:
                    sh.append(ac)
                    armed_dn = True
                base = ao if d == 1 else ac
                ao, ac, d = base, base - brick, -1
                if armed_dn and sh and sl_ and ac < sl_[-1]:
                    leg = sh[-1] - ac
                    if leg > 0:
                        ev.append((j, -1, ac, leg))
                    armed_dn = False
            else:
                break
    return ev


def race(h, l, j, side, P, leg):
    """returns (outcome, resolve_bar, depth_frac)
    outcome: 'win' 'loss' 'tie' 'none'; depth = worst adverse dip / leg
    before resolution (win side) or before failing.

    AUDIT FIX (v2): barriers are centered on P. In v1, P was the BOS brick
    close for events but price at race start had already run past it, so the
    up barrier was mechanically nearer and BOS read 70% vs random 50% - a
    head start, not an edge. Callers now pass P = the actual price at race
    start (next bar's open) for BOTH events and controls."""
    up_t = P + leg if side > 0 else P - leg
    dn_t = P - leg if side > 0 else P + leg
    N = len(h)
    depth = 0.0
    for k in range(j + 1, N):
        adverse = (P - l[k]) if side > 0 else (h[k] - P)
        if adverse / leg > depth:
            depth = adverse / leg
        hit_w = h[k] >= up_t if side > 0 else l[k] <= up_t
        hit_l = l[k] <= dn_t if side > 0 else h[k] >= dn_t
        if hit_w and hit_l:
            return "tie", k, min(depth, 1.0)
        if hit_w:
            return "win", k, depth
        if hit_l:
            return "loss", k, 1.0
    return "none", N - 1, depth


def nonoverlap(events, h, l, o):
    """entry price = next bar's open, the first price actually obtainable"""
    out = []
    free = -1
    for (j, side, P, leg) in events:
        if j <= free or j + 1 >= len(o):
            continue
        entry = float(o[j + 1])
        oc, k, dep = race(h, l, j, side, entry, leg)
        out.append((j, side, entry, leg, oc, dep))
        free = k
    return out


def summarize(rows, label):
    n = len(rows)
    w = sum(1 for r in rows if r[4] == "win")
    lo = sum(1 for r in rows if r[4] == "loss")
    t = sum(1 for r in rows if r[4] == "tie")
    resolved = w + lo + t
    if resolved == 0:
        print(f"  {label:<26} n=0")
        return
    p_tw = (w + t) / resolved
    p_tl = w / resolved
    se = 2 * np.sqrt(0.25 / resolved)
    deps = [r[5] for r in rows if r[4] in ("win", "tie")]
    q = (np.percentile(deps, [25, 50, 75]) if deps else [np.nan] * 3)
    any_r = np.mean([d >= 0.10 for d in deps]) if deps else np.nan
    half = np.mean([d >= 0.50 for d in deps]) if deps else np.nan
    print(f"  {label:<26} n={resolved:<5d} win {p_tl:5.1%}..{p_tw:5.1%} (tie->loss..tie->win, ties {t})  2SE {se:5.1%}")
    if deps:
        print(f"  {'':<26} retrace before continuing: median {q[1]:4.0%} of leg "
              f"(q25 {q[0]:4.0%}, q75 {q[2]:4.0%}); >=10%: {any_r:4.0%}, >=50%: {half:4.0%}")


mt5.initialize(path=r"C:\Program Files\MetaTrader 5\terminal64.exe")
DATA = (("M15", fetch(mt5.TIMEFRAME_M15, 50000)),
        ("H1", fetch(mt5.TIMEFRAME_H1, 46000)))
mt5.shutdown()

rng = np.random.default_rng(0)

for name, R in DATA:
    h = R["high"].astype(float)
    l = R["low"].astype(float)
    c = R["close"].astype(float)
    months = (R["time"][-1] - R["time"][0]) / (86400 * 30.44)
    ev = extract_events(R)
    ups = [e for e in ev if e[1] > 0]
    dns = [e for e in ev if e[1] < 0]
    print("=" * 88)
    print(f"{name}: {len(R)} bars, {months:.0f} months - BOS events: {len(ups)} up, {len(dns)} down")
    o_ = R["open"].astype(float)
    rows_u = nonoverlap(ups, h, l, o_)
    rows_d = nonoverlap(dns, h, l, o_)
    summarize(rows_u, "BOS up  -> continue up")
    summarize(rows_d, "BOS down-> continue dn")

    # random control: same leg distances, random start bars, both directions
    legs = [e[3] for e in ev] or [BRICK * 3]
    ctrl = []
    for side in (+1, -1):
        starts = sorted(rng.integers(1, len(R) - 2, size=len(ev)))
        for s in starts:
            ctrl.append((int(s), side, c[s], float(rng.choice(legs))))
    rows_cu = nonoverlap([e for e in ctrl if e[1] > 0], h, l, o_)
    rows_cd = nonoverlap([e for e in ctrl if e[1] < 0], h, l, o_)
    summarize(rows_cu, "RANDOM  -> up (control)")
    summarize(rows_cd, "RANDOM  -> down (control)")
    print()
