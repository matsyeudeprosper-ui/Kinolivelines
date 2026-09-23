"""Daily profit protection: target, give-back stop, or both?

Owner 2026-09-23: "the worst is seeing high profit balance during the day
and losing it all by the end of the day... the trailing I need is at the
BALANCE level not at each trade level. Protect profit and grow it as days
move. The most realistic profit achievable easily in the day, and stop
immediately."

Step 1 of the plan: describe the days before designing a rule for them.

  - what a day actually produces (so "realistic target" is a measurement,
    not a wish)
  - how far the day's running total climbs ABOVE where it finishes: the
    give-back, which is the thing the owner wants to stop losing
  - then a grid: stop the day at +T realised, and/or stop when the day
    falls G back from its own peak

Days are UTC, matching day_roll() in the bot. P&L is realised-on-close,
the same basis day_pnl uses, at the live 0.02 lot.

    python review/daily_shield_test.py [spread]
"""
import os
import statistics as st
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
_A = sys.argv[1:]
sys.argv = ["daily_shield_test"]

import selector_test as S              # noqa: E402

SPREAD = float(_A[0]) if _A else 7.0


def day_of(ts):
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")


def run_day(trades, target, giveback):
    """One day under a rule. Returns the day's realised total."""
    run = peak = 0.0
    for x in trades:
        run += x["usd"]
        peak = max(peak, run)
        if target is not None and run >= target:
            break                      # target hit: stop opening
        if giveback is not None and peak > 0 and (peak - run) >= giveback:
            break                      # gave back too much: stop
    return run


def main():
    sym, R = S.bars()
    tr = S.replay(R, SPREAD)
    days = {}
    for x in tr:
        days.setdefault(day_of(x["t"]), []).append(x)
    for d in days:
        days[d].sort(key=lambda z: z["t"])
    ds = sorted(days)
    print(f"\n  {sym}  {len(ds)} trading days, {len(tr)} trades, "
          f"spread {SPREAD:.0f}, lot 0.02\n")

    # --- 1. what a day produces -----------------------------------------
    nets = [sum(x["usd"] for x in days[d]) for d in ds]
    peaks = [max(0.0, max(_run(days[d]))) for d in ds]
    gb = [p - n for p, n in zip(peaks, nets)]
    q = lambda v, p: sorted(v)[min(len(v) - 1, int(p * len(v)))]
    print("  1. THE DAY AS IT IS  (no rule)")
    print(f"     net    p10 {q(nets,.1):+7.2f}  median {st.median(nets):+7.2f}"
          f"  p90 {q(nets,.9):+7.2f}   mean {st.mean(nets):+7.2f}")
    print(f"     peak   median {st.median(peaks):+7.2f}"
          f"  p90 {q(peaks,.9):+7.2f}")
    print(f"     GIVE-BACK from the day's peak:"
          f"  median {st.median(gb):6.2f}  p90 {q(gb,.9):6.2f}"
          f"  max {max(gb):6.2f}")
    win_days = sum(1 for n in nets if n > 0)
    gave = sum(1 for p, n in zip(peaks, nets) if p >= 3 and n < p - 3)
    print(f"     {win_days}/{len(ds)} days green"
          f"   |  {gave}/{len(ds)} days were >= $3 up and gave back >= $3")
    print(f"     total over the period: ${sum(nets):+.2f}")

    # --- 2. the grid ----------------------------------------------------
    print("\n  2. STOP THE DAY AT A TARGET  (+T realised, then no new trades)")
    print(f"     {'target':>8}{'total $':>10}{'median day':>12}"
          f"{'green days':>12}{'worst day':>11}")
    base_tot = sum(nets)
    print(f"     {'none':>8}{base_tot:>10.2f}{st.median(nets):>12.2f}"
          f"{win_days:>8}/{len(ds):<3}{min(nets):>11.2f}")
    for T in (3, 5, 8, 10, 15, 20):
        r = [run_day(days[d], T, None) for d in ds]
        print(f"     {T:>8}{sum(r):>10.2f}{st.median(r):>12.2f}"
              f"{sum(1 for x in r if x>0):>8}/{len(ds):<3}{min(r):>11.2f}")

    print("\n  3. STOP WHEN THE DAY GIVES BACK  (G from its own peak)")
    print(f"     {'giveback':>8}{'total $':>10}{'median day':>12}"
          f"{'green days':>12}{'worst day':>11}")
    for G in (3, 5, 8, 10, 15):
        r = [run_day(days[d], None, G) for d in ds]
        print(f"     {G:>8}{sum(r):>10.2f}{st.median(r):>12.2f}"
              f"{sum(1 for x in r if x>0):>8}/{len(ds):<3}{min(r):>11.2f}")

    print("\n  4. BOTH  (target T, give-back G)")
    print(f"     {'':>6}" + "".join(f"{'G='+str(g):>11}" for g in (3, 5, 8, 10)))
    for T in (5, 8, 10, 15, 20):
        row = f"     T={T:<4}"
        for G in (3, 5, 8, 10):
            r = [run_day(days[d], T, G) for d in ds]
            row += f"{sum(r):>11.2f}"
        print(row)
    print()


def _run(tl):
    run, out = 0.0, [0.0]
    for x in tl:
        run += x["usd"]
        out.append(run)
    return out


if __name__ == "__main__":
    main()
