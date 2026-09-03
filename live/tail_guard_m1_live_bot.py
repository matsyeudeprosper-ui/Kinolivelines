"""tail_guard_m1_live_bot.py - "Tail Guard", M1, LIVE account 134499778.

Deployed 2026-08-14 at the user's explicit instruction, after being warned
this is UNVALIDATED at this sample size (34 trades, 0 losses, ~28 days of
M1 backtest - a "1-in-100" claim needs hundreds of trades to mean anything,
not 34). User confirmed they understand the risk and want it live anyway.
See CANDIDATE_TAIL_GUARD.md for the validated H1 version (multi-anchor,
5 independent periods, 0/5 died) and the M1 preliminary look this is based
on. harvest_live_bot.py (the previous live strategy) was moved to demo -
see harvest_live_demo_bot.py - to make room for this on the live account.

THE RULE - deliberately much simpler than harvest_live_bot.py's recovery
machine, because this design has no recovery/basket/daily-protection layer
by construction (that IS the tested shape - see CANDIDATE_TAIL_GUARD.md):
  1. M1 reversal brick (50pt, 2-brick reversal) -> if flat, open ONE
     position, 0.01 lots.
  2. TP = $1.00 flat (100 points). SL = the 1-in-100 rarity percentile of
     historical adverse excursion, calibrated from M1 history available at
     startup (recalibrated once per UTC day thereafter - see CALIBRATE()).
  3. Both TP and SL are broker-side prices on the order itself. No manual
     exit logic, no recovery, no basket, no daily loss limit - MT5 executes
     the bracket automatically. This is a real difference from every other
     bot in this project and is intentional: it is what was backtested.
  4. cap=1: never open a second position while one is open. Concurrency was
     tested and rejected (correlated tail risk killed the account in 1 of 5
     independent history segments) - see CANDIDATE_TAIL_GUARD.md.

KNOWN, ACCEPTED RISK: individual trades can take weeks to months to resolve
(observed up to 135 days in the H1 backtest). During that time this bot is
flat-blocked and will not open anything else. That is by design, not a bug.

KNOWN OPEN WEAKNESS (see CANDIDATE_TAIL_GUARD.md): a random-entry control
performed comparably to the real signal on one test split. The case that
the entry timing itself is adding value over the TP:SL shape alone is not
fully proven.
"""
import json, os, sys, time
from datetime import datetime, timedelta

import MetaTrader5 as mt5

TERMINAL   = r"C:\Projects\MT5-KinoliveTrader\terminal64.exe"   # the LIVE install
LOGIN      = 134499778
SYMBOL     = "BTCUSDm"
# Lot size scaled up 2026-08-15 at the user's instruction: TP/SL POINT
# distances are unchanged (100 pts / 44,439 pts), only the dollar value per
# point changes, so TP goes from $1.00 -> $3.00 and SL from $444.39 ->
# $1,333.17 automatically (both = points * LOTS * $1). User was told and
# confirmed understanding that $1,333.17 is >11x the account balance
# (~$117.65) - in practice the broker's margin call / stop-out would force-
# close a real adverse move long before the SL price is ever reached, so
# the true worst case is "whatever the broker allows before margin call",
# not the calibrated SL amount.
LOTS       = 0.05
MAGIC      = 770492            # distinct from every other bot on either account
BRICK      = 50.0
REVERSAL   = 2
TP_PTS     = 100.0             # distance NEVER changes - $ value comes only
                                 # from LOTS (100pts * LOTS * $1/point/lot).
                                 # At LOTS=0.03 this is $3.00.

# SL - user's decision 2026-08-14: use the WORST (widest) 1-in-100 SL seen
# across the 5 validated H1 multi-anchor test periods ($444.39, segment 4 -
# see CANDIDATE_TAIL_GUARD.md), instead of trusting the M1-specific
# calibration, which was only ever measured from ~55 days / ~1,300 signals -
# far too little to estimate a genuine rare-event tail. The H1 multi-anchor
# validation is the only properly-tested number this project has for this
# strategy shape, so it is used here as the conservative, validated choice.
# No more daily recalibration - this is now a fixed constant.
SL_USD_FIXED = 444.39
PT         = 0.01              # $ per point at 0.01 lots (1 point = $1 raw
                                 # price move here, same convention as the
                                 # backtest scripts - points = USD / PT)

# "Half Trail" - deployed 2026-08-17 at the user's explicit instruction
# ("upgrade the live bot ... I understand the risk"), after backtesting on
# the full 2-year M1 window: net $2,352.50 vs $1,081.10 baseline (~2.2x),
# same entry signal, same TP. See memory: kinolivelines-tailguard-halftrail-
# candidate. Trails the SL down once the account has BANKED (realized,
# closed-trade) profit to spare:
#   realized_profit_peak = highest cumulative realized P&L ever reached
#   since this was deployed - one-way ratchet, only updated when a trade
#   closes, never on floating/unrealized P&L.
#   Below 2x floor of realized_profit_peak: SL stays at the fixed default
#   above (SL_USD_FIXED). At or above it: SL tightens to
#   max(realized_profit_peak / 2, floor) - guaranteeing the account can
#   never give back more than half of its peak banked profit once active.
# Honest, backtested characteristics (see memory file for full detail):
#  - the FIRST disaster after deployment is always unprotected (needs
#    pre-existing banked profit to work with) - realized_cum starts at
#    0.0 today, so this behaves EXACTLY like the old fixed-SL bot until
#    $800 of new profit is banked from this point forward.
#  - it is insurance, not a free edge: it can lose a little in an
#    otherwise-quiet stretch with no real disaster to protect against
#    (confirmed on one historical segment), and only pays off big when a
#    genuine disaster lands on a trade the base strategy would have taken
#    anyway. Net positive over the full 2-year backtest, not guaranteed
#    every quarter.
HALFTRAIL_FLOOR      = 400.0
HALFTRAIL_ACTIVATION = 2.0 * HALFTRAIL_FLOOR

# DISABLED 2026-08-17, same day as the RELATIVE_SL_PCT deploy below. Once
# the relative SL replaced the old fixed SL, backtested the COMBINATION
# (relative SL as the default branch + Half Trail as the active-branch
# override, exactly as both were live together for ~1hr) over the full
# 4-year window and found it WORSE than the relative SL alone:
#   relative SL alone:  1,777 trades, 4 losses,  net $3,802.70
#   combined (both):    3,157 trades, 24 losses, net $2,475.00 (-$1,327.70)
# Mechanism: the relative SL resolves trades fast enough that realized
# profit crosses the $800 activation threshold often; once active, Half
# Trail tightens the SL to ~$545-590 - tighter than the already well-
# calibrated 40% relative SL (confirmed via random-entry control to have a
# real edge), so it clips trades that were fine, turning 4 losses into 24.
# Same "stacking backfires" pattern as Half Trail + Storm Shield earlier
# in the project. realized_cum/realized_profit_peak are still tracked and
# logged below for reference - just no longer used to change the SL. See
# memory kinolivelines-tailguard-halftrail-candidate for the full record.
HALFTRAIL_ENABLED = False

# Relative SL - deployed 2026-08-17, same day as the 4-year backtest that
# found the fixed SL_USD_FIXED above made the base strategy net NEGATIVE
# over 4 years (-$1,435.85). Root cause: SL_USD_FIXED is a FIXED NOMINAL
# point distance, but BTC's own price moved 5-6x across the backtest
# ($15,497 -> $126,198), so a "fixed" $ SL is a wildly different relative
# risk depending on when a trade opens (158.7% of price at BTC=$28k vs
# 39.0% of price at BTC=$114k). All 3 historical disasters were positions
# held 100-250 days that got run over by one of BTC's own normal multi-
# month bull/bear cycles - not sudden crashes - because the SL didn't keep
# pace with price. See memory: kinolivelines-tailguard-relative-sl-
# candidate for the full writeup and CANDIDATE_TAIL_GUARD.md.
#
# Fix: the DEFAULT SL (used whenever Half Trail is inactive) is now a
# PERCENTAGE of entry price instead of a fixed point count:
#   default SL = entry_price * RELATIVE_SL_PCT
# 4-year M1 backtest found 35-45% a stable, robust plateau; 40% is the
# centered pick (net +$3,802.70 over 4yr vs -$1,435.85 for the old fixed
# SL, same entry signal, same TP). Half Trail's ACTIVE-branch formula is
# UNCHANGED (it's an absolute $ guarantee on banked profit, not something
# that needs to scale with price) - this only replaces the INACTIVE/
# default branch. SL_USD_FIXED above is kept only as a historical
# reference value, no longer used to size real trades.
RELATIVE_SL_PCT = 0.40

# Breakeven Ratchet - deployed 2026-08-18 at the user's explicit instruction
# ("deploy it to live now. i understand the risk"), after a CORRECTED,
# continuous (no resets) 6-year M1 backtest found a genuine, wide, flat
# plateau: trigger 26-38% of the default SL width gives the exact same
# result (net $2,168.41 vs $692.34 baseline, ~3.1x) across all 13 points
# tested in 1% steps - the widest, flattest, most trustworthy plateau found
# in this whole project. See memory: kinolivelines-tailguard-breakeven-
# ratchet-candidate for the full corrected writeup. An earlier "dual-cap"
# version tested the SAME day looked even better but turned out to be a
# methodology artifact (per-segment signal resets that don't match how this
# bot actually runs) and was discarded - this is the simpler, correctly-
# validated version: cap = 100% of the normal default width, not below it.
#   default_sl_usd = entry_price * RELATIVE_SL_PCT * LOTS   (unchanged)
#   trigger = RATCHET_TRIGGER_FRAC * default_sl_usd
#   realized_cum (reused from the existing Half Trail state field, reset to
#     0.0 at this deploy - see main()) = cumulative realized P&L since
#     deployment, goes UP on wins and DOWN on losses (not a one-way ratchet)
#   If realized_cum >= trigger: SL = min(realized_cum, default_sl_usd) -
#     tightens to whatever's currently banked, capped at the normal width
#   Otherwise: SL = default_sl_usd (unchanged from today's current behavior)
# HONEST KNOWN LIMITS (full detail in the memory file):
#  - the FIRST disaster after deployment is always unprotected, same
#    limitation as Half Trail - needs pre-existing banked profit to work
#    with. realized_cum starts at 0.0 today.
#  - backtested on ONE historical 6-year run only, not forward-validated.
#    An era-by-era breakdown of that one run found the gain concentrated in
#    a single 2-year stretch (2022-2024) and exactly ZERO effect (neither
#    helped nor hurt - byte-identical trades) in the most recent stretch
#    (2024-2026). Not guaranteed to help in any specific future stretch,
#    though the worst case found in testing so far is "does nothing", not
#    "makes it worse" (unlike the discarded dual-cap version, which always
#    had a losing era).
RATCHET_ENABLED = True
RATCHET_TRIGGER_FRAC = 0.30
RATCHET_CAP_FRAC = 1.00

# "Golden Lane" entry filter - deployed 2026-08-19 at the user's explicit
# instruction ("deploy it to live now. i understand the risk"), same day it
# was found. Combines two backtested candle/trend patterns (see memory:
# kinolivelines-tailguard-candle-pattern-edges for the full search):
#   "Trend Lane": the last CLOSED M15 candle's close is at or below its own
#     21-period EMA (computed causally from M15 closes, same EMA formula
#     already used elsewhere in this file for journaling).
#   "M1-fresh": the M1 signal candle (the bar whose close triggered the
#     brick-reversal) does NOT continue the same-direction color as the M1
#     candle immediately before it - i.e. no 2-bar same-direction run going
#     into the entry.
# A signal only opens a trade if BOTH hold at once. Backtested (6yr
# continuous, no-reset, same ratchet rule as above): the combined bucket
# (379 of 2,724 trades, ~14%) had ZERO losses, checked separately across
# all 3 independent 2-year eras (2020-22, 2022-24, 2024-26) - not just in
# the aggregate. Captured 88% of the strategy's total historical profit
# from 14% of the trades.
# HONEST KNOWN TRADE-OFF: this is a hard filter, not a size/SL adjustment -
# roughly 6 of every 7 signals get skipped entirely, so trading frequency
# drops sharply. The skipped bucket was NOT purely a loser on its own
# (it was still net +$263 over 6yr, just carrying all 16 historical
# losses) - so this trades a small amount of raw backtested profit for a
# large reduction in historical loss count, not a strict improvement on
# every axis. NOT forward-validated - all evidence is this one historical
# backtest, same unvalidated-but-carefully-tested status as every other
# candidate deployed live in this project.
GOLDEN_LANE_ENABLED = False  # DISABLED 2026-08-19, same day as deploy - see comment below.
GOLDEN_LANE_EMA_PERIOD = 21
# CRITICAL METHODOLOGY BUG FOUND 2026-08-19, hours after deploying this:
# every backtest supporting Golden Lane (and every other candle-pattern
# finding from this same session) computed the trend_below/m1_fresh flags
# for EVERY signal in an UNFILTERED run, then sorted trades into buckets
# AFTER THE FACT - it never actually tested what happens when you SKIP the
# blocked signals in real time. Skipping a trade frees the bot up to catch
# the NEXT signal sooner (cap=1), which changes the entire subsequent
# sequence of trades - a true gated-entry simulation is NOT the same as a
# post-hoc subset of an unfiltered run. Ran the real, correctly-gated
# simulation and got the OPPOSITE result: Ratchet+GoldenLane nets -$813.53
# over 6yr (17 losses, worse than Ratchet-alone's 16, worse max drawdown
# $2,883.53 vs $1,996.63) versus Ratchet-alone's proven +$2,158.41. See
# memory kinolivelines-tailguard-candle-pattern-edges for the full
# correction record. Do not re-enable without a properly-gated backtest.

SL_PCTILE  = 99                # "1-in-100" rarity threshold
CALIBRATE_LOOKAHEAD_MIN = 2000  # forward window used WITHIN the calibration
                                 # history only - never applied to a live decision
POLL       = 20
FRESH_MIN  = 6
MAX_FAILS  = 10

# Safety drawdown cutoff - user's instruction 2026-08-15, on top of the wide
# rare-event SL (which is really a margin-call risk, not a practical stop -
# see the LOT SIZE warning below). This is a PRACTICAL circuit breaker:
#   FLOOR = $100 FIXED, absolute, independent of balance - not "$100 below
#   wherever the balance happens to be". As long as equity >= $100, keep
#   trading.
#   Once peak profit-from-baseline exceeds $100, the floor switches to
#   trailing: floor = peak - 100 (so it rises to keep locking in $100 of
#   whatever has been banked, same shape as before but starting from a
#   flat $100 instead of "$100 under the current balance").
# Trips -> closes any open position immediately and stops opening new ones
# until manually cleared.
SAFETY_FLOOR_INITIAL = 100.0

# SELL-only EMA trend-alignment filter - SHADOW MODE ONLY (2026-08-16).
# Not enforced - never blocks or gates a real trade. Logs, for every new
# signal, what this candidate filter would have decided, so it can be
# validated against real forward data before ever being considered live.
# See memory: kinolivelines-tailguard-ema-filter-candidate. Backtested
# result (H1, 4 of 5 segments testable): SELL-only, both M15+H1 must be
# below their own EMA(75), 0 losses across all 4 testable segments.
EMA_SHADOW_PERIOD = 75

HERE    = os.path.dirname(os.path.abspath(__file__))
LOG     = os.path.join(HERE, "tail_guard_live.log")
ALIVE   = os.path.join(HERE, "tail_guard_live_alive.json")
STATE   = os.path.join(HERE, "tail_guard_live_state.json")
EVENTS  = os.path.join(HERE, "tail_guard_live_events.jsonl")
EMA_SHADOW = os.path.join(HERE, "tail_guard_live_ema_shadow.csv")
JOURNAL = os.path.join(HERE, "tail_guard_live_journal.csv")

JOURNAL_COLS = ["position_id", "side", "entry_time_utc", "entry_price",
                "exit_time_utc", "exit_price", "duration_min", "profit_usd",
                "max_dd_usd", "atr_m1_14_at_entry", "atr_m1_14_at_exit",
                "swing_runlen_at_entry", "spread_pts_at_entry",
                "hour_utc_at_entry", "dow_at_entry", "sl_usd", "tp_usd",
                "m1_prev_color", "m1_prev_body_pts", "m1_prev_atr_trend", "m1_above_ema21",
                "m15_prev_color", "m15_prev_body_pts", "m15_prev_atr_trend", "m15_above_ema21",
                "h1_prev_color", "h1_prev_body_pts", "h1_prev_atr_trend", "h1_above_ema21"]


def say(m):
    line = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {m}"
    print(line, flush=True)
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def rec_event(kind, **kw):
    try:
        row = {"ts_utc": datetime.utcnow().isoformat(timespec="milliseconds"),
               "kind": kind, "magic": MAGIC}
        row.update(kw)
        with open(EVENTS, "a", encoding="utf-8") as f:
            f.write(json.dumps(row, default=str) + "\n")
    except Exception:
        pass


def check_account():
    """REAL account 134499778 only, verified on EVERY loop - a terminal can be
    re-logged into a different account while this is running, and this one
    places orders with real money."""
    a = mt5.account_info()
    if a is None:
        return None
    if a.login != LOGIN:
        say(f"*** WRONG ACCOUNT {a.login}, expected {LOGIN} - REFUSING TO TRADE ***")
        return False
    if a.trade_mode != 2:
        say(f"*** not a REAL account (trade_mode={a.trade_mode}) - REFUSING ***")
        return False
    return a


def connect():
    if not mt5.initialize(path=TERMINAL):
        raise SystemExit(f"initialize failed: {mt5.last_error()}")
    a = check_account()
    if not a:
        mt5.shutdown(); raise SystemExit("account check failed at startup")
    return a


def build_bricks(rates):
    out = []
    ao = ac = float(rates[0]["open"]); d = 0
    for r in rates:
        t, c = int(r["time"]), float(r["close"])
        while True:
            up = (ao if d == -1 else ac) + BRICK * (REVERSAL if d == -1 else 1)
            dn = (ao if d == 1 else ac) - BRICK * (REVERSAL if d == 1 else 1)
            if c >= up:
                base = ao if d == -1 else ac; ao, ac, d = base, base + BRICK, 1
            elif c <= dn:
                base = ao if d == 1 else ac; ao, ac, d = base, base - BRICK, -1
            else:
                break
            out.append({"time": t, "dir": d, "close": ac})
    return out


def last_reversal(b):
    for k in range(len(b) - 1, 0, -1):
        if b[k]["dir"] != b[k - 1]["dir"]:
            out = dict(b[k]); out["brick_index"] = k
            return out
    return None


def atr_m1_14(rates):
    """14-period ATR on closed M1 bars, causal (only uses what is passed in).
    Journaling only - never gates a trading decision."""
    if rates is None or len(rates) < 15:
        return None
    trs = []
    for i in range(1, len(rates)):
        hi = float(rates[i]["high"]); lo = float(rates[i]["low"])
        prev = float(rates[i - 1]["close"])
        trs.append(max(hi - lo, abs(hi - prev), abs(lo - prev)))
    if len(trs) < 14:
        return None
    return sum(trs[-14:]) / 14.0


def candle_context(symbol, timeframe, n=60):
    """Snapshot of the last CLOSED candle (not the one still forming) on the
    given timeframe, at the moment of entry: color, body size, whether ATR14
    was rising/falling vs the prior bar, and whether that candle closed
    above EMA21. Journaling only - never gates a trading decision."""
    rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, n)
    if rates is None or len(rates) < 40:
        return {}
    o = rates["open"].astype(float); h = rates["high"].astype(float)
    l = rates["low"].astype(float); c = rates["close"].astype(float)
    closed = len(c) - 2  # last fully closed bar; the last element is still forming
    if closed < 22:
        return {}
    color = "green" if c[closed] > o[closed] else ("red" if c[closed] < o[closed] else "flat")
    body = round(abs(c[closed] - o[closed]), 2)

    def atr14(end):
        trs = []
        for i in range(end - 13, end + 1):
            prev = c[i - 1]
            trs.append(max(h[i] - l[i], abs(h[i] - prev), abs(l[i] - prev)))
        return sum(trs) / 14.0

    atr_now = atr14(closed)
    atr_prev = atr14(closed - 1)
    atr_trend = "rising" if atr_now > atr_prev else ("falling" if atr_now < atr_prev else "flat")

    k = 2.0 / (21 + 1)
    window = c[:closed + 1]
    ema = sum(window[:21]) / 21.0
    for price in window[21:]:
        ema = price * k + ema * (1 - k)
    above_ema21 = bool(c[closed] > ema)

    return dict(color=color, body_pts=body, atr_trend=atr_trend, above_ema21=above_ema21)


def _ema(values, period):
    if len(values) < period:
        return None
    ema = sum(values[:period]) / period
    k = 2.0 / (period + 1)
    for v in values[period:]:
        ema = v * k + ema * (1 - k)
    return ema


SHADOW_COLS = ["signal_time_utc", "side", "verdict",
               "h1_close", "h1_ema75", "m15_close", "m15_ema75"]


def write_shadow_row(row):
    try:
        new_file = not os.path.exists(EMA_SHADOW)
        with open(EMA_SHADOW, "a", encoding="utf-8", newline="") as f:
            if new_file:
                f.write(",".join(SHADOW_COLS) + "\n")
            f.write(",".join(str(row.get(c, "")) for c in SHADOW_COLS) + "\n")
    except Exception as exc:
        say(f"SHADOW WRITE FAILED: {exc}")


def ema_filter_shadow(direction, signal_time):
    """SHADOW ONLY - never gates a trade. For a SELL signal, checks whether
    H1 and M15 are both already below their own EMA(75) (the candidate
    filter's 'aligned' condition). BUY signals are always 'not_filtered'
    since the backtested candidate only ever filters SELL. Logs one row
    per new signal regardless of whether the bot actually trades it."""
    side = "BUY" if direction == 1 else "SELL"
    if direction == 1:
        write_shadow_row(dict(signal_time_utc=signal_time.isoformat(timespec="seconds"),
                               side=side, verdict="not_filtered_buy"))
        return
    h1 = mt5.copy_rates_from_pos(SYMBOL, mt5.TIMEFRAME_H1, 0, 200)
    m15 = mt5.copy_rates_from_pos(SYMBOL, mt5.TIMEFRAME_M15, 0, 200)
    if h1 is None or m15 is None or len(h1) < EMA_SHADOW_PERIOD + 2 or len(m15) < EMA_SHADOW_PERIOD + 2:
        write_shadow_row(dict(signal_time_utc=signal_time.isoformat(timespec="seconds"),
                               side=side, verdict="no_data"))
        return
    h1_closes = h1["close"][:-1].astype(float)   # exclude the still-forming bar
    m15_closes = m15["close"][:-1].astype(float)
    h1_ema = _ema(h1_closes[-(EMA_SHADOW_PERIOD * 3):], EMA_SHADOW_PERIOD)
    m15_ema = _ema(m15_closes[-(EMA_SHADOW_PERIOD * 3):], EMA_SHADOW_PERIOD)
    if h1_ema is None or m15_ema is None:
        write_shadow_row(dict(signal_time_utc=signal_time.isoformat(timespec="seconds"),
                               side=side, verdict="no_data"))
        return
    h1_close = h1_closes[-1]; m15_close = m15_closes[-1]
    aligned = (h1_close < h1_ema) and (m15_close < m15_ema)
    write_shadow_row(dict(signal_time_utc=signal_time.isoformat(timespec="seconds"),
                           side=side, verdict=("aligned" if aligned else "blocked"),
                           h1_close=round(h1_close, 2), h1_ema75=round(h1_ema, 2),
                           m15_close=round(m15_close, 2), m15_ema75=round(m15_ema, 2)))


def swing_runlength(bricks):
    """Tolerant run-length of the swing that ended at the LAST reversal in
    `bricks` (one isolated single-brick counter-move is absorbed, matching
    the definition tested in CANDIDATE_TAIL_GUARD.md / tail_guard_minrun11).
    Journaling only - never gates a trading decision."""
    if not bricks or len(bricks) < 2:
        return None
    dirs = [b["dir"] for b in bricks]
    n = len(dirs)
    runlen = [0] * n
    color = dirs[0]; count = 1; blip_used = False
    runlen[0] = 1
    i = 1
    while i < n:
        if dirs[i] == color:
            count += 1; runlen[i] = count; i += 1
        else:
            if (not blip_used) and i + 1 < n and dirs[i + 1] == color:
                blip_used = True; runlen[i] = count; i += 1
            else:
                color = dirs[i]; count = 1; blip_used = False
                runlen[i] = 1; i += 1
    # the swing being reversed is whatever the tolerant run was JUST BEFORE
    # the final flip (the last index where runlen resets to 1)
    for k in range(n - 1, 0, -1):
        if runlen[k] == 1 and dirs[k] != dirs[k - 1]:
            return runlen[k - 1]
    return runlen[0]


def write_journal_row(row):
    try:
        new_file = not os.path.exists(JOURNAL)
        with open(JOURNAL, "a", encoding="utf-8", newline="") as f:
            if new_file:
                f.write(",".join(JOURNAL_COLS) + "\n")
            f.write(",".join(str(row.get(c, "")) for c in JOURNAL_COLS) + "\n")
    except Exception as exc:
        say(f"JOURNAL WRITE FAILED: {exc}")


def calibrate_sl():
    """1-in-100 percentile of worst-ever adverse move, using every reversal
    signal in the M1 history the broker currently serves (~55 days). Purely
    historical - the forward window used here never reaches into live data,
    it only measures how far PAST signals moved against their own entry
    before the calibration was run."""
    rates = mt5.copy_rates_from_pos(SYMBOL, mt5.TIMEFRAME_M1, 0, 80000)
    if rates is None or len(rates) < 100:
        return None, 0
    o = rates["open"].astype(float); h = rates["high"].astype(float)
    l = rates["low"].astype(float); c = rates["close"].astype(float)
    N = len(c)
    bricks = build_bricks(rates)
    revs = {}
    pd_ = None
    for k in range(1, len(bricks)):
        if bricks[k]["dir"] != bricks[k - 1]["dir"]:
            # map back to the rates index for that brick's time
            t = bricks[k]["time"]
            idx = int((rates["time"] >= t).argmax())
            revs[idx] = bricks[k]["dir"]
    tick = mt5.symbol_info_tick(SYMBOL)
    spread_pts = (tick.ask - tick.bid) if tick else 10.0
    vals = []
    for j, dirn in revs.items():
        if j + 1 >= N:
            continue
        ent_bar = j + 1
        L = (dirn == 1)
        entry = o[ent_bar] + spread_pts if L else o[ent_bar]
        end = min(N, ent_bar + CALIBRATE_LOOKAHEAD_MIN)
        worst = 0.0
        for k in range(ent_bar, end):
            adv = (entry - l[k]) if L else (h[k] - entry)
            if adv > worst:
                worst = adv
        vals.append(worst)
    if not vals:
        return None, 0
    vals.sort()
    idx = min(len(vals) - 1, int(len(vals) * SL_PCTILE / 100.0))
    sl_pts = vals[idx]
    return sl_pts, len(vals)


def load_state():
    try:
        with open(STATE, encoding="utf-8") as f:
            s = json.load(f)
    except Exception:
        s = {"last_brick": 0, "sl_pts": None, "sl_calibrated_day": None,
             "sl_signals_used": 0, "open_trade": None,
             "safety_baseline": None, "safety_peak": None,
             "safety_stopped": False, "safety_stop_reason": None}
    s.setdefault("realized_cum", 0.0)
    s.setdefault("realized_profit_peak", 0.0)
    return s


def halftrail_is_active(st):
    """HALFTRAIL_ENABLED=False as of 2026-08-17 - see the comment by that
    constant. Kept as a function (not inlined) so every caller stays in
    sync if this is ever re-enabled."""
    return HALFTRAIL_ENABLED and st.get("realized_profit_peak", 0.0) >= HALFTRAIL_ACTIVATION


def ratchet_is_active(st, price):
    """RATCHET_ENABLED=True as of 2026-08-18 - see the comment by that
    constant. Active once banked realized_cum has crossed the trigger
    fraction of the current trade's default SL width."""
    if not RATCHET_ENABLED:
        return False
    default_sl_usd = price * RELATIVE_SL_PCT * LOTS
    trigger = RATCHET_TRIGGER_FRAC * default_sl_usd
    return st.get("realized_cum", 0.0) >= trigger


def effective_sl_pts(st, price):
    """Half Trail ACTIVE (only possible if HALFTRAIL_ENABLED, currently
    False): absolute-$ trailing SL, unchanged by price (it's a guarantee on
    banked profit). Breakeven Ratchet ACTIVE (RATCHET_ENABLED): tightens to
    whatever realized profit is currently banked, capped at the normal
    default width - see the RATCHET_ENABLED comment above. Otherwise (the
    fallback case): relative SL = price * RELATIVE_SL_PCT - see the
    RELATIVE_SL_PCT comment above for why."""
    if halftrail_is_active(st):
        peak = st.get("realized_profit_peak", 0.0)
        sl_usd = max(peak / 2.0, HALFTRAIL_FLOOR)
        return sl_usd / LOTS
    default_sl_pts = price * RELATIVE_SL_PCT
    if ratchet_is_active(st, price):
        default_sl_usd = default_sl_pts * LOTS
        cap = RATCHET_CAP_FRAC * default_sl_usd
        sl_usd = min(max(st.get("realized_cum", 0.0), 0.0), cap)
        return sl_usd / LOTS
    return default_sl_pts


def golden_lane_trend_below():
    """'Trend Lane' half of Golden Lane - see GOLDEN_LANE_ENABLED comment.
    True if the last CLOSED M15 candle's close is at or below its own
    causal 21-period EMA. None if not enough M15 history to compute yet
    (treated as a block, same as the live bot's other 'not enough data'
    guards)."""
    m15 = mt5.copy_rates_from_pos(SYMBOL, mt5.TIMEFRAME_M15, 0, 100)
    if m15 is None or len(m15) < GOLDEN_LANE_EMA_PERIOD + 2:
        return None
    c = m15["close"][:-1].astype(float)  # exclude the still-forming M15 bar
    if len(c) < GOLDEN_LANE_EMA_PERIOD:
        return None
    k = 2.0 / (GOLDEN_LANE_EMA_PERIOD + 1)
    ema = float(c[:GOLDEN_LANE_EMA_PERIOD].mean())
    for price in c[GOLDEN_LANE_EMA_PERIOD:]:
        ema = float(price) * k + ema * (1 - k)
    return bool(c[-1] <= ema)


def golden_lane_m1_fresh(rates, rev_time):
    """'M1-fresh' half of Golden Lane - see GOLDEN_LANE_ENABLED comment.
    True if the M1 signal candle does NOT continue the same-direction
    color as the M1 candle immediately before it. None if the signal bar
    can't be located in the current rates window (treated as a block)."""
    idx = None
    for k in range(len(rates) - 1, -1, -1):
        if int(rates["time"][k]) == rev_time:
            idx = k
            break
    if idx is None or idx == 0:
        return None
    def color(k):
        o = float(rates["open"][k]); c = float(rates["close"][k])
        return 1 if c > o else (-1 if c < o else 0)
    c1 = color(idx)
    c2 = color(idx - 1)
    return not (c1 != 0 and c1 == c2)


def save_state(s):
    try:
        tmp = STATE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(s, f); f.flush(); os.fsync(f.fileno())
        os.replace(tmp, STATE)
    except Exception as exc:
        say(f"STATE SAVE FAILED: {exc}")


def mine():
    ps = mt5.positions_get(symbol=SYMBOL)
    if ps is None:
        return None
    return [p for p in ps if p.magic == MAGIC]


def close_position(p, why):
    """Market-close one position. Used only by the safety drawdown cutoff -
    every other exit in this bot is the broker-side TP/SL bracket."""
    tick = mt5.symbol_info_tick(SYMBOL)
    if tick is None:
        say(f"SAFETY CLOSE FAILED: no tick for #{p.ticket}")
        return False
    price = tick.bid if p.type == 0 else tick.ask
    req = {"action": mt5.TRADE_ACTION_DEAL, "position": p.ticket, "symbol": SYMBOL,
           "volume": p.volume,
           "type": mt5.ORDER_TYPE_SELL if p.type == 0 else mt5.ORDER_TYPE_BUY,
           "price": price, "deviation": 30, "magic": MAGIC,
           "comment": "TailGuard-safety-close"}
    r = mt5.order_send(req)
    ok = r is not None and r.retcode in (mt5.TRADE_RETCODE_DONE, mt5.TRADE_RETCODE_PLACED)
    say(f"SAFETY CLOSE #{p.ticket} -> {'OK' if ok else 'FAILED ' + str(getattr(r,'retcode','?'))}  [{why}]")
    rec_event("safety_close", ticket=p.ticket, ok=ok, why=why,
              retcode=getattr(r, "retcode", None))
    return ok


def open_one(direction, why, sl_pts):
    tick = mt5.symbol_info_tick(SYMBOL)
    if tick is None:
        rec_event("open_blocked", why=why, reason="no tick")
        return None
    buy = (direction == 1)
    price = tick.ask if buy else tick.bid
    tp = price + TP_PTS if buy else price - TP_PTS
    sl = price - sl_pts if buy else price + sl_pts
    req = {"action": mt5.TRADE_ACTION_DEAL, "symbol": SYMBOL, "volume": LOTS,
           "type": mt5.ORDER_TYPE_BUY if buy else mt5.ORDER_TYPE_SELL,
           "price": price, "tp": tp, "sl": sl,
           "deviation": 30, "magic": MAGIC, "comment": "TailGuard-M1",
           "type_time": mt5.ORDER_TIME_GTC}
    say(f"OPEN {'BUY' if buy else 'SELL'} {LOTS} @ {price:.2f} TP {tp:.2f} SL {sl:.2f}  [{why}]")
    r = mt5.order_send(req)
    ok = r is not None and r.retcode in (mt5.TRADE_RETCODE_DONE, mt5.TRADE_RETCODE_PLACED)
    say(f"  retcode {getattr(r,'retcode','?')} -> {'OK' if ok else 'FAILED'}")
    rec_event("order_open", side="BUY" if buy else "SELL", volume=LOTS, why=why, ok=ok,
              requested_price=round(price, 2), tp=round(tp, 2), sl=round(sl, 2),
              sl_pts=round(sl_pts, 1), retcode=getattr(r, "retcode", None),
              broker_comment=getattr(r, "comment", ""))
    if not ok:
        return None
    ticket = None
    fill_price = getattr(r, "price", None) or price
    if getattr(r, "deal", 0):
        ds = mt5.history_deals_get(ticket=r.deal)
        if ds:
            ticket = ds[0].position_id
    if ticket is None:
        ticket = getattr(r, "order", None)
    return dict(ticket=ticket, side="BUY" if buy else "SELL", fill_price=fill_price,
                spread_pts=round(tick.ask - tick.bid, 2))


def main():
    acc = connect()
    say("=" * 70)
    say(f"TAIL GUARD M1 BOT UP - REAL MONEY - account {acc.login} {acc.server} "
        f"balance {acc.balance:.2f} {acc.currency}")
    _tp_usd = TP_PTS * LOTS
    _sl_usd_legacy = (SL_USD_FIXED / PT) * LOTS
    say(f"rule: M1 reversal brick (50pt/2), TP {TP_PTS:.0f}pts (${_tp_usd:.2f} at "
        f"{LOTS} lots), SL = RELATIVE {100*RELATIVE_SL_PCT:.0f}% of entry price "
        f"(replaces the old fixed {SL_USD_FIXED/PT:.0f}pts/${_sl_usd_legacy:.2f} "
        f"constant as of 2026-08-17 - see CANDIDATE_TAIL_GUARD.md 'ROOT CAUSE' "
        f"section and memory kinolivelines-tailguard-relative-sl-candidate), "
        f"cap=1, magic {MAGIC}")
    _tick_now = mt5.symbol_info_tick(SYMBOL)
    _px_now = _tick_now.ask if _tick_now else None
    if _px_now:
        _sl_usd_now = _px_now * RELATIVE_SL_PCT * LOTS
        _sl_vs_balance = _sl_usd_now / acc.balance if acc.balance else 0
        say(f"*** SL now scales with BTC's price at entry instead of a frozen dollar "
            f"figure - at the current price (${_px_now:,.2f}) that's a SL of "
            f"${_sl_usd_now:.2f} at {LOTS} lots, {_sl_vs_balance:.1f}x the account "
            f"balance (${acc.balance:.2f}). This can still be a large multiple of a "
            f"small account balance; a real adverse move may still trigger a broker "
            f"margin call / stop-out before the SL price is reached. ***")
    say("NO recovery, NO basket, NO daily loss limit - broker-side TP+SL "
        "bracket per trade. SL changed 2026-08-14 from the M1-only "
        "calibration to a fixed H1 worst-case constant, then 2026-08-17 to "
        "this relative (%-of-price) formula after a 4-year backtest found "
        "the fixed constant made the strategy net negative.")
    say("*** ENTRY SIGNAL STILL UNVALIDATED AT THIS SAMPLE SIZE ON M1 - "
        "user's explicit instruction after being warned ***")
    say("=" * 70)

    st = load_state()
    sl_pts = SL_USD_FIXED / PT   # legacy reference constant only, not used to size trades anymore
    st["sl_pts"] = sl_pts
    st["sl_calibrated_day"] = "RELATIVE-40PCT-since-2026-08-17"
    st["sl_signals_used"] = None
    if st.get("safety_baseline") is None:
        st["safety_baseline"] = acc.balance
        st["safety_peak"] = acc.balance
        st["safety_stopped"] = False
        st["safety_stop_reason"] = None
        say(f"SAFETY DRAWDOWN CUTOFF armed: baseline ${acc.balance:.2f}, "
            f"floor starts FIXED at ${SAFETY_FLOOR_INITIAL:.2f} (not balance-"
            f"relative), switches to trailing (peak - ${SAFETY_FLOOR_INITIAL:.2f}) "
            f"once peak profit exceeds ${SAFETY_FLOOR_INITIAL:.2f}. Trips -> "
            f"closes any open position and halts new trades until manually cleared.")
    else:
        say(f"SAFETY DRAWDOWN CUTOFF resumed: baseline ${st['safety_baseline']:.2f}, "
            f"peak ${st.get('safety_peak', st['safety_baseline']):.2f}, "
            f"stopped={st.get('safety_stopped', False)}")
    save_state(st)
    say(f"(legacy reference only, no longer used to size trades: old fixed SL was "
        f"{sl_pts:.1f} pts / ${sl_pts * LOTS:.2f} at {LOTS} lots)")
    rec_event("sl_fixed_legacy_reference", sl_pts=round(sl_pts, 1), sl_usd=SL_USD_FIXED)

    say(f"HALF TRAIL DISABLED 2026-08-17 (backtested combined with the relative SL - "
        f"WORSE than relative SL alone, see comment above HALFTRAIL_ENABLED). "
        f"realized_profit_peak=${st.get('realized_profit_peak', 0.0):.2f} still tracked "
        f"for reference only, no longer affects the SL.")

    if RATCHET_ENABLED and not st.get("ratchet_deployed"):
        _old_cum = st.get("realized_cum", 0.0)
        st["realized_cum"] = 0.0
        st["ratchet_deployed"] = True
        save_state(st)
        say(f"BREAKEVEN RATCHET DEPLOYED 2026-08-18 - trigger {100*RATCHET_TRIGGER_FRAC:.0f}% "
            f"of default SL, cap {100*RATCHET_CAP_FRAC:.0f}% of default SL. realized_cum reset "
            f"from ${_old_cum:.2f} (stale Half Trail leftover) to $0.00 to start counting fresh "
            f"from this deploy, matching the backtested assumption. See RATCHET_ENABLED comment "
            f"above and memory kinolivelines-tailguard-breakeven-ratchet-candidate for the full "
            f"corrected backtest. KNOWN LIMIT: the first disaster after this point is unprotected "
            f"- needs banked profit to work with, and there is none yet.")
    else:
        say(f"BREAKEVEN RATCHET: enabled={RATCHET_ENABLED}, trigger {100*RATCHET_TRIGGER_FRAC:.0f}% "
            f"cap {100*RATCHET_CAP_FRAC:.0f}%, realized_cum=${st.get('realized_cum', 0.0):.2f}")

    if GOLDEN_LANE_ENABLED:
        say(f"GOLDEN LANE ENTRY FILTER ACTIVE - only opens a trade if BOTH hold: (1) 'Trend Lane' - "
            f"last closed M15 candle's close is at/below its own {GOLDEN_LANE_EMA_PERIOD}-period EMA, "
            f"and (2) 'M1-fresh' - the M1 signal candle does NOT continue the same-direction color "
            f"as the candle right before it. See memory kinolivelines-tailguard-candle-pattern-edges.")
    else:
        say(f"GOLDEN LANE: deployed 2026-08-19, DISABLED same day - the backtest supporting it "
            f"(379 trades, 0 losses) turned out to be built on a flawed methodology (post-hoc "
            f"bucketing of an unfiltered run, not a real gated-entry simulation). The correct, "
            f"properly-gated backtest showed Ratchet+GoldenLane net -$813.53 over 6yr (17 losses, "
            f"worse than Ratchet alone's proven +$2,158.41/16 losses) - the OPPOSITE of what was "
            f"first found. Reverted to Ratchet-only same day. See memory "
            f"kinolivelines-tailguard-candle-pattern-edges for the full correction record.")

    fails = 0
    while True:
        try:
            rates = mt5.copy_rates_from_pos(SYMBOL, mt5.TIMEFRAME_M1, 0, 3000)
            if rates is None or len(rates) < 2:
                fails += 1
                say(f"no bars ({fails}/{MAX_FAILS}) last_error {mt5.last_error()}")
                if fails >= MAX_FAILS:
                    say("TERMINAL UNREACHABLE - exiting for the watchdog")
                    mt5.shutdown(); sys.exit(1)
                time.sleep(POLL); continue

            acc = check_account()
            if acc is False:
                say("halting - wrong account. Fix and restart."); mt5.shutdown(); sys.exit(2)
            if acc is None:
                fails += 1
                say(f"no account_info ({fails}/{MAX_FAILS})")
                if fails >= MAX_FAILS:
                    say("TERMINAL UNREACHABLE - exiting for the watchdog")
                    mt5.shutdown(); sys.exit(1)
                time.sleep(POLL); continue
            fails = 0

            # ---- $100 safety drawdown cutoff REMOVED 2026-08-17 at user's explicit
            # instruction, right after it tripped and closed a position (equity
            # 99.67 <= floor 100.00). Peak/baseline still tracked for the alive.json
            # display only - no trip, no forced close, no trade halt anymore. ----
            st["safety_peak"] = max(st.get("safety_peak", acc.balance), acc.equity)
            _profit_at_peak = st["safety_peak"] - st.get("safety_baseline", acc.balance)
            if _profit_at_peak <= SAFETY_FLOOR_INITIAL:
                _floor = SAFETY_FLOOR_INITIAL
            else:
                _floor = st["safety_peak"] - SAFETY_FLOOR_INITIAL
            save_state(st)

            # SL is now a fixed constant (H1 worst-case) - no recalibration.

            bricks = build_bricks(rates[:-1])
            rev = last_reversal(bricks)
            cur_atr = atr_m1_14(rates[:-1])
            ps = mine()
            if ps is None:
                fails += 1
                say(f"positions_get failed ({fails}/{MAX_FAILS})")
                time.sleep(POLL); continue

            # ---- journal: update running max drawdown on an open trade ----
            ot = st.get("open_trade")
            if ot and ps:
                tick = mt5.symbol_info_tick(SYMBOL)
                if tick is not None:
                    # $ = points * LOTS (same convention as TP_PTS*LOTS and
                    # SL_USD_FIXED/PT*LOTS above - PT=0.01 exactly cancels the
                    # 0.01-lot base unit). Previously multiplied by PT alone with
                    # no LOTS factor, so every recorded drawdown was under-reported
                    # by LOTS/0.01 = 5x at the current 0.05 lot size. Fixed 2026-08-18.
                    if ot["side"] == "BUY":
                        dd = (ot["entry_price"] - tick.bid) * LOTS
                    else:
                        dd = (tick.ask - ot["entry_price"]) * LOTS
                    if dd > ot.get("max_dd_usd", 0.0):
                        ot["max_dd_usd"] = round(dd, 4)
                        st["open_trade"] = ot
                        save_state(st)

            # ---- journal: trade just closed - finalize and write a row ----
            if ot and not ps:
                deals = mt5.history_deals_get(datetime.utcnow() - timedelta(days=3),
                                              datetime.utcnow() + timedelta(hours=1))
                exit_deal = None
                if deals:
                    cand = [d for d in deals if d.magic == MAGIC
                            and d.position_id == ot.get("ticket") and d.entry == 1]
                    if cand:
                        exit_deal = max(cand, key=lambda d: d.time)
                if exit_deal is not None:
                    exit_price = exit_deal.price
                    exit_time = datetime.utcfromtimestamp(exit_deal.time)
                    profit = round(exit_deal.profit + exit_deal.swap + exit_deal.commission
                                    + getattr(exit_deal, "fee", 0.0), 2)
                else:
                    tick = mt5.symbol_info_tick(SYMBOL)
                    exit_price = (tick.bid if ot["side"] == "BUY" else tick.ask) if tick else ot["entry_price"]
                    exit_time = datetime.utcnow()
                    profit = None
                entry_time = datetime.fromisoformat(ot["entry_time_utc"])
                dur_min = round((exit_time - entry_time).total_seconds() / 60, 1)
                row = dict(position_id=ot.get("ticket"), side=ot["side"],
                           entry_time_utc=ot["entry_time_utc"],
                           entry_price=ot["entry_price"],
                           exit_time_utc=exit_time.isoformat(timespec="seconds"),
                           exit_price=exit_price, duration_min=dur_min,
                           profit_usd=profit, max_dd_usd=ot.get("max_dd_usd", 0.0),
                           atr_m1_14_at_entry=ot.get("atr_at_entry"),
                           atr_m1_14_at_exit=(round(cur_atr, 2) if cur_atr else ""),
                           swing_runlen_at_entry=ot.get("runlen_at_entry"),
                           spread_pts_at_entry=ot.get("spread_pts"),
                           hour_utc_at_entry=entry_time.hour,
                           dow_at_entry=entry_time.strftime("%a"),
                           sl_usd=round(ot.get("sl_pts_used", st.get("sl_pts", 0)) * PT, 2),
                           tp_usd=round(TP_PTS * PT, 2),
                           m1_prev_color=ot.get("m1_prev_color"),
                           m1_prev_body_pts=ot.get("m1_prev_body_pts"),
                           m1_prev_atr_trend=ot.get("m1_prev_atr_trend"),
                           m1_above_ema21=ot.get("m1_above_ema21"),
                           m15_prev_color=ot.get("m15_prev_color"),
                           m15_prev_body_pts=ot.get("m15_prev_body_pts"),
                           m15_prev_atr_trend=ot.get("m15_prev_atr_trend"),
                           m15_above_ema21=ot.get("m15_above_ema21"),
                           h1_prev_color=ot.get("h1_prev_color"),
                           h1_prev_body_pts=ot.get("h1_prev_body_pts"),
                           h1_prev_atr_trend=ot.get("h1_prev_atr_trend"),
                           h1_above_ema21=ot.get("h1_above_ema21"))
                write_journal_row(row)
                say(f"JOURNAL: {ot['side']} dur {dur_min}min  profit {profit}  "
                    f"maxDD ${ot.get('max_dd_usd', 0.0):.2f}  "
                    f"ATR entry {ot.get('atr_at_entry')} exit {round(cur_atr,2) if cur_atr else None}  "
                    f"runlen {ot.get('runlen_at_entry')}")
                if profit is not None:
                    st["realized_cum"] = round(st.get("realized_cum", 0.0) + profit, 2)
                    say(f"RATCHET: realized_cum now ${st['realized_cum']:.2f} "
                        f"(trigger is {100*RATCHET_TRIGGER_FRAC:.0f}% of the NEXT trade's own "
                        f"default SL width, recomputed fresh at that trade's entry price)")
                    if st["realized_cum"] > st.get("realized_profit_peak", 0.0):
                        st["realized_profit_peak"] = st["realized_cum"]
                        say(f"HALF TRAIL (disabled, reference only): new realized profit peak "
                            f"${st['realized_profit_peak']:.2f}"
                            + (f"  (would be ACTIVE if enabled, next SL would be ${max(st['realized_profit_peak']/2.0, HALFTRAIL_FLOOR):.2f})"
                               if st["realized_profit_peak"] >= HALFTRAIL_ACTIVATION else
                               f"  ({HALFTRAIL_ACTIVATION - st['realized_profit_peak']:.2f} short of ${HALFTRAIL_ACTIVATION:.2f} would-be activation)"))
                else:
                    say("HALF TRAIL: exit profit unknown (no matching deal found) - realized peak NOT updated this trade")
                st["open_trade"] = None
                save_state(st)

            if rev and rev["time"] > st.get("last_brick", 0):
                ema_filter_shadow(rev["dir"], datetime.utcfromtimestamp(rev["time"]))
                age = (datetime.utcnow() - datetime.utcfromtimestamp(rev["time"])).total_seconds() / 60
                if st.get("safety_stopped"):
                    say(f"skip signal: safety drawdown cutoff is tripped - "
                        f"{st.get('safety_stop_reason')}")
                    rec_event("signal_skipped", reason="safety_stopped")
                    st["last_brick"] = rev["time"]
                elif age <= FRESH_MIN:
                    if not ps:
                        gl_trend = golden_lane_trend_below() if GOLDEN_LANE_ENABLED else True
                        gl_fresh = golden_lane_m1_fresh(rates, rev["time"]) if GOLDEN_LANE_ENABLED else True
                        gl_ok = (gl_trend is True) and (gl_fresh is True)
                        if GOLDEN_LANE_ENABLED and not gl_ok:
                            say(f"skip signal: GOLDEN LANE blocked (trend_below_ema={gl_trend}, m1_fresh={gl_fresh})")
                            rec_event("signal_skipped", reason="golden_lane_blocked",
                                      trend_below_ema=gl_trend, m1_fresh=gl_fresh)
                            st["last_brick"] = rev["time"]
                            opened = None
                        else:
                            tick_now = mt5.symbol_info_tick(SYMBOL)
                            price_now = (tick_now.ask if rev["dir"] == 1 else tick_now.bid) if tick_now else None
                            if price_now is None:
                                say("skip signal: no tick available to size SL")
                                rec_event("signal_skipped", reason="no_tick_for_sl_sizing")
                                opened = None
                            else:
                                sl_pts_to_use = effective_sl_pts(st, price_now)
                                if halftrail_is_active(st):
                                    _mode = "HALF TRAIL ACTIVE"
                                elif ratchet_is_active(st, price_now):
                                    _mode = f"RATCHET ACTIVE (banked ${st.get('realized_cum', 0.0):.2f})"
                                else:
                                    _mode = f"relative {100*RELATIVE_SL_PCT:.0f}% of price (ratchet not yet triggered)"
                                say(f"SL SIZING {_mode} [GOLDEN LANE OK: trend_below_ema={gl_trend}, m1_fresh={gl_fresh}]: "
                                    f"using SL {sl_pts_to_use:.1f}pts (${sl_pts_to_use*LOTS:.2f} at {LOTS} lots) @ price {price_now:.2f}  "
                                    f"realized_cum=${st.get('realized_cum', 0.0):.2f}")
                                opened = open_one(rev["dir"], "new signal", sl_pts_to_use)
                        if opened:
                            st["last_brick"] = rev["time"]
                            ctx_m1 = candle_context(SYMBOL, mt5.TIMEFRAME_M1)
                            ctx_m15 = candle_context(SYMBOL, mt5.TIMEFRAME_M15)
                            ctx_h1 = candle_context(SYMBOL, mt5.TIMEFRAME_H1)
                            st["open_trade"] = dict(
                                ticket=opened["ticket"], side=opened["side"],
                                entry_price=opened["fill_price"],
                                entry_time_utc=datetime.utcnow().isoformat(timespec="seconds"),
                                atr_at_entry=(round(cur_atr, 2) if cur_atr else None),
                                runlen_at_entry=swing_runlength(bricks),
                                spread_pts=opened["spread_pts"],
                                sl_pts_used=sl_pts_to_use,
                                max_dd_usd=0.0,
                                m1_prev_color=ctx_m1.get("color"),
                                m1_prev_body_pts=ctx_m1.get("body_pts"),
                                m1_prev_atr_trend=ctx_m1.get("atr_trend"),
                                m1_above_ema21=ctx_m1.get("above_ema21"),
                                m15_prev_color=ctx_m15.get("color"),
                                m15_prev_body_pts=ctx_m15.get("body_pts"),
                                m15_prev_atr_trend=ctx_m15.get("atr_trend"),
                                m15_above_ema21=ctx_m15.get("above_ema21"),
                                h1_prev_color=ctx_h1.get("color"),
                                h1_prev_body_pts=ctx_h1.get("body_pts"),
                                h1_prev_atr_trend=ctx_h1.get("atr_trend"),
                                h1_above_ema21=ctx_h1.get("above_ema21"))
                    else:
                        say(f"skip signal: already in a position (cap=1)")
                        rec_event("signal_skipped", reason="already_in_position")
                        st["last_brick"] = rev["time"]
                else:
                    say(f"skip signal: stale ({age:.1f}min old)")
                    st["last_brick"] = rev["time"]
                save_state(st)

            ps = mine()
            _display_price = float(rates[-1]["close"])
            _cur_sl_pts = effective_sl_pts(st, _display_price)
            with open(ALIVE, "w", encoding="utf-8") as f:
                json.dump({"alive_utc": datetime.utcnow().isoformat(),
                           "positions": len(ps) if ps else 0,
                           "lots": LOTS,
                           "sl_pts": st.get("sl_pts"),
                           "sl_usd": round(st.get("sl_pts", 0) * LOTS, 2),
                           "sl_mode": "relative_pct_of_price",
                           "default_sl_relative_pct": RELATIVE_SL_PCT,
                           "tp_usd": round(TP_PTS * LOTS, 2),
                           "sl_calibrated_day": st.get("sl_calibrated_day"),
                           "sl_signals_used": st.get("sl_signals_used"),
                           "equity": acc.equity, "balance": acc.balance,
                           "safety_baseline": st.get("safety_baseline"),
                           "safety_peak": st.get("safety_peak"),
                           "safety_floor": round(_floor, 2),
                           "safety_stopped": st.get("safety_stopped", False),
                           "halftrail_enabled": HALFTRAIL_ENABLED,
                           "halftrail_realized_peak": st.get("realized_profit_peak", 0.0),
                           "halftrail_active": halftrail_is_active(st),
                           "ratchet_enabled": RATCHET_ENABLED,
                           "ratchet_trigger_frac": RATCHET_TRIGGER_FRAC,
                           "ratchet_cap_frac": RATCHET_CAP_FRAC,
                           "ratchet_realized_cum": st.get("realized_cum", 0.0),
                           "ratchet_active": ratchet_is_active(st, _display_price),
                           "current_sl_pts": round(_cur_sl_pts, 1),
                           "current_sl_usd": round(_cur_sl_pts * LOTS, 2),
                           "golden_lane_enabled": GOLDEN_LANE_ENABLED}, f)
        except Exception as e:
            say(f"ERROR {type(e).__name__}: {e}")
        time.sleep(POLL)


if __name__ == "__main__":
    main()
