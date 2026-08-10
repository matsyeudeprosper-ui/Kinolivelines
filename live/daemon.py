"""The 24/7 loop. Detects events, wakes the model, executes its decisions.

  python daemon.py                 dry run (DEFAULT) - decides but sends no orders
  python daemon.py --live          actually places orders
  python daemon.py --no-llm        plumbing only, never calls the model

This is the standalone replacement for the Claude-Code-session watcher: it needs
no session, no Desktop, no cron. Detection logic is the same, but instead of
printing an event for a human to read, it builds a briefing and calls the model.

Read-only against MT5 except through brain.execute() -> act.py, which re-verifies
account, side, lot cap and stop placement on every order.
"""
import MetaTrader5 as mt5
import json, os, time, sys, subprocess, traceback
from datetime import datetime, timedelta

# Windows stdout is cp1252 by default and the model's text is full of Unicode.
# See say() below - this is the root fix, the guard there is the backstop.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import brain

TERMINAL = r"C:\Program Files\MetaTrader 5\terminal64.exe"
LOGIN    = 436771046
SYM      = "BTCUSDm"
POLL     = 30
MIN_GAP  = 180
# Longest the decider may go unconsulted while price is actually moving. Only
# fires when price has ALSO travelled more than one ATR(M15) since the last
# wake, so a quiet market costs nothing.
STALE_GAP = 2700     # 45 minutes
HERE     = os.path.dirname(os.path.abspath(__file__))
CONFIG   = os.path.join(HERE, "watch_config.json")
ALIVE    = os.path.join(HERE, "daemon_alive.json")
LOG      = os.path.join(HERE, "daemon.log")

DRY_RUN = "--live"   not in sys.argv
USE_LLM = "--no-llm" not in sys.argv


def say(msg):
    line = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}"
    # Same cp1252 hazard the watcher hit on 2026-07-31: the model's own text is
    # echoed here, it contains Unicode, and an unencodable glyph raised out of
    # print() BEFORE the file write - losing the log line entirely. Guard the
    # print so the durable record always survives.
    try:
        print(line, flush=True)
    except Exception:
        try:
            print(line.encode("ascii", "replace").decode("ascii"), flush=True)
        except Exception:
            pass
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass          # logging must never kill the loop


def load_config():
    try:
        return json.load(open(CONFIG))
    except Exception:
        return {"watch_levels": [], "be_trigger_r": 1.0, "setup_proximity_atr": 0.06}


def connect():
    """Pin the terminal AND verify the login. With two MT5 instances running, a
    bare initialize() attaches to whichever it likes - on 2026-07-30 that
    silently returned a different account than the one holding the position."""
    while True:
        if mt5.initialize(path=TERMINAL):
            acc = mt5.account_info()
            if acc and acc.login == LOGIN:
                if acc.trade_mode != 0 and not DRY_RUN:
                    say(f"REFUSING TO RUN LIVE: account {acc.login} is not a demo "
                        f"(trade_mode={acc.trade_mode}). Restart with --dry-run.")
                    sys.exit(1)
                mt5.symbol_select(SYM, True)
                return
            say(f"wrong account {acc.login if acc else None}, want {LOGIN} - waiting")
            mt5.shutdown()
        time.sleep(15)


def briefing():
    r = subprocess.run([sys.executable, os.path.join(HERE, "briefing.py")],
                       capture_output=True, text=True, timeout=180)
    return (r.stdout or r.stderr).strip()


def wake(trigger):
    """An event needs a decision. Build state, call the model, act on the result."""
    say(f"EVENT  {trigger}")
    if not USE_LLM:
        say("       (--no-llm: plumbing only, no decision made)")
        return
    try:
        summary, acted = brain.decide(briefing(), trigger, dry_run=DRY_RUN)
        for ln in summary.splitlines():
            if ln.strip():
                say(f"       {ln.strip()}")
        if acted:
            say("       -> state changed")
    except Exception as e:
        say(f"       DECISION FAILED: {type(e).__name__}: {e}")
        say(traceback.format_exc()[-800:])


def order_filled_and_closed(ticket, lookback_hours=6):
    """Did pending `ticket` fill and then close, both before we noticed?

    Returns a dict of what actually happened, or None if it never filled.

    Deals are the ground truth here, not positions: a position that has already
    closed is gone from positions_get(), which is precisely why the caller's
    open-position check misses this case. The fill deal carries `order == ticket`
    and the position id it opened; the closing deal shares that position id and
    carries the realised profit.

    Trap (RESTORE.md #3): deal times are broker epoch seconds - subtract two of
    them for a duration, never mix one with a local datetime.
    """
    try:
        frm = datetime.now() - timedelta(hours=lookback_hours)
        deals = mt5.history_deals_get(frm, datetime.now() + timedelta(hours=6)) or []
    except Exception:
        return None
    fill = next((d for d in deals if d.order == ticket and d.entry == mt5.DEAL_ENTRY_IN), None)
    if fill is None:
        return None
    close = next((d for d in deals
                  if d.position_id == fill.position_id and d.entry == mt5.DEAL_ENTRY_OUT), None)
    if close is None:
        return None                     # filled but still open - caller handles that
    how = (close.comment or "").strip() or "closed"
    if "sl" in how.lower():
        how = "stopped out"
    elif "tp" in how.lower():
        how = "hit target"
    return {"entry": fill.price, "exit": close.price, "profit": close.profit,
            "secs": close.time - fill.time, "how": how}


def atr_h1():
    r = mt5.copy_rates_from_pos(SYM, mt5.TIMEFRAME_H1, 0, 30)
    if r is None or len(r) < 16:
        return None
    tr, pc = [], None
    for b in r:
        if pc is not None:
            tr.append(max(b["high"] - b["low"], abs(b["high"] - pc), abs(b["low"] - pc)))
        pc = b["close"]
    return sum(tr[-14:]) / 14 if len(tr) >= 14 else None


def levels():
    """KinoliveLines set: prev closed H4/H1/M15 high+low, ATR-merged."""
    out, a, t = [], atr_h1(), mt5.symbol_info_tick(SYM)
    if a is None or t is None:
        return out
    spread, raw = t.ask - t.bid, []
    for tf, prio, nm in ((mt5.TIMEFRAME_H4, 3, "H4"), (mt5.TIMEFRAME_H1, 2, "H1"),
                         (mt5.TIMEFRAME_M15, 1, "M15")):
        r = mt5.copy_rates_from_pos(SYM, tf, 1, 1)
        if r is None or len(r) == 0:
            continue
        raw += [[r[0]["high"], True, prio, nm], [r[0]["low"], False, prio, nm]]
    if not raw:
        return out
    tol = max(spread * 3.0, a * 0.12)
    raw.sort(key=lambda x: x[0])
    keep = [True] * len(raw)
    for i in range(len(raw)):
        if not keep[i]:
            continue
        for j in range(i + 1, len(raw)):
            if keep[j] and abs(raw[i][0] - raw[j][0]) <= tol:
                if raw[j][2] > raw[i][2]:
                    raw[i] = raw[j]
                keep[j] = False
    merged = [r for i, r in enumerate(raw) if keep[i]]
    md = merged[0][0] * 0.001
    for r in merged:
        if not out or r[1] != out[-1][1] or abs(r[0] - out[-1][0]) >= md:
            out.append(r)
        if len(out) >= 6:
            break
    return out


# ==================== NOTHING ABOVE HERE HAS SIDE EFFECTS ====================
# Everything BELOW is the live loop and runs at import time - there is no main()
# guard, so `import daemon` starts a SECOND daemon on account 436771046.
#
# That is not hypothetical. On 2026-08-02 a session imported this module to unit
# test one helper function and started a rogue loop that was writing its own
# handoffs within two minutes. It happened to be dry-run (no --live in argv) so
# no orders were sent - that was luck, not design. A copy started from a context
# that DID pass --live would have raced the real daemon on the same account and
# could breach the one-position-at-a-time rule.
#
# Refusing the import is deliberate: there is no way to import this file safely,
# so a loud failure beats a silent second trading loop. To test a helper defined
# above, run this file as a script or copy the function out.
if __name__ != "__main__":
    raise ImportError(
        "daemon.py must never be imported - the live trading loop runs at import "
        "time and an import starts a second daemon on account 436771046. "
        "Run it as a script, or copy the helper you want to test."
    )

connect()
say(f"daemon up | {SYM} | account {LOGIN} | "
    f"mode={'DRY RUN (no orders sent)' if DRY_RUN else '*** LIVE ***'} | "
    f"llm={'on' if USE_LLM else 'off'} | poll {POLL}s")
if DRY_RUN:
    say("dry run: the model IS called and DOES return tool calls; only order "
        "execution is stubbed. Read decisions.csv and llm_calls.jsonl.")
if USE_LLM:
    _prov = brain.default_provider()
    _key  = {"openai": "OPENAI_API_KEY", "claude": "ANTHROPIC_API_KEY"}.get(_prov)
    if _prov == "session":
        # Say plainly what this costs, because a green heartbeat looks identical
        # whether a session is reading the handoffs or the terminal was closed.
        _fb = "GPT-5" if os.environ.get("OPENAI_API_KEY") else "NOTHING - no OPENAI_API_KEY"
        say(f"decider: PRIMARY = attached Claude Code session (no API cost). "
            f"Every decision is written to NEEDS_HUMAN.json and waits for a Monitor "
            f"to wake the session - nothing decides while no session is attached. "
            f"Fallback after {brain.SESSION_TIMEOUT_MIN} min of silence: {_fb}.")
    elif _key and not os.environ.get(_key):
        say(f"NOTE: provider={_prov} but {_key} is not set - events will be "
            f"detected and logged, no decisions made.")
    else:
        say(f"decider: {_prov} / {brain.DEFAULT_MODELS.get(_prov)} ({_key} present)")

def own_positions():
    # This loop's trades only (act.py sends magic 0, comment KL-auto). The
    # harvest/renko bots (magic 7704xx) and any EA (9909xx) run recovery baskets
    # on this same account with no SL and multi-hour holds - every rule here
    # (max hold, 1R, open/close wakes) is about OUR trades, and on 2026-08-08
    # the max-hold wake told the decider to CLOSE two harvest baskets.
    return [p for p in (mt5.positions_get(symbol=SYM) or []) if p.magic == 0]

def own_orders():
    # same magic-0 filter as own_positions - on 2026-08-10 a foreign pending
    # (#3067160991) vanishing woke the decider with "PENDING GONE ... NOT by
    # this loop", which was true but not our business.
    return [o for o in (mt5.orders_get(symbol=SYM) or []) if o.magic == 0]

known_pos  = {p.ticket for p in own_positions()}
known_ord  = {o.ticket for o in own_orders()}

# Re-sync on startup. A restart baselines every level and every known order, so
# anything that changed while the daemon was down is absorbed silently and never
# reaches the decider. On 2026-07-30 a manual cancel at 15:45 plus a restart at
# 15:49 left the model holding four watch levels that all referenced an order
# that no longer existed, with nothing able to correct it until some unrelated
# level happened to fire. One call on startup (~$0.02) buys a decider whose view
# matches reality.
if USE_LLM:
    wake(f"DAEMON STARTED / RESTARTED. Your watch levels and any assumptions from "
         f"before the restart may be stale - state can have changed while this loop "
         f"was down, including orders cancelled or filled outside it. Treat the "
         f"briefing below as the only truth: {len(known_pos)} open position(s), "
         f"{len(known_ord)} pending order(s). Re-sync your watch levels to what is "
         f"actually there now.")
fired_1r   = set()
level_side = {}
armed      = {}
declined   = {}      # level price -> time it was last assessed and passed on
forced     = set()   # tickets already flagged for exceeding max hold
fires      = {}      # level key -> how many times it has fired this run
born_dead  = set()   # levels first seen already broken; silent until reclaimed
# Rule 8 escalation: ticket -> the highest threshold already warned about.
#
# This was a set, so the warning fired ONCE per ticket and never again. That treated
# 1.6x and 5.3x as the same event, when they are not - fill odds inside the hold window
# fall from about 28% to about 6% between them. The order that caused rule 8 to exist
# drifted to 5.3x, and under the one-shot design the decider would have been told once
# at 1.5x and then left alone while it got four times worse.
#
# Now each band warns separately, so the wake tracks the situation deteriorating rather
# than assuming the first look settled it. Still bounded - three warnings per ticket at
# most, not one per poll.
UNREACHABLE_BANDS = (1.5, 3.0, 5.0)
unreachable_flagged = {}      # ticket -> highest band already warned
# Seeded to NOW, not 0.0. The staleness backstop measures now - last_event, so a
# zero start meant the first pass after a restart measured against the Unix epoch:
# on 2026-08-01 it woke the decider with "NO DECISION FOR 29759658 MINUTES", about
# 56 years. Harmless in effect - the wake was spurious but not dangerous - yet it
# puts a nonsense number into the permanent decision record, and a later reader has
# no way to tell it from a real 45-minute blind spell. The clock starts when the
# daemon starts.
last_event = time.time()
last_wake_price = None   # mid at the last wake; the staleness backstop's baseline

while True:
    try:
        if not mt5.terminal_info():
            mt5.shutdown()
            connect()

        cfg = load_config()
        tick = mt5.symbol_info_tick(SYM)
        if tick is None:
            time.sleep(POLL)
            continue
        mid  = (tick.bid + tick.ask) / 2
        pos  = own_positions()
        ords = own_orders()
        now  = time.time()

        # --- position appeared / disappeared: always wake, never rate-limited ---
        cur = {p.ticket for p in pos}
        for t in cur - known_pos:
            p = next(x for x in pos if x.ticket == t)
            wake(f"POSITION OPENED #{t} {'BUY' if p.type == 0 else 'SELL'} "
                 f"{p.volume} @ {p.price_open} SL {p.sl or 'NONE'} TP {p.tp or 'NONE'}")
            last_event = now
        for t in known_pos - cur:
            # Journal BEFORE waking the model: capture the full market context of
            # the trade that just closed - ATR at every timeframe, EMA position,
            # structure, Donchian state, candle shape, volume, MFE/MAE. Context
            # cannot be reconstructed later once conditions move on, so it is
            # captured on every close, win or lose.
            try:
                subprocess.run([sys.executable, os.path.join(HERE, "trade_journal.py")],
                               capture_output=True, text=True, timeout=180)
                say(f"       journalled #{t}")
            except Exception as je:
                say(f"       journal failed for #{t}: {type(je).__name__}: {je}")
            wake(f"POSITION CLOSED #{t} - flat now, bid {tick.bid}. "
                 f"Reassess: is there a next setup, and are the watch levels still right?")
            fired_1r.discard(t)
            last_event = now
        known_pos = cur

        # Orders appearing AND disappearing. The first version only watched for
        # new orders, so a pending that vanished was absorbed silently - on
        # 2026-07-30 order #3027380511 was cancelled externally at 15:45 and
        # nothing anywhere recorded it. A pending can leave the book by filling
        # (which surfaces separately as POSITION OPENED), or by being cancelled,
        # expiring, or being rejected - and the last three are all events the
        # decider needs to know about, since its plan was built around that
        # order still resting.
        curo = {o.ticket for o in ords}
        for t in curo - known_ord:
            say(f"pending #{t} now resting")
        for t in known_ord - curo:
            if t in {p.ticket for p in pos}:
                continue                      # it filled; POSITION OPENED covers it
            if brain.was_self_cancelled(t):
                # We cancelled it ourselves; the model already knows and has
                # acted. Waking it to say the order vanished "NOT by this loop"
                # is both a wasted call and a false statement.
                #
                # This consults the on-disk record as well as the in-memory set,
                # because a cancel issued by running act.py directly happens in a
                # different process and would otherwise look mysterious here.
                say(f"pending #{t} gone - our own cancel, not waking")
                brain.SELF_CANCELLED.discard(t)
                continue
            filled = order_filled_and_closed(t)
            if filled:
                # It DID fill - it just also closed before this poll came round.
                # The `t in pos` check above only catches a fill that is STILL
                # open, so a trade that filled and hit its stop inside one 30s
                # poll fell through to the "never filled" message below.
                # Observed 2026-08-02: #3033618550 filled 17:24:30 and stopped
                # out 17:24:46, and the decider was told it never filled and was
                # flat. That is the worst possible briefing - it hides a loss on
                # the exact setup the decider is about to re-place, so it cannot
                # learn the setup is failing. Four identical fades were placed
                # that day, all stopped within 16s, all reported as non-fills.
                wake(f"PENDING GONE #{t} FILLED AND ALREADY CLOSED inside one poll - "
                     f"entry {filled['entry']:.2f}, exit {filled['exit']:.2f}, "
                     f"realised {filled['profit']:+.2f} ({filled['how']}). "
                     f"Held {filled['secs']:.0f}s. You are flat now. This was a REAL "
                     f"completed trade, not a cancelled order - weigh it before "
                     f"re-placing the same setup.")
            else:
                wake(f"PENDING GONE #{t} left the book without filling - cancelled, "
                     f"expired or rejected, and NOT by this loop. Flat with no order "
                     f"unless stated otherwise. Reassess from current structure.")
            last_event = now
        known_ord = curo

        # --- MAX HOLD: force a reassessment on anything open too long ---
        # From 101 real trades (Jul 11-30): trades under 2h were 90% win, +$49.
        # Four trades over 10h were 25% win, -$54 - four losses erased seventy-nine
        # wins. Duration is largely an OUTCOME (winners hit TP fast, losers linger),
        # so this does not turn losers into winners - it turns big losers into small
        # ones. That tail-cap is the only thing in the whole dataset that clearly
        # separated outcomes.
        max_hold = cfg.get("max_hold_minutes", 120)
        for p in pos:
            if p.ticket in forced:
                continue
            held = (now - p.time) / 60.0
            if held >= max_hold:
                forced.add(p.ticket)
                wake(f"MAX HOLD REACHED #{p.ticket} has been open {held:.0f} minutes "
                     f"(limit {max_hold}). P&L {p.profit:+.2f}. Trades this old have a "
                     f"25% win rate historically and produced every catastrophic loss "
                     f"on this account. CLOSE IT unless there is a specific, stated "
                     f"reason it is about to resolve.")
                last_event = now

        # --- open position reached ~1R: candidate for a break-even stop ---
        for p in pos:
            if p.ticket in fired_1r or not p.sl:
                continue
            risk = abs(p.price_open - p.sl)
            if risk <= 0:
                continue
            gain = (tick.bid - p.price_open) if p.type == 0 else (p.price_open - tick.ask)
            if gain >= risk * cfg.get("be_trigger_r", 1.0):
                fired_1r.add(p.ticket)
                wake(f"POSITION AT {gain / risk:.2f}R #{p.ticket} (+{gain:.0f} px, risk "
                     f"{risk:.0f} px). Consider moving the stop to break-even at {p.price_open}.")
                last_event = now

        # --- flagged level broken: test bar EXTREMES, not the current tick ---
        # A level that only trades through for seconds is exactly the one worth
        # waking for; a 30s tick sample misses those wicks entirely.
        recent = mt5.copy_rates_from_pos(SYM, mt5.TIMEFRAME_M1, 0, 3)
        lo = min(b["low"]  for b in recent) if recent is not None and len(recent) else mid
        hi = max(b["high"] for b in recent) if recent is not None and len(recent) else mid

        # Hysteresis on re-arming. The first version re-armed the instant price
        # crossed back, so a level price was oscillating around fired on every
        # crossing - 64730 fired three times in nine minutes on 2026-07-30, one
        # full model call each, none of them informative. Price must now retreat
        # a real distance (0.3 x ATR(M15)) onto the original side before the
        # level can fire again.
        atr_m15 = None
        _m15 = mt5.copy_rates_from_pos(SYM, mt5.TIMEFRAME_M15, 1, 15)
        if _m15 is not None and len(_m15) >= 14:
            _tr, _pc = [], None
            for b in _m15:
                if _pc is not None:
                    _tr.append(max(b["high"] - b["low"], abs(b["high"] - _pc), abs(b["low"] - _pc)))
                _pc = b["close"]
            if _tr:
                atr_m15 = sum(_tr) / len(_tr)
        rearm_gap = (atr_m15 or 120) * 0.3

        # --- RULE 8: a resting pending that price has walked away from ---
        # Fires ONCE per ticket when the entry drifts past 1.5x ATR(M15), where
        # fill probability inside the 120-min hold window drops under 40%. This
        # exists because nothing else prompts the review: the staleness backstop
        # reliably rebuilds stale LEVELS but has only once, incidentally, freed a
        # stale ORDER. On 2026-07-31 one rested 2h45m at 5.3x ATR (6% fill odds)
        # through a 1,465-point trend, holding the single slot rule 1 allows,
        # kept at every wake because its R:R still read 1.81.
        for o in ords:
            away = abs(o.price_open - mid) / (atr_m15 or 120)
            # highest band this order has now crossed, and the highest already warned
            band = max([b for b in UNREACHABLE_BANDS if away > b], default=None)
            if band is None:
                continue
            if unreachable_flagged.get(o.ticket, 0) >= band:
                continue                       # already warned at this band or worse
            if now - last_event <= MIN_GAP:
                continue
            prev = unreachable_flagged.get(o.ticket, 0)
            unreachable_flagged[o.ticket] = band
            odds = "6" if away >= 5 else "15" if away >= 3 else "28"
            again = (f" This is the SECOND escalation - it was already {prev:.1f}x when "
                     f"you last chose to keep it, and it has since got worse." if prev else "")
            wake(f"PENDING #{o.ticket} @ {o.price_open:.2f} is now {away:.1f}x ATR(M15) "
                 f"from price {mid:.2f} - under RULE 8 that is unreachable "
                 f"(roughly {odds}% chance of filling inside 120 minutes) and it is "
                 f"holding the only pending slot.{again} "
                 f"Cancel it unless you can say specifically why price returns there soon. "
                 f"Do NOT replace it at a worse entry.")
            last_event = now
        # forget tickets that have left the book
        for t in [t for t in unreachable_flagged if t not in {o.ticket for o in ords}]:
            unreachable_flagged.pop(t, None)

        # --- STALENESS BACKSTOP: the decider must not sleep through a real move ---
        # Every wake-up depends on the model's own watch levels being correct, and
        # on 2026-07-30 they were not: it set four levels ABOVE price and two
        # BELOW that were already broken when registered, so a falling market had
        # nothing left that could fire. The decider went 60 minutes without a
        # single call while price fell 232 points inside a 1,218-point range,
        # holding a pending order 1,105 points away that it could not reassess.
        #
        # This backstop does not care WHY nothing fired. If the model has not been
        # consulted for STALE_GAP and price has moved more than an ATR(M15) since
        # it last was, wake it. Cost is at most one call per STALE_GAP; the cost of
        # not having it was an hour of blindness.
        if last_wake_price is None:
            last_wake_price = mid
        if (now - last_event > STALE_GAP
                and abs(mid - last_wake_price) > (atr_m15 or 120)):
            moved = mid - last_wake_price
            wake(f"NO DECISION FOR {(now - last_event)/60:.0f} MINUTES while price moved "
                 f"{moved:+.0f} ({abs(moved)/(atr_m15 or 120):.1f} x ATR-M15) to {mid:.2f}. "
                 f"Nothing in your watch levels fired - check whether they are still "
                 f"pointing where the market actually is, and whether any resting order "
                 f"is still reachable. Re-frame from current structure.")
            last_event = now
            last_wake_price = mid

        for wl in cfg.get("watch_levels", []):
            price, side = float(wl["price"]), wl.get("dir", "below")
            key = f"{price}:{side}"
            broken = (lo < price) if side == "below" else (hi > price)
            # clearly back on the original side, not merely re-crossed
            recovered = (mid > price + rearm_gap) if side == "below" else (mid < price - rearm_gap)
            was = level_side.get(key)
            if was is None:
                # A level first seen ALREADY BROKEN is born dead: it is marked
                # broken here and can never fire until price reclaims it past
                # rearm_gap. RESTORE.md documents this for restarts, but it bites
                # NEW levels too - on 2026-07-30 the model set H4 support at
                # 64589.93 from a briefing showing price at 64607, price broke it
                # inside the same minute, and the daemon then stayed silent
                # through a further 120-point drop. Record it so the blind spot is
                # visible in the log and in the briefing instead of silent.
                level_side[key] = broken
                if broken:
                    born_dead.add(key)
                    say(f"level {price} ({side}) was ALREADY BROKEN when registered "
                        f"- it will not fire until price reclaims it")
                else:
                    born_dead.discard(key)
            elif broken and not was and now - last_event > MIN_GAP:
                ext = lo if side == "below" else hi
                fires[key] = fires.get(key, 0) + 1
                extra = ("  NOTE: this level has now fired "
                         f"{fires[key]} times - if it is no longer meaningful, "
                         "replace it via set_watch_levels.") if fires[key] >= 2 else ""
                wake(f"LEVEL BROKEN {side} {price} (reached {ext:.2f}, now {mid:.2f}). "
                     f"Note: {wl.get('note', '')}{extra}")
                level_side[key] = True
                last_event = now
            elif recovered:
                level_side[key] = False
                born_dead.discard(key)

        # --- flat and price arrived at a level: possible new trade ---
        # Two suppressions, both learned the hard way on 2026-07-30:
        #  * An M15 level equal to a recent M15 candle's own extreme is
        #    self-referential - M15 levels ARE the previous M15 bar's extremes by
        #    construction, so price "reaching" one is a definitional artifact that
        #    fires constantly. Those are not setups and must not cost a call.
        #    This deliberately does NOT suppress H1/H4 levels that happen to share
        #    the same price: an H1 level coinciding with a recent M15 extreme means
        #    the H1 bar closed near its high/low, and price returning there is a
        #    genuine retest worth assessing. Seen 2026-07-31 06:07 at 63,886.75.
        #  * Once a level has been assessed and declined, do not re-ask about it
        #    for cooldown_sec. Price oscillating in a band around one level woke
        #    the loop three times in six minutes for the same unchanged answer.
        if not pos and not ords and now - last_event > MIN_GAP:
            a = atr_h1()
            if a:
                near     = cfg.get("setup_proximity_atr", 0.06) * a
                cooldown = cfg.get("setup_cooldown_sec", 1800)
                recent_m15 = mt5.copy_rates_from_pos(SYM, mt5.TIMEFRAME_M15, 1, 2)
                fresh = set()
                if recent_m15 is not None:
                    for b in recent_m15:
                        fresh.add(round(b["high"], 2))
                        fresh.add(round(b["low"], 2))

                for lp, isHigh, prio, nm in levels():
                    k = round(lp, 2)
                    if k in fresh and nm == "M15":
                        continue                    # self-referential, skip silently
                    if abs(mid - lp) <= near:
                        if now - declined.get(k, 0) < cooldown:
                            continue                # already assessed, still stands
                        if armed.get(k, True):
                            armed[k] = False
                            declined[k] = now       # assume declined unless a trade results
                            wake(f"AT LEVEL - flat, price {mid:.2f} at {nm} "
                                 f"{'RESISTANCE' if isHigh else 'SUPPORT'} {lp:.2f} "
                                 f"({abs(mid - lp):.0f} px away). Assess for a trade.")
                            last_event = now
                    elif abs(mid - lp) > near * 2.5:
                        armed[k] = True

        json.dump({"alive_utc": datetime.utcnow().isoformat(), "bid": tick.bid,
                   "dry_run": DRY_RUN, "llm": USE_LLM,
                   "positions": len(pos), "orders": len(ords)}, open(ALIVE, "w"), indent=2)

    except Exception as e:
        say(f"LOOP ERROR {type(e).__name__}: {e}")
        try:
            mt5.shutdown()
        except Exception:
            pass
        time.sleep(10)
        connect()

    time.sleep(POLL)
