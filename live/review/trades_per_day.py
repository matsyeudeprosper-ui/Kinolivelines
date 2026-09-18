"""How many trades a day does an account ACTUALLY take?

Owner 2026-09-18 asked, after I quoted a signal count as if it were a trade
count. It is not: the bot holds ONE position at a time, so most allowed
signals arrive while it is already busy. This replays the live path bar by
bar and counts what would really have been opened.

Faithful to the bot:
  - the same Struct().step() engine, same seeding
  - the awake gate (a flip within AWAKE_WIN)
  - the flip / continuation rule, including used_hi / used_lo
  - S_MIN_DIST, MAX_RISK_PCT, RR, entry at the candle CLOSE
  - weather_gate() with the feed's own nervosity formula
  - ONE position at a time; the next signal is simply lost

Deliberately NOT modelled - so read this as an upper bound on volume:
  - spread and slippage (entry is the clean close)
  - the recovery jar's extra lots (changes P&L, not the trade COUNT)
  - the pullback add (an add is not a new trade for this count)
  - a bar that touches both SL and TP counts as SL, the pessimistic side

Usage:  python review/trades_per_day.py [bars]
"""
import bisect
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
LIVE = os.path.dirname(HERE)
sys.path.insert(0, LIVE)
sys.argv = ["trades_per_day"]          # so the bot module takes VARIANT=live

import MetaTrader5 as mt5              # noqa: E402
import structure_bos_bot as B          # noqa: E402

# the engine narrates CHoCHs through the bot's own say(), which prints AND
# appends to the live log file. A replay must never write to a bot's log.
B.say = lambda *a, **k: None


def bars(n):
    u = next(x for x in json.load(open(os.path.join(
        LIVE, "owl_nest_users.json"), encoding="utf-8"))
        if x["id"] == "std")           # retired account: read-only pull
    if not mt5.initialize(path=u["terminal"]):
        raise SystemExit(f"MT5: {mt5.last_error()}")
    sym = "BTCUSD" if mt5.symbol_info("BTCUSD") else "BTCUSDm"
    R = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_M1, 0, n)
    mt5.shutdown()
    if R is None or len(R) < 3000:
        raise SystemExit("not enough bars")
    return sym, R


def nervosity(rng, i):
    if i < 1440:
        return None
    vr = sorted(rng[i - 1440:i])[720]
    return sorted(rng[i - 60:i])[30] / max(vr, 1e-9)


def run(R, use_gates, balance=230.0, lot=0.02, day_cap=None):
    """Returns (trades, lost_busy, refused, lost_daycap).

    day_cap models the package's daily PROFIT target the way the bot does:
    once today's realised profit reaches it, no new entry - but it is
    WAIVED while the account owes money, so the debt is tracked too
    (high-water-mark, like DEBT_MODE 'hwm')."""
    eng = B.Struct()
    eng.quiet = True                # the engine's own "do not narrate" flag
    rng = [float(r["high"]) - float(r["low"]) for r in R]
    flips, marks = [], []
    prev_trend = 0
    used_hi = used_lo = None
    pos = None                      # (dir, entry, sl, tp, i_open)
    trades, lost_busy, refused, lost_cap = [], 0, 0, 0
    banked = peak = 0.0
    day_key, day_pnl = None, 0.0

    for i, bar in enumerate(R):
        t = int(bar["time"])
        o, h, l, c = (float(bar["open"]), float(bar["high"]),
                      float(bar["low"]), float(bar["close"]))

        # 1. an open position is resolved on THIS bar before anything else
        if pos:
            d, e, sl, tp, oi = pos
            hit_sl = (l <= sl) if d == 1 else (h >= sl)
            hit_tp = (h >= tp) if d == 1 else (l <= tp)
            if hit_sl or hit_tp:
                win = bool(hit_tp and not hit_sl)
                dist = abs(e - sl)
                pnl = (B.RR * dist * lot) if win else -(dist * lot)
                banked += pnl
                peak = max(peak, banked)
                k = t // 86400
                if k != day_key:
                    day_key, day_pnl = k, 0.0
                day_pnl += pnl
                trades.append({"t": t, "d": d, "win": win,
                               "mins": i - oi, "pnl": pnl})
                pos = None

        sig = eng.step(t, o, h, l, c)
        if eng.trend != prev_trend and eng.trend != 0:
            flips.append(t)
            prev_trend = eng.trend
        if sig is not None:
            marks.append(t)
        if sig is None:
            continue

        if not any(f > t - B.AWAKE_WIN for f in flips):
            refused += 1
            continue

        d, slp = sig
        flip = len(flips) > 0 and flips[-1] == t
        if not flip:
            lvl = eng.hi_v if d == 1 else eng.lo_v
            if (d == 1 and used_hi == lvl) or (d == -1 and used_lo == lvl):
                continue
            if d == 1:
                used_hi = lvl
            else:
                used_lo = lvl

        if use_gates:
            nv = nervosity(rng, i)
            mv2 = (bisect.bisect_left(marks, t)
                   - bisect.bisect_left(marks, t - 7200))
            cj = {"vol_now": (nv or 1.0) * 100, "vol_ref": 100,
                  "moves_2h": mv2, "int_brk_1h": 0}
            if nv is not None and B.weather_gate(need_int=False, cj=cj):
                refused += 1
                continue

        # the package's daily profit target, waived while in debt
        if day_cap is not None:
            k = t // 86400
            pnl_today = day_pnl if k == day_key else 0.0
            debt = max(0.0, peak - banked)
            if debt <= 0.5 and pnl_today >= day_cap:
                lost_cap += 1
                continue

        # the one that actually decides the volume
        if pos:
            lost_busy += 1
            continue

        dist = abs(c - slp)
        if dist <= B.S_MIN_DIST:
            refused += 1
            continue
        if dist * lot > B.MAX_RISK_PCT * balance:
            refused += 1
            continue
        tp = c + d * B.RR * dist
        pos = (d, c, slp, tp, i)

    return trades, lost_busy, refused, lost_cap


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 60000
    sym, R = bars(n)
    days = len(R) / 60 / 24
    print(f"  {sym}  {len(R)} bougies M1 = {days:.1f} jours\n")
    cases = [("sans frein, sans plafond", False, None),
             ("freins seuls (441)", True, None),
             ("freins + plafond $3 (Valere)", True, 3.0)]
    print(f"  {'':30}{'trades':>8}{'/jour':>8}{'% gagnes':>10}"
          f"{'perdus occupe':>15}{'perdus plafond':>16}")
    res = {}
    for label, g, cap in cases:
        tr, busy, ref, lc = run(R, g, day_cap=cap)
        w = sum(1 for x in tr if x["win"])
        res[label] = tr
        wr = (100 * w / len(tr)) if tr else 0
        print(f"  {label:30}{len(tr):>8}{len(tr)/days:>8.1f}{wr:>9.1f}%"
              f"{busy:>15}{lc:>16}")
    base = len(res["sans frein, sans plafond"])
    for label in list(res)[1:]:
        print(f"\n  {label:30} -> {100*(1-len(res[label])/max(base,1)):.0f}%"
              f" de trades en moins")
    tr = res["freins seuls (441)"]
    if tr:
        mins = sorted(x["mins"] for x in tr)
        print(f"\n  duree mediane d'un trade : {mins[len(mins)//2]} min"
              f"  (max {mins[-1]/60:.1f} h)")
    print("\n  Le % gagnes est BRUT : ni spread ni slippage. Ne pas le lire"
          "\n  comme une rentabilite.")


if __name__ == "__main__":
    main()
