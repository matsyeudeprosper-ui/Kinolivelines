"""TASK 001 - EXNESS FEASIBILITY CENSUS  (two-stage: shallow screen, then deepen)

Which Exness instruments can a ~$979 account actually trade for a medium-term
strategy while controlling risk?

This is a MEASUREMENT script. It chooses no strategy, recommends no entry rule
and places no order. It reads the terminal, computes per-symbol feasibility and
writes a CSV plus a text report.

--------------------------------------------------------------------------------
WHY TWO STAGES
--------------------------------------------------------------------------------
Asking MetaTrader for deep D1 history forces it to download every yearly history
file for that symbol (~8.8 files each on this account) and the server feeds them
at roughly 9 files/minute. Doing that for all 356 symbols costs about four hours
of continuous downloading on the same terminal a live bot is polling.

Almost all of that work is wasted: a symbol whose MINIMUM LOT already risks 40%
of the account cannot be rescued by knowing its history goes back to 2011.

  STAGE 1  every symbol, at most 400 completed D1 bars. That is enough to compute
           ATR(20), the spread ratio, and to answer the ">= 250 bars" adequacy
           test exactly, while touching only the two or three most recent yearly
           files. d1_start is recorded but marked PROVISIONAL, because a shallow
           request cannot see past the window it asked for.

  STAGE 2  survivors only. Full-depth history, so the first available date, the
           bar count, ATR(20) and every history-dependent figure become EXACT,
           and the final A/B/C ranking is built on those exact values.

Every row carries `history_depth` = EXACT or PROVISIONAL so no reader can mistake
one for the other.

--------------------------------------------------------------------------------
STAGE 2 SURVIVOR RULE  (as specified for this task)
--------------------------------------------------------------------------------
A symbol goes to stage 2 when it has >= 250 D1 bars, a usable profit calculation,
a spread that is not clearly excessive, and either

    risk_2atr <= 1.00% of $979  AND  exposure <= 3.0x equity        (clean pass)

or it misses exactly ONE of those two by no more than 25%:

    risk_2atr <= 1.25%  (failing risk only)   or   exposure <= 3.75x (failing
    exposure only).

Failing BOTH, even slightly, does not qualify.

--------------------------------------------------------------------------------
UNIT-CONVERSION ASSUMPTIONS  (all recorded, none guessed)
--------------------------------------------------------------------------------
A1. Account currency is read from account_info().currency and asserted to be USD.
    Every "USD" figure is really "deposit currency", which is USD on this account.

A2. ECONOMIC NOTIONAL IS NOT price x contract_size.
    That product is denominated in the PROFIT currency, which is not USD for most
    symbols (EURJPYm -> JPY, USDZARm -> ZAR). Notional is instead recovered from
    the terminal's own converter:

        profit_1pct  = order_calc_profit(BUY, sym, vol_min, px, px * 1.01)
        notional_usd = profit_1pct / 0.01

    order_calc_profit() returns deposit currency, so every cross-rate conversion
    is done by the terminal. For a linear instrument
    profit = dPrice * contract * volume * fx, so a +1% move earns exactly 1% of
    the USD notional. `raw_price_x_contract` is kept alongside for comparison;
    the two differ by the profit-currency FX rate whenever profit ccy != USD.
    Measured live: EURJPYm raw 181,812 (JPY) vs true $1,154; USDZARm raw 16,605
    (ZAR) vs true $1,000.

A3. MARGIN comes from order_calc_margin(), never from notional/leverage: Exness
    applies per-symbol and tiered leverage that one account-level number misses.

A4. SWAP. swap_mode is confirmed per symbol before any conversion.
      mode 0 (DISABLED) -> swap-free, costs recorded as 0.
      mode 1 (POINTS)   -> swap_long/short are POINTS per lot per day, converted
                           with the terminal itself:
                             order_calc_profit(BUY, sym, vol_min,
                                               px, px + swap_pts * point)
                           which applies contract size, volume and FX exactly as
                           a price move of that size would. Sign preserved:
                           positive = credit.
      any other mode    -> NOT converted; swap_converted=False so the number is
                           never silently misread. Only modes 0 and 1 occur here;
                           the guard exists so a broker change cannot corrupt it.
    For the short side order_calc_profit is used purely as a points->USD
    converter (the BUY direction gives the value of N points; the sign of
    swap_short already encodes whether a short is credited or debited).
    Cross-check: this reproduces BTCUSDm long carry at about -7.5%/yr, matching a
    figure derived independently from perpetual funding data.

A5. ANNUAL OVERNIGHT COST assumes a charge on all 365 calendar days: a triple-swap
    day means a 7-day week is billed across 5 trading days, so a year is ~365
    swap-days, not ~252. Positive = the position PAYS:
        annual_cost_pct = -(swap_usd_per_day * 365) / notional_usd * 100

A6. ATR(20) on D1 is the simple mean of the last 20 True Ranges (Wilder's TR
    definition, SMA smoothing rather than Wilder smoothing), on completed bars.

A7. The 2-ATR stop loss in USD comes from order_calc_profit() on an adverse move
    of 2 x ATR. If px - 2*ATR would be <= 0 the terminal cannot price it, so a
    linear fallback (notional * 2*ATR/px) is used and flagged in
    `atr_loss_method`.

A8. SPREAD. `spread_price_live` is the current ask-bid, a single snapshot that can
    be unrepresentative in a quiet minute. `spread_price_med_d1` is the median of
    the spread recorded on each D1 bar. Item 21 is reported from the LIVE spread
    as asked, with the median beside it; the RANKING and the "too expensive" test
    use the median, because a snapshot has misled on this account before.

A9. PRICE SOURCE. This census can run while equities are closed, leaving stocks
    with no live tick. Rather than dropping them, price falls back to the last D1
    close and `price_source` records it.

--------------------------------------------------------------------------------
GROUPING  (thresholds are constants below so they can be re-cut)
--------------------------------------------------------------------------------
A  TRADEABLE NOW      min lot survives a 2-ATR stop at <= 1.00% of $979, economic
                      exposure <= 3x equity, tradeable both ways, >= 250 D1 bars,
                      spread <= 10% of D1 ATR.
B  POSSIBLY TRADEABLE fails A but within 3x those risk/exposure limits (<= 3%
                      risk, <= 9x exposure) and spread <= 25% of ATR: a larger
                      balance or a different account type may fix it.
C  NOT TRADEABLE      min lot too big, spread too expensive, history inadequate,
                      or not tradeable at all.

Symbols that FAIL are kept in the CSV, not dropped. Errors are recorded in the
`status`/`error` columns rather than swallowed.

--------------------------------------------------------------------------------
NOT DISTURBING THE RUNNING BOT
--------------------------------------------------------------------------------
A live daemon and two irreplaceable recorders poll this same terminal. So:
  * requests are strictly sequential, one symbol at a time, with a small delay
    between them and a larger one between deep stage-2 downloads;
  * terminal responsiveness is probed with a cheap symbol_info_tick() call and
    the latency is logged. If it degrades past SLOW_MS the census PAUSES, waits,
    re-probes, and records the interruption; if it will not recover the census
    stops early and says so rather than fighting the bot for the terminal;
  * Market Watch is restored in a finally: block, so an abort cannot leave 162
    extra symbols subscribed. Symbols that were ALREADY visible are never touched.
Nothing here starts, stops or modifies the bot or the recorders.
"""
import os
import time
import datetime as dt

import numpy as np
import pandas as pd
import MetaTrader5 as mt5

# ----------------------------------------------------------------------------- config
TERMINAL      = r"C:\Program Files\MetaTrader 5\terminal64.exe"
BALANCE       = 979.00          # the reference account size named by the task

ATR_PERIOD    = 20              # D1
STOP_ATR_MULT = 2.0

RISK_CAPS     = [0.0025, 0.0050, 0.0100]   # fraction of BALANCE
EXPO_CAPS     = [1.0, 2.0, 3.0]            # multiples of BALANCE

MIN_D1_BARS       = 250     # ~1 year; below this history is "inadequate"
SPREAD_CAP_A_PCT  = 10.0    # spread as % of D1 ATR, ceiling for group A
SPREAD_CAP_B_PCT  = 25.0    # ceiling for group B, and "clearly excessive" above
GROUP_B_SLACK     = 3.0     # B allows 3x the A risk and exposure limits

# stage-2 survivor rule
SURV_RISK_PCT     = 1.00    # % of BALANCE at a 2-ATR stop
SURV_EXPO_X       = 3.00    # multiples of BALANCE
NEAR_MISS_SLACK   = 1.25    # a symbol may miss ONE of the two by up to 25%

# history depth
SHALLOW_BARS  = 400         # stage 1: enough for ATR(20) and the >=250 test
DEEP_BARS     = 20000       # stage 2: more than the deepest history on the account
                            # (copy_rates_from_pos rejects much larger counts with
                            #  (-2,'Terminal: Invalid params'), which silently
                            #  zeroed every symbol in the first version of this scan)

# politeness / contention control
SETTLE_SECONDS   = 6.0      # a freshly subscribed symbol has no tick for ~1s
DELAY_STAGE1     = 0.02     # between shallow symbols
DELAY_STAGE2     = 0.25     # between deep downloads - these are the heavy ones
HEALTH_SYMBOL    = "BTCUSDm"   # always subscribed; probing it is read-only
HEALTH_EVERY     = 10       # stage-1 symbols between probes (stage 2 probes each)
SLOW_MS          = 1500.0   # probe latency above this = terminal under strain
PAUSE_SECONDS    = 20.0     # back off this long when strained
MAX_CONSEC_PAUSE = 6        # give up after this many failed recoveries

DAYS = {0: "Sunday", 1: "Monday", 2: "Tuesday", 3: "Wednesday",
        4: "Thursday", 5: "Friday", 6: "Saturday"}

SWAP_MODES = {0: "DISABLED", 1: "POINTS", 2: "CURRENCY_SYMBOL",
              3: "CURRENCY_MARGIN", 4: "CURRENCY_DEPOSIT",
              5: "INTEREST_CURRENT", 6: "INTEREST_OPEN",
              7: "REOPEN_CURRENT", 8: "REOPEN_BID"}

TRADE_MODES = {0: "DISABLED", 1: "LONGONLY", 2: "SHORTONLY",
               3: "CLOSEONLY", 4: "FULL"}

CALC_MODES = {0: "FOREX", 1: "FUTURES", 2: "CFD", 3: "CFDINDEX", 4: "CFDLEVERAGE",
              5: "FOREX_NO_LEVERAGE", 32: "EXCH_STOCKS", 33: "EXCH_FUTURES",
              34: "EXCH_FORTS", 35: "EXCH_BONDS", 36: "EXCH_STOCKS_MOEX",
              37: "EXCH_BONDS_MOEX", 40: "SERV_COLLATERAL"}

HERE    = os.path.dirname(os.path.abspath(__file__))
RESULTS = os.path.join(HERE, "results")
os.makedirs(RESULTS, exist_ok=True)
CSV_PATH = os.path.join(RESULTS, "exness_feasibility_census.csv")
TXT_PATH = os.path.join(RESULTS, "exness_feasibility_report.txt")


# ----------------------------------------------------------------------------- health
class TerminalHealth:
    """Watches how fast the terminal answers, and backs off when it slows down.

    The point is not to measure the terminal for its own sake - it is that a live
    daemon and two recorders share this terminal, and a census has no right to
    starve them. Every latency sample is kept so the report can state plainly
    whether contention affected any result.
    """

    def __init__(self):
        self.samples = []          # (phase, symbol, ms)
        self.events = []           # interruption records
        self.aborted = False

    def probe(self, phase, symbol):
        t0 = time.perf_counter()
        tick = mt5.symbol_info_tick(HEALTH_SYMBOL)
        ms = (time.perf_counter() - t0) * 1000.0
        self.samples.append((phase, symbol, ms))
        return ms, (tick is not None)

    def check(self, phase, symbol):
        """Probe; if the terminal is strained, pause and retry. False = give up."""
        ms, ok = self.probe(phase, symbol)
        if ok and ms <= SLOW_MS:
            return True
        for attempt in range(1, MAX_CONSEC_PAUSE + 1):
            self.events.append({
                "ts": dt.datetime.now().isoformat(timespec="seconds"),
                "phase": phase, "at_symbol": symbol,
                "latency_ms": round(ms, 1), "tick_ok": ok,
                "action": f"pause {PAUSE_SECONDS:g}s (attempt {attempt})",
            })
            print(f"    !! terminal slow ({ms:.0f} ms, tick_ok={ok}) at {symbol} "
                  f"- pausing {PAUSE_SECONDS:g}s [{attempt}/{MAX_CONSEC_PAUSE}]")
            time.sleep(PAUSE_SECONDS)
            ms, ok = self.probe(phase, symbol + "/recheck")
            if ok and ms <= SLOW_MS:
                self.events.append({
                    "ts": dt.datetime.now().isoformat(timespec="seconds"),
                    "phase": phase, "at_symbol": symbol,
                    "latency_ms": round(ms, 1), "tick_ok": ok,
                    "action": "recovered",
                })
                print(f"    .. recovered ({ms:.0f} ms)")
                return True
        self.events.append({
            "ts": dt.datetime.now().isoformat(timespec="seconds"),
            "phase": phase, "at_symbol": symbol,
            "latency_ms": round(ms, 1), "tick_ok": ok,
            "action": "ABORT - terminal did not recover",
        })
        self.aborted = True
        return False

    def stats(self):
        if not self.samples:
            return {}
        a = np.array([s[2] for s in self.samples])
        return {"n": len(a), "median_ms": float(np.median(a)),
                "p95_ms": float(np.percentile(a, 95)), "max_ms": float(a.max())}


def fetch_d1(name, count):
    """D1 rates. Returns (array_or_None, note).

    Smaller-count retries happen ONLY when the terminal rejected the request size
    itself (-2 'Invalid params'). A symbol that simply has no history returns None
    with a different error, and retrying it three more times just pays the server
    round-trip again - that alone dominated the runtime of an earlier version.
    """
    for cnt in (count, 5000, 1000, 300):
        if cnt > count:
            continue
        r = mt5.copy_rates_from_pos(name, mt5.TIMEFRAME_D1, 0, cnt)
        if r is not None and len(r):
            return r, ("" if cnt == count else f"bars_via_count_{cnt}")
        err = mt5.last_error()
        if not (err and err[0] == -2):
            return None, str(err)
    return None, str(mt5.last_error())


def atr_sma(df, period):
    """True Range, SMA-smoothed. Returns (latest, median of the series)."""
    prev_close = df["close"].shift(1)
    tr = pd.concat([df["high"] - df["low"],
                    (df["high"] - prev_close).abs(),
                    (df["low"] - prev_close).abs()], axis=1).max(axis=1)
    a = tr.rolling(period).mean()
    return a.iloc[-1], a.median()


def measure(s, bar_count, deep):
    """Measure one symbol. `deep` only changes how history is labelled."""
    name = s.name
    rec = {
        "symbol": name,
        "asset_class": s.path.split("\\")[1] if "\\" in s.path else "?",
        "path": s.path,
        "status": "ok",
        "error": "",
        "history_depth": "EXACT" if deep else "PROVISIONAL",
        "bars_requested": bar_count,
    }
    i = mt5.symbol_info(name)
    if i is None:
        rec["status"] = "no_symbol_info"
        rec["error"] = str(mt5.last_error())
        return rec

    tick = mt5.symbol_info_tick(name)
    bid = (tick.bid if tick and tick.bid else i.bid) or 0.0
    ask = (tick.ask if tick and tick.ask else i.ask) or 0.0
    if not (ask and bid):                      # one more chance for a slow subscriber
        mt5.symbol_select(name, True)
        time.sleep(0.4)
        i = mt5.symbol_info(name) or i
        tick = mt5.symbol_info_tick(name)
        bid = (tick.bid if tick and tick.bid else i.bid) or 0.0
        ask = (tick.ask if tick and tick.ask else i.ask) or 0.0

    # -- 1..13 static contract facts ------------------------------------------
    rec.update({
        "trade_mode": TRADE_MODES.get(i.trade_mode, i.trade_mode),
        "calc_mode": CALC_MODES.get(i.trade_calc_mode, i.trade_calc_mode),
        "bid": bid, "ask": ask,
        "spread_points_live": i.spread,
        "spread_price_live": (ask - bid) if (ask and bid) else np.nan,
        "digits": i.digits, "point": i.point,
        "volume_min": i.volume_min, "volume_step": i.volume_step,
        "volume_max": i.volume_max,
        "contract_size": i.trade_contract_size,
        "currency_profit": i.currency_profit,
        "currency_margin": i.currency_margin,
        "currency_base": i.currency_base,
        "swap_mode_code": i.swap_mode,
        "swap_mode": SWAP_MODES.get(i.swap_mode, f"UNKNOWN_{i.swap_mode}"),
        "swap_long": i.swap_long, "swap_short": i.swap_short,
        "triple_swap_day": DAYS.get(i.swap_rollover3days, i.swap_rollover3days),
        "raw_price_x_contract": ask * i.trade_contract_size * i.volume_min,
    })

    # -- 16..18 history (first: it also supplies the price fallback) ----------
    t0 = time.perf_counter()
    r, note = fetch_d1(name, bar_count)
    rec["hist_fetch_s"] = round(time.perf_counter() - t0, 2)
    if note:
        rec["error"] = (rec["error"] + " " + note).strip()
    d = None
    if r is not None and len(r):
        d = pd.DataFrame(r)
        d["dtime"] = pd.to_datetime(d["time"], unit="s")
        rec["d1_bars"] = len(d)
        rec["d1_start"] = d["dtime"].iloc[0].strftime("%Y-%m-%d")
        rec["d1_end"] = d["dtime"].iloc[-1].strftime("%Y-%m-%d")
        rec["d1_years"] = round(len(d) / 252.0, 2)
        # a shallow request that came back full may be truncated by the request
        rec["d1_bars_capped"] = (not deep) and len(d) >= bar_count
    else:
        rec["d1_bars"] = 0
        rec["d1_bars_capped"] = False

    # -- price resolution (A9) -------------------------------------------------
    rec["price_source"] = "live_tick"
    if not (ask and bid):
        if d is not None and len(d):
            ask = bid = float(d["close"].iloc[-1])
            rec["price_source"] = "last_d1_close(market_closed)"
            rec["bid"], rec["ask"] = bid, ask
            rec["raw_price_x_contract"] = ask * i.trade_contract_size * i.volume_min
        else:
            rec["status"] = "no_quote"
            rec["error"] = (rec["error"] + " no tick and no history").strip()
            return rec

    # -- symbols the broker does not let you trade at all ----------------------
    if i.trade_mode == 0:
        rec["status"] = "not_tradeable"
        rec["error"] = (rec["error"] + " trade_mode=DISABLED").strip()
        rec["long_available"] = rec["short_available"] = rec["both_sides"] = False
        return rec

    vmin = i.volume_min

    # -- 14 margin, both sides (A3) -------------------------------------------
    m_buy = mt5.order_calc_margin(mt5.ORDER_TYPE_BUY, name, vmin, ask)
    m_sell = mt5.order_calc_margin(mt5.ORDER_TYPE_SELL, name, vmin, bid)
    rec["margin_min_lot_buy_usd"] = m_buy
    rec["margin_min_lot_sell_usd"] = m_sell
    rec["long_available"] = m_buy is not None and i.trade_mode in (1, 4)
    rec["short_available"] = m_sell is not None and i.trade_mode in (2, 4)
    rec["both_sides"] = bool(rec["long_available"] and rec["short_available"])

    # -- 15 P&L for a 1% move, 23 economic notional (A2) -----------------------
    p1 = mt5.order_calc_profit(mt5.ORDER_TYPE_BUY, name, vmin, ask, ask * 1.01)
    rec["pl_1pct_move_min_lot_usd"] = p1
    if p1 is None or not np.isfinite(p1) or p1 <= 0:
        rec["status"] = "no_profit_calc"
        rec["error"] = (rec["error"] + " " + str(mt5.last_error())).strip()
        return rec
    notional = p1 / 0.01
    rec["notional_usd_min_lot"] = notional
    rec["notional_vs_raw_ratio"] = (notional / rec["raw_price_x_contract"]
                                    if rec["raw_price_x_contract"] else np.nan)

    if d is None or len(d) < ATR_PERIOD + 2:
        rec["status"] = "no_history"
        rec["error"] = (rec["error"] + f" only {rec['d1_bars']} D1 bars").strip()
        return rec

    atr, atr_med = atr_sma(d, ATR_PERIOD)
    if not np.isfinite(atr) or atr <= 0:
        rec["status"] = "bad_atr"
        return rec
    rec["atr20_d1_price"] = atr
    rec["atr20_d1_median_price"] = atr_med
    rec["atr20_pct_of_price"] = atr / ask * 100.0

    sp_med_pts = float(np.median(d["spread"].values)) if "spread" in d else np.nan
    rec["spread_points_med_d1"] = sp_med_pts
    rec["spread_price_med_d1"] = sp_med_pts * i.point if np.isfinite(sp_med_pts) else np.nan

    # -- 19..20 USD loss for 1 and 2 ATR at min lot (A7) -----------------------
    for k in (1.0, STOP_ATR_MULT):
        tgt = ask - k * atr
        if tgt > 0:
            pl = mt5.order_calc_profit(mt5.ORDER_TYPE_BUY, name, vmin, ask, tgt)
            meth = "order_calc_profit"
            if pl is None:
                pl = -notional * (k * atr / ask)
                meth = "linear_fallback(calc_returned_None)"
        else:
            pl = -notional * (k * atr / ask)
            meth = "linear_fallback(price<=0)"
        rec[f"loss_{int(k)}atr_min_lot_usd"] = abs(pl)
        if k == STOP_ATR_MULT:
            rec["atr_loss_method"] = meth

    # -- 21 spread as % of D1 ATR (A8) ----------------------------------------
    rec["spread_pct_of_atr_live"] = rec["spread_price_live"] / atr * 100.0
    rec["spread_pct_of_atr_med"] = (rec["spread_price_med_d1"] / atr * 100.0
                                    if np.isfinite(rec["spread_price_med_d1"]) else np.nan)

    # -- 22 annual overnight cost as % of notional (A4/A5) --------------------
    if i.swap_mode == 0:
        rec.update({"swap_converted": True, "swap_free": True,
                    "swap_usd_day_long": 0.0, "swap_usd_day_short": 0.0,
                    "annual_cost_long_pct": 0.0, "annual_cost_short_pct": 0.0})
    elif i.swap_mode == 1:
        rec["swap_free"] = False
        sl = mt5.order_calc_profit(mt5.ORDER_TYPE_BUY, name, vmin,
                                   ask, ask + i.swap_long * i.point)
        ss = mt5.order_calc_profit(mt5.ORDER_TYPE_BUY, name, vmin,
                                   ask, ask + i.swap_short * i.point)
        if sl is None or ss is None:
            rec["swap_converted"] = False
            rec["error"] = (rec["error"] + " swap_calc_none").strip()
        else:
            rec.update({"swap_converted": True,
                        "swap_usd_day_long": sl, "swap_usd_day_short": ss,
                        "annual_cost_long_pct": -(sl * 365.0) / notional * 100.0,
                        "annual_cost_short_pct": -(ss * 365.0) / notional * 100.0})
    else:
        rec["swap_converted"] = False
        rec["swap_free"] = False
        rec["error"] = (rec["error"] + f" unhandled_swap_mode_{i.swap_mode}").strip()

    # -- 24 risk feasibility at a 2-ATR stop ----------------------------------
    l2 = rec[f"loss_{int(STOP_ATR_MULT)}atr_min_lot_usd"]
    rec["risk_2atr_pct_of_balance"] = l2 / BALANCE * 100.0
    for c in RISK_CAPS:
        rec[f"fits_risk_{c*100:.2f}pct"] = bool(l2 <= BALANCE * c)

    # -- 25 exposure -----------------------------------------------------------
    rec["exposure_x_equity"] = notional / BALANCE
    for c in EXPO_CAPS:
        rec[f"under_{int(c)}x_exposure"] = bool(notional <= BALANCE * c)

    return rec


def spread_ratio(rec):
    """Median-based spread/ATR, falling back to the live snapshot."""
    v = rec.get("spread_pct_of_atr_med")
    try:
        v = float(v)
    except (TypeError, ValueError):
        v = np.nan
    if not np.isfinite(v):
        try:
            v = float(rec.get("spread_pct_of_atr_live"))
        except (TypeError, ValueError):
            v = np.nan
    return v


def is_survivor(rec):
    """Stage-2 survivor rule. Returns (bool, why_not)."""
    if rec.get("status") != "ok":
        return False, f"data:{rec.get('status')}"
    if (rec.get("d1_bars") or 0) < MIN_D1_BARS:
        return False, f"history_inadequate({int(rec.get('d1_bars') or 0)})"
    if rec.get("pl_1pct_move_min_lot_usd") in (None, 0):
        return False, "no_profit_calc"
    sr = spread_ratio(rec)
    if np.isfinite(sr) and sr > SPREAD_CAP_B_PCT:
        return False, f"spread_excessive({sr:.0f}%)"
    risk = rec.get("risk_2atr_pct_of_balance", np.inf)
    expo = rec.get("exposure_x_equity", np.inf)
    risk_ok = risk <= SURV_RISK_PCT
    expo_ok = expo <= SURV_EXPO_X
    if risk_ok and expo_ok:
        return True, "clean_pass"
    # allow exactly ONE near miss, by no more than 25%
    if risk_ok and expo <= SURV_EXPO_X * NEAR_MISS_SLACK:
        return True, f"near_miss_exposure({expo:.2f}x)"
    if expo_ok and risk <= SURV_RISK_PCT * NEAR_MISS_SLACK:
        return True, f"near_miss_risk({risk:.2f}%)"
    return False, f"risk{risk:.2f}%_expo{expo:.2f}x"


# ============================================================================= run
if not mt5.initialize(path=TERMINAL):
    raise SystemExit(f"initialize failed: {mt5.last_error()}")

acct = mt5.account_info()
term = mt5.terminal_info()
if acct is None:
    mt5.shutdown()
    raise SystemExit("no account_info - terminal not logged in")

CCY = acct.currency
print(f"terminal   : {term.name}  build {term.build}  connected={term.connected}")
print(f"account    : {acct.login} ({acct.server})  {acct.company}")
print(f"trade_mode : {['DEMO','CONTEST','REAL'][acct.trade_mode]}   leverage 1:{acct.leverage}")
print(f"equity     : {acct.equity:,.2f} {CCY}   (census uses reference balance ${BALANCE:,.2f})")
if CCY != "USD":
    print(f"!! WARNING deposit currency is {CCY}; all 'USD' columns are really {CCY}.")

all_syms = mt5.symbols_get()
originally_visible = {s.name for s in all_syms if s.visible}
print(f"symbols    : {len(all_syms)} total, {len(originally_visible)} visible, "
      f"{len(all_syms)-len(originally_visible)} hidden -> all scanned")

health = TerminalHealth()
made_visible, select_failed = [], {}
rows1, rows2 = [], []
t_stage1 = t_stage2 = 0.0
stage2_syms = []

try:
    # ---------------------------------------------------------------- subscribe
    to_add = [s.name for s in all_syms if not s.visible]
    print(f"\nsubscribing {len(to_add)} hidden symbols...")
    for name in to_add:
        if mt5.symbol_select(name, True):
            made_visible.append(name)
        else:
            select_failed[name] = str(mt5.last_error())
    print(f"  subscribed {len(made_visible)}, failed {len(select_failed)}")
    print(f"  waiting {SETTLE_SECONDS:g}s for quotes and history to populate...")
    time.sleep(SETTLE_SECONDS)

    # ------------------------------------------------------------------ STAGE 1
    print(f"\n=== STAGE 1: shallow screen, <= {SHALLOW_BARS} D1 bars, {len(all_syms)} symbols ===")
    s1_start = time.perf_counter()
    for n, s in enumerate(all_syms, 1):
        if s.name in select_failed:
            rows1.append({"symbol": s.name, "status": "select_failed",
                          "error": select_failed[s.name], "history_depth": "NONE",
                          "asset_class": s.path.split("\\")[1] if "\\" in s.path else "?",
                          "path": s.path})
            continue
        if n % HEALTH_EVERY == 0 and not health.check("stage1", s.name):
            print("  !! aborting stage 1 - terminal not recovering")
            break
        try:
            rows1.append(measure(s, SHALLOW_BARS, deep=False))
        except Exception as ex:
            rows1.append({"symbol": s.name, "status": "exception",
                          "error": f"{type(ex).__name__}: {ex}",
                          "asset_class": s.path.split("\\")[1] if "\\" in s.path else "?",
                          "path": s.path, "history_depth": "NONE"})
        time.sleep(DELAY_STAGE1)
        if n % 50 == 0:
            print(f"  stage1 {n}/{len(all_syms)}  ({time.perf_counter()-s1_start:.0f}s elapsed)")
    t_stage1 = time.perf_counter() - s1_start
    print(f"  stage 1 done in {t_stage1/60:.1f} min")

    # -------------------------------------------------------- pick the survivors
    for rec in rows1:
        ok, why = is_survivor(rec)
        rec["stage2_selected"] = ok
        rec["stage2_reason"] = why
        if ok:
            stage2_syms.append(rec["symbol"])
    print(f"\n  survivors for stage 2: {len(stage2_syms)} of {len(rows1)}")

    # ------------------------------------------------------------------ STAGE 2
    by_name = {s.name: s for s in all_syms}
    if stage2_syms and not health.aborted:
        print(f"\n=== STAGE 2: full depth ({DEEP_BARS} bars) for {len(stage2_syms)} survivors ===")
        s2_start = time.perf_counter()
        for n, name in enumerate(stage2_syms, 1):
            if not health.check("stage2", name):
                print("  !! aborting stage 2 - terminal not recovering")
                break
            try:
                rows2.append(measure(by_name[name], DEEP_BARS, deep=True))
            except Exception as ex:
                rows2.append({"symbol": name, "status": "exception",
                              "error": f"{type(ex).__name__}: {ex}",
                              "history_depth": "PROVISIONAL"})
            time.sleep(DELAY_STAGE2)
            if n % 10 == 0:
                print(f"  stage2 {n}/{len(stage2_syms)}  "
                      f"({time.perf_counter()-s2_start:.0f}s elapsed)")
        t_stage2 = time.perf_counter() - s2_start
        print(f"  stage 2 done in {t_stage2/60:.1f} min")

finally:
    # Market Watch must be restored even if this aborts: a live bot uses this
    # terminal, and leaving 162 extra symbols subscribed is a side effect the
    # census has no right to leave behind.
    print(f"\nrestoring Market Watch: hiding {len(made_visible)} symbols this scan added "
          f"({len(originally_visible)} already-visible symbols untouched)")
    for name in made_visible:
        mt5.symbol_select(name, False)
    still = {s.name for s in mt5.symbols_get() if s.visible}
    leaked = still - originally_visible
    missing = originally_visible - still
    print(f"  visible now {len(still)} (baseline {len(originally_visible)}); "
          f"leaked {len(leaked)}, missing-from-baseline {len(missing)}")
    mt5.shutdown()

# ============================================================================= merge
df = pd.DataFrame(rows1)
deep = pd.DataFrame(rows2)
n_screened = len(df)

if len(deep):
    # stage-2 rows replace their stage-1 counterparts wholesale
    keep_cols = [c for c in df.columns if c in ("stage2_selected", "stage2_reason")]
    meta = df.set_index("symbol")[keep_cols]
    deep = deep.set_index("symbol").join(meta).reset_index()
    df = pd.concat([df[~df["symbol"].isin(deep["symbol"])], deep],
                   ignore_index=True, sort=False)

# ============================================================================= classify
ok = df["status"] == "ok"
has_hist = df.get("d1_bars", pd.Series(0, index=df.index)).fillna(0) >= MIN_D1_BARS
both = df.get("both_sides", pd.Series(False, index=df.index)).fillna(False).astype(bool)
risk_ok_A = df.get(f"fits_risk_{RISK_CAPS[-1]*100:.2f}pct",
                   pd.Series(False, index=df.index)).fillna(False).astype(bool)
expo_ok_A = df.get(f"under_{int(EXPO_CAPS[-1])}x_exposure",
                   pd.Series(False, index=df.index)).fillna(False).astype(bool)

sp = df.get("spread_pct_of_atr_med", pd.Series(np.nan, index=df.index))
sp = sp.fillna(df.get("spread_pct_of_atr_live", pd.Series(np.nan, index=df.index)))
spread_ok_A = sp <= SPREAD_CAP_A_PCT
spread_ok_B = sp <= SPREAD_CAP_B_PCT

risk_ok_B = df.get("risk_2atr_pct_of_balance", pd.Series(np.inf, index=df.index)) \
              .fillna(np.inf) <= (RISK_CAPS[-1] * 100 * GROUP_B_SLACK)
expo_ok_B = df.get("exposure_x_equity", pd.Series(np.inf, index=df.index)) \
              .fillna(np.inf) <= (EXPO_CAPS[-1] * GROUP_B_SLACK)

is_A = ok & has_hist & both & risk_ok_A & expo_ok_A & spread_ok_A
is_B = ok & has_hist & both & risk_ok_B & expo_ok_B & spread_ok_B & ~is_A
df["group"] = np.where(is_A, "A_TRADEABLE_NOW",
              np.where(is_B, "B_POSSIBLY_TRADEABLE", "C_NOT_TRADEABLE"))


def _num(r, key):
    """Numeric cell as float, missing -> NaN.

    Deliberately not `r.get(k) or default`: a legitimate 0.0 is falsy, and that
    idiom would silently rewrite a zero-risk symbol into an infinite-risk one.
    """
    try:
        return float(r.get(key))
    except (TypeError, ValueError):
        return np.nan


def fail_reason(r):
    if r["group"] != "C_NOT_TRADEABLE":
        return ""
    if r["status"] != "ok":
        return f"data:{r['status']}"
    why = []
    if not r.get("both_sides", False):
        why.append(f"not_tradeable_both_sides({r.get('trade_mode')})")
    bars = _num(r, "d1_bars")
    if not (bars >= MIN_D1_BARS):
        why.append(f"history_inadequate({0 if np.isnan(bars) else int(bars)}d1_bars)")
    risk = _num(r, "risk_2atr_pct_of_balance")
    if np.isnan(risk) or risk > RISK_CAPS[-1] * 100 * GROUP_B_SLACK:
        why.append(f"min_lot_risk_{risk:.1f}pct")
    expo = _num(r, "exposure_x_equity")
    if np.isnan(expo) or expo > EXPO_CAPS[-1] * GROUP_B_SLACK:
        why.append(f"exposure_{expo:.1f}x")
    s = _num(r, "spread_pct_of_atr_med")
    if np.isnan(s):
        s = _num(r, "spread_pct_of_atr_live")
    if np.isfinite(s) and s > SPREAD_CAP_B_PCT:
        why.append(f"spread_{s:.0f}pct_of_atr")
    return ";".join(why) or "borderline"


df["fail_reason"] = df.apply(fail_reason, axis=1)

# ============================================================================= rank A
A = df[df["group"] == "A_TRADEABLE_NOW"].copy()
if len(A):
    A["holding_cost_best_side_pct"] = A[["annual_cost_long_pct",
                                         "annual_cost_short_pct"]].min(axis=1)
    A["r_spread"] = A["spread_pct_of_atr_med"].fillna(A["spread_pct_of_atr_live"]).rank()
    A["r_cost"] = A["holding_cost_best_side_pct"].rank()
    A["r_hist"] = A["d1_bars"].rank(ascending=False)
    A["r_risk"] = A["risk_2atr_pct_of_balance"].rank()
    A["rank_score"] = A[["r_spread", "r_cost", "r_hist", "r_risk"]].mean(axis=1)
    A = A.sort_values(["rank_score", "symbol"])
    A["rank"] = range(1, len(A) + 1)
    df = df.merge(A[["symbol", "rank", "rank_score", "holding_cost_best_side_pct"]],
                  on="symbol", how="left")

sort_cols = ["group"] + (["rank"] if "rank" in df.columns else ["symbol"])
df = df.sort_values(sort_cols, na_position="last")
df.to_csv(CSV_PATH, index=False)

# ============================================================================= report
hs = health.stats()
n_stage2 = int((df["history_depth"] == "EXACT").sum())
out = []
w = out.append
w("=" * 100)
w("TASK 001 - EXNESS FEASIBILITY CENSUS")
w("=" * 100)
w(f"generated        : {dt.datetime.now():%Y-%m-%d %H:%M:%S}")
w(f"terminal         : build {term.build}  path {term.path}")
w(f"account          : {acct.login}  {acct.server}  ({acct.company})")
w(f"account type     : {['DEMO','CONTEST','REAL'][acct.trade_mode]}  leverage 1:{acct.leverage}")
w(f"deposit currency : {CCY}   live equity {acct.equity:,.2f}")
w(f"reference balance: ${BALANCE:,.2f}  (the figure named by the task)")
w("")
w("SCAN SUMMARY")
w(f"  symbols on account      : {len(all_syms)} (visible {len(originally_visible)}, "
  f"hidden {len(all_syms)-len(originally_visible)}) - ALL screened")
w(f"  screened in stage 1     : {n_screened}   (<= {SHALLOW_BARS} D1 bars each)")
w(f"  reached stage 2         : {len(stage2_syms)}   (full depth, {DEEP_BARS} bars requested)")
w(f"  stage-2 rows completed  : {len(rows2)}")
w(f"  stage 1 duration        : {t_stage1/60:.1f} min")
w(f"  stage 2 duration        : {t_stage2/60:.1f} min")
w(f"  TOTAL download time     : {(t_stage1+t_stage2)/60:.1f} min")
w(f"  measured cleanly        : {int(ok.sum())}")
w(f"  failed to measure       : {int((~ok).sum())}")
w("")
w("EXACT vs PROVISIONAL")
w(f"  EXACT history (stage 2)      : {n_stage2} symbols - d1_start, d1_bars, ATR(20)")
w(f"                                 and every history-dependent figure are final.")
w(f"  PROVISIONAL (stage 1 only)   : {int((df['history_depth']=='PROVISIONAL').sum())} symbols -")
w(f"                                 d1_start is a LOWER BOUND and d1_bars is capped at")
w(f"                                 {SHALLOW_BARS}. Their sizing, spread, swap, risk and")
w(f"                                 exposure figures are still exact; only the depth of")
w(f"                                 history is unresolved, and every one of them was")
w(f"                                 excluded for a reason that history cannot change.")
capped = int(df.get("d1_bars_capped", pd.Series(False, index=df.index)).fillna(False).sum())
w(f"  provisional rows whose bar count hit the {SHALLOW_BARS}-bar ceiling: {capped}")
w("")
w("TERMINAL CONTENTION")
if hs:
    w(f"  latency probes          : {hs['n']}  median {hs['median_ms']:.0f} ms, "
      f"p95 {hs['p95_ms']:.0f} ms, max {hs['max_ms']:.0f} ms")
w(f"  slow-terminal pauses    : {len([e for e in health.events if 'pause' in e['action']])}")
w(f"  aborted for contention  : {health.aborted}")
if health.events:
    w("  interruption log:")
    for e in health.events:
        w(f"    {e['ts']}  {e['phase']:7s} at {e['at_symbol']:16s} "
          f"{e['latency_ms']:8.1f} ms  {e['action']}")
    w("  -> results gathered after any pause are unaffected: the census waits for the")
    w("     terminal to answer normally again before measuring anything further.")
else:
    w("  no contention detected: the terminal answered every probe within "
      f"{SLOW_MS:.0f} ms, so no result was taken from a strained terminal.")
w("")
w("PARAMETERS")
w(f"  ATR              : SMA of True Range, period {ATR_PERIOD}, timeframe D1")
w(f"  stop assumed     : {STOP_ATR_MULT:g} x ATR(20) D1")
w(f"  risk caps        : {', '.join(f'{c*100:.2f}%' for c in RISK_CAPS)} of ${BALANCE:,.0f} "
  f"(= {', '.join(f'${BALANCE*c:.2f}' for c in RISK_CAPS)})")
w(f"  exposure caps    : {', '.join(f'{int(c)}x' for c in EXPO_CAPS)} of ${BALANCE:,.0f}")
w(f"  history adequate : >= {MIN_D1_BARS} D1 bars")
w(f"  spread ceiling   : group A <= {SPREAD_CAP_A_PCT:g}% of D1 ATR, B <= {SPREAD_CAP_B_PCT:g}%")
w(f"  stage-2 rule     : >= {MIN_D1_BARS} bars, spread <= {SPREAD_CAP_B_PCT:g}% of ATR, and")
w(f"                     (risk <= {SURV_RISK_PCT:.2f}% AND expo <= {SURV_EXPO_X:.2f}x), or ONE")
w(f"                     of them missed by <= {(NEAR_MISS_SLACK-1)*100:.0f}% "
  f"(risk <= {SURV_RISK_PCT*NEAR_MISS_SLACK:.2f}% or expo <= {SURV_EXPO_X*NEAR_MISS_SLACK:.2f}x)")
w("")
w("FORMULAS")
w("  notional_usd        = order_calc_profit(BUY, sym, vol_min, ask, ask*1.01) / 0.01")
w("  margin_usd          = order_calc_margin(BUY, sym, vol_min, ask)")
w("  pl_1pct             = order_calc_profit(BUY, sym, vol_min, ask, ask*1.01)")
w("  loss_k_atr          = |order_calc_profit(BUY, sym, vol_min, ask, ask - k*ATR20)|")
w("  spread_pct_of_atr   = (ask-bid) / ATR20_D1 * 100")
w("  swap_usd_day_side   = order_calc_profit(BUY, sym, vol_min, ask, ask + swap_pts_side*point)")
w("  annual_cost_pct     = -(swap_usd_day * 365) / notional_usd * 100   (positive = you pay)")
w(f"  risk_2atr_pct       = loss_2_atr / {BALANCE:.0f} * 100")
w(f"  exposure_x_equity   = notional_usd / {BALANCE:.0f}")
w("")
w("GROUP COUNTS")
for g in ["A_TRADEABLE_NOW", "B_POSSIBLY_TRADEABLE", "C_NOT_TRADEABLE"]:
    w(f"  {g:24s} {int((df['group']==g).sum()):4d}")
w("")
w("BY ASSET CLASS")
w(df.pivot_table(index="asset_class", columns="group", values="symbol",
                 aggfunc="count", fill_value=0).to_string())
w("")
w("=" * 100)
w("GROUP A - TRADEABLE NOW  (ranked: spread/ATR, holding cost, history, min-lot risk)")
w("=" * 100)
if len(A):
    cols = ["rank", "symbol", "asset_class", "volume_min", "notional_usd_min_lot",
            "exposure_x_equity", "atr20_d1_price", "loss_2atr_min_lot_usd",
            "risk_2atr_pct_of_balance", "spread_pct_of_atr_med",
            "annual_cost_long_pct", "annual_cost_short_pct", "d1_bars", "d1_start",
            "margin_min_lot_buy_usd"]
    show = A.sort_values("rank")[cols].rename(columns={
        "notional_usd_min_lot": "notional$", "exposure_x_equity": "expo_x",
        "atr20_d1_price": "atr20", "loss_2atr_min_lot_usd": "loss2atr$",
        "risk_2atr_pct_of_balance": "risk%", "spread_pct_of_atr_med": "sprd%atr",
        "annual_cost_long_pct": "cost_L%/y", "annual_cost_short_pct": "cost_S%/y",
        "margin_min_lot_buy_usd": "margin$"})
    w(show.to_string(index=False, float_format=lambda x: f"{x:,.4g}"))
    w("")
    w("TOP 20 TRADEABLE INSTRUMENTS")
    for _, r in A.sort_values("rank").head(20).iterrows():
        w(f"  {int(r['rank']):3d}. {r['symbol']:14s} {r['asset_class']:16s} "
          f"min lot {r['volume_min']:<7g} notional ${r['notional_usd_min_lot']:>10,.0f} "
          f"({r['exposure_x_equity']:.2f}x)  2-ATR risk ${r['loss_2atr_min_lot_usd']:>7,.2f} "
          f"({r['risk_2atr_pct_of_balance']:.2f}%)  spread {r['spread_pct_of_atr_med']:.1f}% of ATR")
else:
    w("  NONE")
w("")
w("=" * 100)
w("GROUP B - POSSIBLY TRADEABLE  (needs a larger balance or another account type)")
w("=" * 100)
B = df[df["group"] == "B_POSSIBLY_TRADEABLE"].copy()
if len(B):
    B = B.sort_values("risk_2atr_pct_of_balance")
    w(B[["symbol", "asset_class", "volume_min", "notional_usd_min_lot",
         "exposure_x_equity", "loss_2atr_min_lot_usd", "risk_2atr_pct_of_balance",
         "spread_pct_of_atr_med", "d1_bars", "history_depth"]].to_string(
             index=False, float_format=lambda x: f"{x:,.4g}"))
    w("")
    w(f"  balance that would put each inside the {RISK_CAPS[-1]*100:.2f}% risk cap:")
    for _, r in B.sort_values("loss_2atr_min_lot_usd").head(30).iterrows():
        w(f"    {r['symbol']:14s} ${r['loss_2atr_min_lot_usd']/RISK_CAPS[-1]:>12,.0f}")
else:
    w("  NONE")
w("")
w("=" * 100)
w("GROUP C - NOT TRADEABLE  (reasons tallied)")
w("=" * 100)
C = df[df["group"] == "C_NOT_TRADEABLE"]
reasons = {}
for r in C["fail_reason"]:
    for part in str(r).split(";"):
        if not part:
            continue
        key = part.split("(")[0]
        if key.startswith("min_lot_risk"):
            key = "min_lot_risk_too_large"
        elif key.startswith("spread_"):
            key = "spread_too_expensive"
        elif key.startswith("exposure_"):
            key = "exposure_too_large"
        reasons[key] = reasons.get(key, 0) + 1
for k, v in sorted(reasons.items(), key=lambda x: -x[1]):
    w(f"  {k:42s} {v:4d}")
w("")
w("  (a symbol can fail for more than one reason, so these sum to more than the group)")
w("")
w("=" * 100)
w("ERRORS AND MISSING DATA")
w("=" * 100)
bad = df[df["status"] != "ok"]
w(f"  symbols that could not be fully measured: {len(bad)}")
for st, grp in bad.groupby("status"):
    w(f"    {st:20s} {len(grp):4d}   e.g. {', '.join(grp['symbol'].head(6))}")
if "swap_converted" in df.columns:
    unconv = df[df["swap_converted"] == False]                      # noqa: E712
    w(f"  symbols whose swap could NOT be converted: {len(unconv)}")
    if len(unconv):
        w(f"    {', '.join(unconv['symbol'].head(20))}")
if "atr_loss_method" in df.columns:
    fb = df[df["atr_loss_method"].astype(str).str.startswith("linear_fallback")]
    w(f"  symbols using the linear ATR-loss fallback: {len(fb)}")
    if len(fb):
        w(f"    {', '.join(fb['symbol'].head(20))}")
if "price_source" in df.columns:
    cl = df[df["price_source"].astype(str).str.startswith("last_d1_close")]
    w(f"  symbols priced from the last D1 close (market closed): {len(cl)}")
if "swap_mode" in df.columns:
    w(f"  swap modes seen (confirmed before conversion): "
      f"{dict(df[df['status']=='ok']['swap_mode'].value_counts())}")
w("")
w(f"full table -> {CSV_PATH}")

text = "\n".join(out)
with open(TXT_PATH, "w", encoding="utf-8") as f:
    f.write(text + "\n")
print()
print(text)
