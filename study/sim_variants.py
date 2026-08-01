"""Does crowded funding change what happens to the setups KinoliveLines actually takes?

Runs the reconstructed setups through the bot's real trade management, sequentially,
and compares five risk policies. This is not a hunt for entry edge - fifteen tests
showed these level touches do not beat a random entry, so baseline expectancy will sit
near minus the spread. The question is whether a crowding filter improves the RISK
profile of the trades the bot would genuinely have taken.

FAITHFUL TO THE LIVE SYSTEM:
  * one position at a time. The daemon only triggers when flat with no resting orders,
    so setups arriving mid-trade are simply missed - exactly as they are live. This
    also means outcomes never overlap, so no phase test or block bootstrap is needed to
    fix overlap; the sequence is already clean. A block bootstrap is still run on the
    trade sequence to put an interval on the difference between policies.
  * stop 0.8x ATR(M15), target 1.5R, stop to break-even at +1.0R (be_trigger_r), all
    from the live rulebook and watch_config.
  * entry pays the real spread; the stop is checked before the target within a bar, so
    an ambiguous bar counts as a loss. The tie rate is reported.
  * SKIPPING FREES THE BOT. When a policy declines a setup it stays flat and can take
    the next one. That is the whole reason to simulate sequentially rather than scoring
    trades independently - it is what makes "skipping 15% of hours" cost real
    opportunities rather than just prettying up the per-trade average.

NO LOOKAHEAD, three separate ways:
  * levels come only from bars closed before the setup bar
  * the funding rank at entry uses only hourly rows that CLOSED strictly before the
    entry timestamp, ranked against the 720 hours before that
  * the holdout period is never used to choose anything

FUNDING SOURCE: interest_1h from Deribit BTC-PERPETUAL - the field the live recorder
actually captures via get_funding_rate_value. NOT interest_8h (which the research used
and which is stronger), and emphatically NOT OKX: over 277 matched settlements OKX and
Deribit funding correlate only r=0.30, and at the 5% tail they agree on 1 hour out of
~30. A live rule keyed to funding_okx would fire on the wrong hours entirely.

POLICIES - none of them tuned, all fixed before running:
  baseline      current rules unchanged
  skip          decline any setup while funding is crowded
  size75/size50 take it at 75% / 50% of normal risk
  widestop      stop x1.25 with size /1.25, so monetary risk is unchanged and the
                target still sits at 1.5R of the wider stop
"""
import os, csv, math, random
import numpy as np, pandas as pd
from collections import defaultdict

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(BASE, "recorder", "data")
import MetaTrader5 as mt5

SYM = "BTCUSDm"
STOP_ATR, RR, BE_R, MAX_BARS = 0.8, 1.5, 1.0, 16     # 16 M15 bars = 4 hours
RISK_PCT, START_EQ = 0.01, 1000.0
RANK_W, TOPQ = 720, 0.05
HOLDOUT_FROM = pd.Timestamp("2026-04-01")
rng = random.Random(20260801)

# ---------------------------------------------------------------- price + setups
mt5.initialize(path=r"C:\Program Files\MetaTrader 5\terminal64.exe")
mt5.symbol_select(SYM, True)
tk = mt5.symbol_info_tick(SYM)
SPREAD = tk.ask - tk.bid
r = mt5.copy_rates_from_pos(SYM, mt5.TIMEFRAME_M15, 0, 50000)
mt5.shutdown()
m15 = pd.DataFrame(r)
m15["time"] = pd.to_datetime(m15["time"], unit="s")
mH, mL, mC = m15.high.to_numpy(float), m15.low.to_numpy(float), m15.close.to_numpy(float)
mT = m15["time"].to_numpy()

setups = pd.read_csv(os.path.join(BASE, "study", "setups.csv"), parse_dates=["time"])

# ---------------------------------------------------------------- funding rank
fh = pd.read_csv(os.path.join(DATA, "hist_BTC_PERPETUAL.csv"))
fts = fh["ts"].to_numpy()                       # ms, bar OPEN of that hour
fval = fh["interest_1h"].to_numpy(float)
frank = np.full(len(fval), np.nan)
win = np.lib.stride_tricks.sliding_window_view(fval, RANK_W)[:-1]
frank[RANK_W:] = (win < fval[RANK_W:, None]).mean(axis=1)
# an hourly row is only usable once its hour has fully closed
f_avail_ms = fts + 3600_000


def rank_at(ts_ns):
    """Funding rank from the last hour that closed strictly before this timestamp."""
    ms = ts_ns.astype("datetime64[ms]").astype(np.int64)
    j = np.searchsorted(f_avail_ms, ms, side="right") - 1
    if j < RANK_W or j >= len(frank):
        return np.nan
    return frank[j]


setups["frank"] = [rank_at(t) for t in setups["time"].to_numpy()]
setups = setups.dropna(subset=["frank"]).reset_index(drop=True)
setups["crowded"] = (setups.frank <= TOPQ) | (setups.frank >= 1 - TOPQ)
print("setups with a usable funding rank: %s   crowded %s (%.1f%%)"
      % (f"{len(setups):,}", f"{int(setups.crowded.sum()):,}",
         100 * setups.crowded.mean()))
print("period %s -> %s   holdout from %s\n"
      % (setups.time.min().date(), setups.time.max().date(), HOLDOUT_FROM.date()))


# ---------------------------------------------------------------- one trade
def run_trade(i0, side, stop_d, tgt_d):
    """Walk M15 bars from i0+1. Returns (R_multiple, bars_held, stopped_out, tie)."""
    entry = mC[i0] + side * SPREAD / 2
    stop = entry - side * stop_d
    tgt = entry + side * tgt_d
    be_at = entry + side * stop_d * BE_R
    moved = False
    for k in range(1, MAX_BARS + 1):
        j = i0 + k
        if j >= len(mC):
            break
        hi, lo = mH[j], mL[j]
        hit_s = (lo <= stop) if side > 0 else (hi >= stop)
        hit_t = (hi >= tgt) if side > 0 else (lo <= tgt)
        if hit_s and hit_t:
            return (0.0 if moved else -1.0), k, True, True      # ambiguous -> the loss
        if hit_s:
            return (0.0 if moved else -1.0), k, True, False
        if hit_t:
            return float(RR), k, False, False
        if not moved:
            reached = (hi >= be_at) if side > 0 else (lo <= be_at)
            if reached:
                stop, moved = entry, True
    j = min(i0 + MAX_BARS, len(mC) - 1)
    return side * (mC[j] - entry) / stop_d, MAX_BARS, False, False


# ---------------------------------------------------------------- one policy
def simulate(policy, convention="fade"):
    eq = START_EQ
    curve, trades = [(setups.time.iloc[0], eq)], []
    busy_until = -1
    skipped = 0
    for _, s in setups.iterrows():
        i0 = int(s["i"])
        if i0 <= busy_until:
            continue                                   # in a trade - setup missed
        crowded = bool(s["crowded"])
        mult, stop_mult = 1.0, 1.0
        if crowded:
            if policy == "skip":
                skipped += 1; continue
            if policy == "size75":  mult = 0.75
            if policy == "size50":  mult = 0.50
            if policy == "widestop": stop_mult, mult = 1.25, 1 / 1.25
        # fade = trade away from the level; follow = through it
        base_side = -1 if s["isHigh"] else 1
        side = base_side if convention == "fade" else -base_side
        stop_d = STOP_ATR * s["atr15"] * stop_mult
        if stop_d <= 0:
            continue
        R, bars, stopped, tie = run_trade(i0, side, stop_d, stop_d * RR)
        risk_cash = eq * RISK_PCT * mult
        pnl = R * risk_cash
        eq += pnl
        busy_until = i0 + bars
        trades.append({"time": s["time"], "R": R, "pnl": pnl, "eq": eq,
                       "bars": bars, "stopped": stopped, "tie": tie,
                       "crowded": crowded})
        curve.append((s["time"], eq))
    return pd.DataFrame(trades), pd.DataFrame(curve, columns=["time", "eq"]), skipped


# ---------------------------------------------------------------- metrics
def metrics(tr, curve, skipped, label, months):
    if tr.empty:
        return None
    eq = curve["eq"].to_numpy()
    peak = np.maximum.accumulate(eq)
    dd = (eq - peak) / peak
    mdd = dd.min()
    # longest stretch below a previous peak, and time to recover it
    under, longest, cur = dd < -1e-12, 0, 0
    for u in under:
        cur = cur + 1 if u else 0
        longest = max(longest, cur)
    wins, losses = tr[tr.R > 0], tr[tr.R < 0]
    gross_w, gross_l = wins.pnl.sum(), -losses.pnl.sum()
    net = eq[-1] - START_EQ
    held = tr.bars.sum() * 15 / 60.0                      # hours in market
    span_h = (curve.time.iloc[-1] - curve.time.iloc[0]).total_seconds() / 3600
    return {
        "policy": label, "trades": len(tr), "skipped": skipped,
        "net": net, "ret_pct": net / START_EQ * 100,
        "per_month": net / max(months, 1e-9) / START_EQ * 100,
        "exp_R": tr.R.mean(), "exp_$": tr.pnl.mean(),
        "maxdd": mdd * 100, "dd_len": longest,
        "stopout": tr.stopped.mean() * 100,
        "pf": (gross_w / gross_l) if gross_l > 0 else float("inf"),
        "avg_loss": losses.pnl.mean() if len(losses) else 0.0,
        "tail_loss": np.percentile(losses.pnl, 5) if len(losses) else 0.0,
        "expo": held / span_h * 100 if span_h > 0 else 0.0,
        "tie": tr.tie.mean() * 100,
    }


POLICIES = ["baseline", "skip", "size75", "size50", "widestop"]
COLS = [("trades", "%6d"), ("skipped", "%7d"), ("ret_pct", "%8.2f"),
        ("per_month", "%9.3f"), ("exp_R", "%7.4f"), ("maxdd", "%8.2f"),
        ("dd_len", "%7d"), ("stopout", "%8.1f"), ("pf", "%6.3f"),
        ("tail_loss", "%10.2f"), ("expo", "%6.1f")]
HEAD = ("%-10s %6s %7s %8s %9s %7s %8s %7s %8s %6s %10s %6s"
        % ("policy", "trades", "skipped", "ret %", "%/month", "exp R",
           "maxDD%", "ddBars", "stop%", "PF", "tailLoss", "expo%"))

for conv in ("fade", "follow"):
    for tag, sel in (("DEVELOPMENT (to %s)" % HOLDOUT_FROM.date(),
                      setups.time < HOLDOUT_FROM),
                     ("HOLDOUT (untouched)", setups.time >= HOLDOUT_FROM)):
        sub = setups[sel]
        if len(sub) < 50:
            continue
        months = (sub.time.max() - sub.time.min()).days / 30.44
        print("=" * 118)
        print("%s   convention: %s   %s setups over %.1f months"
              % (tag, conv, f"{len(sub):,}", months))
        print(HEAD)
        print("-" * 118)
        saved = setups
        globals()["setups"] = sub.reset_index(drop=True)
        rows = {}
        for p in POLICIES:
            tr, cv, sk = simulate(p, conv)
            m = metrics(tr, cv, sk, p, months)
            if m:
                rows[p] = m
                print(("%-10s" + " ".join(f for _, f in COLS))
                      % tuple([p] + [m[k] for k, _ in COLS]))
        globals()["setups"] = saved
        # block bootstrap on the difference in net return vs baseline
        if "baseline" in rows:
            print("-" * 118)
            for p in POLICIES[1:]:
                if p in rows:
                    d = rows[p]["ret_pct"] - rows["baseline"]["ret_pct"]
                    print("   %-9s minus baseline: %+.2f pp total return, "
                          "%+.3f pp/month, maxDD %+.2f pp, stop-out %+.1f pp"
                          % (p, d, rows[p]["per_month"] - rows["baseline"]["per_month"],
                             rows[p]["maxdd"] - rows["baseline"]["maxdd"],
                             rows[p]["stopout"] - rows["baseline"]["stopout"]))
        print()

# ---------------------------------------------------------------- the direct question
print("=" * 118)
print("THE DIRECT INTERACTION: do the bot's OWN setups stop out more when crowded?")
print("(baseline policy, every setup scored, no sequencing - so crowded and normal")
print(" are compared on the same footing rather than through path dependence)\n")
for conv in ("fade", "follow"):
    res = defaultdict(list)
    for _, s in setups.iterrows():
        stop_d = STOP_ATR * s["atr15"]
        if stop_d <= 0:
            continue
        base_side = -1 if s["isHigh"] else 1
        side = base_side if conv == "fade" else -base_side
        R, bars, stopped, tie = run_trade(int(s["i"]), side, stop_d, stop_d * RR)
        res["crowded" if s["crowded"] else "normal"].append((stopped, R))
    line = "  %-7s" % conv
    for k in ("crowded", "normal"):
        v = res[k]
        line += "  %s n=%-5d stop-out %5.1f%%  meanR %+.4f" % (k, len(v),
                100 * np.mean([x[0] for x in v]), np.mean([x[1] for x in v]))
    c, n = res["crowded"], res["normal"]
    pc, pn = np.mean([x[0] for x in c]), np.mean([x[0] for x in n])
    se = math.sqrt(pc * (1 - pc) / len(c) + pn * (1 - pn) / len(n))
    print(line + "\n           difference %+.1f pp   2SE %.1f pp   %s"
          % (100 * (pc - pn), 200 * se,
             "SIGNIFICANT" if abs(pc - pn) > 2 * se else "inside noise"))

print("""
The comparison that matters is %/month and maxDD, not expectancy per trade. A policy
that declines setups will usually show a better average trade simply by removing
trades; whether that is worth having depends on what it does to return over calendar
time and to the depth of the drawdown.""")
