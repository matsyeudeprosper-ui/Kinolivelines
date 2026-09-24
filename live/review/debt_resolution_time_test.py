"""How long does a BIG debt actually take to clear under today's rule
(day cap waived until debt <= 0.5), with the real midpoint bullets
running exactly like live?

Owner 2026-09-24, live and current: Mike is $47.67 in debt right now,
demo is $46.06 - not hypothetical. "For an account in debt of a big
amount like 50 or more it's unlikely it resolved the same day right?
Then maybe trying to force and wait for debts to resolve before cutting
for the day may be unrealistic."

This measures, on the real MAIN-trade history (same generator as
bullet_tune_test.py / day_cap_always_binds_test.py), every episode where
running debt crosses above a threshold, and counts how many CALENDAR
DAYS pass before it drops back to (near) zero under today's live rule.

    python review/debt_resolution_time_test.py [spread]
"""
import os
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
LIVE = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, LIVE)
_A = sys.argv[1:]
sys.argv = ["debt_resolution_time_test"]

import MetaTrader5 as mt5              # noqa: E402
import structure_bos_bot as B          # noqa: E402
B.say = lambda *a, **k: None
import bullet_tune_test as BT          # noqa: E402

SPREAD = float(_A[0]) if _A else 7.0
LOT = 0.02
BLOT = 0.01
NB = 3.0
K = 2


def group_by_day(tr):
    days = {}
    for x in tr:
        days.setdefault(datetime.fromtimestamp(
            x["t"], tz=timezone.utc).strftime("%Y-%m-%d"), []).append(x)
    for d in days:
        days[d].sort(key=lambda z: z["t"])
    return days


def debt_curve(days, ds):
    """Today's live rule: cap waived while debt > 0.5 (so trading is
    unrestricted in debt - no cap tested here, this IS the current
    behaviour), bullets fire on debt, streak-gated. Returns end-of-day
    debt for each day."""
    run = pk = 0.0
    streak = 0
    curve = []
    for d in ds:
        for x in days[d]:
            dist = x["dist"]
            debt = max(0.0, pk - run)
            pnl = ((B.RR * dist - SPREAD) if x["win"]
                   else -(dist + SPREAD)) * LOT
            run += pnl
            fire = debt > 0.5 and streak < K
            if fire and x["mid"]:
                bp = ((1.3 * dist - SPREAD) if x["win"]
                      else -(dist / 2.0 + SPREAD)) * BLOT * NB
                run += bp
            streak = 0 if x["win"] else streak + 1
            pk = max(pk, run)
        curve.append(max(0.0, pk - run))
    return curve


def episodes(curve, threshold):
    """Every time debt crosses UP through `threshold`, how many days
    (from that day) until it is back to <= 0.5. Right-censored episodes
    (never resolves before the data ends) are reported separately."""
    out, unresolved = [], 0
    i = 0
    n = len(curve)
    while i < n:
        if curve[i] >= threshold and (i == 0 or curve[i - 1] < threshold):
            j = i
            while j < n and curve[j] > 0.5:
                j += 1
            if j < n:
                out.append(j - i)
            else:
                unresolved += 1
            i = j
        else:
            i += 1
    return out, unresolved


def run_for(R, label):
    tr = BT.trades_with_path(R, SPREAD)
    days = group_by_day(tr)
    ds = sorted(days)
    curve = debt_curve(days, ds)
    print(f"\n  {label}  {len(ds)} days, {len(tr)} trades, spread {SPREAD:.0f}")
    print(f"    debt now: day {len(curve)} = ${curve[-1]:.2f}  "
          f"(peak over the period: ${max(curve):.2f})")
    print(f"    {'threshold':>10}{'episodes':>10}{'median days':>13}"
          f"{'worst seen':>12}{'still open':>12}")
    for T in (10, 20, 30, 40, 50, 60):
        eps, unresolved = episodes(curve, T)
        if eps:
            eps_sorted = sorted(eps)
            med = eps_sorted[len(eps_sorted) // 2]
            worst = eps_sorted[-1]
        else:
            med = worst = None
        print(f"    ${T:>8}{len(eps) + unresolved:>10}"
              f"{(med if med is not None else '-'):>13}"
              f"{(worst if worst is not None else '-'):>12}"
              f"{unresolved:>12}")
    return curve


def main():
    u = next(x for x in __import__("json").load(open(os.path.join(
        LIVE, "owl_nest_users.json"), encoding="utf-8")) if x["id"] == "std")
    if not mt5.initialize(path=u["terminal"]):
        raise SystemExit(f"MT5: {mt5.last_error()}")
    sym = "BTCUSD" if mt5.symbol_info("BTCUSD") else "BTCUSDm"
    R = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_M1, 0, 60000)
    mt5.shutdown()

    run_for(R, f"{sym} FULL PERIOD")
    print("\n  worst single-day debt seen this period:")
    tr = BT.trades_with_path(R, SPREAD)
    days = group_by_day(tr)
    ds = sorted(days)
    curve = debt_curve(days, ds)
    print(f"    ${max(curve):.2f}  (out of {len(ds)} days)\n")


if __name__ == "__main__":
    main()
