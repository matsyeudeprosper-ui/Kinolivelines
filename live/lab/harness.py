"""The lab's replay harness (2026-09-28): ONE simulate() for every what-if.

Same engine as the live bot (structure_bos_bot.Struct), same deployed rules
(awake window, storm line, movement gate, one trade per level, flip + N
continuations in debt, tab/jar bullets), driven by a config dict so the
researcher, the chercheur session and a human can all ask the same
question the same way:

    python lab/harness.py --rr 0.6                # one what-if vs deployed
    python lab/harness.py --wait 20 --ext 500 --json

Verdict rules (fixed, never tuned):
  A  better money in BOTH halves, worst debt not worse
  B  a smaller hole in both halves without losing money, or more money
     overall with one half agreeing
  C  everything else
  =  the change touched fewer than 3 trades / less than $1
"""
import argparse
import bisect
import json
import math
import os
import sys
from datetime import datetime, timezone

LAB = os.path.dirname(os.path.abspath(__file__))
LIVE = os.path.dirname(LAB)
sys.path.insert(0, LIVE)
_ARGV = sys.argv[1:]
sys.argv = ["harness"]

import MetaTrader5 as mt5              # noqa: E402
import structure_bos_bot as B          # noqa: E402
B.say = lambda *a, **k: None

CFG_BASE = {"rr": 0.8, "drag": 0.0, "n_cont": 1, "wait_min": 0, "ext_pts": 0, "skip_wd": [], "skip_hours": [],
            "size_hot": 1.0, "nerv_gate": False, "storm": 1.85, "bullets": 3, "k_streak": 2, "lot": 0.02,
            "debt_nerv_gate": False,   # built 2026-09-29 on the chercheur's request: still in the red AND nervous
            # 2026-10-02 (chercheur): wait_win = minutes with no new entry
            # after a WINNING close only; after a loss the recovery trade
            # goes out as today. 0 = off.
            "wait_win": 0,
            # 2026-10-05 (owner): cap_resume_h4 = after the daily profit cap
            # is hit, resume at the start of the Nth next 4-hour candle
            # (UTC 00/04/08/12/16/20) with the target counted again from
            # zero, instead of waiting for the next UTC day. 0 = off.
            "cap_resume_h4": 0,
            # 2026-10-04 (chercheur): chase_pts = no entry when the last hour
            # already moved more than X points the trade's way (up for a buy,
            # down for a sell); unlike ext_pts a move against it is left alone.
            # 0 = off.
            "chase_pts": 0,
            # 2026-10-04 (chercheur): nerv_floor = no entry when the market's
            # pace at entry is under X (1.0 = usual); the market is almost
            # asleep. 0 = off.
            "nerv_floor": 0.0,
            # 2026-10-05 (chercheur): flip_hot_size = lot multiplier on a
            # change-of-direction trade only, when the market's pace at entry
            # is 1.0 or more. The trade is still taken. 1.0 = off.
            "flip_hot_size": 1.0,
            # 2026-10-06 (chercheur): first_move_size = lot multiplier when
            # the entry is the first big move counted in the last 2 hours
            # (the journal's movement_count = 1, main structure only). The
            # trade is still taken. 1.0 = off.
            "first_move_size": 1.0,
            # 2026-09-29 (owner): cost_max refuses an entry whose fixed spread
            # eats more than X % of the stop distance; min_range refuses one
            # when the median 60-min candle range is under X points
            "cost_max": 0.0, "min_range": 0.0,
            # 2026-09-29 (owner): "what if we take only the first trade of a
            # new hour, between minute 1 and 29?" minute_win = [lo, hi] keeps
            # entries whose minute of the hour is in that window; one_per_hour
            # allows at most one entry per clock hour.
            "minute_win": [], "one_per_hour": False,
            # 2026-09-29 (owner): "wait for the flip, do not take it, then take
            # the continuations that follow it". only_kind "" = every entry,
            # "flip" = only the change of direction, "cont" = only the trades
            # that follow it. The flip still registers (it sets the direction
            # and refills the recovery allowance), it is simply not traded.
            "only_kind": "",
            # 2026-09-29 (owner): "my stop should stay inside the average loss,
            # and two wins of $5 should be what buys me the right to risk $5".
            # risk_max = a hard cap in dollars on one trade's risk.
            # bank_mult = the risk allowed is (BANK0 + profit so far) divided by
            # this, so the account has to earn the right to risk more.
            "risk_max": 0.0, "bank_mult": 0.0,
            # 2026-09-29 (owner): "use a percentage, the cap depends on the
            # balance". risk_pct is the share of the account one trade may
            # risk, and it is what should ever be deployed; risk_max stays as
            # the absolute version used to find the level in the first place.
            "risk_pct": 0.0,
            # 2026-09-30: cap the MONEY, not the trade. risk_fit is a
            # share of the balance, risk_fit_abs a dollar figure; the
            # lot is reduced to fit and the trade is only skipped when
            # 0.01 lot still risks more than the cap. E009 found the
            # widest stops are the BEST trades, so skipping them has to
            # be the last resort, not the first move.
            "risk_fit": 0.0, "risk_fit_abs": 0.0,
            # 2026-09-30 (owner): internal-structure entries. The BOT
            # takes these live and this harness did not model them at
            # all, so every backtest number excluded a trade type that
            # really trades. 0 = off (unchanged behaviour),
            # 1 = the live rule (only when the internal trend agrees
            # with the main one), 2 = also counter-trend, which the
            # bot logs and refuses today.
            "internal": 0,
            # 2026-09-30: an internal entry is meant to be the SMALL
            # structure, yet the one that cost real money carried a
            # 594pt stop against a 214pt main median. int_max_stop
            # refuses an internal entry whose stop is wider than this
            # multiple of the recent median candle range; int_tighter
            # refuses one wider than the MAIN structure's own stop.
            # 0 = off for both.
            "int_max_stop": 0.0, "int_tighter": 0,
            # 2026-09-30: the three rules the parity check found the bot
            # reads and this harness could not express. They were harmless
            # only because every account happened to use the value assumed
            # here; set one differently and the backtest silently stops
            # describing the bot again.
            #   max_trades_day - hard cap on entries per UTC day
            #   movement       - the "has the market moved" brake
            #   debt_mode      - "hwm" (peak) or "half" (0.5x a loss)
            "max_trades_day": 0, "movement": 1, "debt_mode": "hwm",
            # 2026-10-01 (owner): "I enter in calm weather, then tres
            # agite arrives while I am still in the trade - cut at the
            # next positive P&L, or let it run to SL/TP?" Today the bot
            # does NOTHING: nervosity gates entries only, so an open
            # trade runs to its target or its stop whatever the weather.
            #   0 = that, unchanged
            #   1 = once nervosity >= storm, leave at the first close
            #       that is not negative (the owner's suggestion)
            #   2 = leave at the first close after the storm arrives,
            #       whatever the P&L. This is the CONTROL: without it a
            #       win for 1 could just mean "getting out early is
            #       good" rather than "waiting for green is good".
            "storm_exit": 0,
            # 2026-10-01 (owner): "I'm in a buy trade taking long to hit
            # tp and then before it hits tp it's flipped trend and now
            # makes the first BOS on the opposite direction."
            #
            # This can genuinely happen with the original stop intact:
            # the protected level RATCHETS UP on every continuation
            # break, so a close below the LATEST protected low can
            # confirm a bearish CHoCH while the entry's own stop still
            # sits lower and untouched.
            #
            # Today the bot does two things here, both by omission:
            # `if sig is None or pos: continue` drops any signal while a
            # position is open, so it keeps the now-wrong-way trade AND
            # misses the new flip entry.
            #   0 = that, unchanged
            #   1 = close the trade when the opposing flip BOS confirms,
            #       and stand aside
            #   2 = close it AND take the reversal, which is what a
            #       person watching the chart would do
            "flip_exit": 0,
            # 2026-10-01 (owner): "move the SL to the next glowing
            # protected level that will come (if it comes)". The
            # stop follows the structure instead of sitting at the
            # level the trade was born on.
            #   0 = off, the stop never moves (unchanged)
            #   1 = move it to every new protected level, which can
            #       carry it past the entry and lock a gain
            #   2 = only once the level is past the entry, so the
            #       trade is never stopped for less than it risked
            #       but also never protected early
            "trail_prot": 0,
            # 2026-09-29 (owner: "does the backtest include the rattrapage and
            # the daily caps?"). It did not. These three close the gap:
            #   jar      model the real bullet economy - the jar has to pay for
            #            the extra lots, it never buys more recovery than the
            #            debt needs, and it fires only when the market is calm
            #   day_cap  stop taking trades once the day's realised profit
            #            reaches this (waived while still in the red, like live)
            #   kill_net stop for good once the account is this far down
            # All default to OFF so every earlier measurement stays comparable.
            "jar": False, "day_cap": 0.0, "kill_net": 0.0,
            # 2026-10-03 (chercheur): cap_fit = on an account with a daily
            # cap, a trade's target aims only for what is still missing to
            # reach the cap (after the spread), never further than rr.
            # Not applied while in the red, where the cap is waived anyway.
            # 0 = off; does nothing on an account without a daily cap.
            "cap_fit": 0,
            # 2026-10-06 (chercheur): cap_rr = on an account with a daily
            # cap, aim for X times the risk instead of rr. An account without
            # a daily cap keeps rr. 0 = off.
            "cap_rr": 0.0,
            # 2026-09-29 (owner: "each account has a different balance, so not
            # the same risk"). The live bot resizes the lot AND the daily cap
            # by balance / scale_ref, rounding the lot down to 0.01. With
            # balance = 0 the old flat lot is used, so nothing already measured
            # moves. Real balances today run 122 to 356, i.e. lots 0.01 to 0.03.
            "balance": 0.0, "scale_ref": 200.0}
# the live bot's own numbers, read from it so the two cannot drift apart
JAR_SKIM = getattr(B, "JAR_SKIM", 0.50)
JAR_STAKE = getattr(B, "JAR_STAKE", 0.50)
JAR_DEBT_MULT = getattr(B, "JAR_DEBT_MULT", 0.5)
JAR_FLOOR_CAP = getattr(B, "JAR_FLOOR_CAP", 10.0)
CHEST_CAP = getattr(B, "CHEST_CAP", 10.0)
BANK0 = 10.0    # the starting allowance for bank_mult, about two average losses
BAL0 = 230.0    # the reference balance, the same one structure_bos_bot uses
CFG_KEYS = list(CFG_BASE.keys())
# 2026-09-29 (owner): bump this whenever a change makes old numbers wrong.
# Anything stored under an older stamp is shown as "to be re-checked" and is
# never compared against a number from this one.
#   2026-09-29a  the original engine: no jar, no day cap, no kill line, a flat
#                0.02 lot for every account, and the midpoint bullet priced at
#                1.3 x distance (which silently assumed rr = 0.8)
#   2026-09-29b  jar, day cap, kill line, per-account lot and cap, bullet at
#                (0.5 + rr) x distance
ENGINE = "2026-09-29b"
# the two shapes every real account has: with a daily cap and without
REFS = ("base", "valere")
# 2026-09-29 (owner): "does the break's own character say whether it will
# run?" Set TRACE to a list to record one dict per trade: the power of the
# breaking candle, the age of the level it broke, how often that level had
# been approached, and the outcome. None by default, so the nightly battery
# pays nothing. Used by review/bos_break_character.py.
TRACE = None
# 2026-10-07 (owner): a function (t, d) -> bool that allows or refuses a trade
# by the direction another chart points. None by default.
DIRGATE = None
# 2026-10-08 (owner): the loss-pause rule. True -> after a losing trade the
# next trades are VIRTUAL (taken, scored, but booked nowhere: no money, no
# debt, no reserve, no streak) until one of them wins. Off by default.
LOSSPAUSE = False
# 2026-10-08 (owner): the Compte indicator as a bot rule. A callable
# (all_trades) -> (lot_multiplier, virtual) consulted at every entry.
# all_trades = every closed trade so far, real AND virtual, at FULL size
# (money / the multiplier that trade used) - the system's own curve, so a
# paused or shrunk account can still see its curve recover. None = off.
EQHOOK = None
# the internal-structure engine lives in the chart feed, factored out
# of its live loop exactly so other callers can use it. Imported here
# lazily: a harness run with internal=0 must not pay for it, and must
# not fail if the feed module cannot be imported.
_FEED = None


def _feed():
    global _FEED
    if _FEED is None:
        import importlib.util
        _p = os.path.join(LIVE, 'owl_chart_feed.py')
        _sp = importlib.util.spec_from_file_location('owl_chart_feed', _p)
        _m = importlib.util.module_from_spec(_sp)
        _sp.loader.exec_module(_m)
        _FEED = _m
    return _FEED
BLOT = 0.01
# 2026-10-02 (owner): on the SAME entries the bot took, this engine ran
# about $1.80 a trade more generous than the real accounts (lab/proof.json
# sources.drag, measured every night). Every replay charges that gap per
# closed trade, scaled by lot, so a verdict means "better after the gap we
# actually see". Default is RAW (drag 0): the gap is only charged on demand
# (--drag auto, or cfg drag=None) and only once it rests on DRAG_MIN_N
# like-for-like trades - on 18 trades the first figure ($1.84) killed the
# replay at its own kill line, and was not even like-for-like. The gap is
# measured on a raw replay (proof_build passes drag=0), or it would chase
# itself to zero.
DRAG_LOT = 0.02
DRAG_MAX = 5.0
DRAG_MIN_N = 30
_DRAG_CACHE = {}


def measured_drag():
    if "v" in _DRAG_CACHE:
        return _DRAG_CACHE["v"]
    import json as _j
    v = 0.0
    try:
        p = _j.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "proof.json"), encoding="utf-8"))
        dr = (p.get("sources") or {}).get("drag") or {}
        v = float(dr.get("per_trade") or 0.0) if int(dr.get("trades") or 0) >= DRAG_MIN_N else 0.0
    except Exception:
        v = 0.0
    _DRAG_CACHE["v"] = min(DRAG_MAX, max(0.0, -v))
    return _DRAG_CACHE["v"]


def drag_cost(c, lot):
    d = c.get("drag")
    d = measured_drag() if d in (None, "auto") else min(DRAG_MAX, max(0.0, float(d or 0.0)))
    return d * (float(lot) / DRAG_LOT)


def bars(n=60000):
    u = next(x for x in json.load(open(os.path.join(LIVE, "owl_nest_users.json"), encoding="utf-8")) if x["id"] == "std")
    if not mt5.initialize(path=u["terminal"]):
        raise SystemExit(f"MT5: {mt5.last_error()}")
    sym = "BTCUSD" if mt5.symbol_info("BTCUSD") else "BTCUSDm"
    R = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_M1, 0, n)
    mt5.shutdown()
    return sym, R


def package_cfg(name, over=None):
    """2026-09-29 (owner): test an idea with ONE account's own rules, not a
    generic account. Reads live/owl_packages.json and follows `extends`, so
    the test and the bot cannot drift apart."""
    try:
        P = json.load(open(os.path.join(LIVE, "owl_packages.json"), encoding="utf-8"))
    except Exception:
        return cfg_of(over)
    pk = P.get("packages") or P
    chain, seen, cur = [], set(), name
    while cur and cur in pk and cur not in seen:
        seen.add(cur)
        chain.append(pk[cur])
        cur = pk[cur].get("extends")
    merged = {}
    for layer in reversed(chain):
        merged.update(layer)
    c = dict(CFG_BASE)
    c["jar"] = bool(merged.get("jar", True))
    c["day_cap"] = float(merged.get("day_cap") or 0.0)
    c["kill_net"] = float(merged.get("kill_net") or 0.0)
    c["lot"] = float(merged.get("base_lot") or CFG_BASE["lot"])
    c["bullets"] = float(merged.get("max_extra", CFG_BASE["bullets"]))
    c["scale_ref"] = float(merged.get("scale_ref_balance") or CFG_BASE["scale_ref"])
    if not merged.get("scale_with_balance", True):
        c["balance"] = 0.0          # this package keeps the flat lot
    if merged.get("nervosity") is False:
        c["storm"] = 1.85        # the hard ceiling stays even with no gate
    for k, v in (over or {}).items():
        if k in CFG_BASE:
            c[k] = v
    return c


def cfg_of(over=None):
    c = dict(CFG_BASE)
    for k, v in (over or {}).items():
        if k in CFG_BASE:
            c[k] = v
    return c


def simulate(R, spread, cfg):
    c = cfg_of(cfg)
    rr, LOT = float(c["rr"]), float(c["lot"])
    # the account's own size: same arithmetic as structure_bos_bot.day_roll()
    bal = float(c["balance"] or 0.0)
    ratio = (bal / float(c["scale_ref"])) if (bal > 0 and float(c["scale_ref"]) > 0) else 1.0
    if bal > 0:
        LOT = max(0.01, math.floor((LOT * ratio) / 0.01) * 0.01)
    day_cap_eff = float(c["day_cap"]) * ratio
    if c["cap_rr"] and day_cap_eff:
        rr = float(c["cap_rr"])     # a capped account's own target
    bal_ref = bal if bal > 0 else BAL0
    NB, K = float(c["bullets"]), int(c["k_streak"])
    skip_wd, skip_h = set(c["skip_wd"] or []), set(c["skip_hours"] or [])
    eng = B.Struct()
    # internal structure: its own pin per simulate() call, never a
    # module-level one - the docstring on internal_structure is
    # explicit that two anchors sharing a pin corrupt each other, and
    # run_cfg calls this three times (full, h1, h2).
    i_on = int(c["internal"] or 0)
    i_pin = {"t0": None, "start": None}
    i_kept_n = 0
    i_last_t = None
    i_trend = 0
    i_inv = None
    n_int = 0
    eng.quiet = True
    rng = [float(r["high"]) - float(r["low"]) for r in R]
    # Nervosity for EVERY bar, not just the ones an entry lands on, so an
    # open trade can be judged against the weather. Same definition the bot
    # uses - the 31st of the last 60 ranges over the 721st of the last 1440
    # - taken with np.partition so it is the identical element, not a true
    # median, which for an even window is not the same number.
    _nvs = None
    if c["storm_exit"]:
        import numpy as _np
        _ra = _np.asarray(rng, dtype=float)
        _nvs = [0.0] * len(rng)
        for _i in range(1440, len(rng)):
            _m60 = _np.partition(_ra[_i-60:_i], 30)[30]
            _mrf = _np.partition(_ra[_i-1440:_i], 720)[720]
            _nvs[_i] = _m60 / max(_mrf, 1e-9)
    closes = [float(r["close"]) for r in R]
    flips, marks = [], []
    prev = 0
    used_hi = used_lo = None
    pos = None
    run = pk = 0.0
    streak = 0
    curve = []
    day_key = None
    last_flip_t = None
    last_close_t = None
    last_win_t = None
    cont_left = 0
    n_trades = wins = 0
    blocked = 0
    last_hour = None
    pnls = []
    chest = 0.0
    debt_led = 0.0   # the 'half' ledger; unused under hwm
    day_profit = 0.0
    day_n = 0
    cap_h4 = None
    n_rearm = 0
    dead = False
    cur_tr = None
    n_storm_exit = 0     # trades closed because the weather turned
    n_flip_exit = 0      # trades closed because the trend flipped against them
    n_trail = 0          # trades whose stop was moved at least once
    n_trail_exit = 0     # ... and that were then closed by that stop
    trail_gain = 0.0     # points the moved stop saved, vs the first one
    pos_trailed = False
    pos_rr = rr          # the open trade's own target, rr unless cap_fit shrank it
    prev_hi_v = prev_lo_v = None
    hi_since = lo_since = 0.0        # wall time the level value last changed
    hi_touch = lo_touch = 0
    lp_paused = lp_virt = False
    lp_snap = None
    eq_all = []          # EQHOOK: full-size money of every closed trade
    eq_mult = 1.0        # the lot multiplier the open trade used
    n_virt = 0

    def _lp_close(win):
        # called once per closed trade, right after its booking. A virtual
        # trade's booking is undone from the snapshot taken at its entry
        # (one position at a time, so nothing else moved in between).
        nonlocal run, pk, chest, debt_led, day_profit, streak, wins
        nonlocal lp_paused, lp_virt, lp_snap, n_virt
        if EQHOOK is not None and pnls:
            eq_all.append(pnls[-1] / (eq_mult or 1.0))
        if lp_virt:
            day_profit -= run - lp_snap[0]
            run, pk, chest, debt_led, streak, wins = lp_snap
            if pnls:
                pnls.pop()
            n_virt += 1
        # a callable LOSSPAUSE decides it instead (controls: random pauses)
        if LOSSPAUSE:
            lp_paused = LOSSPAUSE(win) if callable(LOSSPAUSE) else (not win)
        lp_virt = False
    for i, bar in enumerate(R):
        t = int(bar["time"])
        o, h, l, cl = (float(bar["open"]), float(bar["high"]), float(bar["low"]), float(bar["close"]))
        g = datetime.fromtimestamp(t, tz=timezone.utc)
        dk = g.strftime("%Y-%m-%d")
        if dk != day_key:
            day_key = dk
            day_profit = 0.0
            day_n = 0
            cap_h4 = None
            curve.append(run)
        if c["cap_resume_h4"] and day_cap_eff:
            if cap_h4 is None:
                if day_profit >= day_cap_eff:
                    cap_h4 = (t - 60) // 14400
            elif t // 14400 >= cap_h4 + int(c["cap_resume_h4"]):
                day_profit = 0.0
                cap_h4 = None
                n_rearm += 1
        if pos:
            d, e, sl, tp, dist, mid, hit_mid, lot = pos
            # The stop follows the structure. This runs BEFORE
            # eng.step() for this bar, so the level it reads already
            # existed when the bar opened - no lookahead.
            if c["trail_prot"] and eng.trend == d:
                _lv = (eng.prot_lo[1] if (d == 1 and eng.prot_lo)
                       else (eng.prot_hi[1] if (d == -1
                                                and eng.prot_hi)
                             else None))
                if _lv is not None and d * (_lv - sl) > 0 \
                        and d * (_lv - o) < 0 \
                        and (int(c["trail_prot"]) == 1
                             or d * (_lv - e) > 0):
                    sl = _lv
                    pos = (d, e, sl, tp, dist, mid, hit_mid, lot)
                    if not pos_trailed:
                        pos_trailed = True
                        n_trail += 1
            if not hit_mid and ((l <= mid) if d == 1 else (h >= mid)):
                hit_mid = True
                pos = (d, e, sl, tp, dist, mid, hit_mid, lot)
            hit_sl = (l <= sl) if d == 1 else (h >= sl)
            hit_tp = (h >= tp) if d == 1 else (l <= tp)
            # The weather turning bad while the trade is open. Only
            # considered when the stop and the target both survived this
            # bar, so a storm exit never pre-empts a real hit. Note there
            # is no `continue` anywhere below: the structure engine must
            # still step on this bar, and skipping it would corrupt every
            # level from here on.
            storm_px = None
            if (_nvs is not None and not hit_sl and not hit_tp
                    and _nvs[i] >= float(c["storm"])):
                if int(c["storm_exit"]) == 2 or d * (cl - e) - spread >= 0:
                    storm_px = cl
            if storm_px is not None:
                # priced at the close the decision was taken on, with the
                # spread charged: the bot polls once a bar has closed and
                # sends a market order within the second.
                pts = d * (storm_px - e) - spread
                win = pts > 0        # the live bot calls a win by profit
                n_storm_exit += 1
                before = run
                run += pts * lot
                if c["debt_mode"] == "half":
                    _pl = pts * lot
                    if _pl < 0:
                        debt_led = round(debt_led + 0.5 * (-_pl), 2)
                    elif _pl > 0:
                        _pay = min(debt_led, _pl)
                        debt_led = round(debt_led - _pay, 2)
                        chest = round(min(CHEST_CAP,
                                          chest + _pl - _pay), 2)
                run -= drag_cost(c, lot)
                day_profit += run - before
                pnls.append(round(run - before, 2))
                if TRACE is not None and cur_tr is not None:
                    cur_tr["win"] = bool(win)
                    cur_tr["pnl"] = round(run - before, 2)
                    cur_tr["tc"] = t      # 2026-10-08: close time (causal joins)
                    cur_tr["storm_exit"] = True
                    cur_tr = None
                streak = 0 if win else streak + 1
                wins += 1 if win else 0
                pk = max(pk, run)
                if LOSSPAUSE or EQHOOK is not None:
                    _lp_close(win)
                pos = None
                pos_trailed = False
                last_close_t = t
                if win:
                    last_win_t = t
            elif hit_sl or hit_tp:
                win = bool(hit_tp and not hit_sl)
                # priced at the stop as it stands, not at the one the
                # trade was born with. With the trail off the original
                # expression is used verbatim: the two are the same
                # number in algebra but not always in the last bit of
                # a float, and `run` carries that bit into every later
                # trade's rounded money.
                pts = ((pos_rr * dist - spread) if win
                       else ((d * (sl - e) - spread) if c["trail_prot"]
                             else -(dist + spread)))
                debt = (debt_led if c["debt_mode"] == "half"
                        else max(0.0, pk - run))
                before = run
                run += pts * lot
                nb = 0
                if debt > 0.5 and streak < K and hit_mid and NB > 0:
                    if c["jar"]:
                        # the live bot's own arithmetic: stake part of the jar,
                        # never buy more recovery than the debt needs, and take
                        # nothing when the market is not calm. `nv` is the
                        # reading at entry, the closest we have to the midpoint.
                        r001 = dist * BLOT
                        gain001 = pos_rr * r001
                        by_budget = int((chest * JAR_STAKE) // r001) if r001 > 0 else 0
                        by_debt = int(math.ceil(debt / gain001)) if gain001 > 0 else 0
                        nb = 0 if nv > 1.0 else max(0, min(int(NB), by_budget, by_debt))
                    else:
                        nb = int(NB)
                bpts = 0.0
                if nb:
                    # the bullet enters at the midpoint, so it walks (0.5 + rr)
                    # of the distance to the target. This was hardcoded to 1.3,
                    # which silently assumed rr = 0.8 and mispriced every other
                    # target we tested.
                    bpts = (((0.5 + pos_rr) * dist - spread) if win
                            else ((d * (sl - mid) - spread)
                                  if c["trail_prot"]
                                  else -(dist / 2.0 + spread)))
                    run += bpts * BLOT * nb
                if c["jar"]:
                    if nb and bpts < 0:
                        chest = max(0.0, chest + bpts * BLOT * nb)
                    if win:
                        chest += JAR_SKIM * (pts * lot)
                    if run > pk:
                        chest = min(CHEST_CAP, chest + (run - pk))
                    chest = min(chest, max(JAR_FLOOR_CAP, JAR_DEBT_MULT * max(0.0, pk - run)))
                if c["debt_mode"] == "half":
                    _pl = run - before
                    if _pl < 0:
                        debt_led = round(debt_led + 0.5 * (-_pl), 2)
                    elif _pl > 0:
                        _pay = min(debt_led, _pl)
                        debt_led = round(debt_led - _pay, 2)
                        chest = round(min(CHEST_CAP,
                                          chest + _pl - _pay), 2)
                run -= drag_cost(c, lot)
                day_profit += run - before
                pnls.append(round(run - before, 2))      # 2026-09-29: per-trade money, for the "normal range" band
                if TRACE is not None and cur_tr is not None:
                    cur_tr["win"] = bool(win)
                    cur_tr["pnl"] = round(run - before, 2)
                    cur_tr["tc"] = t      # 2026-10-08: close time (causal joins)
                    cur_tr = None
                streak = 0 if win else streak + 1
                wins += 1 if win else 0
                pk = max(pk, run)
                if LOSSPAUSE or EQHOOK is not None:
                    _lp_close(win)
                if pos_trailed and not win:
                    n_trail_exit += 1
                    # what the move was worth on this trade: the old
                    # stop would have paid -(dist), this one paid
                    # d*(sl-e). Positive means the trail helped.
                    trail_gain += (d * (sl - e)) + dist
                pos = None
                pos_trailed = False
                last_close_t = t
                if win:
                    last_win_t = t
        touched = False
        if eng.trend == 1 and eng.prot_lo is not None:
            touched = l <= eng.prot_lo[1] <= cl
        elif eng.trend == -1 and eng.prot_hi is not None:
            touched = cl <= eng.prot_hi[1] <= h
        if TRACE is not None:
            # The level as it stands BEFORE this bar is judged: step() moves it
            # on the very bar that breaks it, so reading it after would always
            # give an age of zero. The engine's own hi_i/lo_i are NOT usable
            # here: it counts Renko bricks, not minutes, so subtracting them
            # from a minute index mixes two clocks. Age is taken from the wall
            # time at which the level value last changed.
            p_hi_v, p_lo_v = eng.hi_v, eng.lo_v
            if i >= 60:
                _med = sorted(rng[i-60:i])[30]
                if p_hi_v != prev_hi_v:
                    prev_hi_v, hi_touch, hi_since = p_hi_v, 0, t
                elif p_hi_v is not None and p_hi_v - 0.10 * _med <= h < p_hi_v:
                    hi_touch += 1
                if p_lo_v != prev_lo_v:
                    prev_lo_v, lo_touch, lo_since = p_lo_v, 0, t
                elif p_lo_v is not None and p_lo_v < l <= p_lo_v + 0.10 * _med:
                    lo_touch += 1
        sig = eng.step(t, o, h, l, cl)
        if eng.trend != prev and eng.trend != 0:
            flips.append(t)
            prev = eng.trend
        if sig is not None:
            marks.append(t)
        # ---- internal structure ----------------------------------
        # Recomputed only when a candle actually survived the silence
        # filter, which is the only moment it can change. The main
        # engine's levels are read off the incremental Struct exactly
        # the way the feed's batch engine derives them (see its return
        # block: nxt = hi_v/lo_v, inv = prot_lo/prot_hi).
        i_fire = False
        if i_on and len(eng.kept) != i_kept_n:
            i_kept_n = len(eng.kept)
            _up = eng.trend == 1
            _nx = eng.hi_v if _up else (eng.lo_v if eng.trend == -1 else None)
            _pv = eng.prot_lo if _up else eng.prot_hi
            _iv = _pv[1] if (eng.trend and _pv) else None
            _ivt = _pv[0] if (eng.trend and _pv) else None
            _ai = eng.hi_i if _up else eng.lo_i
            _nxt_t = (eng.kept[_ai][0]
                      if (_nx is not None and 0 <= _ai < len(eng.kept))
                      else None)
            _fd = eng.choch if (eng.choch and eng.choch != eng.trend) else 0
            _flp = eng.hi_v if _fd == 1 else (eng.lo_v if _fd == -1 else None)
            # internal_structure only ever reads marks[-1][0]
            _mk = [[marks[-1]]] if marks else []
            try:
                _r = _feed().internal_structure(
                    eng.kept, _nx, _iv, _ivt, _flp, _mk, _nxt_t, t,
                    pin=i_pin, brk_t=(marks[-1] if marks else None))
                i_trend = int(_r["i_trend"] or 0)
                _new_inv, _new_t = _r["i_inv"], _r["i_inv_t"]
            except Exception:
                i_trend, _new_inv, _new_t = 0, None, None
            # the live trigger: the internal protected level MOVED
            if _new_inv and _new_t and _new_t != i_last_t:
                i_last_t = _new_t
                i_inv = float(_new_inv)
                if i_trend and (i_on == 2 or i_trend == eng.trend):
                    i_fire = True
        if i_fire and sig is None and not pos and not dead:
            # the wide-stop guards. cl is this bar's close, so the
            # internal stop distance is what the trade would really risk.
            _idist = abs(cl - i_inv)
            _med60 = sorted(rng[i-60:i])[30] if i >= 60 else 0.0
            if c["int_max_stop"] and _med60 > 0 and \
                    _idist > float(c["int_max_stop"]) * _med60:
                i_fire = False
                blocked += 1
            elif c["int_tighter"]:
                _mdist = None
                if eng.trend == 1 and eng.prot_lo:
                    _mdist = abs(cl - eng.prot_lo[1])
                elif eng.trend == -1 and eng.prot_hi:
                    _mdist = abs(cl - eng.prot_hi[1])
                if _mdist and _idist > _mdist:
                    i_fire = False
                    blocked += 1
        if i_fire and sig is None and not pos and not dead:
            sig = (i_trend, i_inv)
        if touched and last_flip_t is not None and cont_left < c["n_cont"]:
            cont_left = min(int(c["n_cont"]), cont_left + 1)
        # ---- the trend flips against an open trade ----------------------
        # Runs AFTER eng.step for this bar, so the engine has already seen
        # the candle and no `continue` below can starve it.
        if pos is not None and sig is not None and c["flip_exit"]:
            _d0, _e0, _sl0, _tp0, _dist0, _mid0, _hm0, _lot0 = pos
            if sig[0] == -_d0 and flips and flips[-1] == t:
                # The accounting is deliberately its own block rather than
                # shared with the storm branch above: that branch's numbers
                # are already published (E028) and refactoring it would put
                # them at risk. If either is ever changed, change both.
                _pts = _d0 * (cl - _e0) - spread
                _win = _pts > 0        # the live bot calls a win by profit
                n_flip_exit += 1
                _before = run
                run += _pts * _lot0
                if c["debt_mode"] == "half":
                    _pl = _pts * _lot0
                    if _pl < 0:
                        debt_led = round(debt_led + 0.5 * (-_pl), 2)
                    elif _pl > 0:
                        _pay = min(debt_led, _pl)
                        debt_led = round(debt_led - _pay, 2)
                        chest = round(min(CHEST_CAP,
                                          chest + _pl - _pay), 2)
                run -= drag_cost(c, _lot0)
                day_profit += run - _before
                pnls.append(round(run - _before, 2))
                if TRACE is not None and cur_tr is not None:
                    cur_tr["win"] = bool(_win)
                    cur_tr["pnl"] = round(run - _before, 2)
                    cur_tr["tc"] = t      # 2026-10-08: close time (causal joins)
                    cur_tr["flip_exit"] = True
                    cur_tr = None
                streak = 0 if _win else streak + 1
                wins += 1 if _win else 0
                pk = max(pk, run)
                if LOSSPAUSE or EQHOOK is not None:
                    _lp_close(_win)
                pos = None
                pos_trailed = False
                last_close_t = t
                if _win:
                    last_win_t = t
                if int(c["flip_exit"]) == 1:
                    continue       # stand aside, do not take the reversal
                # flip_exit 2 falls through: the reversal is now considered
                # like any other entry, every later gate still applying
        if sig is None or pos:
            continue
        if dead:
            continue
        if c["kill_net"] and run <= float(c["kill_net"]):
            dead = True          # the live bot closes, stops and says KILL
            continue
        if not i_fire and not any(f > t - B.AWAKE_WIN for f in flips):
            continue
        d, slp = sig
        flip = bool(flips) and flips[-1] == t
        if i_fire:
            n_int += 1
        if not flip and not i_fire:
            lvl = eng.hi_v if d == 1 else eng.lo_v
            if (d == 1 and used_hi == lvl) or (d == -1 and used_lo == lvl):
                continue
            if d == 1:
                used_hi = lvl
            else:
                used_lo = lvl
        nv = 1.0
        if i >= 1440:
            nv = (sorted(rng[i-60:i])[30] / max(sorted(rng[i-1440:i])[720], 1e-9))
            mv2 = (bisect.bisect_left(marks, t) - bisect.bisect_left(marks, t - 7200))
            if nv >= float(c["storm"]) or (c["movement"] and mv2 < 1):
                continue
            if c["nerv_gate"] and nv > 1.0:
                blocked += 1
                continue
            if c["nerv_floor"] and nv < float(c["nerv_floor"]):
                blocked += 1
                continue
            _dbt = (debt_led if c["debt_mode"] == "half"
                    else max(0.0, pk - run))
            if c["debt_nerv_gate"] and nv > 1.0 and _dbt > 0.5:
                blocked += 1
                continue
        # ---- the what-if brakes ----
        if c["wait_min"] and last_close_t is not None and t - last_close_t < c["wait_min"] * 60:
            blocked += 1
            continue
        if c["wait_win"] and last_win_t is not None and t - last_win_t < c["wait_win"] * 60:
            blocked += 1
            continue
        if c["ext_pts"] and i >= 61 and abs(closes[i-1] - closes[i-61]) > c["ext_pts"]:
            blocked += 1
            continue
        if c["chase_pts"] and i >= 61 and d * (closes[i-1] - closes[i-61]) > float(c["chase_pts"]):
            blocked += 1
            continue
        if skip_wd and g.weekday() in skip_wd:
            blocked += 1
            continue
        if skip_h and g.hour in skip_h:
            blocked += 1
            continue
        if DIRGATE is not None and not DIRGATE(t, d):
            blocked += 1
            continue
        debt_now = (debt_led if c["debt_mode"] == "half"
                    else max(0.0, pk - run))
        if flip:
            last_flip_t = t
            cont_left = int(c["n_cont"])
        elif debt_now > 0.5:
            if cont_left > 0 and last_flip_t is not None:
                cont_left -= 1
            else:
                continue
        # the daily profit stop, waived while still in the red like the live bot
        if c["max_trades_day"] and day_n >= int(c["max_trades_day"]):
            blocked += 1
            continue
        if day_cap_eff and day_profit >= day_cap_eff and debt_now <= 0.5:
            blocked += 1
            continue
        if c["only_kind"] == "flip" and not flip:
            blocked += 1
            continue
        if c["only_kind"] == "cont" and flip:
            blocked += 1
            continue
        if c["minute_win"] and not (int(c["minute_win"][0]) <= g.minute <= int(c["minute_win"][1])):
            blocked += 1
            continue
        if c["one_per_hour"] and last_hour == t // 3600:
            blocked += 1
            continue
        dist = abs(cl - slp)
        # 2026-09-29 (owner): the spread is fixed at 7 pts on this broker, but
        # that is 1.2 % of a wide trade and 8.7 % of a tight one - and a market
        # too small to move cannot pay for it at all
        if c["min_range"] and i >= 60 and sorted(rng[i-60:i])[30] < float(c["min_range"]):
            blocked += 1
            continue
        if c["cost_max"] and dist > 0 and (spread / dist) * 100.0 > float(c["cost_max"]):
            blocked += 1
            continue
        lot = LOT * (float(c["size_hot"]) if nv >= 1.0 else 1.0)
        if flip and nv >= 1.0:
            lot *= float(c["flip_hot_size"])
        if not i_fire and i >= 1440 and mv2 == 1:
            lot *= float(c["first_move_size"])
        eq_v = False
        eq_mult = 1.0
        if EQHOOK is not None:
            _m, eq_v = EQHOOK(eq_all)
            if _m != 1.0:
                _l2 = max(0.01, math.floor(lot * _m / 0.01 + 1e-9) * 0.01)
                eq_mult = _l2 / lot if lot else 1.0
                lot = _l2
        if dist <= B.S_MIN_DIST or dist * LOT > B.MAX_RISK_PCT * 230.0:
            continue
        _risk = dist * lot
        if c["risk_max"] and _risk > float(c["risk_max"]):
            blocked += 1
            continue
        # NOTE: against the balance the account STARTED with, not the running
        # one. This strategy trades a fixed lot, so the risk per trade does
        # not grow with profit; a cap that did grow would simply stop binding
        # once the account was ahead - which is exactly when the deep holes
        # happen. Tested both ways on 2026-09-29, see lab/CHERCHEUR.md.
        if c["risk_pct"] and _risk > bal_ref * float(c["risk_pct"]) / 100.0:
            blocked += 1
            continue
        if c["bank_mult"] and _risk > (BANK0 + max(0.0, run)) / float(c["bank_mult"]):
            blocked += 1
            continue
        # cap the money by shrinking the lot, keeping the trade
        _fit = 0.0
        if c["risk_fit"]:
            _fit = bal_ref * float(c["risk_fit"]) / 100.0
        if c["risk_fit_abs"]:
            _a = float(c["risk_fit_abs"])
            _fit = _a if not _fit else min(_fit, _a)
        if _fit and _risk > _fit:
            lot = math.floor((_fit / dist) / 0.01) * 0.01
            if lot < 0.01:
                blocked += 1
                continue
            _risk = dist * lot
        # aim only for what is left of the day's cap, never past rr
        pos_rr = rr
        if c["cap_fit"] and day_cap_eff and debt_now <= 0.5:
            _need = day_cap_eff - day_profit
            if _need > 0:
                pos_rr = min(rr, (_need / lot + spread) / dist)
        tp = cl + d * pos_rr * dist
        lp_virt = bool(LOSSPAUSE and lp_paused) or bool(eq_v)
        if lp_virt:
            lp_snap = (run, pk, chest, debt_led, streak, wins)
        pos = (d, cl, float(slp), tp, dist, cl - d * dist / 2.0, False, lot)
        pos_trailed = False
        last_hour = t // 3600
        n_trades += 1
        day_n += 1
        if TRACE is not None:
            _m = sorted(rng[i-60:i])[30] if i >= 60 else 0.0
            # 2026-10-01: lot and risk recorded so a study can tell whether a
            # money cap BOUND on this trade without reconstructing the lot
            # from the balance and the nervosity. A reconstruction that
            # drifts from this line would quietly mismeasure the cap.
            cur_tr = {"t": t, "d": d, "flip": bool(flip), "dist": round(dist, 1),
                      "lot": round(lot, 2), "risk": round(dist * lot, 2),
                      "med": round(_m, 1), "nerv": round(nv, 2),
                      "power": (round(rng[i] / _m, 2) if _m > 0 else None),
                      "age": int((t - (hi_since if d == 1 else lo_since)) // 60),
                      "touch": (hi_touch if d == 1 else lo_touch),
                      "win": None, "pnl": None, "virt": lp_virt}
            TRACE.append(cur_tr)
    dd = pk2 = worst = 0.0
    for v in curve:
        pk2 = max(pk2, v)
        dd = min(dd, v - pk2)
        worst = max(worst, pk2 - v)
    # 2026-09-29 (proof page): the daily curve with its dates - `curve[i]`
    # is the running net at the START of day i, so pair it with day keys
    days = []
    if len(R):
        seen = set()
        for r in R:
            k = datetime.fromtimestamp(int(r["time"]), tz=timezone.utc).strftime("%Y-%m-%d")
            if k not in seen:
                seen.add(k)
                days.append(k)
    dated = [[days[i], round(v, 2)] for i, v in enumerate(curve) if i < len(days)]
    if days:
        dated.append([days[-1], round(run, 2)])
    return {"net": round(run, 2), "maxdd": round(dd, 2), "worst_debt": round(worst, 2), "trades": n_trades,
            "wr": round(wins / n_trades * 100, 1) if n_trades else 0.0, "blocked": blocked, "rearm": n_rearm, "internal": n_int, "curve": dated, "pnls": pnls,
            "trailed": n_trail, "trail_exits": n_trail_exit,
            "trail_gain_pts": round(trail_gain, 1),
            "storm_exits": n_storm_exit, "flip_exits": n_flip_exit,
            "virtual": n_virt, "eq_all": len(eq_all)}


def run_cfg(R, spread, cfg):
    mid = len(R) // 2
    return {"full": simulate(R, spread, cfg), "h1": simulate(R[:mid], spread, cfg), "h2": simulate(R[mid:], spread, cfg)}


def verdict(v, base):
    f, b = v["full"], base["full"]
    dn = f["net"] - b["net"]
    if abs(f["trades"] - b["trades"]) < 3 and abs(dn) < 1.0 and abs(f["worst_debt"] - b["worst_debt"]) < 1.0:
        return "="
    d1 = v["h1"]["net"] - base["h1"]["net"]
    d2 = v["h2"]["net"] - base["h2"]["net"]
    w = f["worst_debt"] - b["worst_debt"]
    w1 = v["h1"]["worst_debt"] - base["h1"]["worst_debt"]
    w2 = v["h2"]["worst_debt"] - base["h2"]["worst_debt"]
    # 2026-09-29: an A must also make more money over the FULL period - the
    # halves are simulated on their own (each starts with no debt), so both
    # can be up while the full run, path-dependent, is down (rr10 tonight:
    # halves +, full -8.53 -> it was called A and a twin started)
    if d1 > 0 and d2 > 0 and dn > 0 and w <= 0.5:
        return "A"
    if (dn >= -0.05 * abs(b["net"]) and w1 < 0 and w2 < 0) or (dn > 0 and (d1 > 0 or d2 > 0) and w <= 0.5):
        return "B"
    return "C"


# ---- 2026-09-29 (owner): two more views on every idea -------------------
# 1) the LONG window: the most M1 history the terminal gives. Its "Max bars
#    in chart" setting caps it (100000 today = ~69 days); raise the setting
#    and this grows by itself. A weaker result here is a caution, never a
#    reason to drop an idea (owner rule 2026-09-29).
# 2) the REAL trades: the entries the bot really took (bos_journal*.csv,
#    deduplicated across accounts), replayed with the idea's rules on the
#    real M1 path after each entry - the same money and exit code as above.
def bars_long():
    u = next(x for x in json.load(open(os.path.join(LIVE, "owl_nest_users.json"), encoding="utf-8")) if x["id"] == "std")
    if not mt5.initialize(path=u["terminal"]):
        return None, None
    sym = "BTCUSD" if mt5.symbol_info("BTCUSD") else "BTCUSDm"
    R = None
    for n in (499000, 299000, 199000, 149000, 99000, 90000, 80000, 70000):
        try:
            R = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_M1, 0, n)
        except Exception:
            R = None
        if R is not None and len(R) >= n:
            break
        R = None
    mt5.shutdown()
    return sym, R


# the accounts whose journals count as "the real trades": never touched by
# hand (owner 2026-09-29). Names never leave the server.
REAL_SOURCES = ["bos_journal_valere.csv", "bos_journal_infinity.csv"]   # the demo runs on another broker feed: shown apart


def real_entries(files=None):
    import csv
    uniq = {}
    for f in [os.path.join(LIVE, x) for x in (files or REAL_SOURCES)]:
        try:
            with open(f, encoding="utf-8", errors="replace") as fh:
                for r in csv.DictReader(fh):
                    if r.get("is_add") == "True" or not r.get("exit_time_utc") or not r.get("entry_price"):
                        continue
                    key = (r["entry_time_utc"][:16], r["direction"])
                    if key in uniq:
                        continue
                    t = datetime.fromisoformat(r["entry_time_utc"].replace("Z", "+00:00")).timestamp()
                    e, sl = float(r["entry_price"]), float(r["sl"])
                    dist = float(r.get("dist_pts") or abs(e - sl))
                    uniq[key] = {"t": int(t), "d": 1 if r["direction"] == "BUY" else -1, "e": e, "sl": sl, "dist": dist,
                                 "nerv": float(r.get("nervosity") or 1.0), "flip": r.get("kind") == "FLIP-BOS",
                                 "kind": r.get("kind"), "pnl": float(r.get("profit_usd") or 0),
                                 "internal": (r.get("internal") == "True"),
                                 "move": float(r.get("movement_count") or 0)}
        except Exception:
            continue
    return sorted(uniq.values(), key=lambda x: x["t"])


def simulate_real(T, R, spread, cfg):
    """The idea's rules on the bot's REAL entries: filters decide which of
    them it would have taken, the target and the money rules decide what
    they would have paid, walking the real M1 path after each entry."""
    c = cfg_of(cfg)
    rr, LOT = float(c["rr"]), float(c["lot"])
    # the account's own size: same arithmetic as structure_bos_bot.day_roll()
    bal = float(c["balance"] or 0.0)
    ratio = (bal / float(c["scale_ref"])) if (bal > 0 and float(c["scale_ref"]) > 0) else 1.0
    if bal > 0:
        LOT = max(0.01, math.floor((LOT * ratio) / 0.01) * 0.01)
    day_cap_eff = float(c["day_cap"]) * ratio
    if c["cap_rr"] and day_cap_eff:
        rr = float(c["cap_rr"])     # a capped account's own target
    bal_ref = bal if bal > 0 else BAL0
    NB, K = float(c["bullets"]), int(c["k_streak"])
    skip_wd, skip_h = set(c["skip_wd"] or []), set(c["skip_hours"] or [])
    times =[int(r["time"]) for r in R]
    closes = [float(r["close"]) for r in R]
    # This path replays the bot's REAL entries and runs no structure
    # engine of its own, so the trail needs the protected level as it
    # stood BEFORE each bar. Built once, read by index.
    _prot = None
    if c["trail_prot"]:
        _pe = B.Struct()
        _pe.quiet = True
        _prot = []
        for _r in R:
            _prot.append((_pe.trend,
                          _pe.prot_lo[1] if _pe.prot_lo else None,
                          _pe.prot_hi[1] if _pe.prot_hi else None))
            _pe.step(int(_r["time"]), float(_r["open"]),
                     float(_r["high"]), float(_r["low"]),
                     float(_r["close"]))
    run = pk = worst = 0.0
    streak = 0
    last_close_t = last_flip_t = None
    last_win_t = None
    cont_left = 0
    n_trades = wins = blocked = 0
    actual_taken = 0.0        # the real money of exactly the entries taken: like-for-like with `net`
    open_until = -1
    for e in T:
        t = e["t"]
        if not times or t < times[0]:
            continue
        i = bisect.bisect_left(times, t)
        if i >= len(times) or i < open_until:
            continue
        g = datetime.fromtimestamp(t, tz=timezone.utc)
        nv = e["nerv"]
        if e.get("internal") and not int(c.get("internal") or 0):
            blocked += 1          # a kind of trade this replay does not model
            continue
        if nv >= float(c["storm"]):
            continue
        if c["nerv_gate"] and nv > 1.0:
            blocked += 1
            continue
        if c["nerv_floor"] and nv < float(c["nerv_floor"]):
            blocked += 1
            continue
        if c["debt_nerv_gate"] and nv > 1.0 and max(0.0, pk - run) > 0.5:
            blocked += 1
            continue
        if c["wait_min"] and last_close_t is not None and t - last_close_t < c["wait_min"] * 60:
            blocked += 1
            continue
        if c["wait_win"] and last_win_t is not None and t - last_win_t < c["wait_win"] * 60:
            blocked += 1
            continue
        if c["ext_pts"] and i >= 61 and abs(closes[i-1] - closes[i-61]) > c["ext_pts"]:
            blocked += 1
            continue
        if c["chase_pts"] and i >= 61 and e["d"] * (closes[i-1] - closes[i-61]) > float(c["chase_pts"]):
            blocked += 1
            continue
        if skip_wd and g.weekday() in skip_wd:
            blocked += 1
            continue
        if skip_h and g.hour in skip_h:
            blocked += 1
            continue
        debt_now = max(0.0, pk - run)
        if e["flip"]:
            last_flip_t = t
            cont_left = int(c["n_cont"])
        elif debt_now > 0.5:
            if cont_left > 0 and last_flip_t is not None:
                cont_left -= 1
            else:
                blocked += 1
                continue
        d, ent, sl, dist = e["d"], e["e"], e["sl"], e["dist"]
        if c["cost_max"] and dist > 0 and (spread / dist) * 100.0 > float(c["cost_max"]):
            blocked += 1
            continue
        lot = LOT * (float(c["size_hot"]) if nv >= 1.0 else 1.0)
        if e["flip"] and nv >= 1.0:
            lot *= float(c["flip_hot_size"])
        if not e.get("internal") and e.get("move") == 1:
            lot *= float(c["first_move_size"])
        tp =ent + d * rr * dist
        mid = ent - d * dist / 2.0
        hit_mid = False
        win = None
        j = i
        while j < len(R):
            h, l = float(R[j]["high"]), float(R[j]["low"])
            if _prot is not None:
                _tr, _plo, _phi = _prot[j]
                if _tr == d:
                    _lv = _plo if d == 1 else _phi
                    if _lv is not None and d * (_lv - sl) > 0 \
                            and d * (_lv - float(R[j]["open"])) < 0 \
                            and (int(c["trail_prot"]) == 1
                                 or d * (_lv - ent) > 0):
                        sl = _lv
            if not hit_mid and ((l <= mid) if d == 1 else (h >= mid)):
                hit_mid = True
            hit_sl = (l <= sl) if d == 1 else (h >= sl)
            hit_tp = (h >= tp) if d == 1 else (l <= tp)
            if hit_sl or hit_tp:
                win = bool(hit_tp and not hit_sl)
                break
            j += 1
        if win is None:
            continue
        open_until = j
        pts = ((rr * dist - spread) if win
               else ((d * (sl - ent) - spread) if c["trail_prot"]
                     else -(dist + spread)))
        debt = max(0.0, pk - run)
        run += pts * lot
        run -= drag_cost(c, lot)
        if debt > 0.5 and streak < K and hit_mid and NB > 0:
            run += ((1.3 * dist - spread) if win
                    else ((d * (sl - mid) - spread) if c["trail_prot"]
                          else -(dist / 2.0 + spread))) * BLOT * NB
        streak = 0 if win else streak + 1
        wins += 1 if win else 0
        pk = max(pk, run)
        worst = max(worst, pk - run)
        last_close_t = times[j]
        if win:
            last_win_t = times[j]
        n_trades += 1
        actual_taken += float(e.get("pnl") or 0.0)
    return {"debt_mode_modelled": "hwm",  # this path has no chest, so it cannot run "half"
            "net": round(run, 2), "worst_debt": round(worst, 2), "trades": n_trades,
            "wr": round(wins / n_trades * 100, 1) if n_trades else 0.0, "blocked": blocked, "n_real": len(T),
            "actual": round(actual_taken, 2), "actual_all": round(sum(x["pnl"] for x in T), 2)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rr", type=float)
    ap.add_argument("--trail-prot", type=int,
                    help="move the stop to each new protected level:"
                         " 1 = always, 2 = only past the entry")
    ap.add_argument("--n-cont", type=int)
    ap.add_argument("--wait", type=int, help="minutes after a close")
    ap.add_argument("--wait-win", type=int, help="minutes after a winning close only")
    ap.add_argument("--cap-resume-h4", type=int, help="after the daily cap is hit, resume at the Nth next H4 candle (target counted again); needs a cap; 0 = next UTC day")
    ap.add_argument("--ext", type=float, help="no entry after this many points in the last hour")
    ap.add_argument("--chase", type=float, help="no entry after this many points in the last hour the trade's way")
    ap.add_argument("--skip-wd", type=str, help="weekdays to skip, 0=Mon..6=Sun, comma list")
    ap.add_argument("--skip-hours", type=str, help="UTC hours to skip, e.g. 0-8 or 0,1,2")
    ap.add_argument("--size-hot", type=float, help="lot multiplier when nervosity >= 1.0")
    ap.add_argument("--flip-hot-size", type=float, help="lot multiplier on a change-of-direction trade when nervosity >= 1.0")
    ap.add_argument("--first-move-size", type=float, help="lot multiplier when the entry is the first big move counted in the last 2 hours")
    ap.add_argument("--nerv-gate", action="store_true")
    ap.add_argument("--nerv-floor", type=float, help="no entry when the market's pace at entry is under X (1.0 = usual)")
    ap.add_argument("--debt-nerv-gate", action="store_true", help="refuse only when still in the red AND nervous")
    ap.add_argument("--bullets", type=float)
    ap.add_argument("--k-streak", type=int)
    ap.add_argument("--cost-max", type=float, help="refuse an entry whose spread is over X %% of the stop distance")
    ap.add_argument("--min-range", type=float, help="refuse an entry when the median 60-min candle range is under X points")
    ap.add_argument("--cap-fit", type=float,
                    help="aim each target only for what is left of a daily cap of $X"
                         " (this replay has no cap of its own); 0 = off")
    ap.add_argument("--cap-rr", type=float,
                    help="on an account with a daily cap, aim for X times the risk instead of rr;"
                         " base and variant both get valere's daily cap (this replay has none); 0 = off")
    ap.add_argument("--spread", type=float, default=7.0)
    ap.add_argument("--drag", type=str, help="per-trade cost in $ at 0.02 lot: a number, or 'auto' = last night's measured gap once it rests on 30 trades; default raw")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(_ARGV)
    over = {}
    if a.rr is not None: over["rr"] = a.rr
    if a.n_cont is not None: over["n_cont"] = a.n_cont
    if a.wait is not None: over["wait_min"] = a.wait
    if a.wait_win is not None: over["wait_win"] = a.wait_win
    if a.cap_resume_h4 is not None: over["cap_resume_h4"] = a.cap_resume_h4
    if a.drag is not None: over["drag"] = None if str(a.drag).strip().lower() == "auto" else float(a.drag)
    if a.ext is not None: over["ext_pts"] = a.ext
    if a.chase is not None: over["chase_pts"] = a.chase
    if a.skip_wd: over["skip_wd"] = [int(x) for x in a.skip_wd.split(",") if x.strip()]
    if a.skip_hours:
        hs = set()
        for part in a.skip_hours.split(","):
            if "-" in part:
                lo, hi = part.split("-"); hs.update(range(int(lo), int(hi)))
            elif part.strip():
                hs.add(int(part))
        over["skip_hours"] = sorted(hs)
    if a.size_hot is not None: over["size_hot"] = a.size_hot
    if a.flip_hot_size is not None: over["flip_hot_size"] = a.flip_hot_size
    if a.first_move_size is not None: over["first_move_size"] = a.first_move_size
    if a.nerv_gate: over["nerv_gate"] = True
    if a.nerv_floor is not None: over["nerv_floor"] = a.nerv_floor
    if a.debt_nerv_gate: over["debt_nerv_gate"] = True
    if a.bullets is not None: over["bullets"] = a.bullets
    if a.k_streak is not None: over["k_streak"] = a.k_streak
    if a.cost_max is not None: over["cost_max"] = a.cost_max
    if a.min_range is not None: over["min_range"] = a.min_range
    if a.cap_fit:
        over["cap_fit"] = 1
        over["day_cap"] = a.cap_fit
    base_over = {}
    if a.cap_rr:
        over["cap_rr"] = a.cap_rr
        if not over.get("day_cap"):
            over["day_cap"] = base_over["day_cap"] = package_cfg("valere")["day_cap"]
    sym, R = bars()
    base = run_cfg(R, a.spread, base_over)
    v = run_cfg(R, a.spread, over)
    out = {"symbol": sym, "days": round(len(R) / 1440, 1), "spread": a.spread, "cfg": cfg_of(over),
           "base": base, "variant": v, "verdict": verdict(v, base)}
    if a.json:
        print(json.dumps(out))
    else:
        print(f"{sym} {out['days']} days, spread {a.spread:.0f}  cfg {json.dumps(over)}")
        for k in ("full", "h1", "h2"):
            b, x = base[k], v[k]
            print(f"  {k:4s} base {b['trades']:4d} tr {b['wr']:5.1f}% net {b['net']:8.2f} worst {b['worst_debt']:6.2f} | "
                  f"variant {x['trades']:4d} tr {x['wr']:5.1f}% net {x['net']:8.2f} worst {x['worst_debt']:6.2f}  ({x['net']-b['net']:+.2f} net, {x['worst_debt']-b['worst_debt']:+.2f} worst)")
        print(f"  verdict {out['verdict']}")


if __name__ == "__main__":
    main()
