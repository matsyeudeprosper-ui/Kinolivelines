"""If a big debt can sit unresolved for a week or more (confirmed by
debt_resolution_time_test.py: $50+ debt took 6 days once, never
resolved within the window a second time, peak debt hit $74), should
the day-cap waiver have a CEILING - i.e. stop being unlimited once debt
gets past some size, even though it has not cleared?

Owner 2026-09-24: "for an account in debt of a big amount like 50 or
more it's unlikely it resolved the same day... maybe trying to force and
wait for debts to resolve before cutting for the day may be unrealistic
... maybe we should come up with a more realistic strategy."

Rule tested:
  A  today: cap T, waived while ANY debt (0.5 < debt), no ceiling
  B  cap T, waived only while 0.5 < debt <= ceiling C - once debt is
     ABOVE C, the day cap re-engages (bounds how much MORE a bad day can
     add) even though the account is still deep in debt. Bullets are
     UNCHANGED - they fire on debt > 0.5 regardless, same as today; only
     the day cap's own waiver gets a ceiling.

Same faithful generator + bullets + streak gate as the other 2026-09-24
tests (bullet_tune_test.py / day_cap_always_binds_test.py).

    python review/debt_ceiling_test.py [spread]
"""
import os
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
LIVE = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, LIVE)
_A = sys.argv[1:]
sys.argv = ["debt_ceiling_test"]

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


def simulate(days, ds, cap, ceiling):
    """ceiling=None -> today (unlimited waiver). ceiling=C -> the cap
    re-binds once debt > C, even mid-debt."""
    run = pk = 0.0
    streak = 0
    curve = []
    for d in ds:
        day_pnl = 0.0
        for x in days[d]:
            dist = x["dist"]
            debt = max(0.0, pk - run)
            waived = debt > 0.5 and (ceiling is None or debt <= ceiling)
            binds = not waived
            if cap is not None and binds and day_pnl >= cap:
                break
            pnl = ((B.RR * dist - SPREAD) if x["win"]
                   else -(dist + SPREAD)) * LOT
            run += pnl
            day_pnl += pnl
            fire = debt > 0.5 and streak < K
            if fire and x["mid"]:
                bp = ((1.3 * dist - SPREAD) if x["win"]
                      else -(dist / 2.0 + SPREAD)) * BLOT * NB
                run += bp
                day_pnl += bp
            streak = 0 if x["win"] else streak + 1
            pk = max(pk, run)
        curve.append(run)
    dd = 0.0
    pk2 = 0.0
    worst_debt = 0.0
    days_over_50 = 0
    for v in curve:
        pk2 = max(pk2, v)
        dd = min(dd, v - pk2)
        worst_debt = max(worst_debt, pk2 - v)
        if pk2 - v > 50:
            days_over_50 += 1
    return dict(net=run, maxdd=dd, worst_debt=worst_debt,
                days_over_50=days_over_50, curve=curve)


def run_for(R, label):
    tr = BT.trades_with_path(R, SPREAD)
    days = group_by_day(tr)
    ds = sorted(days)
    print(f"\n  {label}  {len(ds)} days, {len(tr)} trades, spread "
          f"{SPREAD:.0f}, cap $3 (the standard target)\n")
    print(f"  {'rule':<38}{'net $':>9}{'max DD':>9}"
          f"{'worst debt':>12}{'days debt>50':>14}")
    cap = 3.0
    rows = [("A  today (waived, no ceiling)", None)]
    for C in (20, 30, 40, 50):
        rows.append((f"B  waived up to ${C:.0f} debt, then binds", C))
    base = None
    for lab, ceiling in rows:
        r = simulate(days, ds, cap, ceiling)
        if base is None:
            base = r
        print(f"  {lab:<38}{r['net']:>9.2f}{r['maxdd']:>9.2f}"
              f"{r['worst_debt']:>12.2f}{r['days_over_50']:>14}")
    print()
    return tr


def main():
    u = next(x for x in __import__("json").load(open(os.path.join(
        LIVE, "owl_nest_users.json"), encoding="utf-8")) if x["id"] == "std")
    if not mt5.initialize(path=u["terminal"]):
        raise SystemExit(f"MT5: {mt5.last_error()}")
    sym = "BTCUSD" if mt5.symbol_info("BTCUSD") else "BTCUSDm"
    R = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_M1, 0, 60000)
    mt5.shutdown()

    run_for(R, f"{sym} FULL PERIOD")
    print("  HALVES (each independently)")
    mid = len(R) // 2
    run_for(R[:mid], "FIRST HALF")
    run_for(R[mid:], "SECOND HALF")


if __name__ == "__main__":
    main()
