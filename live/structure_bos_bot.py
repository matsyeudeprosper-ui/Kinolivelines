"""structure_bos_bot.py - the user's STRUCTURE rules, LIVE on real
account 223995441 (Exness-MT5Real30, BTCUSD, $7 spread).

DEPLOYED 2026-09-08 ON THE USER'S EXPLICIT DECISION with the
backtest evidence stated and accepted beforehand: over 69 days at
$7 spread the exact rule scored +$56 at 0.02 lots, INSIDE the
random-entry control band (-92..+113); the RR probe grid was
sign-unstable and its best cell collapsed in walk-forward (+176
first half -> +11 blind half). The user chose to forward-run their
exact rules anyway. Guard rails below keep the experiment cheap.

THE RULES (user 2026-09-08, verbatim intent):
  - the chart's structure engine IS the brain (silence filter:
    close beyond last shown high/low; swing dots confirmed only by
    full closes; 2-dot bootstrap; CHoCH then first fresh BOS flips
    the trend)
  - enter EVERY BOS of a confirmed trend, in the trend's direction
  - SL at the glowing dot; TP at 0.8 x risk
  - ONE trade at a time; base lot 0.02
  - fighters use available bullets: while there is a debt book,
    extra 0.01 lots ride along ONLY if the chest can pre-pay their
    full risk at this trade's stop distance (max +0.03). A losing
    fighter's extra share is paid by the chest; the base share goes
    to the debt. Wins pay the debt first, overflow fills the chest
    (cap $5).

GUARD RAILS
  - hard kill: bot net (banked+floating, own magic) <= -$60 ->
    close, stop, say KILL. Preregistered review at 100 trades.
  - honors owl_trading_pause.json for new entries
  - waits quietly while balance < $20 (account starts unfunded)

AWAKE GATE (user 2026-09-09, measured before deploy): entries only
when at least one trend FLIP happened in the last 2 hours. The
sleepy-market trades were the losers: gated backtest +207 over 69d
vs all-negative random controls (5 seeds), walk-forward winner
picked on days 1-35 scored +116 blind on days 36-69 (scratchpad
bt_chop*.py). Sleeping market = no fishing.
"""
import json
import math
import os
import time
from datetime import datetime, timezone

import MetaTrader5 as mt5

# --- variants (2026-09-09): argv[1] picks the account/config.
#     "live" (default) = the FROZEN real config.
#     "sniper"  = demo 476989735: ONLY the 2nd trade of each trend,
#        flat 0.06, no chest features (backtest: 65% wr, +106 at
#        0.02 -> ~+318 at 0.06, maxDD ~78, halves +44/+63).
#     "halfdebt" = demo 476989740: full live config but per-loss
#        debt at 0.5x (backtest +372 vs +335, DD 80, chest richer,
#        3x more adds) - the queued upgrade, auditioning forward.
import sys as _sys
VARIANT = _sys.argv[1] if len(_sys.argv) > 1 else "live"
PASSWORD = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                     "owl_secrets.json"), encoding="utf-8"))["mt5_password"]  # not in git
SYMBOL = "BTCUSD"
RR = 0.8
BASE_LOT = 0.02
MAX_EXTRA = 3            # bullets that may ride along (0.01 each)
CHEST_CAP = 10.0         # cap sweep 2026-09-09: $10 = sweet spot
# --- RECOVERY JAR (owner 2026-09-16, switched on after review) ---------
# The old chest only grew on a NEW EQUITY HIGH, so during a drawdown it
# never filled - measured on the live account, 82 of 85 in-debt trades had
# no ammunition at all. The jar now takes a slice of EVERY win.
# Owner was shown the simulation (it loses more on the current record,
# monotonically, because it multiplies a negative expectancy) and chose to
# switch it on anyway. See live/review/DEBT_SYSTEM.md.
JAR = True               # False = old behaviour (new-high overflow only)
JAR_SKIM = 0.50          # owner 2026-09-16: half of each win. The skim is
                         # a PERMISSION dial, not a savings account - it
                         # decides how fast you earn the right to size up,
                         # so higher = faster recovery AND more variance.
JAR_STAKE = 0.50         # most of the jar stakeable on ONE attempt
JAR_DEBT_MULT = 0.5      # jar may hold up to half the debt...
JAR_FLOOR_CAP = 10.0     # ...but never less headroom than the old cap
NERV_STORM = 1.85       # see S_MIN_DIST block above
KILL_NET = -60.0
MIN_BALANCE = 20.0
SEED_BARS = 3000
S_MIN_DIST = 10.0        # dot inside the spread zone = no trade
# HARD CEILING, owner 2026-09-21: "although I asked the main bot to trade
# with no gate on the accounts I asked for, make sure they don't trade the
# nervosite tres agite as an exception." 1.85 is the top band on the weather
# card - the top ~10% of hours, measured over 41.7 days. Owner called it
# "tres agite"; the card now says "tres rapide" because the number tracks
# DISTANCE walked (+0.64) not chop (+0.13, and positive - these hours are
# slightly STRAIGHTER). Same line, honest name. This
# is NOT a package dial: a no-brakes account still refuses here, which is
# the whole point of calling it an exception. The card carries the same
# number as its band boundary; change both together.
# 2026-09-15 (owner, after a 1478-pt stop risked $31): one rule, no
# single trade may risk more than this share of the account balance.
MAX_RISK_PCT = 0.10
AWAKE_WIN = 7200         # awake gate: >=1 flip within this window
DEBT_MODE = "hwm"        # hwm (peak) | half (0.5x per loss)
SNIPER = False           # only the 2nd trade of each trend
ADDS_ON = True
TOUCH_ENTRIES = True     # continuation on level TOUCH (False = candle close)
DAY_CAP = None           # daily realised-profit stop (None = uncapped)
WEEK_TARGET = None       # informational only, printed at startup
_SFX = ""
if VARIANT == "sniper":
    TERMINAL = r"C:\NestTerminals\u476989735\terminal64.exe"
    LOGIN = 476989735
    SERVER = "Exness-MT5Trial9"
    MAGIC = 909201
    COMMENT = "KL-SNIPER"
    BASE_LOT = 0.06
    MAX_EXTRA = 0
    ADDS_ON = False
    SNIPER = True
    KILL_NET = -80.0
    _SFX = "_sniper"
elif VARIANT == "halfdebt":
    TERMINAL = r"C:\NestTerminals\u476989740\terminal64.exe"
    LOGIN = 476989740
    SERVER = "Exness-MT5Trial9"
    MAGIC = 909301
    COMMENT = "KL-HALF"
    DEBT_MODE = "half"
    _SFX = "_half"
elif VARIANT == "kino":
    # 2026-09-18 (owner): the main bot moves onto the Pro real account, with
    # the SAME rules as Valere except one - it ignores the nervosity brake.
    # A live A/B: 41.7 days of replay could not tell whether that brake
    # helps, so the two accounts answer it forward, side by side.
    _ku = [x for x in json.load(open(os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "owl_nest_users.json"), encoding="utf-8"))
        if x.get("id") == "kino"][0]
    TERMINAL = _ku["terminal"]
    LOGIN = int(_ku["mt5_login"])
    SERVER = _ku["mt5_server"]
    PASSWORD = _ku["mt5_password"]
    MAGIC = 909501
    COMMENT = "KL-BOS-K"
    TOUCH_ENTRIES = False       # same candle-close rule as everywhere
    _SFX = "_kino"
elif VARIANT == "infinity":
    _SFX = "_infinity"
    # 2026-09-22 (owner): "add this new account of my cousin and let the
    # main bot run it with the same exact package as Valere." Same bot,
    # same code - only the package differs, which is the whole point of
    # the package split. Credentials from the nest record.
    _iu = [x for x in json.load(open(os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "owl_nest_users.json"), encoding="utf-8"))
        if x.get("id") == "infinity"][0]
    TERMINAL = _iu["terminal"]
    LOGIN = int(_iu["mt5_login"])
    SERVER = _iu["mt5_server"]
    PASSWORD = _iu["mt5_password"]
    MAGIC = 909701
    COMMENT = "KL-BOS"
    TOUCH_ENTRIES = False
elif VARIANT == "demo":
    # 2026-09-19 (owner): the public SHOWCASE account - "a demo account for
    # all to view, so they may see how the bot performs". Same bot, same
    # rules, base package, auto. Credentials from the nest record.
    _du = [x for x in json.load(open(os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "owl_nest_users.json"), encoding="utf-8"))
        if x.get("id") == "demo"][0]
    TERMINAL = _du["terminal"]
    LOGIN = int(_du["mt5_login"])
    SERVER = _du["mt5_server"]
    PASSWORD = _du["mt5_password"]
    MAGIC = 909601
    COMMENT = "KL-BOS-D"
    TOUCH_ENTRIES = False
    _SFX = "_demo"
elif VARIANT == "valere":
    # 2026-09-14 (owner): Valere's real account runs its OWN instance of
    # the frozen live config - identical rules, but its own debt ledger,
    # its own war-chest and its own -$60 kill line, so his account never
    # depends on Kino's. Credentials come from the nest record (that file
    # is untracked); nothing here is shared with the live instance.
    _vu = [x for x in json.load(open(os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "owl_nest_users.json"), encoding="utf-8"))
        if x.get("id") == "u224016179"][0]
    TERMINAL = _vu["terminal"]
    LOGIN = int(_vu["mt5_login"])
    SERVER = _vu["mt5_server"]
    PASSWORD = _vu["mt5_password"]
    MAGIC = 909401
    COMMENT = "KL-BOS-V"
    TOUCH_ENTRIES = False       # same candle-close rule as live
    # owner 2026-09-14: objective ~$20/week. Once the day is +$3
    # REALISED, stop opening (a running position is left alone) and
    # resume next UTC day. Waived while the account is in debt -
    # catching up must not be throttled.
    DAY_CAP = 3.0
    WEEK_TARGET = 20.0
    _SFX = "_valere"
else:
    TERMINAL = r"C:\NestTerminals\u223995441\terminal64.exe"
    LOGIN = 223995441
    SERVER = "Exness-MT5Real30"
    MAGIC = 909101
    COMMENT = "KL-BOS"
    # user 2026-09-11 after the execution audit (Owl/study/audit):
    # continuation entries go back to the candle CLOSE (no execution
    # bias, +237 on ticks vs +206 touch); the touch rule keeps running
    # as a paper twin in bos_paper_touch.py for a side-by-side record.
    TOUCH_ENTRIES = False

DIR = os.path.dirname(os.path.abspath(__file__))
STATE_F = os.path.join(DIR, f"bos_state{_SFX}.json")
LOG_F = os.path.join(DIR, f"bos_bot{_SFX}.log")
# Two switches (owner 2026-09-16). The app writes a per-account file, and
# the bot used to read only the global one - so the per-account pause
# buttons did nothing and pausing "kino" silently stopped every variant.
#   owl_trading_pause.json          = master switch, stops everything
#   owl_trading_pause_<uid>.json    = this account only
PAUSE_UID = {"valere": "u224016179", "sniper": "sniper",
             "halfdebt": "half", "kino": "kino",
             "demo": "demo", "infinity": "infinity"}.get(VARIANT, "bos")
PAUSE_F = os.path.join(DIR, "owl_trading_pause.json")
PAUSE_OWN = os.path.join(DIR, f"owl_trading_pause_{PAUSE_UID}.json")

# --- MONEY MANAGEMENT comes from the account's PACKAGE -----------------
# Owner 2026-09-18: "Valere's difference should just be the daily cut off
# profit... new accounts may have different money management, package kind
# of thing... make things easy for codes to go that route."
#
# So the STRATEGY above is identical on every account, and only the dials
# below may differ. They live in owl_packages.json: a new offer is a few
# lines of JSON, and retuning one costs no code change and no restart.
# review/package_parity.py proves this reproduces, value for value, what
# the hardcoded variants did before.
import owl_package as _PKG
import owl_shadow as SHADOW
_KB = []          # the last 3 closed M1 bars, refreshed every loop


def fvg_pts(d):
    """Fair-value gap left by the confirming candle, in points, or 0.
    bullish: low[i] > high[i-2]; bearish: high[i] < low[i-2].
    Owner 2026-09-19: replayed, a gap split BOS into +0.108 R (with) vs
    -0.050 (without) on 6/6 anchors - but the two halves disagreed and the
    shuffle gave p = 0.076, so it is NOT deployed. Every qualifying signal
    is tagged with its gap and followed virtually instead (book "fvg"),
    so the forward record can re-run those two controls with more data."""
    if len(_KB) < 3:
        return 0.0
    c1, c3 = _KB[-3], _KB[-1]
    if d == 1:
        return max(0.0, float(c3["low"]) - float(c1["high"]))
    return max(0.0, float(c1["low"]) - float(c3["high"]))
_P = _PKG.for_account(PAUSE_UID)
PACKAGE = _P["package"]
BASE_LOT = _P["base_lot"]
MAX_EXTRA = _P["max_extra"]
ADDS_ON = _P["adds_on"]
CHEST_CAP = _P["chest_cap"]
JAR = _P["jar"]
JAR_SKIM = _P["jar_skim"]
JAR_STAKE = _P["jar_stake"]
JAR_DEBT_MULT = _P["jar_debt_mult"]
JAR_FLOOR_CAP = _P["jar_floor_cap"]
KILL_NET = _P["kill_net"]
MIN_BALANCE = _P["min_balance"]
MAX_RISK_PCT = _P["max_risk_pct"]
DEBT_MODE = _P["debt_mode"]
DAY_CAP = _P["day_cap"]
MAX_TRADES_DAY = _P["max_trades_day"]
WEEK_TARGET = _P["week_target"]
NERVOSITY = _P.get("nervosity", True)
MOVEMENT = _P.get("movement", True)


def say(msg):
    line = f"{datetime.now(timezone.utc).isoformat()} {msg}"
    print(line, flush=True)
    with open(LOG_F, "a", encoding="utf-8") as f:
        f.write(line + "\n")


class Struct:
    """The chart's structure engine, incremental (same code that ran
    the backtests in scratchpad bt_bos*)."""

    def __init__(self):
        self.kept = []
        self.ref_h = self.ref_l = None
        self.hi_i = self.lo_i = 0
        self.hi_v = self.lo_v = None
        self.trend = 0
        self.choch = 0
        self.last_lo = self.last_hi = None
        self.up_st = self.dn_st = 0
        self.prot_lo = self.prot_hi = None
        self.quiet = False       # True during the seed replay

    def step(self, t, o, h, l, c):
        if self.ref_h is not None and not (c > self.ref_h
                                           or c < self.ref_l):
            return None
        k = self.kept
        k.append([t, o, h, l, c, 1 if c >= o else -1])
        self.ref_h, self.ref_l = h, l
        i = len(k) - 1
        if i == 0:
            self.hi_v, self.lo_v = h, l
            return None
        sig = None
        if (self.trend == 1 and self.prot_lo is not None
                and c < self.prot_lo[1]):
            self.choch = -1
            self.prot_lo = None
            self.lo_i, self.lo_v = i, l
            if not self.quiet:
                say(f"CHoCH bearish at {self.kept[i][4]:.2f}")
        elif (self.trend == -1 and self.prot_hi is not None
                and c > self.prot_hi[1]):
            self.choch = 1
            self.prot_hi = None
            self.hi_i, self.hi_v = i, h
            if not self.quiet:
                say(f"CHoCH bullish at {self.kept[i][4]:.2f}")
        if c > self.hi_v:
            span = k[self.hi_i + 1:i]
            if span and any(x[5] == -1 for x in span):
                m = min(span, key=lambda x: x[3])
                nd = [m[0], m[3], 1]
                if self.choch == 1 and self.trend != 1:
                    self.trend = 1
                    self.choch = 0
                    self.prot_lo = nd
                    self.up_st = self.dn_st = 0
                    sig = (1, m[3])
                elif self.trend == 1:
                    self.prot_lo = nd
                    self.choch = 0
                    sig = (1, m[3])
                elif self.trend == 0:
                    # Owner 2026-09-19: "two glowing dots = a structure, a
                    # trend forming is enough" - and "internal trades follow
                    # the SAME rules as main trades". The chart engine was
                    # aligned first; this is the same change here, so the
                    # bot cannot sit on a structure the chart already shows.
                    # Old locks removed: the 2nd dot no longer has to be
                    # higher, and the 1st confirmed dot now counts.
                    self.up_st += 1
                    self.dn_st = 0
                    if self.up_st >= 2:
                        self.trend = 1
                        self.prot_lo = nd
                        sig = (1, m[3])
                self.last_lo = m[3]
                self.lo_i = k.index(m)
                self.lo_v = m[3]
            self.hi_i, self.hi_v = i, h
        elif c < self.lo_v:
            span = k[self.lo_i + 1:i]
            if span and any(x[5] == 1 for x in span):
                m = max(span, key=lambda x: x[2])
                nd = [m[0], m[2], -1]
                if self.choch == -1 and self.trend != -1:
                    self.trend = -1
                    self.choch = 0
                    self.prot_hi = nd
                    self.up_st = self.dn_st = 0
                    sig = (-1, m[2])
                elif self.trend == -1:
                    self.prot_hi = nd
                    self.choch = 0
                    sig = (-1, m[2])
                elif self.trend == 0:
                    # mirror of the bullish bootstrap (owner 2026-09-19)
                    self.dn_st += 1
                    self.up_st = 0
                    if self.dn_st >= 2:
                        self.trend = -1
                        self.prot_hi = nd
                        sig = (-1, m[2])
                self.last_hi = m[2]
                self.hi_i = k.index(m)
                self.hi_v = m[2]
            self.lo_i, self.lo_v = i, l
        return sig


def paused():
    for _f in (PAUSE_F, PAUSE_OWN):
        try:
            if json.load(open(_f)).get("paused"):
                return True
        except Exception:
            pass
    return False


def load_state():
    try:
        return json.load(open(STATE_F))
    except Exception:
        return {"debt": 0.0, "chest": 0.0, "banked": 0.0,
                "trades": 0, "killed": False, "last_bar": 0,
                "open_lot": 0.0}


CHART_F = os.path.join(DIR, "owl_chart_btc.json")


def weather(max_age=180):
    """The market-weather feed, or None when it is missing or stale."""
    try:
        st = os.stat(CHART_F)
        if time.time() - st.st_mtime > max_age:
            return None
        with open(CHART_F, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def weather_gate(need_int=False, cj=None):
    """Shared entry brakes. None allows, a string refuses.

    Owner 2026-09-18: "every time we make a change in the main bot, update
    the rest of the bots everywhere". These two rules lived only in the
    manual desk, so account 441 obeyed them and Valere did not - Valere
    entered at 05:01 in a 1.30x market that the desk refused at 05:31.
    They are STRATEGY, so they belong here, shared by every account.

    Both rules only ever STOP a trade; neither was shown to make money,
    and they cut volume by roughly 90%. A missing or stale feed ALLOWS -
    a brake that fires on its own silence would stop everything the moment
    the feed hiccups.
    """
    cj = cj if cj is not None else weather()
    if not cj:
        return None
    # BOTH halves can now be switched off per account. nervosity: owner
    # 2026-09-18 live A/B. movement: owner 2026-09-20, "trade all signals,
    # no gates, good weather or bad". Turning a brake off is not an edge
    # claim - neither brake was ever shown to make money (see the packages
    # memo), so an account with both off is the honest control arm.
    vn, vr = cj.get("vol_now"), cj.get("vol_ref")
    if vn and vr:
        nerv = vn / max(vr, 1)
        # the exception that outranks every dial (owner 2026-09-21)
        if nerv >= NERV_STORM:
            return (f"marche tres rapide ({nerv:.2f}x) - exception, "
                    f"personne ne trade")
        if NERVOSITY and nerv > 1.0:
            return f"trop nerveux ({nerv:.2f}x)"
    if not MOVEMENT:
        return None
    if need_int:
        if (cj.get("int_brk_1h") or 0) < 1:
            return "aucun petit mouvement depuis 1 h"
    else:
        if (cj.get("moves_2h") or 0) < 1:
            return "aucun grand mouvement depuis 2 h"
    return None


def day_key():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def day_roll(st):
    """Reset the daily counters when the UTC date changes."""
    if st.get("day_key") != day_key():
        st["day_key"] = day_key()
        st["day_pnl"] = 0.0
        st["day_n"] = 0
        st["day_capped"] = False
    return st.get("day_pnl", 0.0)


def day_blocked(st):
    """Why no new entry today, or None to allow.

    Two different limits (owner 2026-09-18):
      day_cap        a PROFIT target. Waived while the account owes money,
                     because catching up must not be throttled.
      max_trades_day a PACKAGE limit - how many trades this offer includes.
                     Never waived: it is what the account signed up for.
    """
    pnl = day_roll(st)
    cap = MAX_TRADES_DAY
    if cap is not None and st.get("day_n", 0) >= cap:
        return (f"{st.get('day_n', 0)}/{cap} trades du jour "
                f"(forfait {PACKAGE})")
    if DAY_CAP is None:
        return None
    if st.get("debt", 0.0) > 0.5:
        return None
    if pnl >= DAY_CAP:
        return f"+{pnl:.2f} aujourd'hui (>= ${DAY_CAP:.2f}), sans dette"
    return None


def save_state(st):
    # the app reads the recovery dials from here, so there is ONE source of
    # truth for them instead of a copy in the server (owner 2026-09-16)
    st["jar"] = JAR
    st["jar_skim"] = JAR_SKIM
    st["jar_stake"] = JAR_STAKE
    st["jar_cap"] = round(max(JAR_FLOOR_CAP,
                              JAR_DEBT_MULT * st.get("debt", 0.0)), 2)
    st["base_lot"] = BASE_LOT
    st["max_extra"] = MAX_EXTRA
    st["rr"] = RR
    tmp = STATE_F + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(st, fh)
    for _ in range(12):
        try:
            os.replace(tmp, STATE_F)
            return
        except PermissionError:
            time.sleep(0.05)
    try:
        os.replace(tmp, STATE_F)
    except Exception:
        pass


def ensure_algo():
    ti = mt5.terminal_info()
    if ti is not None and ti.trade_allowed:
        return True
    try:
        import ctypes
        import ctypes.wintypes as wt
        import subprocess
        tok = os.path.basename(os.path.dirname(TERMINAL))
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-CimInstance Win32_Process -Filter "
             "\"Name='terminal64.exe'\" | Where-Object "
             "{ $_.CommandLine -match '" + tok + "' } | "
             "Select-Object -ExpandProperty ProcessId"],
            capture_output=True, text=True, timeout=30)
        pid = int(out.stdout.strip().splitlines()[0])
        user32 = ctypes.windll.user32
        hwnds = []

        @ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)
        def cb(hh, ll):
            p = wt.DWORD()
            user32.GetWindowThreadProcessId(hh, ctypes.byref(p))
            if p.value == pid and user32.IsWindowVisible(hh):
                hwnds.append(hh)
            return True

        # 2026-09-19: on the public demo the first attempt ran seconds
        # after the terminal was launched, found NO windows yet, posted
        # nothing and reported False - the same toggle by PID worked on
        # the first try once the terminal was up. So wait for a window,
        # up to 30 s, and re-enumerate before posting.
        ok = False
        for _try in range(6):
            hwnds.clear()
            user32.EnumWindows(cb, 0)
            if not hwnds:
                time.sleep(5)
                continue
            for hh in hwnds:
                user32.PostMessageW(hh, 0x0111, 32851, 0)
            time.sleep(3)
            ti = mt5.terminal_info()
            ok = ti is not None and ti.trade_allowed
            if ok:
                break
        say(f"ensure_algo -> trade_allowed={ok} (windows {len(hwnds)})")
        return ok
    except Exception as e:
        say(f"ensure_algo FAILED {type(e).__name__}: {e}")
        return False


def my_positions():
    return [p for p in (mt5.positions_get(symbol=SYMBOL) or [])
            if p.magic == MAGIC]


def floating():
    return sum(p.profit + p.swap for p in my_positions())


def book_closes(st, t_from):
    """Ledger bookkeeping for deals closed since t_from."""
    ds = mt5.history_deals_get(
        datetime.fromtimestamp(t_from, tz=timezone.utc),
        datetime.now(timezone.utc)) or []
    seen = st.setdefault("seen_deals", [])
    for d in ds:
        if d.magic != MAGIC or d.entry != mt5.DEAL_ENTRY_OUT:
            continue
        if d.ticket in seen:
            continue          # the query window overlaps on purpose;
        seen.append(d.ticket)  # each deal books exactly once
        del seen[:-200]
        pnl = d.profit + d.swap + d.commission
        lot = float(d.volume)
        st["banked"] = round(st.get("banked", 0.0) + pnl, 2)
        day_roll(st)
        st["day_pnl"] = round(st.get("day_pnl", 0.0) + pnl, 2)
        # HIGH-WATER-MARK ledger (user 2026-09-09, measured: same
        # net as the per-loss ledger, maxDD 72 vs 80): the debt IS
        # the drawdown from the equity peak; fighters hunt until
        # the peak is reclaimed. Chest fills from new-high overflow
        # (cap $10) and pays every bullet's losses.
        is_add = d.position_id in (st.get("add_ids") or [])
        if not is_add:
            # consecutive losing MAIN trades. Owner 2026-09-23: bullets do
            # not fire during a bad run - measured +$26 and the same
            # drawdown over 41.7 days, better on 6/6 anchors, both halves
            # and every spread, and proven to be SELECTION not size
            # (review/bullet_tune_test.py streak_rule()).
            st["loss_streak"] = 0 if pnl > 0 else st.get("loss_streak", 0) + 1
        if pnl < 0:
            if is_add:
                st["chest"] = round(max(0.0, st["chest"] + pnl), 2)
            elif lot > BASE_LOT + 0.001:
                extra_sh = pnl * (1.0 - BASE_LOT / lot)
                st["chest"] = round(max(0.0,
                                        st["chest"] + extra_sh), 2)
        if JAR and pnl > 0:
            st["chest"] = round(st.get("chest", 0.0) + JAR_SKIM * pnl, 2)
        if DEBT_MODE == "half":
            # per-loss debt at 0.5x; wins pay it, overflow -> chest
            if pnl < 0:
                st["debt"] = round(st["debt"] + 0.5 * (-pnl), 2)
            elif pnl > 0:
                pay = min(st["debt"], pnl)
                st["debt"] = round(st["debt"] - pay, 2)
                st["chest"] = round(min(CHEST_CAP,
                                        st["chest"] + pnl - pay), 2)
        else:
            pk = st.get("peak", 0.0)
            if st["banked"] > pk:
                st["chest"] = round(min(CHEST_CAP,
                                        st["chest"]
                                        + st["banked"] - pk), 2)
                st["peak"] = st["banked"]
            st["debt"] = round(max(0.0, st.get("peak", 0.0)
                                   - st["banked"]), 2)
        if JAR:
            _cap = max(JAR_FLOOR_CAP, JAR_DEBT_MULT * st["debt"])
            st["chest"] = round(min(st.get("chest", 0.0), _cap), 2)
        if not is_add:
            st["trades"] = st.get("trades", 0) + 1
        tag = "ADD" if is_add else ("WIN" if pnl > 0 else
                                    "LOSS" if pnl < 0 else "FLAT")
        say(f"{tag} {pnl:+.2f} (lot {lot:.2f}): debt "
            f"${st['debt']:.2f} (peak {st.get('peak', 0.0):+.2f}), "
            f"chest ${st['chest']:.2f} - bot net "
            f"{st['banked']:+.2f} ({st.get('trades', 0)} trades)")


def main():
    assert mt5.initialize(path=TERMINAL, login=LOGIN,
                          password=PASSWORD, server=SERVER,
                          timeout=60000), "MT5 init failed"
    ai = mt5.account_info()
    assert ai and ai.login == LOGIN, f"wrong account {ai}"
    mt5.symbol_select(SYMBOL, True)
    # name the package and the two brakes. A package reaches a bot only at
    # import, so the log line is the only place that can prove WHICH dials
    # this process is actually running (owner 2026-09-20).
    _br = ([] if NERVOSITY and MOVEMENT else
           ["AUCUN FREIN - tous les signaux"] if not (NERVOSITY or MOVEMENT)
           else ["sans frein nervosite"] if not NERVOSITY
           else ["sans frein mouvement"])
    say(f"BOS-BOT starting on {ai.login} balance {ai.balance:.2f} "
        f"base {BASE_LOT} RR {RR} kill {KILL_NET} | paquet {PACKAGE}"
        + ("".join(f" | {x}" for x in _br))
        + (f" | day cap +${DAY_CAP:.2f} (waived while in debt), "
           f"target ${WEEK_TARGET:.0f}/week" if DAY_CAP else ""))
    ensure_algo()

    eng = Struct()
    eng.quiet = True
    flips = []               # epoch times of trend flips (awake gate)
    R = mt5.copy_rates_from_pos(SYMBOL, mt5.TIMEFRAME_M1, 1,
                                SEED_BARS)
    assert R is not None and len(R) > 100, "no history"
    for r in R:
        _pt = eng.trend
        eng.step(int(r["time"]), float(r["open"]), float(r["high"]),
                 float(r["low"]), float(r["close"]))
        if eng.trend != _pt and eng.trend != 0 and _pt != 0:
            flips.append(int(r["time"]))
    flips = flips[-20:]
    eng.quiet = False
    st = load_state()
    st["last_bar"] = int(R["time"][-1])
    save_state(st)
    say(f"seeded {len(R)} bars: trend {eng.trend} "
        f"choch {eng.choch} kept {len(eng.kept)}")

    def enter(d, slp, kind, internal=False):
        """Shared entry executor (close-BOS, flip-BOS, touch, and - owner
        2026-09-19 - the INTERNAL structure: "the bot is main and internal
        structure both, wherever it is used, same code for all accounts").
        An internal entry follows the desk's approved rules: the 1 h
        small-move brake instead of the 2 h one, half the base lot, no
        recovery bullets."""
        if my_positions():
            return False
        if paused():
            return False
        _wg = weather_gate(need_int=internal)
        if _wg:
            say(f"{kind} refuse: {_wg}")
            # Owner 2026-09-18: the nervosity brake could not be settled in
            # 41.7 days, so every trade it refuses is written down and
            # followed virtually. Only nervosity refusals, and only when the
            # movement rule would have passed - that is the counterfactual.
            if _wg.startswith("trop nerveux"):
                _cjx = weather()
                if _cjx and not weather_gate(
                        cj=dict(_cjx, vol_now=0, vol_ref=1)):
                    _tk = mt5.symbol_info_tick(SYMBOL)
                    if _tk:
                        _e = _tk.ask if d == 1 else _tk.bid
                        _ds = abs(_e - slp)
                        if _ds > S_MIN_DIST:
                            SHADOW.open_trade(
                                PAUSE_UID, d, _e, slp,
                                _e + d * RR * _ds, _wg, BASE_LOT)
            return False
        _why = day_blocked(st)
        if _why:
            if not st.get("day_capped"):
                st["day_capped"] = True
                save_state(st)
                say(f"LIMITE DU JOUR: {_why} - plus d'entree jusqu'au "
                    f"prochain jour UTC")
            return False
        ai2 = mt5.account_info()
        if ai2 is None or ai2.balance < MIN_BALANCE:
            return False
        tick = mt5.symbol_info_tick(SYMBOL)
        if tick is None:
            return False
        e_ref = tick.ask if d == 1 else tick.bid
        dist = abs(e_ref - slp)
        if dist <= S_MIN_DIST:
            say(f"{kind} skipped: dot {dist:.0f}pts inside the "
                f"spread zone")
            return False
        # Owner 2026-09-20: "at the BOS level it's a normal lot. If price
        # pulls back to the midpoint we introduce the combat bullets there,
        # if the economy allows, as always." So the recovery bullets no
        # longer ride the first entry - they wait for the 50% pullback,
        # where the stop is half as far and each bullet costs half as much.
        lot = BASE_LOT
        # Owner 2026-09-22: "equal the lot of the internal structure to be
        # same as the main structure except for counter trend trade. Same
        # direction as main structure gets the usual main structure base
        # lot." The half lot was a caution from 2026-09-15 taken before
        # there was any evidence; 37 forward internal trades since show
        # 59% wins and +$5.27 net - indistinguishable from the main
        # structure, so an aligned internal trade no longer rides smaller.
        #
        # NOTE: the counter-trend branch below is UNREACHABLE today. The
        # loop only calls enter(..., internal=True) when the internal trend
        # EQUALS the main trend; a counter-trend internal break is recorded
        # and skipped. It is written so the rule is complete if that ever
        # opens up, not because it runs now.
        if internal and d != eng.trend:
            _half = round(max(0.01, int((BASE_LOT / 2) / 0.01) * 0.01), 2)
            if not _half < BASE_LOT - 1e-9:
                say(f"{kind} refuse: demi-lot impossible a {BASE_LOT}")
                return False
            lot = _half
        # --- no single trade may risk more than 10% of the balance
        risk = dist * lot
        cap = MAX_RISK_PCT * ai2.balance
        if risk > cap:
            say(f"{kind} SKIPPED: risk ${risk:.2f} > "
                f"{MAX_RISK_PCT:.0%} of the ${ai2.balance:.2f} balance "
                f"(${cap:.2f})")
            return False
        tp = e_ref + d * RR * dist
        # forward record for the FVG filter: this signal passed every rule
        # the bot has, so it is exactly what the replay counted. Virtual,
        # settled on raw bars by SHADOW.settle(..., book="fvg").
        # selector forward record (owner 2026-09-20). "after each virtual
        # loss" is a slice of this book's own outcomes, so it needs nothing
        # stored; "the 2nd trade of a trend" needs the ordinal, which only
        # the bot knows. Internal trades carry ord=i - they are a separate
        # sequence and the replay never had them. Tag only: nothing filters.
        if internal:
            _ordt = "i"
        else:
            st["tord"] = st.get("tord", 0) + 1
            _ordt = str(st["tord"])
        SHADOW.open_trade(PAUSE_UID, d, e_ref, slp, tp,
                          f"fvg={fvg_pts(d):.0f} {kind} ord={_ordt}",
                          BASE_LOT, book="fvg")
        req = {"action": mt5.TRADE_ACTION_DEAL, "symbol": SYMBOL,
               "volume": lot,
               "type": (mt5.ORDER_TYPE_BUY if d == 1
                        else mt5.ORDER_TYPE_SELL),
               "price": e_ref, "sl": round(slp, 2),
               "tp": round(tp, 2), "deviation": 200,
               "magic": MAGIC, "comment": COMMENT,
               "type_time": mt5.ORDER_TIME_GTC,
               "type_filling": mt5.ORDER_FILLING_IOC}
        r = mt5.order_send(req)
        if r is not None and r.retcode == 10027 and ensure_algo():
            r = mt5.order_send(req)
        if r is None or r.retcode != mt5.TRADE_RETCODE_DONE:
            say(f"ENTRY FAILED retcode={r.retcode if r else None}")
            return False
        say(f"{kind} ENTRY: {'BUY' if d == 1 else 'SELL'} {lot} @ "
            f"~{e_ref:.2f} SL {slp:.2f} TP {tp:.2f} "
            f"(risk ${dist * lot:.2f}, "
            f"trend {'up' if d == 1 else 'down'})")
        # a package's trades-per-day limit counts ENTRIES, so it is spent
        # when the trade is taken, not when it closes (owner 2026-09-18)
        day_roll(st)
        st["day_n"] = st.get("day_n", 0) + 1
        # arm the 50%-pullback add (user 2026-09-09, measured:
        # +343/+422 vs +263 without; chest-funded bullets only)
        if ADDS_ON:
            st["add"] = {"d": d,
                         "lvl": round(e_ref - d * 0.5 * dist, 2),
                         "sl": round(slp, 2), "tp": round(tp, 2),
                         "risk001": round(0.5 * dist * 0.01, 2),
                         "done": False}
        save_state(st)
        return True
    last_book = time.time() - 60
    warned_funds = 0.0
    last_house = 0.0

    while True:
        # user 2026-09-08: act ON the candle close - wake right
        # after each broker minute boundary (max ~0.2s + processing
        # lag), light 1s ticks in between
        _to_min = 60.0 - (time.time() % 60.0) + 0.2
        time.sleep(min(_to_min, 1.0))
        try:
            if st.get("killed"):
                time.sleep(300)
                continue
            if time.time() - last_house >= 10.0:
                last_house = time.time()
                book_closes(st, last_book - 30)
                last_book = time.time()
                save_state(st)
            net = st.get("banked", 0.0) + floating()
            if net <= KILL_NET:
                say(f"KILL LINE: net {net:.2f} <= {KILL_NET} - "
                    f"closing and stopping")
                for p in my_positions():
                    tick = mt5.symbol_info_tick(SYMBOL)
                    mt5.order_send({
                        "action": mt5.TRADE_ACTION_DEAL,
                        "symbol": SYMBOL, "volume": p.volume,
                        "position": p.ticket,
                        "type": (mt5.ORDER_TYPE_SELL
                                 if p.type == mt5.POSITION_TYPE_BUY
                                 else mt5.ORDER_TYPE_BUY),
                        "price": (tick.bid
                                  if p.type == mt5.POSITION_TYPE_BUY
                                  else tick.ask),
                        "deviation": 200, "magic": MAGIC,
                        "comment": COMMENT + "-kill",
                        "type_filling": mt5.ORDER_FILLING_IOC})
                st["killed"] = True
                save_state(st)
                continue
            # 50%-PULLBACK ADD on the open trade (chest bullets)
            _ad = st.get("add")
            if _ad and not _ad.get("done") and my_positions():
                tk3 = mt5.symbol_info_tick(SYMBOL)
                if tk3 is not None:
                    _hit = (tk3.bid <= _ad["lvl"] if _ad["d"] == 1
                            else tk3.bid >= _ad["lvl"])
                    if _hit:
                        _ad["done"] = True
                        # Owner 2026-09-20: "make sure we don't add up at the
                        # pullback when the market is not calm." Calm = the
                        # weather card's own word: nervosity below 1.00x.
                        # Applied on EVERY account, even one whose package
                        # turns the nervosity brake off for entries - this is
                        # about sizing up a position that is already open.
                        _cjw = weather()
                        _vn, _vr = ((_cjw or {}).get("vol_now"),
                                    (_cjw or {}).get("vol_ref"))
                        _nerv = (_vn / max(_vr, 1)) if (_vn and _vr) else None
                        _r001 = max(_ad["risk001"], 0.01)
                        if _nerv is not None and _nerv > 1.0:
                            say(f"COMBAT skipped: marche pas calme "
                                f"({_nerv:.2f}x) - pas de balles ici")
                            _n = 0
                        elif st.get("loss_streak", 0) >= 2:
                            say(f"COMBAT skipped: "
                                f"{st['loss_streak']} pertes de suite - "
                                f"pas de balles dans une mauvaise serie")
                            _n = 0
                        elif st["debt"] <= 0.5:
                            _n = 0        # nothing to recover, no fighters
                        elif JAR:
                            # the BOS entry's economy, now applied at the
                            # midpoint: stake only part of the jar, and never
                            # buy more recovery than the debt needs. A bullet
                            # here risks half of what it did at the BOS, so
                            # the same jar buys more of them.
                            _gain001 = RR * _r001
                            _by_budget = int((st["chest"] * JAR_STAKE)
                                             // _r001)
                            _by_debt = (int(math.ceil(st["debt"] / _gain001))
                                        if _gain001 > 0 else 0)
                            _n = max(0, min(MAX_EXTRA, _by_budget, _by_debt))
                        else:
                            _n = min(MAX_EXTRA,
                                     int(st["chest"] // _r001))
                        if _n > 0:
                            _al = round(_n * 0.01, 2)
                            _r3 = mt5.order_send({
                                "action": mt5.TRADE_ACTION_DEAL,
                                "symbol": SYMBOL, "volume": _al,
                                "type": (mt5.ORDER_TYPE_BUY
                                         if _ad["d"] == 1
                                         else mt5.ORDER_TYPE_SELL),
                                "price": (tk3.ask if _ad["d"] == 1
                                          else tk3.bid),
                                "sl": _ad["sl"], "tp": _ad["tp"],
                                "deviation": 200, "magic": MAGIC,
                                "comment": COMMENT + "-ADD",
                                "type_time": mt5.ORDER_TIME_GTC,
                                "type_filling":
                                    mt5.ORDER_FILLING_IOC})
                            if (_r3 is not None and _r3.retcode
                                    == mt5.TRADE_RETCODE_DONE):
                                st.setdefault("add_ids", [])\
                                    .append(_r3.order)
                                del st["add_ids"][:-40]
                                say(f"COMBAT: {_n} balle"
                                    f"{'s' if _n > 1 else ''} de 0.01 au "
                                    f"mi-chemin ({_ad['lvl']:.2f}), meme "
                                    f"SL/TP - dette ${st['debt']:.2f}, "
                                    f"bocal ${st['chest']:.2f}, mise "
                                    f"${_n * _ad['risk001']:.2f}")
                            else:
                                say(f"ADD FAILED retcode="
                                    f"{_r3.retcode if _r3 else None}")
                        save_state(st)
            if st.get("add") and not my_positions():
                st["add"] = None
                save_state(st)
            # TOUCH continuation (user 2026-09-09, measured first:
            # +263/DD67 vs +207/DD85 close-only; flips keep the
            # close rule). Checked every ~1s wake on live ticks.
            if (TOUCH_ENTRIES and not my_positions()
                    and any(f > time.time() - AWAKE_WIN
                            for f in flips)):
                tk2 = mt5.symbol_info_tick(SYMBOL)
                if tk2 is not None:
                    if (eng.trend == 1 and eng.hi_v is not None
                            and tk2.bid > eng.hi_v
                            and st.get("used_hi") != eng.hi_v):
                        span = eng.kept[eng.hi_i + 1:]
                        if span and any(x[5] == -1 for x in span):
                            m = min(span, key=lambda x: x[3])
                            st["used_hi"] = eng.hi_v
                            st["ord"] = st.get("ord", 0) + 1
                            save_state(st)
                            if not SNIPER or st["ord"] == 2:
                                enter(1, m[3], "TOUCH")
                    elif (eng.trend == -1 and eng.lo_v is not None
                            and tk2.bid < eng.lo_v
                            and st.get("used_lo") != eng.lo_v):
                        span = eng.kept[eng.lo_i + 1:]
                        if span and any(x[5] == 1 for x in span):
                            m = max(span, key=lambda x: x[2])
                            st["used_lo"] = eng.lo_v
                            st["ord"] = st.get("ord", 0) + 1
                            save_state(st)
                            if not SNIPER or st["ord"] == 2:
                                enter(-1, m[2], "TOUCH")
            # 3 closed bars, not 2: the fair-value-gap tag needs the bar
            # two before the confirming one (owner 2026-09-19, forward test)
            kb = mt5.copy_rates_from_pos(SYMBOL, mt5.TIMEFRAME_M1,
                                         1, 3)
            if kb is None or len(kb) < 3:
                continue
            _KB[:] = list(kb)
            bar = kb[-1]
            bt = int(bar["time"])
            if bt == st.get("last_bar"):
                continue
            st["last_bar"] = bt
            # settle the virtual trades the nervosity brake refused, on the
            # raw bar - they must be judged on every minute, not only on the
            # candles the silence filter keeps (owner 2026-09-18)
            SHADOW.settle(PAUSE_UID, float(bar["high"]), float(bar["low"]))
            SHADOW.settle(PAUSE_UID, float(bar["high"]), float(bar["low"]),
                          book="fvg")
            _pt = eng.trend
            _hv, _lv = eng.hi_v, eng.lo_v
            sig = eng.step(bt, float(bar["open"]),
                           float(bar["high"]), float(bar["low"]),
                           float(bar["close"]))
            if eng.trend != _pt and eng.trend != 0 and _pt != 0:
                flips.append(bt)
                del flips[:-20]
                say(f"FLIP: trend now "
                    f"{'up' if eng.trend == 1 else 'down'}")
            awake = any(f > bt - AWAKE_WIN for f in flips)
            try:
                # live bullet price estimate: distance to the
                # trend's protected dot = the likely next stop
                _c = float(bar["close"])
                _pd = (eng.prot_lo if eng.trend == 1
                       else eng.prot_hi if eng.trend == -1 else None)
                _blt = (round(max(0.5, min(3.0,
                        abs(_c - _pd[1]) * 0.01)), 2)
                        if _pd else 3.0)
                json.dump({"awake": awake, "trend": eng.trend,
                           "choch": eng.choch,
                           "flips_2h": sum(1 for f in flips
                                           if f > bt - AWAKE_WIN),
                           "bullet": _blt,
                           "updated": int(time.time())},
                          open(os.path.join(
                              DIR, f"bos_weather{_SFX}.json"), "w"))
            except Exception:
                pass
            save_state(st)
            # ---- INTERNAL structure (owner 2026-09-19): mirrors the desk.
            # The chart feed is the one implementation of the internal
            # engine; its protected level moves on every internal break, so
            # a changed int_inv_t is a break just confirmed. Entered only in
            # the direction of the MAIN trend, and only once per level -
            # the last level is persisted so a restart cannot replay it.
            _cj = weather()
            if _cj:
                _iv, _ivt = _cj.get("int_inv"), _cj.get("int_inv_t")
                _itr = _cj.get("int_trend") or 0
                if (_iv and _ivt and _ivt != st.get("int_last_t")
                        and _itr and _itr == eng.trend):
                    st["int_last_t"] = _ivt
                    save_state(st)
                    enter(_itr, float(_iv), "INT", internal=True)
                elif _ivt and _ivt != st.get("int_last_t"):
                    # noted, not traded. This used to be SILENT, which made
                    # account divergences impossible to diagnose after the
                    # fact (owner 2026-09-22: Infinity took an internal trade
                    # that Kino and the demo, both flat and ungated, did not -
                    # and no log line anywhere said why). Say which rule
                    # declined it.
                    _why = ("pas de tendance interne" if not _itr
                            else f"contre la tendance principale "
                                 f"(interne {'haut' if _itr == 1 else 'bas'}, "
                                 f"principale "
                                 f"{'haut' if eng.trend == 1 else 'bas'})")
                    say(f"INT note, pas pris: {_why}")
                    st["int_last_t"] = _ivt
                    save_state(st)
            if sig is None:
                continue
            if not awake:
                say("BOS signal skipped - market asleep (no flip "
                    "in 2h)")
                continue
            d, slp = sig
            flip = eng.trend != _pt
            if flip:
                st["ord"] = 1
                st["tord"] = 0     # taken-trade ordinal, for the shadow tag
                save_state(st)
                if SNIPER:
                    continue      # sniper skips the flip trade
            else:
                # touch owns continuations; close-entry only as the
                # fallback when the level was never touched (gap,
                # downtime)
                lvl = _hv if d == 1 else _lv
                if (d == 1 and st.get("used_hi") == lvl) or \
                        (d == -1 and st.get("used_lo") == lvl):
                    continue
                st["ord"] = st.get("ord", 0) + 1
                save_state(st)
                if SNIPER and st["ord"] != 2:
                    continue
            enter(d, slp, "FLIP-BOS" if flip else "BOS")
        except Exception as e:
            say(f"ERROR {type(e).__name__}: {e}")
            time.sleep(30)


if __name__ == "__main__":
    main()
