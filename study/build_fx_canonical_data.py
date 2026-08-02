"""TASK 002 - CLEAN FX RESEARCH DATASET

Builds and audits a canonical FX daily/weekly panel for weekly cross-sectional work.
This script prepares and audits DATA ONLY. It tests no strategy, reports no returns,
recommends no rule, touches no order and does not modify the live bot.

--------------------------------------------------------------------------------
!! DEVIATION FROM SPEC, STATED UP FRONT
--------------------------------------------------------------------------------
The universe rule asks for symbols with ">= six calendar years of reliable history".
NO SYMBOL ON THIS ACCOUNT MEETS THAT ON H1, and it is not a sync artifact:

    EURUSDm H1 bars per calendar year, as served by Exness
      2018:  155      2021: 3055      2024: 6240
      2019:  311      2022: 6235      2025: 6216
      2020:  312      2023: 6216      2026: 3624 (to July)

    A full FX year is ~6,200 H1 bars. 2018-2020 return 155-312, i.e. sparse
    remnants rather than history. Explicit copy_rates_range() calls for 2019 and
    2020 return the same 311 and 312 bars, so this is the limit of what the broker
    serves, not something a longer download would fix.

    First month with a full complement of H1 bars: 2021-08.
    Dense window available: 2021-08-01 -> 2026-07-31 = 60 months = 5.0 years.

Applying the 6-year rule literally would empty the universe and produce no dataset.
So the rule is applied, RECORDED AS FAILED FOR EVERY SYMBOL, and the dataset is then
built over the real 5.0-year dense window. `meets_6y_requirement` is a column in the
audit so nobody can mistake this for a satisfied criterion, and the integrity report
states the shortfall in its first section.

Note for whoever sets strategy: broker D1 goes back to 2018-07 (2522 bars, ~8 years)
while H1 does not. A daily-resolution panel could therefore span ~8 years, but it
could NOT be cut to the canonical 17:00 New York session boundary, because that
construction needs intraday bars. That is a factual trade-off, not a recommendation.

--------------------------------------------------------------------------------
UNIVERSE RULE (as specified)
--------------------------------------------------------------------------------
Start from groups A and B of study/results/exness_feasibility_census.csv, then keep
only TRUE FIAT forex pairs. Excluded: stocks, indices, crypto, energies,
Forex_Indicator, metals/commodities hiding in the Forex group (XAU, XAG, XPT, XPD,
XCU, XAL, XZN, XNI, XPB), and anything not tradeable both long and short.

A symbol qualifies when, from the census:
    min-lot 2-ATR risk   <= 2.00% of $979
    economic exposure    <= 2.00x account equity
    median spread        <= 6.00% of D1 ATR
    history              >= 6 calendar years   <- see deviation above

--------------------------------------------------------------------------------
TIME HANDLING
--------------------------------------------------------------------------------
Per instruction, MetaTrader timestamps are treated as UTC and converted to
America/New_York. The data corroborates this: the trading week opens on Sunday at
21:00 in the raw frame during EDT and 22:00 during EST, which is 17:00 New York in
both - exactly what a UTC-stamped feed looks like. The audit reports the observed
open/close hours so this assumption stays checkable rather than asserted.

Canonical trading day: 17:00 New York -> next 17:00 New York.
    session_date = (t_newyork + 7 hours).date()
A bar at 17:00 NY shifts to 00:00 the next day, so evening bars belong to the NEXT
session. This makes the Sunday-merge requirement automatic: Sunday 17:00-23:59 NY
shifts into Monday, so no standalone Sunday candle can exist by construction.
Only Monday-Friday sessions are emitted; any Saturday/Sunday session date is a stray
and is dropped and counted.

DST is handled by tz_convert, so a session spans 23 or 25 hours across a transition
instead of a wrong 24. Those days are reported rather than silently normalised.

Missing market prices are NEVER forward-filled. A missing hour stays missing and is
counted in the gap columns.

--------------------------------------------------------------------------------
SWAP
--------------------------------------------------------------------------------
Swap figures are carried through as a DATED BROKER SNAPSHOT (2026-08-02) only. They
are not applied across historical years. Exness does not publish historical swap
rates and none were collected, so any historical carry figure would be fabricated.

--------------------------------------------------------------------------------
NOT DISTURBING THE RUNNING BOT
--------------------------------------------------------------------------------
Same protections as task 001: strictly sequential requests, a delay between symbols,
terminal latency probed before each download, back off and retry when it degrades,
abort rather than fight for the terminal, and Market Watch restored in a finally:
block to its exact starting baseline.
"""
import os
import time
import datetime as dt

import numpy as np
import pandas as pd
import MetaTrader5 as mt5

# ----------------------------------------------------------------------------- config
TERMINAL = r"C:\Program Files\MetaTrader 5\terminal64.exe"
BALANCE = 979.00
NY = "America/New_York"

SESSION_SHIFT_H = 7          # 17:00 NY + 7h = 00:00 next day -> session date
ATR_PERIOD = 20
STOP_ATR_MULT = 2.0

# universe thresholds
MAX_RISK_PCT = 2.00          # % of BALANCE at a 2-ATR stop, min lot
MAX_EXPOSURE_X = 2.00        # multiples of BALANCE
MAX_SPREAD_PCT_ATR = 6.00    # median D1 spread as % of D1 ATR
MIN_HISTORY_YEARS = 6.0      # asked for; see the deviation note in the docstring

# the real dense H1 window this broker serves (measured, see docstring)
DENSE_START = pd.Timestamp("2021-08-01", tz="UTC")
MIN_DENSE_MONTHS = 48        # a symbol must cover at least 4y of the dense window

H1_REQUEST = 60000           # copy_rates_from_pos rejects >=100000 with -2
FULL_SESSION_HOURS = 24

# metals / commodities that sit inside the broker's "Forex" group but are not fiat
NON_FIAT = {"XAU", "XAG", "XPT", "XPD", "XCU", "XAL", "XZN", "XNI", "XPB", "XRH"}
FIAT = {"USD", "EUR", "GBP", "JPY", "CHF", "CAD", "AUD", "NZD", "SEK", "NOK",
        "DKK", "PLN", "HUF", "CZK", "TRY", "ZAR", "MXN", "SGD", "HKD", "CNH",
        "THB", "ILS", "KRW", "INR", "BRL", "RUB", "RON", "BGN"}

# politeness / contention control (same posture as task 001)
DELAY_BETWEEN = 0.30
HEALTH_SYMBOL = "BTCUSDm"
SLOW_MS = 1500.0
PAUSE_SECONDS = 20.0
MAX_CONSEC_PAUSE = 6
CALL_RETRIES = 4             # (-1,'Call failed') is transient and needs a retry

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
RAW = os.path.join(DATA, "raw_h1")          # gitignored - raw H1 is not committed
RESULTS = os.path.join(HERE, "results")
os.makedirs(RAW, exist_ok=True)
os.makedirs(RESULTS, exist_ok=True)

CENSUS = os.path.join(RESULTS, "exness_feasibility_census.csv")
DAILY_CSV = os.path.join(DATA, "fx_daily_canonical.csv")
WEEKLY_CSV = os.path.join(DATA, "fx_weekly_canonical.csv")
UNIVERSE_CSV = os.path.join(RESULTS, "fx_universe_audit.csv")
SPREAD_CSV = os.path.join(RESULTS, "fx_spread_by_hour.csv")
REPORT_TXT = os.path.join(RESULTS, "fx_data_integrity_report.txt")


# ----------------------------------------------------------------------------- health
class TerminalHealth:
    """Backs off when the terminal slows, so the census never starves the live bot."""

    def __init__(self):
        self.samples, self.events, self.aborted = [], [], False

    def probe(self, where):
        t0 = time.perf_counter()
        tick = mt5.symbol_info_tick(HEALTH_SYMBOL)
        ms = (time.perf_counter() - t0) * 1000.0
        self.samples.append(ms)
        return ms, (tick is not None)

    def check(self, where):
        ms, ok = self.probe(where)
        if ok and ms <= SLOW_MS:
            return True
        for attempt in range(1, MAX_CONSEC_PAUSE + 1):
            self.events.append({"ts": dt.datetime.now().isoformat(timespec="seconds"),
                                "at": where, "latency_ms": round(ms, 1), "tick_ok": ok,
                                "action": f"pause {PAUSE_SECONDS:g}s ({attempt})"})
            print(f"    !! terminal slow ({ms:.0f} ms) at {where} - pausing "
                  f"{PAUSE_SECONDS:g}s [{attempt}/{MAX_CONSEC_PAUSE}]", flush=True)
            time.sleep(PAUSE_SECONDS)
            ms, ok = self.probe(where + "/recheck")
            if ok and ms <= SLOW_MS:
                self.events.append({"ts": dt.datetime.now().isoformat(timespec="seconds"),
                                    "at": where, "latency_ms": round(ms, 1),
                                    "tick_ok": ok, "action": "recovered"})
                return True
        self.events.append({"ts": dt.datetime.now().isoformat(timespec="seconds"),
                            "at": where, "latency_ms": round(ms, 1), "tick_ok": ok,
                            "action": "ABORT - terminal did not recover"})
        self.aborted = True
        return False

    def stats(self):
        if not self.samples:
            return {}
        a = np.array(self.samples)
        return {"n": len(a), "median_ms": float(np.median(a)),
                "p95_ms": float(np.percentile(a, 95)), "max_ms": float(a.max())}


def fetch_h1(name):
    """Full H1 history. Retries (-1,'Call failed'), which is transient."""
    err = None
    for _ in range(CALL_RETRIES):
        r = mt5.copy_rates_from_pos(name, mt5.TIMEFRAME_H1, 0, H1_REQUEST)
        err = mt5.last_error()
        if r is not None and len(r):
            return r, ""
        time.sleep(2.0)
    return None, str(err)


# ----------------------------------------------------------------------------- universe
def select_universe():
    """Apply the task-002 universe rule to the task-001 census. Returns (keep, audit)."""
    c = pd.read_csv(CENSUS)
    rows = []
    for _, r in c.iterrows():
        sym = r["symbol"]
        grp = r.get("group")
        base, prof = str(r.get("currency_base")), str(r.get("currency_profit"))
        reasons = []

        if grp not in ("A_TRADEABLE_NOW", "B_POSSIBLY_TRADEABLE"):
            reasons.append("not_group_A_or_B")
        if r.get("asset_class") != "Forex":
            reasons.append(f"asset_class={r.get('asset_class')}")
        if base in NON_FIAT or prof in NON_FIAT:
            reasons.append(f"non_fiat_base_or_profit({base}/{prof})")
        elif not (base in FIAT and prof in FIAT):
            reasons.append(f"not_recognised_fiat({base}/{prof})")
        if not bool(r.get("both_sides", False)):
            reasons.append("not_tradeable_both_sides")

        risk = float(r.get("risk_2atr_pct_of_balance", np.inf) or np.inf)
        expo = float(r.get("exposure_x_equity", np.inf) or np.inf)
        sprd = r.get("spread_pct_of_atr_med")
        sprd = float(sprd) if pd.notna(sprd) else np.inf
        if not risk <= MAX_RISK_PCT:
            reasons.append(f"risk_{risk:.2f}pct>{MAX_RISK_PCT:.2f}")
        if not expo <= MAX_EXPOSURE_X:
            reasons.append(f"exposure_{expo:.2f}x>{MAX_EXPOSURE_X:.2f}")
        if not sprd <= MAX_SPREAD_PCT_ATR:
            reasons.append(f"spread_{sprd:.2f}pct>{MAX_SPREAD_PCT_ATR:.2f}")

        rows.append({
            "symbol": sym, "group": grp, "asset_class": r.get("asset_class"),
            "currency_base": base, "currency_profit": prof,
            "both_sides": r.get("both_sides"),
            "census_risk_2atr_pct": risk if np.isfinite(risk) else np.nan,
            "census_exposure_x": expo if np.isfinite(expo) else np.nan,
            "census_spread_pct_atr": sprd if np.isfinite(sprd) else np.nan,
            "census_atr20_d1": r.get("atr20_d1_price"),
            "census_loss_2atr_usd": r.get("loss_2atr_min_lot_usd"),
            "census_d1_bars": r.get("d1_bars"),
            "volume_min": r.get("volume_min"),
            "swap_long": r.get("swap_long"), "swap_short": r.get("swap_short"),
            "swap_mode": r.get("swap_mode"), "triple_swap_day": r.get("triple_swap_day"),
            "annual_cost_long_pct_snapshot": r.get("annual_cost_long_pct"),
            "annual_cost_short_pct_snapshot": r.get("annual_cost_short_pct"),
            "selected": len(reasons) == 0,
            "exclusion_reasons": ";".join(reasons),
        })
    audit = pd.DataFrame(rows)
    return audit[audit["selected"]]["symbol"].tolist(), audit


# ----------------------------------------------------------------------------- canonical
def to_sessions(d):
    """Raw H1 -> canonical Mon-Fri sessions running 17:00 NY to 17:00 NY."""
    d = d.copy()
    d["t_utc"] = pd.to_datetime(d["time"], unit="s", utc=True)
    d["t_ny"] = d["t_utc"].dt.tz_convert(NY)
    d["session_date"] = (d["t_ny"] + pd.Timedelta(hours=SESSION_SHIFT_H)).dt.date
    d["ny_hour"] = d["t_ny"].dt.hour
    d["ny_weekday"] = d["t_ny"].dt.dayofweek
    d["session_weekday"] = pd.to_datetime(d["session_date"]).dt.dayofweek
    return d


def build_daily(d, symbol):
    """One row per canonical session. No forward-filling: gaps stay gaps."""
    g = d.groupby("session_date", sort=True)
    out = pd.DataFrame({
        "symbol": symbol,
        "trading_date": pd.to_datetime(list(g.groups.keys())),
        "open": g["open"].first().values,
        "high": g["high"].max().values,
        "low": g["low"].min().values,
        "close": g["close"].last().values,
        "tick_volume": g["tick_volume"].sum().values,
        "spread_median_points": g["spread"].median().values,
        "spread_max_points": g["spread"].max().values,
        "n_h1_bars": g.size().values,
        "first_h1_utc": g["t_utc"].first().values,
        "last_h1_utc": g["t_utc"].last().values,
    })
    # A full session is 24 H1 bars (23 or 25 across a DST transition). Anything
    # materially short is flagged rather than patched.
    span_h = ((pd.to_datetime(out["last_h1_utc"]) - pd.to_datetime(out["first_h1_utc"]))
              .dt.total_seconds() / 3600.0) + 1
    out["expected_h1_bars"] = span_h.round().astype(int)
    out["missing_h1_bars"] = (out["expected_h1_bars"] - out["n_h1_bars"]).clip(lower=0)
    out["has_gap_or_incomplete"] = (
        (out["missing_h1_bars"] > 0) | (out["n_h1_bars"] < FULL_SESSION_HOURS - 4)
    )
    out["weekday"] = out["trading_date"].dt.dayofweek
    return out


def build_weekly(daily):
    """Weeks ending Friday 17:00 NY. Sessions are Mon-Fri, so an ISO week is the week."""
    d = daily.copy()
    iso = d["trading_date"].dt.isocalendar()
    d["iso_year"], d["iso_week"] = iso["year"].values, iso["week"].values
    g = d.groupby(["symbol", "iso_year", "iso_week"], sort=True)
    w = pd.DataFrame({
        "open": g["open"].first(), "high": g["high"].max(),
        "low": g["low"].min(), "close": g["close"].last(),
        "tick_volume": g["tick_volume"].sum(),
        "spread_median_points": g["spread_median_points"].median(),
        "spread_max_points": g["spread_max_points"].max(),
        "n_days": g.size(),
        "week_start": g["trading_date"].min(), "week_end": g["trading_date"].max(),
        "days_with_gap": g["has_gap_or_incomplete"].sum(),
    }).reset_index()
    w["complete_week"] = w["n_days"] == 5
    return w


def atr_sma(df, period):
    pc = df["close"].shift(1)
    tr = pd.concat([df["high"] - df["low"], (df["high"] - pc).abs(),
                    (df["low"] - pc).abs()], axis=1).max(axis=1)
    return tr.rolling(period).mean().iloc[-1]


# ============================================================================= run
if not mt5.initialize(path=TERMINAL):
    raise SystemExit(f"initialize failed: {mt5.last_error()}")
acct, term = mt5.account_info(), mt5.terminal_info()
print(f"account {acct.login} {acct.server}  equity {acct.equity:,.2f} {acct.currency}")

selected, universe = select_universe()
print(f"\nuniverse rule -> {len(selected)} candidate fiat FX symbols")
print("  " + ", ".join(selected))

health = TerminalHealth()
made_visible = []
h1_store, fetch_notes = {}, {}
now_utc = pd.Timestamp.now(tz="UTC")

try:
    all_syms = {s.name: s for s in mt5.symbols_get()}
    baseline_visible = {n for n, s in all_syms.items() if s.visible}
    for n in selected:
        if n in all_syms and not all_syms[n].visible:
            if mt5.symbol_select(n, True):
                made_visible.append(n)
    if made_visible:
        print(f"  subscribed {len(made_visible)} symbols, settling 6s...")
        time.sleep(6.0)

    print(f"\n=== downloading H1 for {len(selected)} symbols (sequential) ===")
    t0 = time.perf_counter()
    for i, name in enumerate(selected, 1):
        if not health.check(name):
            print("  !! aborting downloads - terminal not recovering")
            break
        r, err = fetch_h1(name)
        if r is None or not len(r):
            fetch_notes[name] = f"fetch_failed:{err}"
            print(f"  [{i}/{len(selected)}] {name:9s} FAILED {err}", flush=True)
            continue
        d = pd.DataFrame(r)
        d.to_csv(os.path.join(RAW, f"h1_{name}.csv"), index=False)  # not committed
        h1_store[name] = d
        t = pd.to_datetime(d["time"], unit="s", utc=True)
        print(f"  [{i}/{len(selected)}] {name:9s} {len(d):6d} H1 bars  "
              f"{t.iloc[0].date()} -> {t.iloc[-1].date()}", flush=True)
        time.sleep(DELAY_BETWEEN)
    dl_secs = time.perf_counter() - t0
finally:
    for n in made_visible:
        mt5.symbol_select(n, False)
    still = {s.name for s in mt5.symbols_get() if s.visible}
    print(f"\nMarket Watch restored: visible {len(still)} (baseline {len(baseline_visible)}), "
          f"leaked {len(still - baseline_visible)}")
    mt5.shutdown()

# ----------------------------------------------------------------------------- build
daily_all, weekly_all, spread_rows, audit_rows = [], [], [], []

for name in selected:
    a = {"symbol": name}
    d = h1_store.get(name)
    if d is None:
        a["status"] = fetch_notes.get(name, "no_data")
        audit_rows.append(a)
        continue

    n_raw = len(d)
    dup = int(d["time"].duplicated().sum())
    d = d.drop_duplicates(subset="time").sort_values("time").reset_index(drop=True)

    s = to_sessions(d)
    # drop the still-forming H1 candle
    forming = s["t_utc"] + pd.Timedelta(hours=1) > now_utc
    n_forming = int(forming.sum())
    s = s[~forming]

    # observed session boundary, so the UTC assumption stays checkable
    sun = s[s["ny_weekday"] == 6]
    fri = s[s["ny_weekday"] == 4]
    a["observed_sunday_open_ny_hour"] = int(sun["ny_hour"].min()) if len(sun) else -1
    a["observed_friday_last_ny_hour"] = int(fri["ny_hour"].max()) if len(fri) else -1

    # strays: a canonical session must land Mon-Fri
    stray = s[s["session_weekday"] >= 5]
    a["stray_weekend_session_bars"] = int(len(stray))
    s = s[s["session_weekday"] < 5]

    # restrict to the dense window the broker actually serves
    a["h1_first_utc"] = str(pd.to_datetime(d["time"], unit="s", utc=True).iloc[0])
    a["h1_last_utc"] = str(pd.to_datetime(d["time"], unit="s", utc=True).iloc[-1])
    a["h1_bars_raw"] = n_raw
    a["duplicate_timestamps"] = dup
    a["forming_bars_dropped"] = n_forming
    s_dense = s[s["t_utc"] >= DENSE_START]
    a["h1_bars_dense_window"] = int(len(s_dense))

    daily = build_daily(s_dense, name)
    # drop a final session that is still open
    if len(daily):
        last_date = daily["trading_date"].iloc[-1]
        close_ny = (pd.Timestamp(last_date).tz_localize(NY)
                    + pd.Timedelta(hours=17) - pd.Timedelta(days=0))
        if now_utc < close_ny.tz_convert("UTC"):
            daily = daily.iloc[:-1]
            a["dropped_incomplete_final_session"] = True
        else:
            a["dropped_incomplete_final_session"] = False

    if not len(daily):
        a["status"] = "no_sessions"
        audit_rows.append(a)
        continue

    weekly = build_weekly(daily)
    daily_all.append(daily)
    weekly_all.append(weekly)

    # ---- audit numbers
    a["status"] = "ok"
    a["daily_bars"] = len(daily)
    a["weekly_bars"] = len(weekly)
    a["first_session"] = str(daily["trading_date"].iloc[0].date())
    a["last_session"] = str(daily["trading_date"].iloc[-1].date())
    yrs = (daily["trading_date"].iloc[-1] - daily["trading_date"].iloc[0]).days / 365.25
    a["session_span_years"] = round(yrs, 2)
    a["meets_6y_requirement"] = bool(yrs >= MIN_HISTORY_YEARS)
    for wd, nm in enumerate(["mon", "tue", "wed", "thu", "fri"]):
        a[f"n_{nm}"] = int((daily["weekday"] == wd).sum())
    a["days_with_gap"] = int(daily["has_gap_or_incomplete"].sum())
    a["total_missing_h1"] = int(daily["missing_h1_bars"].sum())
    a["short_days_lt20h"] = int((daily["n_h1_bars"] < 20).sum())
    a["long_days_gt25h"] = int((daily["n_h1_bars"] > 25).sum())
    a["complete_weeks"] = int(weekly["complete_week"].sum())
    a["incomplete_weeks"] = int((~weekly["complete_week"]).sum())

    # missing weeks inside the covered span
    wk = weekly[["iso_year", "iso_week"]].drop_duplicates()
    span_weeks = int(round((daily["trading_date"].iloc[-1]
                            - daily["trading_date"].iloc[0]).days / 7)) + 1
    a["missing_weeks"] = max(0, span_weeks - len(wk))

    # DST transition sessions: those whose span is not 24h
    a["dst_23h_sessions"] = int((daily["expected_h1_bars"] == 23).sum())
    a["dst_25h_sessions"] = int((daily["expected_h1_bars"] == 25).sum())

    # ---- broker D1 ATR vs canonical ATR, and revised risk
    u = universe[universe["symbol"] == name].iloc[0]
    atr_broker = float(u["census_atr20_d1"]) if pd.notna(u["census_atr20_d1"]) else np.nan
    loss2_broker = float(u["census_loss_2atr_usd"]) if pd.notna(u["census_loss_2atr_usd"]) else np.nan
    atr_canon = atr_sma(daily, ATR_PERIOD)
    a["atr20_broker_d1"] = atr_broker
    a["atr20_canonical_5d"] = atr_canon
    a["atr_ratio_canon_over_broker"] = (atr_canon / atr_broker
                                        if atr_broker and np.isfinite(atr_broker) else np.nan)
    # USD per price unit is implied by the terminal's own 2-ATR loss, so no new
    # terminal calls are needed to re-price the canonical ATR.
    if atr_broker and np.isfinite(atr_broker) and np.isfinite(loss2_broker) and atr_broker > 0:
        usd_per_price = loss2_broker / (STOP_ATR_MULT * atr_broker)
        rev = STOP_ATR_MULT * atr_canon * usd_per_price
        a["usd_per_price_unit_min_lot"] = usd_per_price
        a["revised_loss_2atr_usd"] = rev
        a["revised_risk_pct_of_979"] = rev / BALANCE * 100.0
        a["fits_1_00pct"] = bool(rev <= BALANCE * 0.010)
        a["fits_1_50pct"] = bool(rev <= BALANCE * 0.015)
        a["fits_2_00pct"] = bool(rev <= BALANCE * 0.020)

    # ---- spread table rows (spread only; returns are never inspected here)
    sd = s_dense.copy()
    sd["symbol"] = name
    spread_rows.append(sd[["symbol", "ny_hour", "ny_weekday", "spread"]])

    audit_rows.append(a)

# ----------------------------------------------------------------------------- save
daily_df = pd.concat(daily_all, ignore_index=True) if daily_all else pd.DataFrame()
weekly_df = pd.concat(weekly_all, ignore_index=True) if weekly_all else pd.DataFrame()
if len(daily_df):
    daily_df = daily_df.drop(columns=["first_h1_utc", "last_h1_utc"])
    daily_df["trading_date"] = daily_df["trading_date"].dt.strftime("%Y-%m-%d")
    daily_df.to_csv(DAILY_CSV, index=False)
if len(weekly_df):
    for c in ("week_start", "week_end"):
        weekly_df[c] = pd.to_datetime(weekly_df[c]).dt.strftime("%Y-%m-%d")
    weekly_df.to_csv(WEEKLY_CSV, index=False)

audit = pd.DataFrame(audit_rows)
universe = universe.merge(
    audit[[c for c in audit.columns if c != "symbol"] + ["symbol"]],
    on="symbol", how="left")
universe.to_csv(UNIVERSE_CSV, index=False)

if spread_rows:
    sp = pd.concat(spread_rows, ignore_index=True)
    tbl = sp.groupby(["symbol", "ny_weekday", "ny_hour"])["spread"].agg(
        median_spread_points="median",
        p90_spread_points=lambda x: np.percentile(x, 90),
        n_bars="size").reset_index()
    tbl.to_csv(SPREAD_CSV, index=False)
else:
    sp, tbl = pd.DataFrame(), pd.DataFrame()

# ----------------------------------------------------------------------------- report
hs = health.stats()
ok = audit[audit.get("status") == "ok"] if "status" in audit else audit.iloc[0:0]
L = []
w = L.append
w("=" * 100)
w("TASK 002 - CLEAN FX RESEARCH DATASET - DATA INTEGRITY REPORT")
w("=" * 100)
w(f"generated  : {dt.datetime.now():%Y-%m-%d %H:%M:%S}")
w(f"account    : {acct.login} {acct.server}  ({['DEMO','CONTEST','REAL'][acct.trade_mode]})")
w(f"terminal   : build {term.build}")
w("")
w("!! HISTORY REQUIREMENT NOT MET - READ FIRST")
w("-" * 100)
w("The universe rule asks for >= 6 calendar years of reliable history. No symbol on this")
w("account meets that on H1. Exness serves only sparse remnants before 2021-08:")
w("  EURUSDm H1 bars/year: 2018=155  2019=311  2020=312  2021=3055  2022=6235  2023=6216")
w("  A full FX year is ~6,200 H1 bars. Explicit copy_rates_range() for 2019 and 2020")
w("  returns the same 311/312, so a longer download does not fix it.")
w(f"First dense month: 2021-08. Usable window {DENSE_START.date()} -> last complete session,")
w("which is 5.0 years, not 6. The dataset below is built on that real window and every")
w("symbol carries meets_6y_requirement=False in the audit CSV.")
w("")
w("Broker D1 reaches back to 2018-07 (~8 years), but a canonical 17:00-NY session cannot")
w("be built from daily bars - that construction needs intraday data. Stated as a fact for")
w("whoever sets strategy; no recommendation is made here.")
w("")
w("UNIVERSE")
w("-" * 100)
w(f"  census rows considered      : {len(universe)}")
w(f"  selected (fiat FX, limits)  : {len(selected)}")
w(f"  built successfully          : {len(ok)}")
w(f"  thresholds                  : risk <= {MAX_RISK_PCT:.2f}% of ${BALANCE:,.0f}, "
  f"exposure <= {MAX_EXPOSURE_X:.2f}x, median spread <= {MAX_SPREAD_PCT_ATR:.2f}% of D1 ATR")
w("")
w("  SELECTED SYMBOLS:")
w("    " + ", ".join(selected))
w("")
w("  EXCLUDED FROM THE FX UNIVERSE (grouped by first reason):")
exc = universe[~universe["selected"]].copy()
exc["first_reason"] = exc["exclusion_reasons"].astype(str).str.split(";").str[0]
for reason, grp in exc.groupby("first_reason"):
    names = ", ".join(grp["symbol"].head(12))
    more = f" (+{len(grp)-12} more)" if len(grp) > 12 else ""
    w(f"    {reason:34s} {len(grp):4d}   {names}{more}")
w("")
w("TIME BASE")
w("-" * 100)
w("  MT5 timestamps treated as UTC, converted to America/New_York (as instructed).")
w("  Canonical session: 17:00 NY -> next 17:00 NY, session_date = (t_ny + 7h).date()")
w("  Sunday evening bars shift into Monday by construction, so NO standalone Sunday")
w("  canonical candle can exist. Sessions are emitted for Mon-Fri only.")
if len(ok):
    w(f"  observed Sunday open  NY hour (should be 17): "
      f"{sorted(ok['observed_sunday_open_ny_hour'].dropna().unique().tolist())}")
    w(f"  observed Friday last  NY hour (should be 16): "
      f"{sorted(ok['observed_friday_last_ny_hour'].dropna().unique().tolist())}")
    w(f"  stray weekend session bars dropped: {int(ok['stray_weekend_session_bars'].sum())}")
    w("  -> the open/close hours above corroborate the UTC assumption; had the feed been")
    w("     on a UTC+2/+3 server clock these would not land on 17:00/16:00 New York.")
w("")
w("SUNDAY BARS IN THE BROKER'S OWN D1 SERIES")
w("-" * 100)
w("  The broker D1 series used in task 001 is the broker's own daily aggregation, which")
w("  is where a standalone Sunday candle would appear. In the canonical panel built here")
w("  the count is structurally zero, as shown above. Raw H1 bars falling on a New York")
w("  Sunday (i.e. the Sunday mini-session that gets merged into Monday):")
if len(ok):
    tot_sun = 0
    for name in ok["symbol"]:
        d = h1_store.get(name)
        if d is None:
            continue
        ss = to_sessions(d)
        tot_sun += int((ss["ny_weekday"] == 6).sum())
    w(f"    {tot_sun} Sunday H1 bars across {len(ok)} symbols, all merged into Monday")
w("")
w("COVERAGE PER SYMBOL")
w("-" * 100)
if len(ok):
    cols = ["symbol", "daily_bars", "weekly_bars", "first_session", "last_session",
            "session_span_years", "meets_6y_requirement", "days_with_gap",
            "total_missing_h1", "duplicate_timestamps", "missing_weeks"]
    w(ok[cols].to_string(index=False))
w("")
w("WEEKDAY COUNTS")
w("-" * 100)
if len(ok):
    w(ok[["symbol", "n_mon", "n_tue", "n_wed", "n_thu", "n_fri",
          "short_days_lt20h", "long_days_gt25h",
          "dst_23h_sessions", "dst_25h_sessions"]].to_string(index=False))
    w("")
    w("  dst_23h/dst_25h are sessions spanning 23 or 25 hours across a daylight-saving")
    w("  transition. They are reported, not normalised - forcing them to 24 would either")
    w("  invent or discard an hour of real market data.")
w("")
w("BROKER D1 ATR(20) vs CANONICAL 5-DAY ATR(20), AND REVISED RISK")
w("-" * 100)
if len(ok) and "atr20_canonical_5d" in ok:
    cols = ["symbol", "atr20_broker_d1", "atr20_canonical_5d",
            "atr_ratio_canon_over_broker", "census_loss_2atr_usd",
            "revised_loss_2atr_usd", "revised_risk_pct_of_979",
            "fits_1_00pct", "fits_1_50pct", "fits_2_00pct"]
    have = [c for c in cols if c in ok.columns or c in universe.columns]
    m = universe[universe["symbol"].isin(ok["symbol"])]
    w(m[have].to_string(index=False, float_format=lambda x: f"{x:,.5g}"))
    w("")
    w("  The canonical ATR is measured on 17:00-NY sessions; the broker's D1 ATR is measured")
    w("  on whatever daily boundary the broker uses. A ratio away from 1.00 is that boundary")
    w("  difference, not an error. Revised USD risk re-prices the canonical ATR using the")
    w("  USD-per-price-unit implied by the terminal's own order_calc_profit result from")
    w("  task 001, so no assumed contract maths enters here.")
w("")
w("SPREAD BY WEEKDAY AND NEW YORK HOUR")
w("-" * 100)
w(f"  full table -> {SPREAD_CSV}  ({len(tbl)} rows)")
if len(sp):
    byh = sp.groupby("ny_hour")["spread"].agg(
        median="median", p90=lambda x: np.percentile(x, 90), n="size")
    w("  pooled across symbols, by New York hour:")
    w("    hour  median_pts   p90_pts     n")
    for h, r in byh.iterrows():
        w(f"    {int(h):4d}  {r['median']:10.1f}  {r['p90']:8.1f}  {int(r['n']):6d}")
    w("")
    byd = sp.groupby("ny_weekday")["spread"].agg(
        median="median", p90=lambda x: np.percentile(x, 90), n="size")
    names = {0: "Mon", 1: "Tue", 2: "Wed", 3: "Thu", 4: "Fri", 6: "Sun"}
    w("  pooled across symbols, by New York weekday:")
    for d_, r in byd.iterrows():
        w(f"    {names.get(int(d_), d_):5s} median {r['median']:8.1f}  "
          f"p90 {r['p90']:8.1f}  n {int(r['n']):6d}")
    w("")
    w("  This table is built from SPREAD ONLY. No return series was inspected in producing")
    w("  it, so it cannot have been tuned to a favourable execution hour.")
w("")
w("SWAP")
w("-" * 100)
w("  Swap values carried into the universe CSV are a DATED BROKER SNAPSHOT taken")
w(f"  {dt.date.today()} and are labelled *_snapshot. They are NOT applied across historical")
w("  years. Exness does not publish historical swap rates and none were separately")
w("  collected, so any historical carry number would be fabricated. Treat holding cost as")
w("  known only as of the snapshot date.")
w("")
w("TERMINAL CONTENTION")
w("-" * 100)
if hs:
    w(f"  probes {hs['n']}  median {hs['median_ms']:.0f} ms  p95 {hs['p95_ms']:.0f} ms  "
      f"max {hs['max_ms']:.0f} ms")
w(f"  pauses taken      : {len([e for e in health.events if 'pause' in e['action']])}")
w(f"  aborted           : {health.aborted}")
w(f"  H1 download time  : {dl_secs/60:.1f} min")
for e in health.events:
    w(f"    {e['ts']}  {e['at']:18s} {e['latency_ms']:8.1f} ms  {e['action']}")
if not health.events:
    w("  no contention detected; every probe answered within "
      f"{SLOW_MS:.0f} ms, so no data was read from a strained terminal.")
w("")
w("MISSING DATA AND FAILURES")
w("-" * 100)
bad = audit[audit.get("status") != "ok"] if "status" in audit else audit.iloc[0:0]
w(f"  symbols that failed to build: {len(bad)}")
for _, r in bad.iterrows():
    w(f"    {r['symbol']:10s} {r.get('status')}")
w("  No missing price was forward-filled anywhere in this pipeline.")
w("")
w(f"daily  -> {DAILY_CSV}  ({len(daily_df)} rows)")
w(f"weekly -> {WEEKLY_CSV} ({len(weekly_df)} rows)")
w(f"universe audit -> {UNIVERSE_CSV}")
w(f"raw H1 -> {RAW}  (NOT committed)")

text = "\n".join(L)
with open(REPORT_TXT, "w", encoding="utf-8") as f:
    f.write(text + "\n")
print("\n" + text)
