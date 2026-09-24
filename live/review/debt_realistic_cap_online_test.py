"""Same idea as debt_realistic_cap_test.py, but the HONEST online
version: the median is only ever computed from debt-days ALREADY SEEN
so far (a growing history, starting empty) - never from the future,
which is what the live bot will actually have to do. This is the
mechanism that gets built into structure_bos_bot.py.

Rule: the FIRST time a day opens in debt, there is no history yet, so
it falls back to today's unlimited-waiver behaviour (can't compute a
realistic number from zero samples). Once >= MIN_SAMPLES debt-days have
been recorded, every new debt-day gets capped at
median(recent debt-day results) + today's normal target, ALWAYS binding.
Each debt-day's own result is added to the history right after it ends
(recompute every debt-day, owner's choice), capped at the most recent
WINDOW entries.

    python review/debt_realistic_cap_online_test.py [spread]
"""
import os
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
LIVE = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, LIVE)
_A = sys.argv[1:]
sys.argv = ["debt_realistic_cap_online_test"]

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
MIN_SAMPLES = 3
WINDOW = 40


def group_by_day(tr):
    days = {}
    for x in tr:
        days.setdefault(datetime.fromtimestamp(
            x["t"], tz=timezone.utc).strftime("%Y-%m-%d"), []).append(x)
    for d in days:
        days[d].sort(key=lambda z: z["t"])
    return days


def median(vals):
    if not vals:
        return None
    s = sorted(vals)
    n = len(s)
    mid = n // 2
    return s[mid] if n % 2 else (s[mid - 1] + s[mid]) / 2.0


def simulate(days, ds, adaptive):
    """adaptive=False -> today. adaptive=True -> the real online rule."""
    run = pk = 0.0
    streak = 0
    curve = []
    history = []        # debt-day results seen SO FAR (online, honest)
    debt_at_open_prev = 0.0
    hits = attempts = fallbacks = 0
    for d in ds:
        debt_at_open = max(0.0, pk - run)
        in_debt = debt_at_open > 0.5
        if adaptive and in_debt:
            rec = median(history) if len(history) >= MIN_SAMPLES else None
            if rec is None:
                cap_today = None            # not enough history: unlimited
                fallbacks += 1
            else:
                cap_today = max(TARGET, max(0.0, rec) + TARGET)
                attempts += 1
        else:
            cap_today = TARGET
        day_pnl = 0.0
        for x in days[d]:
            if cap_today is not None and day_pnl >= cap_today:
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
        if in_debt:
            history.append(day_pnl)
            del history[:-WINDOW]
            if adaptive and cap_today is not None and day_pnl >= cap_today:
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
                attempts=attempts, fallbacks=fallbacks)


def run_for(R, label):
    tr = BT.trades_with_path(R, SPREAD)
    days = group_by_day(tr)
    ds = sorted(days)
    print(f"\n  {label}  {len(ds)} days, {len(tr)} trades, spread {SPREAD:.0f}")
    r0 = simulate(days, ds, False)
    r1 = simulate(days, ds, True)
    print(f"  {'rule':<38}{'net $':>8}{'max DD':>9}{'worst debt':>11}"
          f"{'days>50':>9}")
    print(f"  {'A  today (unlimited while in debt)':<38}{r0['net']:>8.2f}"
          f"{r0['maxdd']:>9.2f}{r0['worst_debt']:>11.2f}"
          f"{r0['days_over_50']:>9}")
    print(f"  {'B  ONLINE adaptive (median+target)':<38}{r1['net']:>8.2f}"
          f"{r1['maxdd']:>9.2f}{r1['worst_debt']:>11.2f}"
          f"{r1['days_over_50']:>9}")
    print(f"    adaptive cap used on {r1['attempts']} debt-days, hit it "
          f"{r1['hit_rate']:.0f}% of the time; fell back to unlimited "
          f"(not enough history yet) on {r1['fallbacks']} debt-days")
    return r1


def main():
    u = next(x for x in __import__("json").load(open(os.path.join(
        LIVE, "owl_nest_users.json"), encoding="utf-8")) if x["id"] == "std")
    if not mt5.initialize(path=u["terminal"]):
        raise SystemExit(f"MT5: {mt5.last_error()}")
    sym = "BTCUSD" if mt5.symbol_info("BTCUSD") else "BTCUSDm"
    R = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_M1, 0, 60000)
    mt5.shutdown()

    run_for(R, f"{sym} FULL PERIOD")
    print("\n  HALVES (each independently, own online history from scratch)")
    mid = len(R) // 2
    run_for(R[:mid], "FIRST HALF")
    run_for(R[mid:], "SECOND HALF")
    print()


if __name__ == "__main__":
    main()
