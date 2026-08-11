"""Max profit / max drawdown for SPEC_FRESH_EARLY_COMBO, by day/week/month.
Uses the engine's own equity curve (per-bar), resampled to calendar periods
via the bar timestamps - no re-derivation of the rule logic.
"""
import datetime as dt

import numpy as np
import MetaTrader5 as mt5

from hedge_engine import simulate

ANCH = range(6)
BRICK_S = 50.0
BRICK_B = 150.0


def fresh_rev_masks(R, brick, rev=2):
    o = R["open"].astype(float)
    c = R["close"].astype(float)
    N = len(c)
    ao = ac = float(o[0])
    d = 0
    since = 99
    buy = np.zeros(N, bool)
    sell = np.zeros(N, bool)
    for j in range(N):
        ci = c[j]
        while True:
            up = (ao if d == -1 else ac) + brick * (rev if d == -1 else 1)
            dn = (ao if d == 1 else ac) - brick * (rev if d == 1 else 1)
            if ci >= up:
                base = ao if d == -1 else ac
                since = 0 if d == -1 else since + 1
                ao, ac, d = base, base + brick, 1
            elif ci <= dn:
                base = ao if d == 1 else ac
                since = 0 if d == 1 else since + 1
                ao, ac, d = base, base - brick, -1
            else:
                break
        if d != 0 and since <= 1:
            buy[j] = d == 1
            sell[j] = d == -1
    return buy, sell


def period_key(t, kind):
    d = dt.datetime.utcfromtimestamp(int(t))
    if kind == "day":
        return d.strftime("%Y-%m-%d")
    if kind == "week":
        iso = d.isocalendar()
        return f"{iso[0]}-W{iso[1]:02d}"
    if kind == "month":
        return d.strftime("%Y-%m")
    raise ValueError(kind)


def period_stats(tm, curve):
    """For each period kind, return (best period P&L, worst period P&L,
    worst peak-to-trough drawdown observed WITHIN any single period)."""
    out = {}
    for kind in ("day", "week", "month"):
        keys = [period_key(t, kind) for t in tm]
        uniq = []
        seen = set()
        for k in keys:
            if k not in seen:
                seen.add(k)
                uniq.append(k)
        starts = {}
        for i, k in enumerate(keys):
            if k not in starts:
                starts[k] = i
        best_pl = -1e18
        worst_pl = 1e18
        worst_dd = 0.0
        idxs = sorted(starts.values()) + [len(tm)]
        for a, b in zip(idxs, idxs[1:]):
            seg = curve[a:b]
            if len(seg) < 2:
                continue
            start_eq = curve[a - 1] if a > 0 else seg[0]
            pl = seg[-1] - start_eq
            best_pl = max(best_pl, pl)
            worst_pl = min(worst_pl, pl)
            peak = start_eq
            dd = 0.0
            for v in seg:
                peak = max(peak, v)
                dd = max(dd, peak - v)
            worst_dd = max(worst_dd, dd)
        out[kind] = dict(best=best_pl, worst=worst_pl, worst_dd=worst_dd,
                         n_periods=len(uniq))
    return out


def run_symbol(symbol, brick_s, brick_b, spread, daily_loss_limit=None):
    print(f"=== {symbol}  brick {brick_s}  big {brick_b}  spread {spread}  "
          f"daily_loss_limit {daily_loss_limit} ===")
    tfs = [("M1", mt5.TIMEFRAME_M1), ("M5", mt5.TIMEFRAME_M5),
           ("M15", mt5.TIMEFRAME_M15), ("H1", mt5.TIMEFRAME_H1)]
    data = {name: mt5.copy_rates_from_pos(symbol, tf, 0, 80000) for name, tf in tfs}
    agg = {"day": [], "week": [], "month": []}
    for name, R in data.items():
        mb, ms = fresh_rev_masks(R, brick_b)
        # report per-anchor stats, then take the median anchor for headline
        per_anchor = []
        for a in ANCH:
            r = simulate(R, a=a, arm="same", brick=brick_s, spread=spread,
                        entry_filter=("mask", mb, ms), day_stop=("cap", 2),
                        daily_loss_limit=daily_loss_limit)
            assert r["ok"]
            tm = np.asarray(R["time"], dtype=np.int64)[a:]
            ps = period_stats(tm, r["curve"])
            per_anchor.append(ps)
        for kind in ("day", "week", "month"):
            bests = [p[kind]["best"] for p in per_anchor]
            worsts = [p[kind]["worst"] for p in per_anchor]
            dds = [p[kind]["worst_dd"] for p in per_anchor]
            npd = per_anchor[0][kind]["n_periods"]
            print(f"  {name:<4} {kind:<5} n={npd:4d}  "
                  f"best +{max(bests):8.2f} (median +{np.median(bests):7.2f})  "
                  f"worst {min(worsts):9.2f} (median {np.median(worsts):8.2f})  "
                  f"max intra-period DD {max(dds):8.2f}")
            agg[kind].append((name, max(bests), min(worsts), max(dds)))
    print()
    return agg


if __name__ == "__main__":
    mt5.initialize(path=r"C:\Program Files\MetaTrader 5\terminal64.exe")
    agg_btc = run_symbol("BTCUSDm", 50.0, 150.0, 10.0, daily_loss_limit=20.0)
    mt5.shutdown()

    print("=" * 80)
    print("HEADLINE (worst-case across all timeframes/anchors, WITH the live "
          "$20/day protection folded in)")
    for kind in ("day", "week", "month"):
        rows = agg_btc[kind]
        best = max(r[1] for r in rows)
        worst = min(r[2] for r in rows)
        dd = max(r[3] for r in rows)
        print(f"  {kind:<5}  best single period {best:+8.2f}   "
              f"worst single period {worst:+9.2f}   worst intra-period DD {dd:8.2f}")
