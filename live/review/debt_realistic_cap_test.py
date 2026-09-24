"""Owner's proposal, 2026-09-24: instead of an unlimited waiver OR a
flat always-binds cap while in debt, compute how much a debt-day
REALISTICALLY makes (from the account's own trade history), and give the
bot that much room for the day - target = realistic_recoverable +
today's normal target ($3) - then stop, ALWAYS, even if debt remains.
Repeat day after day until clean. "Maybe the total needs to be
realistic still, otherwise reduce the average debt for the day a bit."

Step 1 MEASURES the real distribution: on every day that started in
debt (today's unlimited-waiver rule, so nothing is cut off), how much
did that day actually make? That distribution IS "how much can a debt
day realistically produce" - no guessing.

Step 2 tests candidate caps at several percentiles of that distribution
(low percentile = conservative/achievable almost every time, high
percentile = aspirational/rarely reached) plus the $3 target, ALWAYS
BINDING - this is the key difference from review/debt_ceiling_test.py's
failed ceiling idea, which fell back to the plain $3 cap past its
ceiling. Here the debt-day cap is bigger AND still fixed for the day.

Reports net $, max DD, worst debt, days>$50 debt, AND how often the cap
actually gets hit (the "realistic" check the owner asked for - a cap
that's hit 0% of the time is really still unlimited; one hit 100% of the
time is really just the flat cap again).

    python review/debt_realistic_cap_test.py [spread]
"""
import os
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
LIVE = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, LIVE)
_A = sys.argv[1:]
sys.argv = ["debt_realistic_cap_test"]

import MetaTrader5 as mt5              # noqa: E402
import structure_bos_bot as B          # noqa: E402
B.say = lambda *a, **k: None
import bullet_tune_test as BT          # noqa: E402

SPREAD = float(_A[0]) if _A else 7.0
LOT = 0.02
BLOT = 0.01
NB = 3.0
K = 2
TARGET = 3.0


def group_by_day(tr):
    days = {}
    for x in tr:
        days.setdefault(datetime.fromtimestamp(
            x["t"], tz=timezone.utc).strftime("%Y-%m-%d"), []).append(x)
    for d in days:
        days[d].sort(key=lambda z: z["t"])
    return days


def measure_debt_day_pnl(days, ds):
    """Pass 1: no cap at all while in debt (today's rule) - what does a
    debt-day actually make, uncapped?"""
    run = pk = 0.0
    streak = 0
    out = []
    for d in ds:
        debt_at_open = max(0.0, pk - run)
        day_pnl = 0.0
        for x in days[d]:
            dist = x["dist"]
            debt = max(0.0, pk - run)
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
        if debt_at_open > 0.5:
            out.append(day_pnl)
    return out


def percentile(vals, p):
    if not vals:
        return 0.0
    s = sorted(vals)
    i = min(len(s) - 1, max(0, int(round(p / 100.0 * (len(s) - 1)))))
    return s[i]


def simulate(days, ds, recoverable):
    """recoverable=None -> today (unlimited). Else: debt-day cap =
    recoverable + TARGET, decided ONCE at day-open (matches the once-a-
    day cadence already live for balance scaling), ALWAYS binds."""
    run = pk = 0.0
    streak = 0
    curve = []
    hits = attempts = 0
    for d in ds:
        debt_at_open = max(0.0, pk - run)
        cap_today = (recoverable + TARGET
                     if (recoverable is not None and debt_at_open > 0.5)
                     else TARGET)
        if debt_at_open > 0.5 and recoverable is not None:
            attempts += 1
        day_pnl = 0.0
        for x in days[d]:
            if day_pnl >= cap_today:
                break
            dist = x["dist"]
            debt = max(0.0, pk - run)
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
        if (debt_at_open > 0.5 and recoverable is not None
                and day_pnl >= cap_today):
            hits += 1
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
    hit_rate = 100 * hits / attempts if attempts else 0
    return dict(net=run, maxdd=dd, worst_debt=worst_debt,
                days_over_50=days_over_50, hit_rate=hit_rate,
                attempts=attempts)


def run_for(R, label):
    tr = BT.trades_with_path(R, SPREAD)
    days = group_by_day(tr)
    ds = sorted(days)
    debt_day_pnls = measure_debt_day_pnl(days, ds)
    print(f"\n  {label}  {len(ds)} days, {len(tr)} trades, spread "
          f"{SPREAD:.0f}")
    print(f"    debt-days in this window: {len(debt_day_pnls)} of {len(ds)}")
    if debt_day_pnls:
        print(f"    what a debt-day actually made, uncapped: "
              f"p25={percentile(debt_day_pnls,25):+.2f}  "
              f"median={percentile(debt_day_pnls,50):+.2f}  "
              f"p75={percentile(debt_day_pnls,75):+.2f}")
    print(f"\n  {'rule':<40}{'net $':>8}{'max DD':>9}{'worst debt':>11}"
          f"{'days>50':>9}{'cap hit %':>11}")
    r0 = simulate(days, ds, None)
    print(f"  {'A  today (unlimited while in debt)':<40}{r0['net']:>8.2f}"
          f"{r0['maxdd']:>9.2f}{r0['worst_debt']:>11.2f}"
          f"{r0['days_over_50']:>9}{'':>11}")
    for p in (25, 40, 50, 60, 75):
        R_val = percentile(debt_day_pnls, p)
        r = simulate(days, ds, R_val)
        lab = f"B  p{p} recoverable (${R_val:.2f}) + $3 target"
        print(f"  {lab:<40}{r['net']:>8.2f}{r['maxdd']:>9.2f}"
              f"{r['worst_debt']:>11.2f}{r['days_over_50']:>9}"
              f"{r['hit_rate']:>10.0f}%")
    print()


def main():
    u = next(x for x in __import__("json").load(open(os.path.join(
        LIVE, "owl_nest_users.json"), encoding="utf-8")) if x["id"] == "std")
    if not mt5.initialize(path=u["terminal"]):
        raise SystemExit(f"MT5: {mt5.last_error()}")
    sym = "BTCUSD" if mt5.symbol_info("BTCUSD") else "BTCUSDm"
    R = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_M1, 0, 60000)
    mt5.shutdown()

    run_for(R, f"{sym} FULL PERIOD")
    print("  HALVES (each independently, own percentiles from its own data)")
    mid = len(R) // 2
    run_for(R[:mid], "FIRST HALF")
    run_for(R[mid:], "SECOND HALF")


if __name__ == "__main__":
    main()
