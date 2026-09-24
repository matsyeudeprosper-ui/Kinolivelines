"""Would the day cap ALWAYS binding (not waived in debt) grow the account
faster, if the debt still gets paid down day by day through the existing
midpoint combat bullets - which already fire independently of the day cap
in the live bot?

Owner 2026-09-24: "would it help grow if we cap at Target for the day
regardless of debts then catch up little by little each new day with a
combat lot at midpoint like we always do?"

This is NOT the same question as review/cap_waiver_test.py (2026-09-23),
which compared waived-vs-always-binds with NO bullet recovery modeled at
all - that is why "always binds" only won there by starving the account of
its one recovery path (more trades). Here bullets fire every day exactly
as they do live: whenever debt > 0.5, at the midpoint, gated by the
deployed streak rule (no bullet after 2 straight MAIN losses). The day cap
only ever stops NEW MAIN entries - never a bullet on an already-open
trade - which matches enter()/day_blocked() in structure_bos_bot.py today.

  A  cap T, WAIVED while in debt   (live default: Valere/demo/Infinity)
  B  cap T, ALWAYS binds           (the proposal)
  C  no cap at all                  (Kino/Mike today, reference only)

Debt is the live high-water-mark definition: debt = peak_banked - banked.
Bullets: nb=3 max, streak rule K=2 (both match the deployed live config).

    python review/day_cap_always_binds_test.py [spread]
"""
import os
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
LIVE = os.path.dirname(HERE)
sys.path.insert(0, LIVE)
_A = sys.argv[1:]
sys.argv = ["day_cap_always_binds_test"]

import MetaTrader5 as mt5              # noqa: E402
import structure_bos_bot as B          # noqa: E402
B.say = lambda *a, **k: None
import bullet_tune_test as BT          # noqa: E402

SPREAD = float(_A[0]) if _A else 7.0
LOT = 0.02
BLOT = 0.01
NB = 3.0
K = 2   # deployed streak rule: no bullet after 2 straight MAIN losses


def group_by_day(tr):
    days = {}
    for x in tr:
        days.setdefault(datetime.fromtimestamp(
            x["t"], tz=timezone.utc).strftime("%Y-%m-%d"), []).append(x)
    for d in days:
        days[d].sort(key=lambda z: z["t"])
    return days


def simulate(days, ds, cap, waive):
    """Walk day by day. A day cap only ever refuses a NEW MAIN entry -
    an open trade's own midpoint bullet still fires regardless, exactly
    like enter()/day_blocked() vs the separate _ad pullback-add path in
    structure_bos_bot.py."""
    run = pk = 0.0
    streak = 0
    curve = []
    day_trades = day_bullets = 0
    for d in ds:
        day_pnl = 0.0
        for x in days[d]:
            dist = x["dist"]
            debt = max(0.0, pk - run)
            binds = (debt <= 0.5) if waive else True
            if cap is not None and binds and day_pnl >= cap:
                break                      # no new MAIN entry today
            pnl = ((B.RR * dist - SPREAD) if x["win"]
                   else -(dist + SPREAD)) * LOT
            run += pnl
            day_pnl += pnl
            day_trades += 1
            # the bullet: fires off THIS trade's own path if it touched
            # its midpoint, same as the live _ad mechanism - independent
            # of the day cap, gated only by debt and the streak rule
            fire = debt > 0.5 and streak < K
            if fire and x["mid"]:
                bp = ((1.3 * dist - SPREAD) if x["win"]
                      else -(dist / 2.0 + SPREAD)) * BLOT * NB
                run += bp
                day_pnl += bp
                day_bullets += 1
            streak = 0 if x["win"] else streak + 1
            pk = max(pk, run)
        curve.append(run)
    dd = 0.0
    pk2 = 0.0
    for v in curve:
        pk2 = max(pk2, v)
        dd = min(dd, v - pk2)
    debt_days = sum(1 for i, v in enumerate(curve)
                     if (max(c for c in curve[:i + 1]) - v) > 0.5)
    return dict(net=run, trades=day_trades, bullets=day_bullets,
                maxdd=dd, debt_days=debt_days, curve=curve)


def run_for(R, label):
    tr = BT.trades_with_path(R, SPREAD)
    days = group_by_day(tr)
    ds = sorted(days)
    print(f"\n  {label}  {len(ds)} days, {len(tr)} trades, spread "
          f"{SPREAD:.0f}, lot {LOT}, bullets nb={NB:.0f} lot {BLOT}, "
          f"streak K={K}\n")
    print(f"  {'rule':<34}{'trades':>7}{'balls':>7}{'net $':>9}"
          f"{'max DD':>9}{'debt days':>12}")
    rows = [("C  no cap at all", None, False)]
    for T in (3, 5, 10):
        rows.append((f"A  cap ${T}, waived in debt (today)", T, True))
        rows.append((f"B  cap ${T}, ALWAYS binds (proposal)", T, False))
    results = {}
    for lab, cap, waive in rows:
        r = simulate(days, ds, cap, waive)
        results[lab] = r
        print(f"  {lab:<34}{r['trades']:>7}{r['bullets']:>7}"
              f"{r['net']:>9.2f}{r['maxdd']:>9.2f}"
              f"{r['debt_days']:>10}/{len(ds):<3}")
    print()
    for T in (3, 5, 10):
        a = results[f"A  cap ${T}, waived in debt (today)"]
        b = results[f"B  cap ${T}, ALWAYS binds (proposal)"]
        print(f"  at ${T}: always-binds vs waived = "
              f"{b['net'] - a['net']:+.2f} net, "
              f"{b['maxdd'] - a['maxdd']:+.2f} DD, "
              f"{b['debt_days'] - a['debt_days']:+d} fewer/more debt-days")
    print()
    return results


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
