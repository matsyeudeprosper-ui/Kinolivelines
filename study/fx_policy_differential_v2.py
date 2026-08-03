"""TASK 005 - FX POLICY-RATE DIFFERENTIAL V2  (preregistered, frozen)

FX_POLICY_DIFFERENTIAL_V2_20260802

A directional FX strategy on official BIS policy-rate differences, specified entirely by
the strategy lead. Nothing here is tuned, reinterpreted or substituted by me. If a hard
condition fails, V2 is reported FAILED and left alone.

No live deployment is recommended and no V3 is proposed. The live bot is not touched and
no order is placed or changed.

================================================================================
WHAT THIS STRATEGY MAY NOT CLAIM
================================================================================
It may NOT claim that Exness pays the theoretical interest differential. Task 004A
measured the opposite on the current snapshot: for 0 of the 19 executable pairs does the
theoretically positive side receive positive carry - the broker zeroes that side and
charges the other.

So the PRINCIPAL test is scenario 1, ZERO-CREDIT EXECUTION: historical spreads only, no
carry credit of any kind. The policy differential is used purely as a DIRECTIONAL signal.
Scenario 5 computes what the differential would have paid if it were actually credited;
it is diagnostic, non-executable, and cannot satisfy any pass condition.

================================================================================
CERTIFIED MACHINERY INHERITED FROM TASK 003B
================================================================================
* MT5 bars are BID (chart_mode == 0, verified). BUY enters at ask = bar + that bar's
  recorded spread and exits at bid; SELL enters at bid and exits at ask.
* A BUY stop triggers on the bar low, a SELL stop on bar high + spread.
* Stop is live from the ENTRY bar itself.
* An unstopped trade exits at the OPEN of the next scheduled rebalance bar, and that bar
  is never scanned for the old position's stop.
* Gap fills take the WORSE of the stop price or the first tradeable price.
* Currency conversion is refitted at the EXACT H1 timestamp of every fill from midpoint
  opens (bid + half that bar's spread), USD pinned to zero, rank-checked for connectivity.

================================================================================
POLICY DATA - TASK 004A RULES ARE NOT ALTERED
================================================================================
Rates come from the 004A snapshots, which already encode the information cutoff (the
completed Friday before each first Monday), availability and finiteness. An unavailable
rate is NEVER imputed - JPY simply has no policy rate between 2013-04-04 and 2016-09-20,
so no JPY pair can be selected in those months.

================================================================================
FROZEN PARAMETERS - do not edit to chase a result
================================================================================
"""
import os
import datetime as dt

import numpy as np
import pandas as pd

# ----------------------------------------------------------------- frozen spec
START_EQUITY = 979.00
STOP_ATR_MULT = 1.5               # V2 stop, NOT V1's 2.0
ATR_PERIOD = 20
MAX_RISK_PCT = 1.50               # of CURRENT equity
MAX_EXPOSURE_X = 2.00             # of CURRENT equity
LOTS = 0.01
CONTRACT = 100_000.0

REBAL_HOUR_NY = 20
REBAL_DEADLINE_HOURS = 24         # no later than Tuesday 20:00 New York

N_PERM = 10_000
PERM_SEED = 20260802

UNIV_MAX_RISK_PCT = 1.50
UNIV_MAX_EXPO_X = 2.00
UNIV_MAX_SPREAD_PCT_ATR = 6.00

DEV_END = pd.Timestamp("2021-07-31")
VAL_START, VAL_END = pd.Timestamp("2021-08-01"), pd.Timestamp("2023-12-31")
HOLD_START, HOLD_END = pd.Timestamp("2024-01-01"), pd.Timestamp("2026-07-31")

FIN_STRESS = {"baseline_zero_credit": 0.0, "fin_1.5pct": 0.015, "fin_3.0pct": 0.030}

NY = "America/New_York"
HERE = os.path.dirname(os.path.abspath(__file__))
DATA, RAW = os.path.join(HERE, "data"), os.path.join(HERE, "data", "raw_h1")
RES = os.path.join(HERE, "results")

UNIV = os.path.join(RES, "fx_universe_audit.csv")
CENSUS = os.path.join(RES, "exness_feasibility_census.csv")
DAILY = os.path.join(DATA, "fx_daily_canonical.csv")
SNAPS = os.path.join(DATA, "fx_policy_rate_rebalance_snapshots.csv")
LONGPOL = os.path.join(DATA, "fx_policy_rates_long.csv")

OUT_TRADES = os.path.join(RES, "fx_policy_differential_v2_trades.csv")
OUT_MONTHLY = os.path.join(RES, "fx_policy_differential_v2_monthly.csv")
OUT_SIGNAL = os.path.join(RES, "fx_policy_differential_v2_signal_tests.csv")
OUT_CONTROLS = os.path.join(RES, "fx_policy_differential_v2_controls.csv")
OUT_COND = os.path.join(RES, "fx_policy_differential_v2_pass_conditions.csv")
OUT_REPORT = os.path.join(RES, "fx_policy_differential_v2_report.txt")

LOG = []


def say(s=""):
    print(s, flush=True)
    LOG.append(s)


# ============================================================ universe
u = pd.read_csv(UNIV)
_sel = u[u["selected"] == True]                                        # noqa: E712
_ex = _sel[(_sel["revised_risk_pct_of_979"] <= UNIV_MAX_RISK_PCT)
           & (_sel["census_exposure_x"] <= UNIV_MAX_EXPO_X)
           & (_sel["census_spread_pct_atr"] <= UNIV_MAX_SPREAD_PCT_ATR)
           & (_sel["both_sides"] == True)]                              # noqa: E712
PAIRS = sorted(_ex["symbol"].tolist())
CCYS = sorted({p[:3] for p in PAIRS} | {p[3:6] for p in PAIRS})
SNAPSHOT_SWAP = _ex.set_index("symbol")

say("=" * 100)
say("TASK 005 - FX POLICY-RATE DIFFERENTIAL V2")
say("=" * 100)
say(f"generated : {dt.datetime.now():%Y-%m-%d %H:%M:%S}")
say("")
say("FROZEN RULES")
say(f"  signal          : rate_differential = policy_rate(BASE) - policy_rate(QUOTE)")
say(f"  direction       : >0 BUY, <0 SELL, ==0 not a candidate")
say(f"  selection       : largest |differential|, ties alphabetical by symbol, no threshold")
say(f"  schedule        : first Monday 20:00 New York, first H1 bar at/after, "
    f"deadline Tuesday 20:00")
say(f"  info cutoff     : preceding completed Friday; source_observation_date <= cutoff")
say(f"  stop            : {STOP_ATR_MULT} x canonical NY-session ATR({ATR_PERIOD}), "
    f"live from the entry bar, never trailed, no take profit")
say(f"  ATR data        : only canonical sessions completed on or before the Friday cutoff")
say(f"  size            : broker minimum lot {LOTS} only, never increased to reach a target")
say(f"  limits          : stop risk <= {MAX_RISK_PCT}% of current equity, "
    f"exposure <= {MAX_EXPOSURE_X}x, skip rather than violate")
say(f"  equity          : ${START_EQUITY:,.2f}")
say("")
say(f"EXECUTABLE UNIVERSE ({len(PAIRS)} pairs):")
for i in range(0, len(PAIRS), 6):
    say("   " + "  ".join(PAIRS[i:i + 6]))
say(f"currencies ({len(CCYS)}): {', '.join(CCYS)}")
say("")

# ============================================================ data
census = pd.read_csv(CENSUS).set_index("symbol")
canon = pd.read_csv(DAILY)
canon["trading_date"] = pd.to_datetime(canon["trading_date"])
canon = canon[canon["symbol"].isin(PAIRS)].reset_index(drop=True)

H1, H1IDX = {}, {}
for s in PAIRS:
    d = pd.read_csv(os.path.join(RAW, f"h1_{s}.csv"))
    d["t_utc"] = pd.to_datetime(d["time"], unit="s", utc=True)
    d = d.drop_duplicates(subset="time").sort_values("t_utc").reset_index(drop=True)
    d["point"] = float(census.loc[s, "point"])
    H1[s] = d
    H1IDX[s] = dict(zip(d["t_utc"], zip(d["open"], d["spread"], d["point"])))

snap = pd.read_csv(SNAPS)
snap["first_monday"] = pd.to_datetime(snap["first_monday"])
snap["information_cutoff_friday"] = pd.to_datetime(snap["information_cutoff_friday"])
snap["source_observation_date"] = pd.to_datetime(snap["source_observation_date"],
                                                 errors="coerce")
say(f"policy snapshots loaded: {len(snap):,} rows, "
    f"{snap['rebalance_month'].nunique()} months; "
    f"available {int(snap['is_policy_rate_available'].sum()):,}, "
    f"unavailable {int((~snap['is_policy_rate_available']).sum()):,}")
say("")

_GC = {}


def h1_graph(ts):
    """Exact-timestamp currency graph from H1 midpoint opens. USD pinned to zero."""
    key = pd.Timestamp(ts)
    if key in _GC:
        return _GC[key]
    free = [c for c in CCYS if c != "USD"]
    idx = {c: i for i, c in enumerate(free)}
    A, b = [], []
    for p in PAIRS:
        rec = H1IDX[p].get(key)
        if rec is None:
            continue
        mid = rec[0] + 0.5 * rec[1] * rec[2]
        if mid <= 0:
            continue
        row = np.zeros(len(free))
        if p[:3] in idx:
            row[idx[p[:3]]] += 1.0
        if p[3:6] in idx:
            row[idx[p[3:6]]] -= 1.0
        A.append(row)
        b.append(np.log(mid))
    out = None
    if len(A) >= len(free):
        A, b = np.array(A), np.array(b)
        if np.linalg.matrix_rank(A) >= len(free):
            sol, *_ = np.linalg.lstsq(A, b, rcond=None)
            resid = float(np.sqrt(np.mean((A @ sol - b) ** 2)))
            vals = {"USD": 0.0}
            vals.update({c: float(sol[idx[c]]) for c in free})
            out = (vals, resid, len(A), key)
    _GC[key] = out
    return out


def first_monday(y, m):
    d = dt.date(y, m, 1)
    while d.weekday() != 0:
        d += dt.timedelta(days=1)
    return pd.Timestamp(d)


def canonical_atr(sym, cutoff_friday):
    """ATR20 from canonical sessions completed ON OR BEFORE the Friday cutoff."""
    d = canon[(canon["symbol"] == sym) & (canon["trading_date"] <= cutoff_friday)]
    if len(d) < ATR_PERIOD + 2:
        return np.nan, None
    pc = d["close"].shift(1)
    tr = pd.concat([d["high"] - d["low"], (d["high"] - pc).abs(),
                    (d["low"] - pc).abs()], axis=1).max(axis=1)
    return float(tr.rolling(ATR_PERIOD).mean().iloc[-1]), d["trading_date"].iloc[-1]


def simulate_leg(h1, t_entry, t_exit, direction, atr, spread_mult=1.0):
    """Certified 003B leg: entry-bar stop live, unstopped exit at next rebalance OPEN."""
    hold = h1[(h1["t_utc"] >= t_entry) & (h1["t_utc"] < t_exit)]
    xb = h1[h1["t_utc"] == t_exit]
    if not len(hold) or not len(xb):
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

    hit, exit_px, t_out, reason, ebs = False, None, None, "rebalance", False
    for n_, (_, r) in enumerate(hold.iterrows()):
        sp = r["spread"] * point * spread_mult
        if direction > 0 and r["low"] <= stop:
            exit_px = min(stop, entry if n_ == 0 else r["open"])
            hit, t_out, reason, ebs = True, r["t_utc"], "stop", n_ == 0
            break
        if direction < 0 and r["high"] + sp >= stop:
            exit_px = max(stop, entry if n_ == 0 else r["open"] + sp)
            hit, t_out, reason, ebs = True, r["t_utc"], "stop", n_ == 0
            break
    if not hit:
        x = xb.iloc[0]
        exit_px = x["open"] if direction > 0 else x["open"] + x["spread"] * point * spread_mult
        t_out = x["t_utc"]
    return {"entry_px": entry, "exit_px": exit_px, "stop_px": stop, "t_out": t_out,
            "exit_reason": reason, "entry_bar_stop": ebs,
            "gross_quote": (exit_px - entry) * direction * CONTRACT * LOTS,
            "days_held": max((t_out - t_entry).total_seconds() / 86400.0, 0.0),
            "notional_quote": abs(entry) * CONTRACT * LOTS,
            "exit_bar_open_bid": float(xb.iloc[0]["open"]),
            "exit_bar_spread_px": float(xb.iloc[0]["spread"] * point * spread_mult)}


# ============================================================ schedule + eligibility
h1_any = H1[PAIRS[0]]
months = pd.period_range(canon["trading_date"].min(), canon["trading_date"].max(), freq="M")
sched, sched_skips = [], []
for m in months:
    fm = first_monday(m.year, m.month)
    t0 = fm.tz_localize(NY) + pd.Timedelta(hours=REBAL_HOUR_NY)
    t1 = t0 + pd.Timedelta(hours=REBAL_DEADLINE_HOURS)
    cand = h1_any[(h1_any["t_utc"] >= t0.tz_convert("UTC"))
                  & (h1_any["t_utc"] <= t1.tz_convert("UTC"))]
    if not len(cand):
        sched_skips.append({"month": str(m), "reason": "no H1 bar in the entry window"})
        continue
    sched.append({"month": str(m), "first_monday": fm,
                  "cutoff_friday": fm - pd.Timedelta(days=3),
                  "entry_utc": cand.iloc[0]["t_utc"]})
sched = pd.DataFrame(sched).reset_index(drop=True)
say(f"SCHEDULE: {len(sched)} rebalances, {len(sched_skips)} months without an entry bar")
say("")


def precompute(entry_offset_h=0, spread_mult=1.0):
    """Every eligible (month, pair, direction) outcome, plus the baseline selection."""
    out, skips = [], []
    for k in range(len(sched) - 1):
        row = sched.loc[k]
        cutoff = row["cutoff_friday"]
        t_in = pd.Timestamp(row["entry_utc"]) + pd.Timedelta(hours=entry_offset_h)
        t_out_sched = pd.Timestamp(sched.loc[k + 1, "entry_utc"]) + \
            pd.Timedelta(hours=entry_offset_h)

        pol = snap[snap["rebalance_month"] == row["month"]]
        rates, sdate, sage, sreg = {}, {}, {}, {}
        for _, pr in pol.iterrows():
            if not bool(pr["is_policy_rate_available"]):
                continue
            v = pr["policy_rate_pct"]
            if not np.isfinite(v):
                continue
            if pd.notna(pr["source_observation_date"]) and \
                    pr["source_observation_date"] > cutoff:
                continue                       # never use post-cutoff information
            rates[pr["currency"]] = float(v)
            sdate[pr["currency"]] = pr["source_observation_date"]
            sage[pr["currency"]] = pr["value_age_days"]
            sreg[pr["currency"]] = pr["policy_regime"]

        gi = h1_graph(t_in)
        cands = []
        for p in PAIRS:
            b_, q_ = p[:3], p[3:6]
            if b_ not in rates or q_ not in rates:
                skips.append({"month": row["month"], "pair": p,
                              "reason": "policy_rate_unavailable"})
                continue
            atr, atr_last = canonical_atr(p, cutoff)
            if not np.isfinite(atr) or atr <= 0:
                skips.append({"month": row["month"], "pair": p, "reason": "no_ATR"})
                continue
            if H1IDX[p].get(t_in) is None:
                skips.append({"month": row["month"], "pair": p, "reason": "no_entry_bar"})
                continue
            if gi is None:
                skips.append({"month": row["month"], "pair": p,
                              "reason": "conversion_graph_unreliable"})
                continue
            diff = rates[b_] - rates[q_]
            if diff == 0:
                skips.append({"month": row["month"], "pair": p,
                              "reason": "zero_differential_not_a_candidate"})
                continue
            cands.append((p, diff, atr, atr_last))

        if not cands:
            continue
        # largest |differential|, ties resolved alphabetically by symbol
        best = sorted(cands, key=lambda c: (-abs(c[1]), c[0]))[0]
        bpair, bdiff = best[0], best[1]
        bdir = 1 if bdiff > 0 else -1

        for p, diff, atr, atr_last in cands:
            pdir = 1 if diff > 0 else -1
            for d_ in (1, -1):
                leg = simulate_leg(H1[p], t_in, t_out_sched, d_, atr, spread_mult)
                if leg is None:
                    continue
                go = h1_graph(leg["t_out"])
                if go is None:
                    continue
                q_ = p[3:6]
                q2u_in = float(np.exp(gi[0][q_]))
                q2u_out = float(np.exp(go[0][q_]))
                notional = leg["notional_quote"] * q2u_in
                out.append({
                    "k": k, "month": row["month"], "first_monday": row["first_monday"],
                    "cutoff_friday": cutoff, "t_in": t_in, "t_out": leg["t_out"],
                    "pair": p, "dir": d_, "policy_dir": pdir,
                    "rate_base_pct": rates[p[:3]], "rate_quote_pct": rates[q_],
                    "rate_differential": diff, "abs_differential": abs(diff),
                    "src_date_base": sdate[p[:3]], "src_date_quote": sdate[q_],
                    "age_base_days": sage[p[:3]], "age_quote_days": sage[q_],
                    "regime_base": sreg[p[:3]], "regime_quote": sreg[q_],
                    "atr": atr, "atr_last_session": atr_last,
                    "gross_usd": leg["gross_quote"] * q2u_out,
                    "notional_usd": notional,
                    "stop_risk_usd": STOP_ATR_MULT * atr * CONTRACT * LOTS * q2u_in,
                    "days_held": leg["days_held"], "exit_reason": leg["exit_reason"],
                    "entry_bar_stop": leg["entry_bar_stop"],
                    "entry_px": leg["entry_px"], "exit_px": leg["exit_px"],
                    "stop_px": leg["stop_px"],
                    "exit_bar_open_bid": leg["exit_bar_open_bid"],
                    "exit_bar_spread_px": leg["exit_bar_spread_px"],
                    "entry_graph_timestamp": gi[3], "exit_graph_timestamp": go[3],
                    "entry_graph_residual_rms": gi[1], "exit_graph_residual_rms": go[1],
                    "q2u_entry": q2u_in, "q2u_exit": q2u_out,
                    # theoretical policy credit, diagnostic only (scenario 5)
                    "policy_credit_usd": notional * (d_ * diff) / 100.0 / 365.0
                                         * leg["days_held"],
                    "swap_snapshot_usd": -notional * (
                        float(SNAPSHOT_SWAP.loc[p, "annual_cost_long_pct_snapshot"])
                        if d_ > 0 else
                        float(SNAPSHOT_SWAP.loc[p, "annual_cost_short_pct_snapshot"])
                    ) / 100.0 / 365.0 * leg["days_held"],
                    "is_signal": (p == bpair and d_ == bdir),
                    "signal_pair": bpair, "signal_dir": bdir, "signal_diff": bdiff,
                })
    return pd.DataFrame(out), pd.DataFrame(skips)


say("precomputing eligible outcomes...")
PRE, SKIPS = precompute()
say(f"  {len(PRE):,} outcome rows over {PRE['k'].nunique()} rebalances")
say(f"  eligibility skips: {len(SKIPS):,}")
if len(SKIPS):
    for r_, g in SKIPS.groupby("reason"):
        say(f"     {r_:38s} {len(g):5d}")
say("")

# ============================================================ assertions
say("=" * 100)
say("DETERMINISTIC ASSERTIONS")
say("=" * 100)
ASSERTS = []


def check(name, cond, detail=""):
    ASSERTS.append({"assertion": name, "passed": bool(cond), "detail": detail})
    say(f"  [{'OK ' if cond else 'FAIL'}] {name}  {detail}")
    assert cond, f"ASSERTION FAILED: {name} {detail}"


SIG = PRE[PRE["is_signal"]].copy()

# 1 every signal uses policy observations dated no later than its Friday cutoff
_b = pd.to_datetime(SIG["src_date_base"]); _q = pd.to_datetime(SIG["src_date_quote"])
_c = pd.to_datetime(SIG["cutoff_friday"])
check("policy observation dates <= Friday cutoff", bool((_b <= _c).all() and (_q <= _c).all()),
      f"max base age {SIG['age_base_days'].max():.0f}d, quote {SIG['age_quote_days'].max():.0f}d")

# 2 every selected currency available and finite
check("selected rates finite",
      bool(np.isfinite(SIG["rate_base_pct"]).all() and np.isfinite(SIG["rate_quote_pct"]).all()),
      f"{len(SIG)} selections")

# 3 JPY pairs cannot be selected while JPY is unavailable
_jpy_un = set(snap[(snap["currency"] == "JPY")
                   & (~snap["is_policy_rate_available"])]["rebalance_month"])
_bad_jpy = SIG[(SIG["pair"].str.contains("JPY")) & (SIG["month"].isin(_jpy_un))]
check("no JPY selection while JPY unavailable", len(_bad_jpy) == 0,
      f"{len(_jpy_un)} JPY-unavailable months in the snapshot table")

# 4 at most one baseline selection per calendar month
check("one baseline selection per month", int(SIG["month"].duplicated().sum()) == 0,
      f"{SIG['month'].nunique()} months")

# 5 ATR uses no data after the cutoff
check("ATR last session <= Friday cutoff",
      bool((pd.to_datetime(SIG["atr_last_session"]) <= _c).all()),
      f"ATR period {ATR_PERIOD} on canonical sessions")

# 6 conversion timestamps equal their fills
check("entry graph timestamp == entry fill",
      bool((pd.to_datetime(PRE["entry_graph_timestamp"], utc=True)
            == pd.to_datetime(PRE["t_in"], utc=True)).all()), f"{len(PRE)} rows")
check("exit graph timestamp == exit fill",
      bool((pd.to_datetime(PRE["exit_graph_timestamp"], utc=True)
            == pd.to_datetime(PRE["t_out"], utc=True)).all()), f"{len(PRE)} rows")

# 9 entry-bar stops are detected (synthetic; the real data may never trigger one)
_pt = 1e-5
_fake = pd.DataFrame({
    "t_utc": pd.to_datetime(["2022-01-03 20:00", "2022-01-03 21:00", "2022-02-07 20:00"],
                            utc=True),
    "open": [1.10000, 1.09000, 1.08000], "high": [1.10050, 1.09050, 1.08050],
    "low": [1.09000, 1.08500, 1.07900], "close": [1.09500, 1.08800, 1.08000],
    "spread": [10, 10, 10], "point": [_pt] * 3})
_r = simulate_leg(_fake, _fake["t_utc"].iloc[0], _fake["t_utc"].iloc[-1], 1, 0.00300)
check("entry-bar stop detected (synthetic breach)",
      _r["exit_reason"] == "stop" and _r["entry_bar_stop"] and
      _r["t_out"] == _fake["t_utc"].iloc[0],
      f"real-data entry-bar stops: {int(PRE['entry_bar_stop'].sum())}")

# 10 unstopped exits at the next rebalance open
_un = PRE[PRE["exit_reason"] == "rebalance"]
_l, _s = _un[_un["dir"] == 1], _un[_un["dir"] == -1]
check("unstopped exit == next rebalance bar open",
      bool(np.allclose(_l["exit_px"], _l["exit_bar_open_bid"], atol=1e-12)
           and np.allclose(_s["exit_px"],
                           _s["exit_bar_open_bid"] + _s["exit_bar_spread_px"], atol=1e-12)),
      f"{len(_l)} long at bid, {len(_s)} short at ask")

# 11 positions never overlap
_ov = sum(1 for a, b in zip(SIG.sort_values("k").itertuples(),
                            SIG.sort_values("k").iloc[1:].itertuples())
          if b.t_in < a.t_out)
check("consecutive positions never overlap", _ov == 0, f"{len(SIG)} signal legs")

say("")


# ============================================================ equity engine
def run(pre, choose, fin_rate=0.0, credit_col=None):
    """Walk equity applying the frozen limits. Minimum lot, so size never scales."""
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
        if not (np.isfinite(r["stop_risk_usd"]) and np.isfinite(r["notional_usd"])):
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
        credit = float(r[credit_col]) if credit_col else 0.0
        net = r["gross_usd"] - fin + credit
        eq += net
        trades.append({**r.to_dict(), "financing_usd": fin, "credit_usd": credit,
                       "net_usd": net, "equity_after": eq})
        if eq <= 0:
            break
    return pd.DataFrame(trades), pd.DataFrame(skipped), eq


def choose_signal(k, sub):
    r = sub[sub["is_signal"]]
    return None if not len(r) else (r.iloc[0]["pair"], int(r.iloc[0]["dir"]))


def choose_reverse(k, sub):
    r = sub[sub["is_signal"]]
    return None if not len(r) else (r.iloc[0]["pair"], -int(r.iloc[0]["dir"]))


def stats(tr, start_eq=START_EQUITY):
    if not len(tr):
        return {"n": 0, "net": 0.0, "ret_pct": 0.0, "pf": np.nan, "maxdd_pct": 0.0,
                "win_pct": np.nan, "top_share": np.nan, "start_equity": start_eq}
    eq = pd.concat([pd.Series([start_eq]), tr["equity_after"]], ignore_index=True)
    dd = (eq / eq.cummax() - 1.0).min() * 100.0
    wins = tr[tr["net_usd"] > 0]
    gw, gl = wins["net_usd"].sum(), -tr[tr["net_usd"] < 0]["net_usd"].sum()
    net = tr["net_usd"].sum()
    return {"n": len(tr), "net": net,
            "ret_pct": (tr["equity_after"].iloc[-1] / start_eq - 1) * 100.0,
            "pf": (gw / gl) if gl > 0 else np.inf, "maxdd_pct": dd,
            "win_pct": len(wins) / len(tr) * 100.0,
            "top_share": (tr["net_usd"].max() / gw * 100.0) if gw > 0 else np.nan,
            "start_equity": start_eq}


def window(tr, a, b):
    if not len(tr):
        return tr, START_EQUITY
    t = pd.to_datetime(tr["t_in"], utc=True).dt.tz_localize(None)
    sl = tr[(t >= a) & (t <= b)]
    if not len(sl):
        return sl, START_EQUITY
    prior = tr[t < a]
    return sl, (float(prior["equity_after"].iloc[-1]) if len(prior) else START_EQUITY)


# ============================================================ scenarios
say("=" * 100)
say("COST SCENARIOS")
say("=" * 100)
SC = {}
for nm, rate in FIN_STRESS.items():
    tr, sk, eq = run(PRE, choose_signal, rate)
    SC[nm] = {"trades": tr, "skipped": sk, "stats": stats(tr)}
    s = SC[nm]["stats"]
    say(f"  {nm:22s} trades {s['n']:3d}  net ${s['net']:8.2f}  ret {s['ret_pct']:7.2f}%  "
        f"PF {s['pf']:5.2f}  maxDD {s['maxdd_pct']:6.2f}%  win {s['win_pct']:5.1f}%")

tr_swap, _, eq_swap = run(PRE, choose_signal, 0.0, credit_col="swap_snapshot_usd")
s_swap = stats(tr_swap)
say(f"  {'swap_snapshot_2026':22s} trades {s_swap['n']:3d}  net ${s_swap['net']:8.2f}  "
    f"ret {s_swap['ret_pct']:7.2f}%   <- NON-HISTORICAL sensitivity, not evidence of cost")
tr_pol, _, eq_pol = run(PRE, choose_signal, 0.0, credit_col="policy_credit_usd")
s_pol = stats(tr_pol)
say(f"  {'5B policy_credit_rec':22s} trades {s_pol['n']:3d}  net ${s_pol['net']:8.2f}  "
    f"ret {s_pol['ret_pct']:7.2f}%   <- RECURSIVELY GATED: credit changes equity, which")
say(f"  {'':22s} changes which months pass the risk gate, so the trade set differs "
    f"from baseline ({s_pol['n']} vs {SC['baseline_zero_credit']['stats']['n']})")
say("")
say("  Exness does not pay the theoretical differential: task 004A found 0 of 19 pairs")
say("  where the theoretically positive side receives positive carry. Scenario 1 is the")
say("  principal test and assumes ZERO credit.")
say("")

BASE = SC["baseline_zero_credit"]
tr0, sk0 = BASE["trades"], BASE["skipped"]
base_net = BASE["stats"]["net"]

# TASK 005A CORRECTION 4 - apples-to-apples credit counterfactual.
# 5B above re-runs the account, so the credit alters equity, which alters which months
# clear the risk gate, which changes the trade SET (49 vs 47). That answers a different
# question. 5A holds the 47 baseline trades fixed - same symbols, directions, entries,
# exits and skips - and adds only the theoretical credit.
fixed_credit = float(tr0["policy_credit_usd"].sum()) if len(tr0) else 0.0
fixed_net = base_net + fixed_credit
say(f"  {'5A policy_credit_fixed':22s} trades {len(tr0):3d}  net ${fixed_net:8.2f}  "
    f"ret {fixed_net / START_EQUITY * 100:7.2f}%   <- FIXED baseline trade set, "
    f"credit ${fixed_credit:.2f} added")
say("     A = fixed-baseline-trade credit counterfactual (this line)")
say("     B = recursively gated theoretical-credit account path (line above)")
say("     NEITHER may satisfy a hard pass condition.")
say("")

say("PERIOD SPLITS (canonical executable panel)")
PER = {}
for pnm, a, b in [("validation", VAL_START, VAL_END), ("holdout", HOLD_START, HOLD_END)]:
    for scn in ("baseline_zero_credit", "fin_3.0pct"):
        t, seq = window(SC[scn]["trades"], a, b)
        PER[(pnm, scn)] = stats(t, seq)
        s = PER[(pnm, scn)]
        say(f"  {pnm:11s} {scn:22s} trades {s['n']:3d}  net ${s['net']:8.2f}  "
            f"ret {s['ret_pct']:7.2f}%  PF {s['pf']:5.2f}  maxDD {s['maxdd_pct']:6.2f}%  "
            f"(opened ${s['start_equity']:.2f})")
say("  The holdout is untouched for THIS policy-rate strategy family. It is NOT globally")
say("  untouched by every prior study in this project - earlier work has looked at this")
say("  calendar period for other questions.")
say("")

# ============================================================ signal-only
say("SIGNAL-ONLY TESTS (no stop, no financing)")


def signal_only_canonical(a=None, b=None):
    recs = []
    for k in sorted(PRE["k"].unique()):
        sub = PRE[(PRE["k"] == k) & PRE["is_signal"]]
        if not len(sub):
            continue
        r = sub.iloc[0]
        t = pd.Timestamp(r["t_in"]).tz_localize(None)
        if a is not None and (t < a or t > b):
            continue
        recs.append({"month": r["month"], "t": t, "pair": r["pair"], "dir": r["dir"],
                     "differential": r["rate_differential"],
                     "logret": r["dir"] * np.log(r["exit_px"] / r["entry_px"])})
    return pd.DataFrame(recs)


# The long-history panel must come from BROKER D1 bars, which reach back to 2018-07.
# Resampling the H1 files would NOT be a longer-history panel: dense H1 only begins
# 2021-08, so such a panel would silently cover the same window as the canonical one
# and report an empty development period while calling itself "long".
import MetaTrader5 as mt5                                              # noqa: E402

# --------------------------------------------------------------------------------
# TASK 005A CORRECTION 1 - BROKER D1 COMPLETENESS
# --------------------------------------------------------------------------------
# Task 005 reported a D1 span ending 2026-08-03 while running on 2026-08-02. Cause:
#
#   * The MT5 Python API returns bar and tick timestamps in UTC, and a bar's timestamp
#     is its OPEN time. The measured -0.0 h offset against the live tick clock confirms
#     the timestamps this script receives are UTC-aligned - it does NOT independently
#     establish the broker's internal server timezone, and no such claim is made. Only
#     the UTC alignment matters here, because that is what the completeness rule uses.
#   * The FX week opens Sunday ~21:00 UTC, so Sunday carries a partial D1 bar - on
#     2026-08-02 it held 2,969 ticks against 31,000-58,000 for a full weekday.
#   * That Sunday bar was still FORMING at retrieval (last H1 bar 23:00 UTC, now
#     23:15 UTC), and the Sunday->Monday merge relabelled it "2026-08-03".
#
# So a forming session was being used as a price point. Any session whose UTC day
# has not fully elapsed at the recorded retrieval timestamp is now excluded.
D1_RETRIEVAL_UTC = None
d1, d1_dropped = {}, []
if mt5.initialize(path=r"C:\Program Files\MetaTrader 5\terminal64.exe"):
    D1_RETRIEVAL_UTC = pd.Timestamp.utcnow().tz_localize(None)
    _tick = mt5.symbol_info_tick(PAIRS[0])
    D1_SERVER_NOW = pd.to_datetime(_tick.time, unit="s") if _tick else None
    for s in PAIRS:
        r = mt5.copy_rates_from_pos(s, mt5.TIMEFRAME_D1, 0, 20000)
        if r is None:
            continue
        d = pd.DataFrame(r)
        d["t"] = pd.to_datetime(d["time"], unit="s")
        d["dow"] = d["t"].dt.dayofweek
        d["eff"] = d["t"].dt.normalize()
        d.loc[d["dow"] == 6, "eff"] += pd.Timedelta(days=1)   # Sunday -> Monday
        g = d.groupby("eff")["close"].last()
        g = g[g.index.dayofweek < 5]
        # a session dated D is closed only once the whole UTC day D has elapsed
        closed = (g.index + pd.Timedelta(days=1)) <= D1_RETRIEVAL_UTC
        for x in g.index[~closed]:
            d1_dropped.append({"symbol": s, "session": x.date()})
        d1[s] = g[closed]
    mt5.shutdown()
_off_h = ((D1_SERVER_NOW - D1_RETRIEVAL_UTC).total_seconds() / 3600
          if D1_SERVER_NOW is not None else float("nan"))
say(f"  D1 retrieval (UTC)   : {D1_RETRIEVAL_UTC:%Y-%m-%d %H:%M:%S}")
say(f"  MT5 tick clock       : {D1_SERVER_NOW:%Y-%m-%d %H:%M:%S}  "
    f"(offset {_off_h:+.1f} h -> API timestamps are UTC-aligned;")
say(f"                         this does NOT establish the broker's server timezone)")
say(f"  D1 timestamp meaning : bar OPEN time, UTC day boundary")
say(f"  incomplete/forming sessions excluded: {len(d1_dropped)} "
    f"({len(d1_dropped)//max(len(PAIRS),1)} per pair)")
if d1_dropped:
    say(f"     dropped session date: {d1_dropped[0]['session']} "
        "(still open at retrieval)")
say(f"  broker D1 usable for {len(d1)}/{len(PAIRS)} pairs; span "
    f"{min(v.index.min() for v in d1.values()).date()} .. "
    f"{max(v.index.max() for v in d1.values()).date()}")
say(f"  LAST FULLY COMPLETED D1 SESSION: "
    f"{max(v.index.max() for v in d1.values()).date()}")

# independent monthly schedule for the D1 panel, so it is not limited by H1 coverage
_d1_start = max(v.index.min() for v in d1.values())
_d1_end = min(v.index.max() for v in d1.values())
sched_d1 = []
for m in pd.period_range(_d1_start, _d1_end, freq="M"):
    fm = first_monday(m.year, m.month)
    if fm < _d1_start or fm > _d1_end:
        continue
    sched_d1.append({"month": str(m), "first_monday": fm,
                     "cutoff_friday": fm - pd.Timedelta(days=3)})
sched_d1 = pd.DataFrame(sched_d1).reset_index(drop=True)
say(f"  D1 monthly schedule: {len(sched_d1)} months "
    f"({sched_d1['first_monday'].min().date()} .. {sched_d1['first_monday'].max().date()})")


def signal_only_d1(a=None, b=None):
    """APPROXIMATE: nearest available broker daily close consistent with the schedule."""
    recs = []
    for k in range(len(sched_d1) - 1):
        row, nxt = sched_d1.loc[k], sched_d1.loc[k + 1]
        cutoff = row["cutoff_friday"]
        pol = snap[snap["rebalance_month"] == row["month"]]
        rates = {p["currency"]: float(p["policy_rate_pct"]) for _, p in pol.iterrows()
                 if bool(p["is_policy_rate_available"]) and np.isfinite(p["policy_rate_pct"])
                 and (pd.isna(p["source_observation_date"])
                      or p["source_observation_date"] <= cutoff)}
        cands = []
        for p in PAIRS:
            if p[:3] in rates and p[3:6] in rates:
                d_ = rates[p[:3]] - rates[p[3:6]]
                if d_ != 0:
                    cands.append((p, d_))
        if not cands:
            continue
        p, diff = sorted(cands, key=lambda c: (-abs(c[1]), c[0]))[0]
        dd = 1 if diff > 0 else -1
        s_ = d1[p]
        i0 = s_.index[s_.index >= row["first_monday"]]
        i1 = s_.index[s_.index >= nxt["first_monday"]]
        if not len(i0) or not len(i1):
            continue
        c0, c1 = s_.loc[i0[0]], s_.loc[i1[0]]
        if not (np.isfinite(c0) and np.isfinite(c1) and c0 > 0 and c1 > 0):
            continue
        t = row["first_monday"]
        if a is not None and (t < a or t > b):
            continue
        recs.append({"month": row["month"], "t": t, "pair": p, "dir": dd,
                     "differential": diff, "logret": dd * np.log(c1 / c0)})
    return pd.DataFrame(recs)


SIGROWS = []
for panel, fn in (("canonical", signal_only_canonical), ("long_D1_approx", signal_only_d1)):
    for pnm, a, b in [("development", pd.Timestamp("1900-01-01"), DEV_END),
                      ("validation", VAL_START, VAL_END),
                      ("holdout", HOLD_START, HOLD_END)]:
        r = fn(a, b)
        tot = r["logret"].sum() if len(r) else np.nan
        SIGROWS.append({"panel": panel, "period": pnm, "n_months": len(r),
                        "sum_logret": tot,
                        "mean_logret": r["logret"].mean() if len(r) else np.nan,
                        "sign": np.sign(tot) if np.isfinite(tot) else np.nan,
                        "pricing": ("scheduled_H1_open_with_spread" if panel == "canonical"
                                    else "APPROXIMATE_daily_close_no_spread")})
SIGDF = pd.DataFrame(SIGROWS)
say(SIGDF[["panel", "period", "n_months", "sum_logret", "sign"]].to_string(index=False))

for panel, fn in (("canonical", signal_only_canonical), ("long_D1_approx", signal_only_d1)):
    rr = fn()
    if len(rr):
        assert int(rr["month"].duplicated().sum()) == 0, f"{panel}: duplicate months"
check("signal-only <= 1 observation per calendar month", True, "both panels")

# --- 005A: every D1 bar used was fully closed before retrieval
_last_used = max(v.index.max() for v in d1.values())
check("every D1 bar used was fully closed before retrieval",
      bool(all(((v.index + pd.Timedelta(days=1)) <= D1_RETRIEVAL_UTC).all()
               for v in d1.values())),
      f"last completed session {_last_used.date()}, retrieval "
      f"{D1_RETRIEVAL_UTC:%Y-%m-%d %H:%M}Z, {len(d1_dropped)} forming bars excluded")

# --- 005A: independent historical check on the JPY unavailable interval.
# This proves the availability rule works. It says NOTHING about the task-005 traded
# or D1 periods: the D1 panel starts 2018-07, which is after the interval ended on
# 2016-09-20, so the interval does NOT bind anywhere in this task.
_jpy_win = snap[(snap["currency"] == "JPY")
                & (snap["first_monday"] >= pd.Timestamp("2013-04-04"))
                & (snap["first_monday"] <= pd.Timestamp("2016-09-20"))]
check("JPY unavailable across 2013-04-04..2016-09-20 (historical check only)",
      len(_jpy_win) > 0 and not _jpy_win["is_policy_rate_available"].any(),
      f"{len(_jpy_win)} months all unavailable; interval ends before the "
      f"2018-07 D1 panel, so it does not bind in task 005")

ov = signal_only_canonical().merge(signal_only_d1(), on="month", suffixes=("_c", "_d"))
say(f"  overlap {len(ov)} months: same pair "
    f"{(ov['pair_c'] == ov['pair_d']).mean()*100:.1f}%, same direction "
    f"{(ov['dir_c'] == ov['dir_d']).mean()*100:.1f}%")
ov_c = ov["logret_c"].sum() if len(ov) else np.nan
ov_d = ov["logret_d"].sum() if len(ov) else np.nan
say(f"  overlapping sum_logret: canonical {ov_c:+.4f}, long-D1 {ov_d:+.4f}")
say("")

# ---- differential tercile diagnostic (all eligible outcomes at the policy direction)
say("DIFFERENTIAL-TERCILE DIAGNOSTIC (diagnostic only, not a pass condition)")
pol_side = PRE[PRE["dir"] == PRE["policy_dir"]].copy()
pol_side["logret"] = pol_side["dir"] * np.log(pol_side["exit_px"] / pol_side["entry_px"])
try:
    pol_side["tercile"] = pd.qcut(pol_side["abs_differential"], 3,
                                  labels=["low", "middle", "high"])
    terc = pol_side.groupby("tercile", observed=True).agg(
        n=("logret", "size"), mean_logret=("logret", "mean"),
        sum_logret=("logret", "sum"), win_pct=("logret", lambda x: (x > 0).mean() * 100),
        mean_abs_diff=("abs_differential", "mean"))
    say(terc.to_string())
    say("  Monotonicity across terciles is a property of eligible outcomes at the")
    say("  policy-implied direction; it is NOT the traded strategy and cannot pass a condition.")
except Exception as ex:
    terc = pd.DataFrame()
    say(f"  tercile split unavailable: {type(ex).__name__}: {ex}")
say("")

# ============================================================ controls
say("=" * 100)
say("CONTROLS")
say("=" * 100)
CTRL = []


def index_pre(pre):
    idx = {}
    for r in pre.itertuples():
        idx.setdefault(r.k, {})[(r.pair, r.dir)] = (
            r.gross_usd, r.notional_usd, r.stop_risk_usd, r.days_held, r.policy_dir)
    return idx


def run_fast(idx, choose_kv, fin_rate=0.0):
    """TASK 005A CORRECTION 2 - every simulation walks its OWN account path.

    `eq` is local to this call and starts at $979 every time. Both gates are
    recomputed against THAT path's evolving equity, so two paths holding different
    equity can reach opposite skip decisions on the identical candidate trade. The
    baseline's monthly pass/fail, trade count and equity curve are never consulted;
    only market outcomes (gross P&L, notional, stop risk, days held) are precomputed,
    and those are path-independent by construction.

    Returns (net, final_equity, n_trades, n_risk_skips, n_expo_skips).
    """
    eq, tot, n, rskip, xskip = START_EQUITY, 0.0, 0, 0, 0
    for k in sorted(idx):
        sel = choose_kv(k)
        if sel is None:
            continue
        v = idx[k].get(sel)
        if v is None:
            continue
        gross, notional, risk, days, _pd = v
        if not (np.isfinite(risk) and np.isfinite(notional)):
            continue
        if risk > eq * MAX_RISK_PCT / 100.0:      # gate uses THIS path's equity
            rskip += 1
            continue
        if notional > eq * MAX_EXPOSURE_X:        # gate uses THIS path's equity
            xskip += 1
            continue
        net = gross - notional * fin_rate / 365.0 * days
        eq += net
        tot += net
        n += 1
        if eq <= 0:
            break
    return tot, eq, n, rskip, xskip


IDX = index_pre(PRE)
sig_kv = {int(r.k): (r.signal_pair, int(r.signal_dir)) for r in SIG.itertuples()}
_chk, _eqc, _nc, _rs, _xs = run_fast(IDX, lambda k: sig_kv.get(k), 0.0)
check("fast control engine reproduces the costed engine",
      abs(_chk - base_net) < 1e-6 and _nc == BASE["stats"]["n"],
      f"net ${_chk:.2f}, {_nc} trades, {_rs} risk skips")

# --- 005A: prove path-dependence of the risk gate, synthetically and deterministically.
# One candidate, two accounts. At $979 the 1.50% budget is $14.69 and a $12 stop risk
# is allowed; at $700 the budget is $10.50 and the SAME candidate must be skipped.
_synth = {0: {("X", 1): (5.0, 100.0, 12.0, 30.0, 1)}}
_rich = run_fast(_synth, lambda k: ("X", 1))              # starts at $979 -> takes it
_poor_eq = 700.0
_p_eq, _p_n = _poor_eq, 0
for _k in _synth:
    _g, _no, _rk, _dy, _ = _synth[_k][("X", 1)]
    if _rk <= _p_eq * MAX_RISK_PCT / 100.0:
        _p_eq += _g
        _p_n += 1
check("two paths at different equity make different risk-skip decisions",
      _rich[2] == 1 and _p_n == 0,
      f"$979 budget ${979*MAX_RISK_PCT/100:.2f} takes a $12.00 risk; "
      f"${_poor_eq:.0f} budget ${_poor_eq*MAX_RISK_PCT/100:.2f} skips it")

# the eligible monthly outcome set the controls draw from is EXACTLY the baseline's
ks = sorted(IDX.keys())
opts = {k: list(IDX[k].keys()) for k in ks}
pol_opts = {k: sorted({(p, d) for (p, d) in IDX[k] if d == IDX[k][(p, d)][4]})
            for k in ks}
check("random controls use the same eligible monthly outcome set as baseline",
      all(sig_kv[k] in opts[k] for k in ks if k in sig_kv),
      f"{len(ks)} months, {sum(len(v) for v in opts.values())} eligible outcomes")
say("")

# 1 random pair AND direction
def randomise(seed, choices, label):
    """10,000 independent account paths. Records the full distribution, not just net."""
    rng_ = np.random.default_rng(seed)
    nets = np.empty(N_PERM)
    ntr = np.empty(N_PERM, dtype=int)
    nrs = np.empty(N_PERM, dtype=int)
    for j in range(N_PERM):
        pm = {k: choices[k][rng_.integers(len(choices[k]))] for k in ks if choices[k]}
        net, _eq, n_, rs_, _xs = run_fast(IDX, lambda k, _p=pm: _p.get(k), 0.0)
        nets[j], ntr[j], nrs[j] = net, n_, rs_
    p = (1 + int((nets >= base_net).sum())) / (N_PERM + 1)
    say(f"  {label}")
    say(f"     net    : median ${np.median(nets):8.2f}   5th ${np.percentile(nets,5):8.2f}"
        f"   95th ${np.percentile(nets,95):8.2f}   baseline ${base_net:.2f}")
    say(f"     trades : median {np.median(ntr):5.0f}   min {ntr.min():3d}   max {ntr.max():3d}"
        f"      (baseline {BASE['stats']['n']})")
    say(f"     risk skips : median {np.median(nrs):4.0f}   min {nrs.min():3d}   "
        f"max {nrs.max():3d}   (baseline {len(sk0)})")
    say(f"     one-sided p = {p:.4f}")
    return {"nets": nets, "ntr": ntr, "nrs": nrs, "p": p,
            "median": float(np.median(nets))}


R1 = randomise(PERM_SEED, opts, "1. random pair AND direction")
p1, med1 = R1["p"], R1["median"]
CTRL.append({"control": "random_pair_and_direction", "n": N_PERM,
             "baseline_net": base_net, "median_random_net": med1,
             "p_value_one_sided": p1, "beats_median": bool(base_net > med1),
             "net_pct5": float(np.percentile(R1["nets"], 5)),
             "net_pct95": float(np.percentile(R1["nets"], 95)),
             "trades_median": float(np.median(R1["ntr"])),
             "trades_min": int(R1["ntr"].min()), "trades_max": int(R1["ntr"].max()),
             "risk_skips_median": float(np.median(R1["nrs"])),
             "risk_skips_min": int(R1["nrs"].min()),
             "risk_skips_max": int(R1["nrs"].max())})

R2 = randomise(PERM_SEED + 1, pol_opts, "2. random pair, POLICY-IMPLIED direction")
p2, med2 = R2["p"], R2["median"]
CTRL.append({"control": "random_pair_policy_direction", "n": N_PERM,
             "baseline_net": base_net, "median_random_net": med2,
             "p_value_one_sided": p2, "beats_median": bool(base_net > med2),
             "net_pct5": float(np.percentile(R2["nets"], 5)),
             "net_pct95": float(np.percentile(R2["nets"], 95)),
             "trades_median": float(np.median(R2["ntr"])),
             "trades_min": int(R2["ntr"].min()), "trades_max": int(R2["ntr"].max()),
             "risk_skips_median": float(np.median(R2["nrs"])),
             "risk_skips_min": int(R2["nrs"].min()),
             "risk_skips_max": int(R2["nrs"].max())})

# 3 reverse
tr_r, _, eq_r = run(PRE, choose_reverse, 0.0)
s_r = stats(tr_r)
say(f"  3. reverse                   : net ${s_r['net']:.2f} vs baseline ${base_net:.2f}")
CTRL.append({"control": "reverse", "net": s_r["net"], "n": s_r["n"],
             "worse_than_baseline": bool(s_r["net"] < base_net),
             "net_le_zero": bool(s_r["net"] <= 0)})

# 4 / 5 delayed entry
DELAY = {}
for nm, hrs in (("delay_24h", 24), ("delay_1week", 168)):
    pre_d, _ = precompute(entry_offset_h=hrs)
    t_d, _, e_d = run(pre_d, choose_signal, 0.0)
    s_d = stats(t_d)
    DELAY[nm] = s_d
    say(f"  {'4' if hrs == 24 else '5'}. {nm:25s}: net ${s_d['net']:8.2f}  "
        f"ret {s_d['ret_pct']:7.2f}%  trades {s_d['n']}")
    CTRL.append({"control": nm, "net": s_d["net"], "ret_pct": s_d["ret_pct"],
                 "n": s_d["n"], "still_positive": bool(s_d["net"] > 0)})

# 6 doubled spreads
pre_2, _ = precompute(spread_mult=2.0)
t_2, _, e_2 = run(pre_2, choose_signal, 0.0)
s_2 = stats(t_2)
say(f"  6. double spreads            : net ${s_2['net']:8.2f}  ret {s_2['ret_pct']:7.2f}%  "
    f"trades {s_2['n']}")
CTRL.append({"control": "double_spread", "net": s_2["net"], "ret_pct": s_2["ret_pct"],
             "n": s_2["n"], "still_positive": bool(s_2["net"] > 0)})

# 7 current-swap static sensitivity (NOT historical)
CTRL.append({"control": "current_swap_static_sensitivity_NON_HISTORICAL",
             "net": s_swap["net"], "ret_pct": s_swap["ret_pct"], "n": s_swap["n"]})
say(f"  7. 2026 swap snapshot static : net ${s_swap['net']:8.2f}   "
    "NON-HISTORICAL, not evidence of past cost")
say("")

# ============================================================ pass conditions
say("=" * 100)
say("HARD PASS CONDITIONS")
say("=" * 100)
sv = PER[("validation", "baseline_zero_credit")]
sh = PER[("holdout", "baseline_zero_credit")]
allc = BASE["stats"]
comb3 = SC["fin_3.0pct"]["stats"]


def sig(panel, period):
    r = SIGDF[(SIGDF.panel == panel) & (SIGDF.period == period)]["sum_logret"]
    return float(r.iloc[0]) if len(r) and np.isfinite(r.iloc[0]) else np.nan


COND = [
    ("1  canonical validation net profit > 0", sv["net"] > 0, f"${sv['net']:.2f}"),
    ("2  canonical holdout net profit > 0", sh["net"] > 0, f"${sh['net']:.2f}"),
    ("3  combined canonical > 0 under 3.0% financing", comb3["net"] > 0,
     f"${comb3['net']:.2f}"),
    ("4  doubled-spread result > 0", s_2["net"] > 0, f"${s_2['net']:.2f}"),
    ("5  long-D1 validation signal-only > 0", sig("long_D1_approx", "validation") > 0,
     f"{sig('long_D1_approx','validation'):+.4f}"),
    ("6  long-D1 holdout signal-only > 0", sig("long_D1_approx", "holdout") > 0,
     f"{sig('long_D1_approx','holdout'):+.4f}"),
    ("7  canonical and long-D1 overlap both positive",
     bool(np.isfinite(ov_c) and np.isfinite(ov_d) and ov_c > 0 and ov_d > 0),
     f"canon {ov_c:+.4f}, D1 {ov_d:+.4f}"),
    ("8  baseline beats median random pair+direction", base_net > med1,
     f"${base_net:.2f} vs ${med1:.2f}"),
    ("9  randomisation p <= 0.10", p1 <= 0.10, f"p={p1:.4f}"),
    ("10 reverse net <= 0 AND worse than baseline",
     bool(s_r["net"] <= 0 and s_r["net"] < base_net),
     f"${s_r['net']:.2f} vs ${base_net:.2f}"),
    ("11 at least 45 completed canonical trades", allc["n"] >= 45, f"{allc['n']}"),
    ("12 profit factor > 1.10", bool(np.isfinite(allc["pf"]) and allc["pf"] > 1.10),
     f"{allc['pf']:.3f}" if np.isfinite(allc["pf"]) else "n/a"),
    ("13 max drawdown <= 20%", abs(allc["maxdd_pct"]) <= 20.0, f"{allc['maxdd_pct']:.2f}%"),
    ("14 no trade > 25% of total positive net profit",
     None if allc["net"] <= 0 else bool(allc["top_share"] <= 25.0),
     "NOT APPLICABLE (net profit <= 0)" if allc["net"] <= 0 else f"{allc['top_share']:.1f}%"),
    ("15 24-hour delayed entry remains positive", DELAY["delay_24h"]["net"] > 0,
     f"${DELAY['delay_24h']['net']:.2f}"),
    ("16 no margin call / negative equity / overlap",
     bool(BASE["stats"]["n"] >= 0 and _ov == 0 and
          (tr0["equity_after"].min() > 0 if len(tr0) else True)),
     f"min equity ${tr0['equity_after'].min():.2f}" if len(tr0) else "no trades"),
]
n_pass = n_na = 0
rows = []
for name, okc, val in COND:
    tag = "N/A " if okc is None else ("PASS" if okc else "FAIL")
    say(f"  [{tag}] {name:52s} {val}")
    rows.append({"condition": name, "result": tag, "value": val})
    if okc is None:
        n_na += 1
    else:
        n_pass += bool(okc)
VERDICT = "PASSED" if (n_pass == len(COND) and n_na == 0) else "FAILED"
say("")
say(f"  conditions passed: {n_pass}/{len(COND)}"
    + (f"   ({n_na} NOT APPLICABLE, not counted as passes)" if n_na else ""))
say(f"  >>> V2 VERDICT: {VERDICT}")
if VERDICT == "FAILED":
    say("  Per the specification V2 is reported FAILED. It is NOT optimised, repaired,")
    say("  reversed, thresholded, or given a different stop after seeing these results.")
say("")
pd.DataFrame(rows).to_csv(OUT_COND, index=False)

say("SKIPPED TRADES (baseline)")
if len(sk0):
    say(sk0["reason"].value_counts().to_string())
else:
    say("  none")
say("")

# ============================================================ outputs
if len(tr0):
    tr0.to_csv(OUT_TRADES, index=False)
    mth = tr0.copy()
    mth.groupby("month").agg(trades=("net_usd", "size"), net_usd=("net_usd", "sum"),
                             equity_after=("equity_after", "last"),
                             pair=("pair", "first"), differential=("rate_differential", "first")
                             ).to_csv(OUT_MONTHLY)
else:
    pd.DataFrame().to_csv(OUT_TRADES, index=False)
    pd.DataFrame().to_csv(OUT_MONTHLY, index=False)
SIGDF.to_csv(OUT_SIGNAL, index=False)
pd.DataFrame(CTRL).to_csv(OUT_CONTROLS, index=False)

say(f"assertions passed: {sum(a['passed'] for a in ASSERTS)}/{len(ASSERTS)}")
say("")
say(f"trades     -> {OUT_TRADES}")
say(f"monthly    -> {OUT_MONTHLY}")
say(f"signal     -> {OUT_SIGNAL}")
say(f"controls   -> {OUT_CONTROLS}")
say(f"conditions -> {OUT_COND}")
with open(OUT_REPORT, "w", encoding="utf-8") as f:
    f.write("\n".join(LOG) + "\n")
print(f"report     -> {OUT_REPORT}")
