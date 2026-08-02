"""TASK 003 - FX CROSS-SECTIONAL MOMENTUM 3M-1M V1  (preregistered, frozen)

Implementation and verification of a strategy specified entirely by the strategy lead.
Nothing here is tuned, optimised or chosen by me. Every parameter below is copied from
the frozen specification. If V1 fails a hard condition it is reported FAILED and left
alone - no repair, no parameter search, no replacement.

This script does not touch the live bot and places no orders. It reads history only.

================================================================================
VERIFIED BROKER FACTS (checked, not assumed)
================================================================================
* MT5 historical OHLC bars are BID prices. symbol_info('EURUSDm').chart_mode == 0
  (SYMBOL_CHART_MODE_BID), and the last H1 close reproduced the live bid exactly
  (1.15284 vs bid 1.15284, ask 1.15332). So:
      BUY  enters at ask = bar price + spread, exits at bid = bar price
      SELL enters at bid = bar price,          exits at ask = bar price + spread
  and a BUY stop triggers on bid (bar low), a SELL stop on ask (bar high + spread).
* All 19 executable pairs: contract size 100,000, minimum lot 0.01.

================================================================================
CURRENCY CONVERSION - why it is done with the fitted graph
================================================================================
P&L accrues in each pair's QUOTE currency and must be converted to USD at the rate
that prevailed AT THE TIME, not today. GBPUSDm is not in the executable universe, so
there is no direct GBP/USD column to convert with.

The least-squares currency system already provides this. With USD pinned to zero and
    log(pair) = value(BASE) - value(QUOTE)
a pair XXXUSD satisfies log(XXXUSD) = value(XXX), so
    XXX->USD rate = exp(value(XXX))
for every currency in the system, including ones with no direct USD pair. This is the
"contemporaneous currency-conversion graph" the specification asks for, it is fitted
from that week's closes only, and its residuals are recorded so triangular
inconsistency stays visible rather than hidden.

================================================================================
FROZEN PARAMETERS - do not edit to chase a result
================================================================================
"""
import os
import json
import datetime as dt

import numpy as np
import pandas as pd
import MetaTrader5 as mt5

# ----------------------------------------------------------------- frozen spec
START_EQUITY = 979.00
FORMATION_WEEKS = 13              # frozen baseline
DIAG_FORMATIONS = [4, 13, 26]     # 4 and 26 are diagnostics only
STOP_ATR_MULT = 2.0
ATR_PERIOD = 20
MAX_RISK_PCT = 1.50               # of CURRENT equity
MAX_EXPOSURE_X = 2.00             # of CURRENT equity
LOTS = 0.01
CONTRACT = 100_000.0

REBAL_HOUR_NY = 20                # first Monday of the month, 20:00 New York
REBAL_DEADLINE_HOURS = 24         # no later than Tuesday 20:00, else skip the month

FIN_STRESS = {"spread_only": 0.0, "fin_1.5pct": 0.015, "fin_3.0pct": 0.030}
N_PERM = 10_000
PERM_SEED = 20260802              # fixed so the randomisation is reproducible

# universe filters (task 002 revised numbers)
UNIV_MAX_RISK_PCT = 1.50
UNIV_MAX_EXPO_X = 2.00
UNIV_MAX_SPREAD_PCT_ATR = 6.00

# test periods
DEV_END = pd.Timestamp("2021-07-31")
VAL_START, VAL_END = pd.Timestamp("2021-08-01"), pd.Timestamp("2023-12-31")
HOLD_START, HOLD_END = pd.Timestamp("2024-01-01"), pd.Timestamp("2026-07-31")

NY = "America/New_York"
TERMINAL = r"C:\Program Files\MetaTrader 5\terminal64.exe"

HERE = os.path.dirname(os.path.abspath(__file__))
DATA, RAW = os.path.join(HERE, "data"), os.path.join(HERE, "data", "raw_h1")
RES = os.path.join(HERE, "results")
os.makedirs(RES, exist_ok=True)

CENSUS = os.path.join(RES, "exness_feasibility_census.csv")
UNIV = os.path.join(RES, "fx_universe_audit.csv")
DAILY = os.path.join(DATA, "fx_daily_canonical.csv")

OUT_TRADES = os.path.join(RES, "fx_momentum_v1_trades.csv")
OUT_MONTHLY = os.path.join(RES, "fx_momentum_v1_monthly.csv")
OUT_SIGNAL = os.path.join(RES, "fx_momentum_v1_signal_tests.csv")
OUT_CONTROLS = os.path.join(RES, "fx_momentum_v1_controls.csv")
OUT_REPORT = os.path.join(RES, "fx_momentum_v1_report.txt")

LOG = []


def say(s=""):
    print(s, flush=True)
    LOG.append(s)


# ============================================================ 1. universe
def executable_universe():
    u = pd.read_csv(UNIV)
    s = u[u["selected"] == True].copy()                                # noqa: E712
    ex = s[(s["revised_risk_pct_of_979"] <= UNIV_MAX_RISK_PCT)
           & (s["census_exposure_x"] <= UNIV_MAX_EXPO_X)
           & (s["census_spread_pct_atr"] <= UNIV_MAX_SPREAD_PCT_ATR)
           & (s["both_sides"] == True)].copy()                          # noqa: E712
    dropped = s[~s["symbol"].isin(ex["symbol"])]
    return sorted(ex["symbol"].tolist()), ex, dropped


# ============================================================ 2. H1 + audit
def load_h1(sym):
    d = pd.read_csv(os.path.join(RAW, f"h1_{sym}.csv"))
    d["t_utc"] = pd.to_datetime(d["time"], unit="s", utc=True)
    d = d.drop_duplicates(subset="time").sort_values("t_utc").reset_index(drop=True)
    d["t_ny"] = d["t_utc"].dt.tz_convert(NY)
    d["session"] = pd.to_datetime((d["t_ny"] + pd.Timedelta(hours=7)).dt.date)
    return d


def session_grid_audit(h1, sessions):
    """Strengthened completeness audit.

    Task 002 only measured gaps INSIDE the span of bars that arrived, so a session
    missing its first or last hour looked complete. Here the expected hourly grid is
    constructed independently, from the session definition rather than from the data,
    so a missing opening or closing hour is detectable.

    Session D runs 17:00 NY on D-1 through the 16:00 NY bar on D: 24 hourly slots.
    Built in New York local time so daylight saving is handled by the calendar rather
    than by arithmetic.
    """
    have = {}
    for sess, g in h1.groupby("session"):
        have[sess] = set(g["t_ny"].dt.strftime("%Y-%m-%d %H"))
    rows = []
    for sess in sessions:
        start = (pd.Timestamp(sess) - pd.Timedelta(days=1)).tz_localize(NY) \
            + pd.Timedelta(hours=17)
        grid = pd.date_range(start, periods=24, freq="h", tz=NY)
        keys = [t.strftime("%Y-%m-%d %H") for t in grid]
        present = have.get(sess, set())
        miss = [k for k in keys if k not in present]
        rows.append({
            "session": sess,
            "expected_hours": len(keys),
            "present_hours": len(keys) - len(miss),
            "missing_hours": len(miss),
            "missing_open_hour": keys[0] not in present,
            "missing_close_hour": keys[-1] not in present,
            "complete": len(miss) == 0,
        })
    return pd.DataFrame(rows)


# ============================================================ 3. currency LS
def currency_values(week_close, ccys, pairs):
    """Least-squares currency log-values with USD pinned to zero.

    Returns (values dict, residual rms). Residual rms is the triangular
    inconsistency of the broker's own quotes and is reported, never smoothed away.
    """
    free = [c for c in ccys if c != "USD"]
    idx = {c: i for i, c in enumerate(free)}
    A, b = [], []
    for p in pairs:
        base, quote = p[:3], p[3:6]
        v = week_close.get(p)
        if v is None or not np.isfinite(v) or v <= 0:
            continue
        row = np.zeros(len(free))
        if base in idx:
            row[idx[base]] += 1.0
        if quote in idx:
            row[idx[quote]] -= 1.0
        A.append(row)
        b.append(np.log(v))
    if len(A) < len(free):
        return None, np.nan
    A, b = np.array(A), np.array(b)
    sol, *_ = np.linalg.lstsq(A, b, rcond=None)
    resid = float(np.sqrt(np.mean((A @ sol - b) ** 2)))
    vals = {"USD": 0.0}
    vals.update({c: float(sol[idx[c]]) for c in free})
    return vals, resid


def fit_graph(quotes, ccys, pairs_):
    """Least-squares currency log-values from {pair: price}, USD pinned to zero.

    Returns (values, residual_rms, n_pairs_used) or (None, nan, 0) when the system
    is rank-deficient - i.e. the available pairs do not connect every currency back
    to USD, so some currency's value would be unidentifiable.
    """
    free = [c for c in ccys if c != "USD"]
    idx = {c: i for i, c in enumerate(free)}
    A, b = [], []
    for p in pairs_:
        v = quotes.get(p)
        if v is None or not np.isfinite(v) or v <= 0:
            continue
        row = np.zeros(len(free))
        if p[:3] in idx:
            row[idx[p[:3]]] += 1.0
        if p[3:6] in idx:
            row[idx[p[3:6]]] -= 1.0
        A.append(row)
        b.append(np.log(v))
    if len(A) < len(free):
        return None, np.nan, len(A)
    A, b = np.array(A), np.array(b)
    if np.linalg.matrix_rank(A) < len(free):      # graph not connected to USD
        return None, np.nan, len(A)
    sol, *_ = np.linalg.lstsq(A, b, rcond=None)
    resid = float(np.sqrt(np.mean((A @ sol - b) ** 2)))
    vals = {"USD": 0.0}
    vals.update({c: float(sol[idx[c]]) for c in free})
    return vals, resid, len(A)


# --------------------------------------------------------------------------------
# TASK 003B CORRECTION 1 - EXACT H1 CURRENCY GRAPHS
# --------------------------------------------------------------------------------
# 003A still converted with the newest completed WEEKLY graph, which could be up to
# five trading days stale at the moment of a fill. The graph is now rebuilt at the
# exact H1 timestamp of every entry and every exit, from that bar's MIDPOINT opens:
#
#     mid_open = bid_open + 0.5 * spread_points * point
#
# Midpoints, not bids, because a currency value is a property of the market rather
# than of one side of the quote; using bids would push a systematic half-spread into
# every fitted currency and therefore into every conversion.
#
# A stop that fires inside an H1 bar is converted with the graph built from THAT
# bar's opening prices - the finest historical timestamp the data supports.
H1IDX = {}
_GCACHE = {}


def h1_graph(ts):
    """Currency graph at exactly `ts`, from that H1 bar's midpoint opens.

    Returns (values, residual_rms, n_pairs, ts) or None when no connected graph
    exists at that timestamp.
    """
    key = pd.Timestamp(ts)
    if key in _GCACHE:
        return _GCACHE[key]
    quotes = {}
    for p, tbl in H1IDX.items():
        rec = tbl.get(key)
        if rec is None:
            continue
        bid_open, spread_pts, point = rec
        mid = bid_open + 0.5 * spread_pts * point
        if mid > 0:
            quotes[p] = mid
    vals, resid, n = fit_graph(quotes, CCYS, list(H1IDX.keys()))
    out = None if vals is None else (vals, resid, n, key)
    _GCACHE[key] = out
    return out


def build_weekly_currency(weekly_close, ccys, pairs):
    recs = []
    for wk, row in weekly_close.iterrows():
        vals, resid = currency_values(row.to_dict(), ccys, pairs)
        if vals is None:
            continue
        r = {"week_end": wk, "resid_rms": resid}
        r.update({f"cv_{c}": v for c, v in vals.items()})
        recs.append(r)
    return pd.DataFrame(recs).set_index("week_end")


# ============================================================ 4. schedule
def first_monday(year, month):
    d = dt.date(year, month, 1)
    while d.weekday() != 0:
        d += dt.timedelta(days=1)
    return d


def rebalance_bars(h1_any, first_m, deadline_h):
    """First H1 bar at/after Monday 20:00 NY, else up to Tuesday 20:00, else skip."""
    t0 = pd.Timestamp(first_m).tz_localize(NY) + pd.Timedelta(hours=REBAL_HOUR_NY)
    t1 = t0 + pd.Timedelta(hours=deadline_h)
    cand = h1_any[(h1_any["t_ny"] >= t0) & (h1_any["t_ny"] <= t1)]
    if not len(cand):
        return None
    return cand.iloc[0]["t_utc"]


# ============================================================ 5. trade sim
def simulate_leg(sym, h1, t_entry, t_exit, direction, atr, spread_mult=1.0):
    """One trade at minimum lot. Bars are BID (verified). Returns a dict or None.

    BUY  : enter ask (bid+spread), exit bid,          stop on bar low
    SELL : enter bid,              exit ask (+spread), stop on bar high + spread
    Stop gaps fill at the WORSE of the stop price or the first tradeable price.

    TASK 003A CORRECTIONS 1 and 2
    -----------------------------
    (1) An unstopped trade now closes at the OPEN of the next rebalance H1 bar, and
        that bar is NOT scanned for the old trade's stop. Previously the holding
        window ran `t_utc <= t_exit` and exited at that bar's CLOSE, which both
        monitored the old position inside the bar where the new one is opened and
        credited it an extra hour of drift it could never have captured.
    (2) The stop is now checked during the ENTRY bar itself. Previously the scan
        started at `seg.iloc[1:]`, so a position whose stop was breached in its own
        first hour survived to the next bar - a free hour of immunity.

    Holding window is therefore [t_entry, t_exit) for stop monitoring, with the bar
    at t_exit used only to supply the exit open.
    """
    hold = h1[(h1["t_utc"] >= t_entry) & (h1["t_utc"] < t_exit)]
    exit_bar = h1[h1["t_utc"] == t_exit]
    if not len(hold) or not len(exit_bar):
        return None
    point = hold["point"].iloc[0]
    e = hold.iloc[0]
    sp_e = e["spread"] * point * spread_mult
    if direction > 0:
        entry = e["open"] + sp_e
        stop = entry - STOP_ATR_MULT * atr
    else:
        entry = e["open"]
        stop = entry + STOP_ATR_MULT * atr

    hit, exit_px, t_out, reason = False, None, None, "rebalance"
    entry_bar_stop = False
    for n_, (_, r) in enumerate(hold.iterrows()):        # includes the entry bar
        sp = r["spread"] * point * spread_mult
        if direction > 0:
            if r["low"] <= stop:                        # bid touched the stop
                # on the entry bar the position exists from the open, so a gap
                # cannot be worse than the entry itself
                ref = entry if n_ == 0 else r["open"]
                exit_px = min(stop, ref)
                hit, t_out, reason = True, r["t_utc"], "stop"
                entry_bar_stop = (n_ == 0)
                break
        else:
            if r["high"] + sp >= stop:                  # ask touched the stop
                ref = entry if n_ == 0 else r["open"] + sp
                exit_px = max(stop, ref)
                hit, t_out, reason = True, r["t_utc"], "stop"
                entry_bar_stop = (n_ == 0)
                break
    if not hit:
        x = exit_bar.iloc[0]
        sp_x = x["spread"] * point * spread_mult
        exit_px = x["open"] if direction > 0 else x["open"] + sp_x
        t_out = x["t_utc"]

    gross_quote = (exit_px - entry) * direction * CONTRACT * LOTS
    days = max((t_out - t_entry).total_seconds() / 86400.0, 0.0)
    return {"entry_px": entry, "exit_px": exit_px, "stop_px": stop, "t_out": t_out,
            "exit_reason": reason, "gross_quote": gross_quote, "days_held": days,
            "notional_quote": abs(entry) * CONTRACT * LOTS,
            "entry_bar_stop": entry_bar_stop,
            "exit_bar_open_bid": float(exit_bar.iloc[0]["open"]),
            "exit_bar_spread_px": float(exit_bar.iloc[0]["spread"] * point * spread_mult)}


# ============================================================ run
say("=" * 100)
say("TASK 003 - FX CROSS-SECTIONAL MOMENTUM 3M-1M V1")
say("=" * 100)
say(f"generated : {dt.datetime.now():%Y-%m-%d %H:%M:%S}")
say("")

pairs, univ_ex, univ_drop = executable_universe()
CCYS = sorted({p[:3] for p in pairs} | {p[3:6] for p in pairs})
say(f"EXECUTABLE UNIVERSE ({len(pairs)} pairs), printed before any test:")
for i in range(0, len(pairs), 6):
    say("   " + "  ".join(pairs[i:i + 6]))
say(f"currencies ({len(CCYS)}): {', '.join(CCYS)}")
say("")
say(f"dropped from the task-002 23 ({len(univ_drop)}):")
for _, r in univ_drop.iterrows():
    say(f"   {r['symbol']:9s} revised risk {r['revised_risk_pct_of_979']:.3f}% "
        f"> {UNIV_MAX_RISK_PCT:.2f}%")
say("   NZDCHFm remains excluded from task 002 (spread 6.02% > 6.00%); "
    "the limit was not rounded.")
say("")

# ---- H1 + strengthened audit
say("STRENGTHENED COMPLETENESS AUDIT (expected hourly grid per session)")
canon = pd.read_csv(DAILY)
canon["trading_date"] = pd.to_datetime(canon["trading_date"])
# the canonical file holds all 23 task-002 pairs; this task trades only the 19
canon = canon[canon["symbol"].isin(pairs)].reset_index(drop=True)
H1, AUD = {}, {}
census = pd.read_csv(CENSUS).set_index("symbol")
for s in pairs:
    h = load_h1(s)
    h["point"] = float(census.loc[s, "point"])
    H1[s] = h
    sess = canon[canon["symbol"] == s]["trading_date"].tolist()
    AUD[s] = session_grid_audit(h, sess)
    # timestamp -> (bid open, spread points, point) for the exact-H1 graph builder
    H1IDX[s] = dict(zip(h["t_utc"], zip(h["open"], h["spread"], h["point"])))

aud_all = pd.concat([a.assign(symbol=s) for s, a in AUD.items()], ignore_index=True)
say(f"  sessions audited        : {len(aud_all)}")
say(f"  complete                : {int(aud_all['complete'].sum())}")
say(f"  incomplete              : {int((~aud_all['complete']).sum())}")
say(f"  missing OPENING hour    : {int(aud_all['missing_open_hour'].sum())}   "
    "<- undetectable by the task-002 audit")
say(f"  missing CLOSING hour    : {int(aud_all['missing_close_hour'].sum())}   "
    "<- undetectable by the task-002 audit")
say("")

# a session is usable only if complete for EVERY pair (cross-sectional requirement)
bad_sess = set(aud_all[~aud_all["complete"]]["session"])
canon["session_ok"] = ~canon["trading_date"].isin(bad_sess)

# ---- weekly canonical panel, complete weeks only
canon["iso_year"] = canon["trading_date"].dt.isocalendar().year
canon["iso_week"] = canon["trading_date"].dt.isocalendar().week
canon["wk"] = canon["iso_year"].astype(str) + "-W" + canon["iso_week"].astype(str).str.zfill(2)
grp = canon.groupby(["symbol", "wk"])
wk_tbl = grp.agg(close=("close", "last"), n_days=("trading_date", "size"),
                 all_ok=("session_ok", "all"),
                 week_end=("trading_date", "max")).reset_index()
full_wk = wk_tbl.groupby("wk").agg(min_days=("n_days", "min"), all_ok=("all_ok", "all"),
                                   n_sym=("symbol", "nunique"),
                                   week_end=("week_end", "max"))
good_weeks = full_wk[(full_wk["min_days"] == 5) & (full_wk["all_ok"])
                     & (full_wk["n_sym"] == len(pairs))]
say(f"CANONICAL WEEKLY PANEL: {len(full_wk)} weeks, "
    f"{len(good_weeks)} complete and usable, {len(full_wk)-len(good_weeks)} excluded")
say("")

wc = wk_tbl[wk_tbl["wk"].isin(good_weeks.index)].pivot(index="wk", columns="symbol",
                                                       values="close")
wc = wc.loc[sorted(wc.index)]
wk_end = good_weeks["week_end"]
cv_canon = build_weekly_currency(wc, CCYS, pairs)
cv_canon["week_end"] = wk_end.reindex(cv_canon.index).values
say(f"currency LS residual rms (canonical): median {cv_canon['resid_rms'].median():.2e}  "
    f"max {cv_canon['resid_rms'].max():.2e}")
say("")

# ---- long D1 signal panel
say("LONG-HISTORY D1 SIGNAL PANEL")
if not mt5.initialize(path=TERMINAL):
    raise SystemExit(f"initialize failed: {mt5.last_error()}")
d1 = {}
for s in pairs:
    r = mt5.copy_rates_from_pos(s, mt5.TIMEFRAME_D1, 0, 20000)
    if r is None:
        continue
    d = pd.DataFrame(r)
    d["t"] = pd.to_datetime(d["time"], unit="s")
    d1[s] = d
mt5.shutdown()

d1_rows, sunday_merged = [], 0
for s, d in d1.items():
    d = d.copy()
    d["dow"] = d["t"].dt.dayofweek
    # merge any Sunday D1 candle into the following Monday
    d["eff"] = d["t"].dt.normalize()
    sun = d["dow"] == 6
    sunday_merged += int(sun.sum())
    d.loc[sun, "eff"] = d.loc[sun, "eff"] + pd.Timedelta(days=1)
    g = d.groupby("eff").agg(open=("open", "first"), high=("high", "max"),
                             low=("low", "min"), close=("close", "last"),
                             tick_volume=("tick_volume", "sum")).reset_index()
    g["symbol"] = s
    g = g[g["eff"].dt.dayofweek < 5]
    d1_rows.append(g)
d1p = pd.concat(d1_rows, ignore_index=True)
d1p["iso_year"] = d1p["eff"].dt.isocalendar().year
d1p["iso_week"] = d1p["eff"].dt.isocalendar().week
d1p["wk"] = d1p["iso_year"].astype(str) + "-W" + d1p["iso_week"].astype(str).str.zfill(2)
g2 = d1p.groupby(["symbol", "wk"]).agg(close=("close", "last"), n=("eff", "size"),
                                       week_end=("eff", "max")).reset_index()
f2 = g2.groupby("wk").agg(min_days=("n", "min"), n_sym=("symbol", "nunique"),
                          week_end=("week_end", "max"))
good2 = f2[(f2["min_days"] == 5) & (f2["n_sym"] == len(pairs))]
wc_d1 = g2[g2["wk"].isin(good2.index)].pivot(index="wk", columns="symbol", values="close")
wc_d1 = wc_d1.loc[sorted(wc_d1.index)]
cv_d1 = build_weekly_currency(wc_d1, CCYS, pairs)
cv_d1["week_end"] = good2["week_end"].reindex(cv_d1.index).values
say(f"  D1 bars merged from Sunday into Monday : {sunday_merged}")
say(f"  weeks total {len(f2)}, complete and usable {len(good2)}, "
    f"excluded {len(f2)-len(good2)}")
say(f"  span: {good2['week_end'].min().date()} -> {good2['week_end'].max().date()}")
say(f"  currency LS residual rms (D1): median {cv_d1['resid_rms'].median():.2e}")
say("  no forward-filling; incomplete weeks excluded; execution costs NOT claimed here")
say("")


# ============================================================ signal
def pair_scores(cv, wk_list, i, formation):
    """currency_score = value(latest completed Friday) - value(formation weeks earlier)."""
    if i - formation < 0:
        return None
    now, then = cv.loc[wk_list[i]], cv.loc[wk_list[i - formation]]
    cs = {c: now[f"cv_{c}"] - then[f"cv_{c}"] for c in CCYS}
    return {p: cs[p[:3]] - cs[p[3:6]] for p in pairs}


def pick(scores):
    p = max(scores, key=lambda k: abs(scores[k]))
    return p, (1 if scores[p] > 0 else -1), scores[p]


# monthly schedule over the canonical panel
h1_any = H1[pairs[0]]
months = pd.period_range(canon["trading_date"].min(), canon["trading_date"].max(), freq="M")
sched = []
for m in months:
    fm = first_monday(m.year, m.month)
    tb = rebalance_bars(h1_any, fm, REBAL_DEADLINE_HOURS)
    sched.append({"month": str(m), "first_monday": fm, "entry_utc": tb})
sched = pd.DataFrame(sched)
n_skip_sched = int(sched["entry_utc"].isna().sum())
sched = sched.dropna(subset=["entry_utc"]).reset_index(drop=True)
say(f"MONTHLY SCHEDULE: {len(sched)} rebalances, {n_skip_sched} months skipped "
    "(no H1 bar between Monday 20:00 and Tuesday 20:00 New York)")
say("")

wk_list = list(cv_canon.index)
wk_end_ts = pd.to_datetime(cv_canon["week_end"])


def latest_week_before(ts):
    ok = wk_end_ts[wk_end_ts < pd.Timestamp(ts).tz_localize(None)]
    if not len(ok):
        return None
    return wk_list.index(ok.index[-1])


def canonical_atr(sym, before_ts):
    d = canon[(canon["symbol"] == sym)
              & (canon["trading_date"] <= pd.Timestamp(before_ts).tz_localize(None))]
    if len(d) < ATR_PERIOD + 2:
        return np.nan
    pc = d["close"].shift(1)
    tr = pd.concat([d["high"] - d["low"], (d["high"] - pc).abs(),
                    (d["low"] - pc).abs()], axis=1).max(axis=1)
    return float(tr.rolling(ATR_PERIOD).mean().iloc[-1])


def quote_to_usd(week_i, ccy):
    row = cv_canon.loc[wk_list[week_i]]
    return float(np.exp(row[f"cv_{ccy}"]))


def graph_at(ts):
    """TASK 003A CORRECTION 4.

    Index of the newest completed weekly currency graph at or before `ts`.
    Previously risk, exposure AND realised P&L were all converted with the SIGNAL
    week's graph. For a trade held a month that meant the exit was converted at a
    rate up to five weeks stale, so P&L carried an FX error that had nothing to do
    with the trade. Now risk/exposure use the graph at the ENTRY timestamp and
    realised P&L uses the graph at the EXIT timestamp.
    """
    return latest_week_before(ts)


def precompute(entry_offset_h=0, spread_mult=1.0, formation=FORMATION_WEEKS):
    """Outcome of EVERY (month, pair, direction) so controls reuse one costed engine."""
    out = []
    for k in range(len(sched) - 1):
        t_in = pd.Timestamp(sched.loc[k, "entry_utc"]) + pd.Timedelta(hours=entry_offset_h)
        t_out = pd.Timestamp(sched.loc[k + 1, "entry_utc"]) + pd.Timedelta(hours=entry_offset_h)
        wi = latest_week_before(t_in)
        if wi is None:
            continue
        sc = pair_scores(cv_canon, wk_list, wi, formation)
        if sc is None:
            continue
        best, bdir, bval = pick(sc)
        for p in pairs:
            atr = canonical_atr(p, t_in)
            if not np.isfinite(atr) or atr <= 0:
                continue
            for d_ in (1, -1):
                leg = simulate_leg(p, H1[p], t_in, t_out, d_, atr, spread_mult)
                if leg is None:
                    continue
                # 003A correction 4 + 003B correction 1: the graph is now rebuilt at
                # the EXACT H1 timestamp of the fill, not the newest weekly graph.
                gi = h1_graph(t_in)
                go = h1_graph(leg["t_out"])
                if gi is None or go is None:
                    continue                      # no connected graph -> skip outcome
                q2u_in = float(np.exp(gi[0][p[3:6]]))
                q2u_out = float(np.exp(go[0][p[3:6]]))
                out.append({
                    "k": k, "month": sched.loc[k, "month"], "t_in": t_in, "t_out": leg["t_out"],
                    "pair": p, "dir": d_, "atr": atr,
                    "gross_usd": leg["gross_quote"] * q2u_out,
                    "notional_usd": leg["notional_quote"] * q2u_in,
                    "stop_risk_usd": STOP_ATR_MULT * atr * CONTRACT * LOTS * q2u_in,
                    "days_held": leg["days_held"], "exit_reason": leg["exit_reason"],
                    "entry_px": leg["entry_px"], "exit_px": leg["exit_px"],
                    "stop_px": leg["stop_px"], "entry_bar_stop": leg["entry_bar_stop"],
                    "exit_bar_open_bid": leg["exit_bar_open_bid"],
                    "exit_bar_spread_px": leg["exit_bar_spread_px"],
                    "entry_graph_timestamp": gi[3], "exit_graph_timestamp": go[3],
                    "entry_graph_residual_rms": gi[1], "exit_graph_residual_rms": go[1],
                    "entry_graph_pairs": gi[2], "exit_graph_pairs": go[2],
                    "q2u_entry": q2u_in, "q2u_exit": q2u_out,
                    "is_signal": (p == best and d_ == bdir),
                    "signal_pair": best, "signal_dir": bdir, "signal_score": bval,
                })
    return pd.DataFrame(out)


say("precomputing costed outcomes for every (month, pair, direction)...")
PRE = precompute()
say(f"  {len(PRE)} outcome rows over {PRE['k'].nunique()} rebalances")
say("")

# ============================================================ 5b. assertions
say("=" * 100)
say("DETERMINISTIC ASSERTIONS (task 003A)")
say("=" * 100)

# --- A1: an unstopped exit equals the OPEN of the next rebalance bar
_un = PRE[PRE["exit_reason"] == "rebalance"]
assert len(_un), "no unstopped trades to verify"
_long = _un[_un["dir"] == 1]
_short = _un[_un["dir"] == -1]
assert np.allclose(_long["exit_px"], _long["exit_bar_open_bid"], atol=1e-12), \
    "A1 long: unstopped exit is not the next rebalance bar open (bid)"
assert np.allclose(_short["exit_px"],
                   _short["exit_bar_open_bid"] + _short["exit_bar_spread_px"],
                   atol=1e-12), \
    "A1 short: unstopped exit is not the next rebalance bar open (ask)"
say(f"  [OK] A1 unstopped exit == next rebalance bar OPEN "
    f"({len(_long)} long at bid, {len(_short)} short at ask)")

# --- A2: a stop inside the entry bar is detected (synthetic, data-independent)
_pt = 1e-5
_fake = pd.DataFrame({
    "t_utc": pd.to_datetime(["2022-01-03 20:00", "2022-01-03 21:00",
                             "2022-02-07 20:00"], utc=True),
    "open": [1.10000, 1.09000, 1.08000],
    "high": [1.10050, 1.09050, 1.08050],
    "low":  [1.09000, 1.08500, 1.07900],      # entry bar low breaches a 2-ATR stop
    "close": [1.09500, 1.08800, 1.08000],
    "spread": [10, 10, 10], "point": [_pt] * 3})
_r = simulate_leg("TEST", _fake, _fake["t_utc"].iloc[0], _fake["t_utc"].iloc[-1],
                  1, 0.00200)
assert _r["exit_reason"] == "stop" and _r["entry_bar_stop"] is True \
    and _r["t_out"] == _fake["t_utc"].iloc[0], \
    f"A2 entry-bar stop not detected: {_r['exit_reason']}, {_r['entry_bar_stop']}"
_n_ebs = int(PRE["entry_bar_stop"].sum())
say(f"  [OK] A2 entry-bar stop detected on a synthetic breach; "
    f"{_n_ebs} entry-bar stops present in the real precompute")

# --- A3: conversion graph timestamps EQUAL the trade timestamps (003B)
# Equality, not "earlier than". 003A only proved the graph was not from the future;
# it could still be five days stale. This requires the graph to be built at exactly
# the bar being priced.
_eq_in = (pd.to_datetime(PRE["entry_graph_timestamp"], utc=True)
          == pd.to_datetime(PRE["t_in"], utc=True))
_eq_out = (pd.to_datetime(PRE["exit_graph_timestamp"], utc=True)
           == pd.to_datetime(PRE["t_out"], utc=True))
assert bool(_eq_in.all()), \
    f"A3 entry_graph_timestamp != entry timestamp on {int((~_eq_in).sum())} rows"
assert bool(_eq_out.all()), \
    f"A3 exit_graph_timestamp != exit timestamp on {int((~_eq_out).sum())} rows"
_diff = int((PRE["entry_graph_timestamp"] != PRE["exit_graph_timestamp"]).sum())
say(f"  [OK] A3 entry/exit graph timestamps EQUAL the trade timestamps exactly "
    f"({len(PRE)} rows); {_diff} rows use different graphs at the two ends")
say(f"       graph residual rms: entry median {PRE['entry_graph_residual_rms'].median():.2e}, "
    f"exit median {PRE['exit_graph_residual_rms'].median():.2e}; "
    f"pairs per graph min {int(PRE['entry_graph_pairs'].min())}")

# --- A5: consecutive positions never overlap
_s = PRE[PRE["is_signal"]].sort_values("k")
_ov = 0
for _a, _b in zip(_s.itertuples(), _s.iloc[1:].itertuples()):
    if _b.t_in < _a.t_out:
        _ov += 1
assert _ov == 0, f"A5 {_ov} consecutive signal positions overlap"
say(f"  [OK] A5 consecutive positions never overlap ({len(_s)} signal legs checked)")
say("")


def run_equity(pre, choose, fin_rate=0.0):
    """Walk equity applying the frozen skip rules. Minimum lot, so size never scales."""
    eq, trades, skipped = START_EQUITY, [], []
    for k in sorted(pre["k"].unique()):
        sub = pre[pre["k"] == k]
        sel = choose(k, sub)
        if sel is None:
            continue
        r = sub[(sub["pair"] == sel[0]) & (sub["dir"] == sel[1])]
        if not len(r):
            skipped.append({"k": k, "reason": "no_outcome"})
            continue
        r = r.iloc[0]
        if not np.isfinite(r["stop_risk_usd"]) or not np.isfinite(r["notional_usd"]):
            skipped.append({"k": k, "reason": "conversion_unreliable", "pair": r["pair"]})
            continue
        if r["stop_risk_usd"] > eq * MAX_RISK_PCT / 100.0:
            skipped.append({"k": k, "reason": "risk_gt_1.5pct", "pair": r["pair"],
                            "risk_usd": r["stop_risk_usd"], "equity": eq})
            continue
        if r["notional_usd"] > eq * MAX_EXPOSURE_X:
            skipped.append({"k": k, "reason": "exposure_gt_2x", "pair": r["pair"],
                            "notional": r["notional_usd"], "equity": eq})
            continue
        fin = r["notional_usd"] * fin_rate / 365.0 * r["days_held"]
        net = r["gross_usd"] - fin
        eq += net
        trades.append({**r.to_dict(), "financing_usd": fin, "net_usd": net,
                       "equity_after": eq})
        if eq <= 0:
            break
    return pd.DataFrame(trades), pd.DataFrame(skipped), eq


def choose_signal(k, sub):
    r = sub[sub["is_signal"]]
    return None if not len(r) else (r.iloc[0]["pair"], int(r.iloc[0]["dir"]))


def choose_reverse(k, sub):
    r = sub[sub["is_signal"]]
    return None if not len(r) else (r.iloc[0]["pair"], -int(r.iloc[0]["dir"]))


def stats(tr, eq_end, start_eq=None):
    """TASK 003A CORRECTION 5.

    `start_eq` is the equity the period ACTUALLY began with. Previously every period
    was measured against the global $979 opening balance, so a validation window that
    started at $979 and a holdout window that started at $882 were both divided by
    $979 - understating the holdout return and computing its drawdown against a peak
    the account never had while that period was running.
    """
    base = START_EQUITY if start_eq is None else start_eq
    if not len(tr):
        return {"n": 0, "net": 0.0, "ret_pct": 0.0, "pf": np.nan, "maxdd_pct": np.nan,
                "win_pct": np.nan, "top_trade_share": np.nan, "start_equity": base}
    eq = pd.concat([pd.Series([base]), tr["equity_after"]], ignore_index=True)
    dd = (eq / eq.cummax() - 1.0).min() * 100.0
    wins = tr[tr["net_usd"] > 0]
    gross_win = wins["net_usd"].sum()
    gross_loss = -tr[tr["net_usd"] < 0]["net_usd"].sum()
    net = tr["net_usd"].sum()
    top = (tr["net_usd"].max() / net * 100.0) if net > 0 else np.nan
    return {"n": len(tr), "net": net,
            "ret_pct": (tr["equity_after"].iloc[-1] / base - 1) * 100.0,
            "pf": (gross_win / gross_loss) if gross_loss > 0 else np.inf,
            "maxdd_pct": dd, "win_pct": len(wins) / len(tr) * 100.0,
            "top_trade_share": top, "start_equity": base}


def window(tr, a, b):
    """Slice a period AND return the equity it actually started with (correction 5)."""
    if not len(tr):
        return tr, START_EQUITY
    t = pd.to_datetime(tr["t_in"]).dt.tz_localize(None)
    mask = (t >= a) & (t <= b)
    sl = tr[mask]
    if not len(sl):
        return sl, START_EQUITY
    prior = tr[t < a]
    start_eq = float(prior["equity_after"].iloc[-1]) if len(prior) else START_EQUITY
    return sl, start_eq


# ============================================================ 6. baseline
say("=" * 100)
say("BASELINE V1 - frozen 13-week formation, minimum lot, one position")
say("=" * 100)

BASE = {}
for nm, rate in FIN_STRESS.items():
    tr, sk, eq = run_equity(PRE, choose_signal, rate)
    BASE[nm] = {"trades": tr, "skipped": sk, "equity": eq, "stats": stats(tr, eq)}
    s = BASE[nm]["stats"]
    say(f"  {nm:14s} trades {s['n']:3d}  net ${s['net']:8.2f}  ret {s['ret_pct']:7.2f}%  "
        f"PF {s['pf']:5.2f}  maxDD {s['maxdd_pct']:6.2f}%  win {s['win_pct']:5.1f}%")

tr0 = BASE["spread_only"]["trades"]
sk0 = BASE["spread_only"]["skipped"]

# 2026-08-02 swap snapshot, labelled sensitivity only
snap = univ_ex.set_index("symbol")


def swap_snapshot_cost(tr):
    tot = 0.0
    for _, r in tr.iterrows():
        col = ("annual_cost_long_pct_snapshot" if r["dir"] > 0
               else "annual_cost_short_pct_snapshot")
        pct = snap.loc[r["pair"], col] if r["pair"] in snap.index else 0.0
        pct = 0.0 if not np.isfinite(pct) else float(pct)
        tot += r["notional_usd"] * (pct / 100.0) / 365.0 * r["days_held"]
    return tot


swap_cost = swap_snapshot_cost(tr0) if len(tr0) else 0.0
say(f"  {'swap_snapshot':14s} SENSITIVITY ONLY: 2026-08-02 snapshot would cost "
    f"${swap_cost:.2f} -> net ${(tr0['net_usd'].sum() if len(tr0) else 0)-swap_cost:8.2f}")
say("    (not a historical cost - Exness publishes no historical swap rates)")
say("")

# period splits
say("PERIOD SPLITS (canonical executable panel)")
PER = {}
for nm, a, b in [("validation", VAL_START, VAL_END), ("holdout", HOLD_START, HOLD_END)]:
    for fin in ("spread_only", "fin_3.0pct"):
        t, seq = window(BASE[fin]["trades"], a, b)
        eq = seq + (t["net_usd"].sum() if len(t) else 0.0)
        PER[(nm, fin)] = stats(t, eq, start_eq=seq)
        s = PER[(nm, fin)]
        say(f"  {nm:11s} {fin:12s} trades {s['n']:3d}  net ${s['net']:8.2f}  "
            f"ret {s['ret_pct']:7.2f}%  PF {s['pf']:5.2f}  maxDD {s['maxdd_pct']:6.2f}%  "
            f"(period opened at ${s['start_equity']:.2f})")
say("  (holdout results are reported and NOT used to change anything)")
say("")


# ============================================================ 7. signal-only tests
def signal_only_canonical(formation, a=None, b=None):
    """TASK 003B CORRECTION 2 - canonical signal test priced at the ACTUAL schedule.

    003A still measured the signal from Friday weekly CLOSES, while the strategy it
    represents enters at the Monday 20:00 New York H1 open and exits at the next
    scheduled monthly open. Those are different prices on different days, so the
    signal test and the executable test were not measuring the same thing.

    Now: enter at the real scheduled H1 open and exit at the next real scheduled H1
    open, with bid/ask applied by direction (bars are BID, so a BUY pays the spread
    on entry and a SELL pays it on exit). Still no stop, no financing and no risk
    skipping - that is what makes it signal-only rather than the strategy.

    One observation per calendar month by construction: the schedule has one
    rebalance per month.
    """
    recs = []
    for k in range(len(sched) - 1):
        t_in = pd.Timestamp(sched.loc[k, "entry_utc"])
        t_out = pd.Timestamp(sched.loc[k + 1, "entry_utc"])
        wi = latest_week_before(t_in)
        if wi is None:
            continue
        sc = pair_scores(cv_canon, wk_list, wi, formation)
        if sc is None:
            continue
        p, d_, v = pick(sc)
        rin, rout = H1IDX[p].get(t_in), H1IDX[p].get(t_out)
        if rin is None or rout is None:
            continue
        sp_in = rin[1] * rin[2]
        sp_out = rout[1] * rout[2]
        if d_ > 0:
            entry, exit_ = rin[0] + sp_in, rout[0]          # buy ask, sell bid
        else:
            entry, exit_ = rin[0], rout[0] + sp_out          # sell bid, buy ask
        if not (entry > 0 and exit_ > 0):
            continue
        t = t_in.tz_localize(None) if t_in.tzinfo else t_in
        if a is not None and (t < a or t > b):
            continue
        recs.append({"month": sched.loc[k, "month"], "t": t, "pair": p, "dir": d_,
                     "score": v, "logret": d_ * np.log(exit_ / entry)})
    return pd.DataFrame(recs)


def signal_only_d1(formation, a=None, b=None):
    """Long-D1 panel: APPROXIMATE signal-only analysis.

    D1 has no intraday resolution, so the scheduled 20:00 New York open cannot be
    reproduced. The nearest available broker D1 close at or after each scheduled
    first Monday is used instead, and no spread is applied - this panel is not
    entitled to claim execution costs. Labelled approximate everywhere it appears.
    """
    px = d1p.pivot_table(index="eff", columns="symbol", values="close")
    dates = px.index
    ends = pd.to_datetime(cv_d1["week_end"])
    wl = list(cv_d1.index)
    recs = []
    for m in pd.period_range(dates.min(), dates.max(), freq="M"):
        fm = pd.Timestamp(first_monday(m.year, m.month))
        nxt = dates[dates >= fm]
        if not len(nxt):
            continue
        d_in = nxt[0]
        ok = ends[ends < fm]
        if not len(ok):
            continue
        i = wl.index(ok.index[-1])
        if i < formation:
            continue
        sc = pair_scores(cv_d1, wl, i, formation)
        if sc is None:
            continue
        p, d_, v = pick(sc)
        nm = pd.Timestamp(first_monday(*( (m + 1).year, (m + 1).month )))
        nxt2 = dates[dates >= nm]
        if not len(nxt2):
            continue
        d_out = nxt2[0]
        c0, c1 = px.loc[d_in, p], px.loc[d_out, p]
        if not (np.isfinite(c0) and np.isfinite(c1) and c0 > 0 and c1 > 0):
            continue
        if a is not None and (d_in < a or d_in > b):
            continue
        recs.append({"month": str(m), "t": d_in, "pair": p, "dir": d_, "score": v,
                     "logret": d_ * np.log(c1 / c0)})
    return pd.DataFrame(recs)


say("SIGNAL-ONLY TESTS (no stop, no financing; canonical priced at the real schedule)")
SIG = []
PANELS = [("canonical", cv_canon, wk_list, wc),
          ("long_D1", cv_d1, list(cv_d1.index), wc_d1)]
for panel, cv, wl, cl in PANELS:
    for f in DIAG_FORMATIONS:
        for pnm, a, b in [("development", pd.Timestamp("1900-01-01"), DEV_END),
                          ("validation", VAL_START, VAL_END),
                          ("holdout", HOLD_START, HOLD_END)]:
            r = (signal_only_canonical(f, a, b) if panel == "canonical"
                 else signal_only_d1(f, a, b))
            tot = r["logret"].sum() if len(r) else np.nan
            SIG.append({"panel": panel, "formation_weeks": f, "period": pnm,
                        "n_months": len(r), "sum_logret": tot,
                        "mean_logret": r["logret"].mean() if len(r) else np.nan,
                        "sign": (np.sign(tot) if np.isfinite(tot) else np.nan),
                        "is_frozen_baseline": f == FORMATION_WEEKS,
                        "pricing": ("scheduled_H1_open_with_spread" if panel == "canonical"
                                    else "APPROXIMATE_broker_D1_close_no_spread")})
SIGDF = pd.DataFrame(SIG)

# --- A4: signal-only output has at most ONE observation per calendar month
for _f in DIAG_FORMATIONS:
    for _pn, _fn in (("canonical", signal_only_canonical), ("long_D1", signal_only_d1)):
        _r = _fn(_f)
        if not len(_r):
            continue
        _dup = int(_r["month"].duplicated().sum())
        assert _dup == 0, f"A4 {_pn} f={_f}: {_dup} duplicate calendar months"
        assert _r["month"].is_monotonic_increasing, f"A4 {_pn} f={_f}: months unordered"
say("  [OK] A4 signal-only output has at most one observation per calendar month "
    "(checked on every panel x formation)")
say("")

say(SIGDF[SIGDF["formation_weeks"] == FORMATION_WEEKS][
    ["panel", "period", "n_months", "sum_logret", "sign"]].to_string(index=False))
say("")
say("  formation diagnostics (4 / 13 / 26) - 4 and 26 CANNOT replace the frozen 13:")
say(SIGDF.pivot_table(index=["panel", "period"], columns="formation_weeks",
                      values="sum_logret").to_string())
say("")

ov = signal_only_canonical(FORMATION_WEEKS).merge(
    signal_only_d1(FORMATION_WEEKS), on="month", suffixes=("_canon", "_d1"))
agree_pair = float((ov["pair_canon"] == ov["pair_d1"]).mean() * 100) if len(ov) else np.nan
agree_dir = float((ov["dir_canon"] == ov["dir_d1"]).mean() * 100) if len(ov) else np.nan
say(f"  panel overlap {len(ov)} MONTHS: same pair {agree_pair:.1f}%, "
    f"same direction {agree_dir:.1f}%")
say("")

# ============================================================ 8. controls
say("=" * 100)
say("REQUIRED CONTROLS")
say("=" * 100)
CTRL = []
base_net = BASE["spread_only"]["stats"]["net"]

def index_pre(pre):
    """(k -> {(pair,dir): (gross, notional, stop_risk, days)}) for the fast path.

    The permutation loop is 10,000 x 55 equity walks. Doing that with pandas
    filtering inside the loop is ~100x slower than it needs to be and was the only
    reason this could not finish. The arithmetic below is identical to run_equity();
    an assertion checks the two agree on the baseline before the loop is trusted.
    """
    idx = {}
    for r in pre.itertuples():
        idx.setdefault(r.k, {})[(r.pair, r.dir)] = (
            r.gross_usd, r.notional_usd, r.stop_risk_usd, r.days_held)
    return idx


def run_equity_fast(idx, choose_kv, fin_rate=0.0):
    eq, net_tot, n = START_EQUITY, 0.0, 0
    for k in sorted(idx):
        sel = choose_kv(k)
        if sel is None:
            continue
        v = idx[k].get(sel)
        if v is None:
            continue
        gross, notional, risk, days = v
        if not (np.isfinite(risk) and np.isfinite(notional)):
            continue
        if risk > eq * MAX_RISK_PCT / 100.0:
            continue
        if notional > eq * MAX_EXPOSURE_X:
            continue
        net = gross - notional * fin_rate / 365.0 * days
        eq += net
        net_tot += net
        n += 1
        if eq <= 0:
            break
    return net_tot, eq, n


IDX = index_pre(PRE)
sig_kv = {int(r.k): (r.signal_pair, int(r.signal_dir))
          for r in PRE[PRE["is_signal"]].itertuples()}
_chk_net, _chk_eq, _chk_n = run_equity_fast(IDX, lambda k: sig_kv.get(k), 0.0)
assert abs(_chk_net - base_net) < 1e-6 and _chk_n == BASE["spread_only"]["stats"]["n"], (
    f"fast path disagrees with run_equity: {_chk_net} vs {base_net}, "
    f"{_chk_n} vs {BASE['spread_only']['stats']['n']}")
say(f"  (fast permutation engine verified against the costed engine: "
    f"net ${_chk_net:.2f}, {_chk_n} trades - identical)")

rng = np.random.default_rng(PERM_SEED)
ks = sorted(IDX.keys())
opts = {k: list(IDX[k].keys()) for k in ks}
perm_nets = np.empty(N_PERM)
for j in range(N_PERM):
    pm = {k: opts[k][rng.integers(len(opts[k]))] for k in ks}
    perm_nets[j] = run_equity_fast(IDX, lambda k, _pm=pm: _pm.get(k), 0.0)[0]
p_val = float((perm_nets >= base_net).mean())
med_perm = float(np.median(perm_nets))
say(f"  1. randomisation  {N_PERM} perms: baseline ${base_net:.2f} vs median "
    f"${med_perm:.2f}  one-sided p = {p_val:.4f}")
CTRL.append({"control": "randomisation", "baseline_net": base_net,
             "median_random_net": med_perm, "p_value_one_sided": p_val,
             "n_perm": N_PERM, "beats_median": bool(base_net > med_perm)})

tr_r, _, eq_r = run_equity(PRE, choose_reverse, 0.0)
s_r = stats(tr_r, eq_r)
say(f"  2. reverse (buy weak / sell strong): net ${s_r['net']:.2f} vs baseline ${base_net:.2f}")
CTRL.append({"control": "reverse", "net": s_r["net"],
             "worse_than_baseline": bool(s_r["net"] < base_net)})

for nm, hrs, lbl in [("delay_24h", 24, "3"), ("delay_1week", 168, "4")]:
    pre_d = precompute(entry_offset_h=hrs)
    t_d, _, e_d = run_equity(pre_d, choose_signal, 0.0)
    s_d = stats(t_d, e_d)
    say(f"  {lbl}. {nm:11s} net ${s_d['net']:8.2f}  ret {s_d['ret_pct']:7.2f}%  "
        f"trades {s_d['n']}")
    CTRL.append({"control": nm, "net": s_d["net"], "ret_pct": s_d["ret_pct"], "n": s_d["n"]})

pre_2 = precompute(spread_mult=2.0)
t_2, _, e_2 = run_equity(pre_2, choose_signal, 0.0)
s_2 = stats(t_2, e_2)
say(f"  5. doubled spread: net ${s_2['net']:8.2f}  ret {s_2['ret_pct']:7.2f}%  "
    f"trades {s_2['n']}")
CTRL.append({"control": "double_spread", "net": s_2["net"], "ret_pct": s_2["ret_pct"],
             "n": s_2["n"], "still_positive": bool(s_2["net"] > 0)})

for f in DIAG_FORMATIONS:
    r = SIGDF[(SIGDF["panel"] == "canonical") & (SIGDF["formation_weeks"] == f)]
    CTRL.append({"control": f"formation_{f}w_signal_only",
                 "sum_logret_validation": float(
                     r[r["period"] == "validation"]["sum_logret"].iloc[0]),
                 "sum_logret_holdout": float(
                     r[r["period"] == "holdout"]["sum_logret"].iloc[0]),
                 "diagnostic_only": f != FORMATION_WEEKS})
say("")

# ============================================================ 9. pass conditions
say("=" * 100)
say("PASS CONDITIONS")
say("=" * 100)
sv = PER[("validation", "spread_only")]
sh = PER[("holdout", "spread_only")]
comb3 = BASE["fin_3.0pct"]["stats"]
allc = BASE["spread_only"]["stats"]
sig_c = SIGDF[(SIGDF.panel == "canonical") & (SIGDF.formation_weeks == FORMATION_WEEKS)
              & (SIGDF.period.isin(["validation", "holdout"]))]["sum_logret"].sum()
sig_d = SIGDF[(SIGDF.panel == "long_D1") & (SIGDF.formation_weeks == FORMATION_WEEKS)
              & (SIGDF.period.isin(["validation", "holdout"]))]["sum_logret"].sum()

COND = [
    ("1  canonical return positive in validation", sv["ret_pct"] > 0, f"{sv['ret_pct']:.2f}%"),
    ("2  canonical return positive in holdout", sh["ret_pct"] > 0, f"{sh['ret_pct']:.2f}%"),
    ("3  positive under 3.0% financing stress", comb3["ret_pct"] > 0, f"{comb3['ret_pct']:.2f}%"),
    ("4  doubled-spread result positive", s_2["net"] > 0, f"${s_2['net']:.2f}"),
    ("5  long-D1 and canonical signal same sign",
     bool(np.isfinite(sig_c) and np.isfinite(sig_d) and np.sign(sig_c) == np.sign(sig_d)),
     f"canon {sig_c:+.4f} / D1 {sig_d:+.4f}"),
    ("6  baseline beats median randomised", base_net > med_perm,
     f"${base_net:.2f} vs ${med_perm:.2f}"),
    ("7  randomisation p <= 0.10", p_val <= 0.10, f"p={p_val:.4f}"),
    ("8  reverse performs worse than baseline", s_r["net"] < base_net,
     f"${s_r['net']:.2f} vs ${base_net:.2f}"),
    ("9  at least 40 completed trades", allc["n"] >= 40, f"{allc['n']}"),
    ("10 max drawdown <= 20%", abs(allc["maxdd_pct"]) <= 20.0, f"{allc['maxdd_pct']:.2f}%"),
    ("11 profit factor > 1.10", allc["pf"] > 1.10, f"{allc['pf']:.3f}"),
    # CORRECTION 6: with net profit negative there is no profit to concentrate, so
    # this condition cannot be evaluated. It is marked NOT APPLICABLE and is NOT
    # counted as a pass - previously it scored a free PASS in a losing run.
    ("12 no trade > 25% of net profit",
     None if allc["net"] <= 0 else bool(allc["top_trade_share"] <= 25.0),
     "NOT APPLICABLE (net profit <= 0)" if allc["net"] <= 0
     else f"{allc['top_trade_share']:.1f}%"),
    ("13 no margin call / account failure", BASE["spread_only"]["equity"] > 0,
     f"final equity ${BASE['spread_only']['equity']:.2f}"),
]
n_pass = n_na = 0
for name, okc, val in COND:
    tag = "N/A " if okc is None else ("PASS" if okc else "FAIL")
    say(f"  [{tag}] {name:46s} {val}")
    if okc is None:
        n_na += 1
    else:
        n_pass += bool(okc)
VERDICT = "PASS CANDIDATE" if (n_pass == len(COND) and n_na == 0) else "FAILED"
say("")
say(f"  conditions passed: {n_pass}/{len(COND)}"
    + (f"   ({n_na} not applicable, not counted as passes)" if n_na else ""))
say(f"  >>> V1 VERDICT: {VERDICT}")
if VERDICT == "FAILED":
    say("  Per the specification V1 is reported FAILED and is NOT optimised or repaired.")
say("")

# ============================================================ 10. outputs
say("SKIPPED TRADES")
if len(sk0):
    say(sk0["reason"].value_counts().to_string())
else:
    say("  none")
say("")

if len(tr0):
    tr0.to_csv(OUT_TRADES, index=False)
    mth = tr0.copy()
    mth["month"] = mth["month"].astype(str)
    mth.groupby("month").agg(trades=("net_usd", "size"), net_usd=("net_usd", "sum"),
                             equity_after=("equity_after", "last")).to_csv(OUT_MONTHLY)
else:
    pd.DataFrame().to_csv(OUT_TRADES, index=False)
    pd.DataFrame().to_csv(OUT_MONTHLY, index=False)
SIGDF.to_csv(OUT_SIGNAL, index=False)
pd.DataFrame(CTRL).to_csv(OUT_CONTROLS, index=False)

say(f"trades   -> {OUT_TRADES}")
say(f"monthly  -> {OUT_MONTHLY}")
say(f"signal   -> {OUT_SIGNAL}")
say(f"controls -> {OUT_CONTROLS}")
with open(OUT_REPORT, "w", encoding="utf-8") as f:
    f.write("\n".join(LOG) + "\n")
print(f"report   -> {OUT_REPORT}")
