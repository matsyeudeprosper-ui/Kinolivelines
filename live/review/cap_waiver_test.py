"""Should the daily profit cap still be waived while the account owes money?

Owner 2026-09-23. The cap today is a PROFIT target that switches OFF while
the account is in debt - so the brake releases exactly when an account is
losing. Valere is healthy and its cap binds (debt 0); Kino and the demo are
sick and theirs is waived. That is the one structural difference between
them, so it gets measured.

  A  no cap at all                      (Kino / package "special")
  B  cap T, WAIVED while in debt        (Valere / demo / Infinity today)
  C  cap T, ALWAYS binds                (the proposal)

Debt is the live high-water-mark definition: debt = peak_banked - banked.

Post-filtering the trade list is FAITHFUL here, unlike the exit tests: a
day cap stops the account for the rest of the day, so no freed position
slot can let a different trade in. Trades before the stop are unchanged.

    python review/cap_waiver_test.py [spread]
"""
import os
import statistics as st
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
_A = sys.argv[1:]
sys.argv = ["cap_waiver_test"]

import selector_test as S              # noqa: E402

SPREAD = float(_A[0]) if _A else 7.0


def simulate(days, ds, cap, waive):
    """Walk the period day by day, carrying banked/peak/debt across days."""
    banked = peak = 0.0
    taken = 0
    curve = []
    for d in ds:
        day = 0.0
        for x in days[d]:
            if cap is not None:
                debt = max(0.0, peak - banked)
                binds = (debt <= 0.5) if waive else True
                if binds and day >= cap:
                    break              # stopped for the day
            banked += x["usd"]
            day += x["usd"]
            peak = max(peak, banked)
            taken += 1
        curve.append(banked)
    dd = 0.0
    pk = 0.0
    for v in curve:
        pk = max(pk, v)
        dd = min(dd, v - pk)
    in_debt = sum(1 for v, p in zip(curve, _peaks(curve)) if p - v > 0.5)
    return dict(net=banked, trades=taken, maxdd=dd,
                debt_days=in_debt, curve=curve,
                green=sum(1 for i, v in enumerate(curve)
                          if v > (curve[i - 1] if i else 0.0)))


def _peaks(c):
    out, p = [], 0.0
    for v in c:
        p = max(p, v)
        out.append(p)
    return out


def main():
    sym, R = S.bars()
    tr = S.replay(R, SPREAD)
    days = {}
    for x in tr:
        days.setdefault(datetime.fromtimestamp(
            x["t"], tz=timezone.utc).strftime("%Y-%m-%d"), []).append(x)
    for d in days:
        days[d].sort(key=lambda z: z["t"])
    ds = sorted(days)
    print(f"\n  {sym}  {len(ds)} days, {len(tr)} trades, spread {SPREAD:.0f}, "
          f"lot 0.02\n")
    print(f"  {'rule':<34}{'trades':>7}{'net $':>9}{'max DD':>9}"
          f"{'days in debt':>14}")
    rows = [("A  no cap (Kino today)", None, False)]
    for T in (3, 5, 10):
        rows.append((f"B  cap ${T}, waived in debt (today)", T, True))
        rows.append((f"C  cap ${T}, ALWAYS binds", T, False))
    best = None
    for lab, cap, waive in rows:
        r = simulate(days, ds, cap, waive)
        mark = ""
        if cap is not None and not waive:
            mark = ""
        print(f"  {lab:<34}{r['trades']:>7}{r['net']:>9.2f}"
              f"{r['maxdd']:>9.2f}{r['debt_days']:>10}/{len(ds):<3}{mark}")
        if best is None or r["net"] > best[1]:
            best = (lab, r["net"])
    print(f"\n  best by net: {best[0]}  (${best[1]:+.2f})")
    print("\n  max DD is on the account equity curve, in dollars at 0.02 lot.")
    print("  'days in debt' = days ending below the running peak, which is")
    print("  what keeps the cap waived under rule B.\n")


if __name__ == "__main__":
    main()
