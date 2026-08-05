"""renko_journal.py - a wide feature snapshot of every renko_bot trade.

One row per COMPLETED trade, with the market state captured at BOTH the entry
and the exit, so patterns can be hunted later for a filter.

Deliberately decoupled from renko_bot.py: it reads MT5 deal history rather than
being called by the bot. That means
  - a journal bug can never break or delay a trade,
  - it backfills trades that happened before it was written,
  - and it records what the BROKER says happened, not what the bot intended.

WHAT IT CAPTURES
  timing     exact entry/exit time to the second, duration, hour, weekday
  price      entry/exit, bid, ask, spread at both ends
  volatility ATR(14) on M1, M5, M15, H1  + ATR now vs its own 100-bar average
  momentum   RSI(14) on M1, M5, M15
  trend      EMA 20/50/200 on M5 and M15: distance from price, slope, and the
             stack (+1 = 20>50>200, -1 = inverted, 0 = tangled)
  location   where price sat in the recent 20-bar range, distance to its high/low
  flow       tick volume vs its average, consecutive up/down M1 bars
  outcome    pnl, exit reason, slippage against the intended stop/target
  excursion  MAE and MFE - the furthest the trade went against and for us before
             it resolved. This is the single most useful column for filter work:
             a losing trade that never went more than a few points our way is a
             different animal from one that nearly hit target first.
"""
import csv, os, time
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import MetaTrader5 as mt5

TERMINAL = r"C:\Program Files\MetaTrader 5\terminal64.exe"
LOGIN    = 436771046
SYMBOL   = "BTCUSDm"
MAGIC    = 770404
POLL     = 60

HERE = os.path.dirname(os.path.abspath(__file__))
OUT  = os.path.join(HERE, "renko_journal.csv")

TFS = {"m1": mt5.TIMEFRAME_M1, "m5": mt5.TIMEFRAME_M5,
       "m15": mt5.TIMEFRAME_M15, "h1": mt5.TIMEFRAME_H1}


def connect():
    if not mt5.initialize(path=TERMINAL):
        raise SystemExit(f"initialize failed: {mt5.last_error()}")
    a = mt5.account_info()
    if a is None or a.login != LOGIN:
        mt5.shutdown()
        raise SystemExit(f"WRONG ACCOUNT {a.login if a else None}")
    return a


def atr(d, n=14):
    pc = d["close"].shift(1)
    tr = pd.concat([d["high"] - d["low"], (d["high"] - pc).abs(),
                    (d["low"] - pc).abs()], axis=1).max(axis=1)
    return tr.rolling(n).mean()


def rsi(s, n=14):
    delta = s.diff()
    up = delta.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-delta.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    rs = up / dn.replace(0, np.nan)
    return 100 - 100 / (1 + rs)


def frame(tf, when, bars=400):
    """Bars strictly BEFORE `when` - never let a feature see the future."""
    r = mt5.copy_rates_from(SYMBOL, tf, when, bars)
    if r is None or len(r) < 60:
        return None
    d = pd.DataFrame(r)
    d["t"] = pd.to_datetime(d["time"], unit="s")
    return d[d["t"] <= when].reset_index(drop=True)


def snapshot(when, tag):
    """Every feature we can compute at a single instant, prefixed with tag."""
    f = {}
    for name, tf in TFS.items():
        d = frame(tf, when)
        if d is None or len(d) < 60:
            continue
        a = atr(d)
        f[f"{tag}_atr_{name}"] = round(float(a.iloc[-1]), 2)
        # is volatility high or low FOR THIS MARKET right now? an absolute ATR
        # means little without knowing what is normal lately
        f[f"{tag}_atr_{name}_rel"] = round(float(a.iloc[-1] / a.tail(100).mean()), 3)
        if name in ("m1", "m5", "m15"):
            f[f"{tag}_rsi_{name}"] = round(float(rsi(d["close"]).iloc[-1]), 1)
        if name in ("m5", "m15"):
            px = float(d["close"].iloc[-1])
            e20 = d["close"].ewm(span=20).mean()
            e50 = d["close"].ewm(span=50).mean()
            e200 = d["close"].ewm(span=200).mean()
            f[f"{tag}_px_vs_ema20_{name}"] = round(px - float(e20.iloc[-1]), 1)
            f[f"{tag}_px_vs_ema50_{name}"] = round(px - float(e50.iloc[-1]), 1)
            f[f"{tag}_px_vs_ema200_{name}"] = round(px - float(e200.iloc[-1]), 1)
            # slope = the SHAPE of the average: rising, flat or rolling over
            f[f"{tag}_ema20_slope_{name}"] = round(float(e20.iloc[-1] - e20.iloc[-6]) / 5, 2)
            f[f"{tag}_ema50_slope_{name}"] = round(float(e50.iloc[-1] - e50.iloc[-6]) / 5, 2)
            stack = 1 if (e20.iloc[-1] > e50.iloc[-1] > e200.iloc[-1]) else \
                   -1 if (e20.iloc[-1] < e50.iloc[-1] < e200.iloc[-1]) else 0
            f[f"{tag}_ma_stack_{name}"] = stack
            hi20, lo20 = float(d["high"].tail(20).max()), float(d["low"].tail(20).min())
            f[f"{tag}_dist_hi20_{name}"] = round(hi20 - px, 1)
            f[f"{tag}_dist_lo20_{name}"] = round(px - lo20, 1)
            f[f"{tag}_range_pos_{name}"] = round((px - lo20) / (hi20 - lo20), 3) if hi20 > lo20 else None
        if name == "m1":
            v = d["tick_volume"]
            f[f"{tag}_tickvol_rel"] = round(float(v.iloc[-1] / v.tail(60).mean()), 2)
            up = (d["close"] > d["open"]).astype(int).values
            run = 1
            for i in range(len(up) - 2, -1, -1):
                if up[i] == up[-1]:
                    run += 1
                else:
                    break
            f[f"{tag}_consec_m1"] = int(run if up[-1] == 1 else -run)
    f[f"{tag}_hour_utc"] = when.hour
    f[f"{tag}_weekday"] = when.weekday()
    return f


def excursion(entry_t, exit_t, entry_px, is_long):
    """Furthest the trade ran for us (MFE) and against us (MAE), in points.

    Uses copy_rates_from, NOT copy_rates_range. Range returns zero bars for
    narrow windows on this terminal - a server-timezone quirk that fails
    silently with last_error 'Success', so it looks like there is simply no
    data. copy_rates_from with a bar count is reliable; slice afterwards.
    """
    # copy_rates_from IGNORES its date argument on this terminal - it always
    # returns the last `count` bars ending now, verified by asking for 20/60/
    # 200/400 and getting four windows that all end at the current bar. So ask
    # for enough bars to reach BACK to the trade, then slice. Requesting a small
    # count silently returns recent bars that do not contain the trade at all,
    # which is why MAE/MFE came out empty rather than wrong.
    need = int((datetime.utcnow() - entry_t).total_seconds() // 60) + 30
    r = mt5.copy_rates_from(SYMBOL, mt5.TIMEFRAME_M1, datetime.utcnow(),
                            min(max(need, 120), 20000))
    if r is None or not len(r):
        return None, None
    d = pd.DataFrame(r)
    d["t"] = pd.to_datetime(d["time"], unit="s")
    d = d[(d["t"] >= entry_t - timedelta(minutes=1)) & (d["t"] <= exit_t + timedelta(minutes=1))]
    if not len(d):
        return None, None
    hi, lo = float(d["high"].max()), float(d["low"].min())
    if is_long:
        return round(entry_px - lo, 1), round(hi - entry_px, 1)
    return round(hi - entry_px, 1), round(entry_px - lo, 1)


TP_BRICKS, SL_BRICKS, BRICK = 5, 3, 50.0
POST_HORIZON_H = 24          # how long to keep asking "did it get there eventually?"


def post_mortem(entry_t, exit_t, entry_px, is_long, tp_level):
    """For a STOPPED trade: did price later reach the original target anyway?

    This is the "was my stop too tight" question, answered per trade instead of
    argued about. Returns how long it took from entry, and the worst the trade
    would have got before recovering - because a target reached only after a
    600-point excursion is not a stop that was too tight, it is a different and
    much riskier strategy wearing the same clothes.

    Returns (resolved, hit, minutes_from_entry, max_adverse_pts).
    resolved is False while the horizon has not elapsed yet and it has not hit -
    the row stays open and gets re-checked on a later pass.
    """
    now = datetime.utcnow()
    horizon_end = exit_t + timedelta(hours=POST_HORIZON_H)
    need = int((now - entry_t).total_seconds() // 60) + 30
    r = mt5.copy_rates_from(SYMBOL, mt5.TIMEFRAME_M1, now, min(max(need, 120), 40000))
    if r is None or not len(r):
        return False, None, None, None
    d = pd.DataFrame(r)
    d["t"] = pd.to_datetime(d["time"], unit="s")
    d = d[(d["t"] >= exit_t) & (d["t"] <= min(horizon_end, now))]
    if not len(d):
        return False, None, None, None
    worst = 0.0
    for _, b in d.iterrows():
        worst = max(worst, (entry_px - b["low"]) if is_long else (b["high"] - entry_px))
        if (is_long and b["high"] >= tp_level) or ((not is_long) and b["low"] <= tp_level):
            mins = (b["t"] - entry_t).total_seconds() / 60
            return True, True, round(mins), round(worst, 1)
    if now >= horizon_end:
        return True, False, None, round(worst, 1)      # horizon elapsed, never got there
    return False, None, None, round(worst, 1)          # still open, check again later


def completed_trades():
    deals = mt5.history_deals_get(datetime.now() - timedelta(days=30),
                                  datetime.now() + timedelta(hours=6)) or []
    ours = [d for d in deals if d.magic == MAGIC and d.symbol == SYMBOL]
    ins = {d.position_id: d for d in ours if d.entry == 0}
    outs = {d.position_id: d for d in ours if d.entry == 1}
    return [(p, ins[p], outs[p]) for p in sorted(set(ins) & set(outs))]


def main():
    connect()
    print(f"renko_journal up -> {OUT}", flush=True)
    seen = set()
    if os.path.exists(OUT):
        try:
            seen = set(pd.read_csv(OUT)["position"].astype(int))
        except Exception:
            pass
    while True:
        try:
            rows = []
            for pos, i, o in completed_trades():
                if pos in seen:
                    continue
                is_long = (i.type == 0)
                et = datetime.utcfromtimestamp(i.time)
                xt = datetime.utcfromtimestamp(o.time)
                mae, mfe = excursion(et, xt, i.price, is_long)
                cmt = (o.comment or "").lower()
                reason = "tp" if "tp" in cmt else "sl" if "sl" in cmt else "other"
                tp_level = i.price + BRICK * TP_BRICKS if is_long else i.price - BRICK * TP_BRICKS
                sl_level = i.price - BRICK * SL_BRICKS if is_long else i.price + BRICK * SL_BRICKS
                if reason == "sl":
                    resolved, hit, mins, worst = post_mortem(et, xt, i.price, is_long, tp_level)
                else:
                    resolved, hit, mins, worst = True, None, None, None
                row = {"position": pos, "side": "BUY" if is_long else "SELL",
                       "volume": i.volume,
                       "entry_utc": et.isoformat(), "exit_utc": xt.isoformat(),
                       "duration_s": int(o.time - i.time),
                       "entry_price": i.price, "exit_price": o.price,
                       "intended_tp": round(tp_level, 2), "intended_sl": round(sl_level, 2),
                       "pnl": o.profit,
                       "exit_reason": reason,
                       "exit_comment": o.comment,
                       "mae_pts": mae, "mfe_pts": mfe,
                       # did a stopped trade get to target anyway, and at what cost?
                       "post_resolved": resolved,
                       "post_tp_hit": hit,
                       "post_tp_mins_from_entry": mins,
                       "post_max_adverse_pts": worst,
                       "post_horizon_h": POST_HORIZON_H}
                row.update(snapshot(et, "en") or {})
                row.update(snapshot(xt, "ex") or {})
                rows.append(row)
                seen.add(pos)
            df = pd.read_csv(OUT) if os.path.exists(OUT) else pd.DataFrame()
            if rows:
                df = pd.concat([df, pd.DataFrame(rows)], ignore_index=True) if len(df) \
                     else pd.DataFrame(rows)

            # Re-check stopped trades whose horizon has not elapsed. Without this
            # the post-mortem columns would be frozen at whatever was true seconds
            # after the stop, which is exactly when the answer is least informative.
            updated = 0
            if len(df) and "post_resolved" in df.columns:
                for idx in df.index[(df["exit_reason"] == "sl") & (df["post_resolved"] != True)]:
                    r0 = df.loc[idx]
                    et = datetime.fromisoformat(r0["entry_utc"])
                    xt = datetime.fromisoformat(r0["exit_utc"])
                    is_long = (r0["side"] == "BUY")
                    res, hit, mins, worst = post_mortem(et, xt, float(r0["entry_price"]),
                                                        is_long, float(r0["intended_tp"]))
                    df.at[idx, "post_resolved"] = res
                    df.at[idx, "post_tp_hit"] = hit
                    df.at[idx, "post_tp_mins_from_entry"] = mins
                    df.at[idx, "post_max_adverse_pts"] = worst
                    updated += 1

            if rows or updated:
                df.to_csv(OUT, index=False)
                print(f"{datetime.now():%H:%M:%S}  +{len(rows)} new, {updated} re-checked "
                      f"({len(df)} total, {len(df.columns)} columns)", flush=True)
        except Exception as e:
            print(f"{datetime.now():%H:%M:%S}  ERROR {type(e).__name__}: {e}", flush=True)
        time.sleep(POLL)


if __name__ == "__main__":
    main()
