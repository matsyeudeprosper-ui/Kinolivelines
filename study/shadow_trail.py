"""shadow_trail.py - run the daily trail WITHOUT trading it.

Computes the $5-activation / $3-giveback daily trail against the real live
account every 20 seconds, records everything it WOULD have done, and closes
nothing. This is the step before any decision to run it for real, because the
backtest result is unstable across anchors and the execution cost of a
liquidation has never been measured on this account.

IT CANNOT TRADE. There is no order_send call in this file and no code path that
reaches one. It is safe to run beside the live bot.

THE DEFINITION (per review, 2026-08-07)

    bot_value  = every realised P&L this magic has ever booked
                 + the floating P&L of whatever it holds right now
    daily_total = bot_value now - bot_value at the start of the UTC day

Deliberately NOT "daily realised + current-cycle realised + floating": a
take-profit banked inside the open cycle appears in BOTH of the first two
terms, so that formula double-counts exactly the harvest events this strategy
lives on. Anchoring to a stored day-start value has no such overlap.

STATE MACHINE

    daily_total >= ACTIVATE          -> armed
    peak         = max daily_total seen since arming
    locked_floor = max(0, peak - GIVEBACK)
    daily_total <= locked_floor      -> would block new cycles, would liquidate

WHAT IS BEING MEASURED. The number worth having is the gap between
`pnl_when_floor_hit` and what a real liquidation would actually realise. This
file records the first honestly. The second needs a live close, which is why
the active version has to prove itself on demo before it goes anywhere near
real money.
"""
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone

import MetaTrader5 as mt5

TERMINAL = r"C:\Projects\MT5-KinoliveTrader\terminal64.exe"
LOGIN    = 134499778
MAGIC    = 770407
SYMBOL   = "BTCUSDm"

ACTIVATE = 5.00          # arm once the day is this far up
GIVEBACK = 3.00          # give back this much from the peak and it fires
POLL     = 20            # seconds

HERE  = os.path.dirname(os.path.abspath(__file__))
SNAP  = os.path.join(HERE, "shadow_trail_snapshots.jsonl")
EVENT = os.path.join(HERE, "shadow_trail_events.jsonl")
STATE = os.path.join(HERE, "shadow_trail_state.json")
ALIVE = os.path.join(HERE, "shadow_trail_alive.json")
LOG   = os.path.join(HERE, "shadow_trail.log")

# History is walked from here once per poll. The account is days old, so this is
# cheap; if it ever gets slow, cache the realised total per closed deal ticket
# rather than shortening the window - a short window silently changes what
# "every realised P&L" means and would break the day-start anchor.
EPOCH = datetime(2026, 8, 1)


def say(m):
    line = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {m}"
    print(line, flush=True)
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def append(path, row):
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(row, default=str) + "\n")
    except Exception:
        pass


def load_state():
    try:
        with open(STATE) as f:
            return json.load(f)
    except Exception:
        return {}


def save_state(s):
    try:
        tmp = STATE + ".tmp"
        with open(tmp, "w") as f:
            json.dump(s, f)
        os.replace(tmp, STATE)
    except Exception:
        pass


def day_id(now_utc):
    return now_utc.strftime("%Y-%m-%d")


def read_account():
    """Everything this tick needs, or None if the terminal is not usable."""
    a = mt5.account_info()
    if a is None or a.login != LOGIN:
        return None
    deals = mt5.history_deals_get(EPOCH, datetime.now() + timedelta(days=1))
    if deals is None:
        return None
    realised = sum(d.profit + d.swap + d.commission + getattr(d, "fee", 0.0)
                   for d in deals if d.magic == MAGIC)
    ps = [p for p in (mt5.positions_get(symbol=SYMBOL) or []) if p.magic == MAGIC]
    floating = sum(p.profit + p.swap for p in ps)
    tick = mt5.symbol_info_tick(SYMBOL)
    return dict(realised=realised, floating=floating, positions=len(ps),
                bot_value=realised + floating,
                bid=getattr(tick, "bid", 0.0), ask=getattr(tick, "ask", 0.0),
                spread=round(getattr(tick, "ask", 0.0) - getattr(tick, "bid", 0.0), 2),
                balance=a.balance, equity=a.equity,
                margin_free=a.margin_free,
                margin_level=round(a.margin_level or 0.0, 1))


def main():
    say(f"shadow trail up | activate ${ACTIVATE:.2f} giveback ${GIVEBACK:.2f} "
        f"| poll {POLL}s | RECORD ONLY, NEVER TRADES")
    st = load_state()
    fails = 0

    while True:
        try:
            if not mt5.initialize(path=TERMINAL):
                fails += 1
                if fails % 15 == 1:
                    say(f"terminal unreachable: {mt5.last_error()}")
                time.sleep(POLL)
                continue
            acc = read_account()
            mt5.shutdown()
            if acc is None:
                fails += 1
                time.sleep(POLL)
                continue
            fails = 0

            now = datetime.now(timezone.utc)
            did = day_id(now)

            # ---- day roll-over --------------------------------------------
            if st.get("day_id") != did:
                if st.get("day_id"):
                    append(EVENT, dict(ts_utc=now.isoformat(), kind="day_reset",
                                       previous_day=st.get("day_id"),
                                       previous_daily_total=round(
                                           st.get("last_daily_total", 0.0), 2),
                                       armed_at_reset=st.get("armed", False),
                                       positions_open_at_reset=acc["positions"]))
                    # Midnight while armed and still holding is the hole in this
                    # rule: the protection resets and the position survives it.
                    if st.get("armed") and acc["positions"]:
                        append(EVENT, dict(ts_utc=now.isoformat(),
                                           kind="midnight_with_open_positions",
                                           note="armed trail reset while holding; "
                                                "a live version should liquidate first",
                                           positions=acc["positions"]))
                st = dict(day_id=did, day_start_bot_value=acc["bot_value"],
                          armed=False, peak=0.0, locked_floor=0.0,
                          floor_hit=False, hit_ts=None, hit_pnl=None,
                          last_daily_total=0.0)
                say(f"new UTC day {did} | day-start bot value {acc['bot_value']:+.2f}")

            daily_total = acc["bot_value"] - st["day_start_bot_value"]
            st["last_daily_total"] = daily_total

            # ---- state machine (records only) -----------------------------
            if not st["armed"] and daily_total >= ACTIVATE:
                st["armed"] = True
                st["peak"] = daily_total
                st["locked_floor"] = max(0.0, daily_total - GIVEBACK)
                append(EVENT, dict(ts_utc=now.isoformat(), kind="trail_armed",
                                   daily_total=round(daily_total, 2),
                                   locked_floor=round(st["locked_floor"], 2)))
                say(f"ARMED at {daily_total:+.2f}, floor {st['locked_floor']:.2f}")

            elif st["armed"] and daily_total > st["peak"]:
                st["peak"] = daily_total
                new_floor = max(0.0, daily_total - GIVEBACK)
                append(EVENT, dict(ts_utc=now.isoformat(), kind="new_peak",
                                   daily_total=round(daily_total, 2),
                                   peak=round(st["peak"], 2)))
                if new_floor > st["locked_floor"]:
                    st["locked_floor"] = new_floor
                    append(EVENT, dict(ts_utc=now.isoformat(), kind="floor_raised",
                                       locked_floor=round(new_floor, 2)))

            if st["armed"] and not st["floor_hit"] and daily_total <= st["locked_floor"]:
                st["floor_hit"] = True
                st["hit_ts"] = now.isoformat()
                st["hit_pnl"] = daily_total
                append(EVENT, dict(
                    ts_utc=now.isoformat(), kind="floor_hit_SHADOW",
                    pnl_when_floor_hit=round(daily_total, 2),
                    locked_floor=round(st["locked_floor"], 2),
                    peak=round(st["peak"], 2),
                    positions_that_would_close=acc["positions"],
                    floating_that_would_be_realised=round(acc["floating"], 2),
                    bid=acc["bid"], ask=acc["ask"], spread=acc["spread"],
                    note="RECORD ONLY - nothing was closed"))
                say(f"*** SHADOW FLOOR HIT at {daily_total:+.2f} "
                    f"(floor {st['locked_floor']:.2f}, peak {st['peak']:.2f}) - "
                    f"would close {acc['positions']} positions, "
                    f"floating {acc['floating']:+.2f}. NOTHING CLOSED. ***")

            # After a shadow hit the real bot keeps trading, so the difference
            # between the P&L at the hit and where the day actually ends is the
            # thing this whole exercise exists to measure.
            drift = None
            if st["floor_hit"] and st["hit_pnl"] is not None:
                drift = daily_total - st["hit_pnl"]

            append(SNAP, dict(
                ts_utc=now.isoformat(), day_id=did,
                day_start_bot_value=round(st["day_start_bot_value"], 2),
                realised_all_time=round(acc["realised"], 2),
                floating_liquidation_pnl=round(acc["floating"], 2),
                bot_value=round(acc["bot_value"], 2),
                daily_total_pnl=round(daily_total, 2),
                trail_armed=st["armed"], daily_peak=round(st["peak"], 2),
                locked_floor=round(st["locked_floor"], 2),
                activation=ACTIVATE, giveback=GIVEBACK,
                floor_hit=st["floor_hit"],
                pnl_when_floor_hit=(round(st["hit_pnl"], 2)
                                    if st["hit_pnl"] is not None else None),
                pnl_since_floor_hit=(round(drift, 2) if drift is not None else None),
                positions_open=acc["positions"],
                bid=acc["bid"], ask=acc["ask"], spread=acc["spread"],
                balance=round(acc["balance"], 2), equity=round(acc["equity"], 2),
                free_margin=round(acc["margin_free"], 2),
                margin_level=acc["margin_level"],
                mode="SHADOW"))

            save_state(st)
            try:
                with open(ALIVE, "w") as f:
                    json.dump(dict(alive_utc=datetime.utcnow().isoformat(),
                                   mode="SHADOW", day_id=did,
                                   daily_total=round(daily_total, 2),
                                   armed=st["armed"],
                                   locked_floor=round(st["locked_floor"], 2),
                                   floor_hit=st["floor_hit"],
                                   positions=acc["positions"]), f)
            except Exception:
                pass

        except Exception as e:
            say(f"ERROR {type(e).__name__}: {e}")
            try:
                mt5.shutdown()
            except Exception:
                pass
            fails += 1

        if fails >= 30:
            say("30 consecutive failures - exiting so the watchdog restarts me")
            sys.exit(1)
        time.sleep(POLL)


if __name__ == "__main__":
    main()
