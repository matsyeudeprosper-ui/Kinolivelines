"""Full-context record of every closed trade.

Captures the state of the market at the moment of entry, so that later - when
there are enough trades to mean anything - the question "what did the winners
have in common?" can be answered with data instead of recollection.

Reconstructs everything from MT5 history rather than hooking the entry moment,
which means (a) no state to keep between open and close, and (b) it can backfill
trades that already happened.

  python trade_journal.py            update the journal with any new closed trades
  python trade_journal.py --rebuild  rebuild from scratch

DELIBERATELY NOT FED TO THE MODEL YET. With a handful of trades, patterns are
noise, and a decider shown "winners were long in an H1 uptrend" after 3 wins
will learn superstition. This accumulates until the sample is worth something.
"""
import MetaTrader5 as mt5
import pandas as pd, numpy as np, os, sys, csv
from datetime import datetime, timedelta

HERE     = os.path.dirname(os.path.abspath(__file__))
JOURNAL  = os.path.join(HERE, "trades_journal.csv")
TERMINAL = r"C:\Program Files\MetaTrader 5\terminal64.exe"
LOGIN    = 436771046
SYM      = "BTCUSDm"
REBUILD  = "--rebuild" in sys.argv


def bars(tf, n=20000):
    for k in (n, 10000, 5000):
        r = mt5.copy_rates_from_pos(SYM, tf, 0, k)
        if r is not None and len(r):
            d = pd.DataFrame(r)
            d["time"] = pd.to_datetime(d["time"], unit="s")
            return d.sort_values("time").reset_index(drop=True)
    return None


def atr(d, n=14):
    pc = d["close"].shift(1)
    tr = pd.concat([d["high"] - d["low"], (d["high"] - pc).abs(),
                    (d["low"] - pc).abs()], axis=1).max(axis=1)
    return tr.rolling(n).mean()


def state_at(d, t, label):
    """Trend state of one timeframe as of time t, using only CLOSED bars."""
    past = d[d["time"] + pd.Timedelta(minutes=TF_MIN[label]) <= t]
    if len(past) < 25:
        return {}
    px = past["close"]
    ema21 = px.ewm(span=21).mean().iloc[-1]
    ema8  = px.ewm(span=8).mean().iloc[-1]
    c = px.iloc[-1]
    hh = past["high"].iloc[-1] > past["high"].iloc[-2]
    ll = past["low"].iloc[-1] < past["low"].iloc[-2]
    struct = "HH_HL" if (hh and not ll) else ("LH_LL" if (ll and not hh) else "mixed")
    don_hi = past["high"].iloc[-21:-1].max()
    don_lo = past["low"].iloc[-21:-1].min()
    a = atr(past).iloc[-1]
    return {
        f"{label}_close":      round(float(c), 2),
        f"{label}_atr":        round(float(a), 1) if np.isfinite(a) else None,
        f"{label}_vs_ema21":   "above" if c > ema21 else "below",
        f"{label}_ema_cross":  "bull" if ema8 > ema21 else "bear",
        f"{label}_structure":  struct,
        f"{label}_slope5":     round(float(px.iloc[-1] - px.iloc[-6]), 1) if len(px) > 6 else None,
        f"{label}_donchian":   "breakout_up" if c >= don_hi else ("breakout_dn" if c <= don_lo else "inside"),
        f"{label}_pct_of_range": round(float((c - don_lo) / (don_hi - don_lo) * 100), 1)
                                 if don_hi > don_lo else None,
    }


TF_MIN = {"M1": 1, "M5": 5, "M15": 15, "H1": 60, "H4": 240}

mt5.initialize(path=TERMINAL)
acc = mt5.account_info()
if acc.login != LOGIN:
    mt5.shutdown(); raise SystemExit(f"wrong account {acc.login}")
si = mt5.symbol_info(SYM)

frames = {k: bars(getattr(mt5, f"TIMEFRAME_{k}")) for k in TF_MIN}

# --- collect closed round trips from deal history ---
deals = mt5.history_deals_get(datetime.now() - timedelta(days=30), datetime.now() + timedelta(hours=6))
by_pos = {}
for d in (deals or []):
    if d.symbol != SYM or d.type > 1:
        continue
    by_pos.setdefault(d.position_id, []).append(d)

done = set()
if os.path.exists(JOURNAL) and not REBUILD:
    with open(JOURNAL, encoding="utf-8") as f:
        done = {int(r["position_id"]) for r in csv.DictReader(f)}

rows = []
for pid, ds in sorted(by_pos.items()):
    if pid in done:
        continue
    ds.sort(key=lambda x: x.time)
    ins  = [x for x in ds if x.entry == 0]
    outs = [x for x in ds if x.entry == 1]
    if not ins or not outs:
        continue                      # still open
    e, x = ins[0], outs[-1]
    t_in  = pd.to_datetime(e.time, unit="s")
    t_out = pd.to_datetime(x.time, unit="s")
    is_buy = (e.type == 0)
    pnl = sum(o.profit for o in outs)
    move = (x.price - e.price) if is_buy else (e.price - x.price)
    dur_s = (t_out - t_in).total_seconds()

    m1 = frames["M1"]
    win = m1[(m1["time"] >= t_in) & (m1["time"] <= t_out)]
    if len(win):
        mfe = (win["high"].max() - e.price) if is_buy else (e.price - win["low"].min())
        mae = (e.price - win["low"].min()) if is_buy else (win["high"].max() - e.price)
    else:
        mfe = mae = np.nan

    entry_bar = m1[m1["time"] <= t_in].tail(1)
    if len(entry_bar):
        b = entry_bar.iloc[0]
        rng = b["high"] - b["low"]
        body = abs(b["close"] - b["open"])
        candle = {
            "entry_candle_dir":   "up" if b["close"] > b["open"] else "down",
            "entry_candle_range": round(float(rng), 1),
            "entry_body_pct":     round(float(body / rng * 100), 1) if rng > 0 else None,
            "entry_upper_wick_pct": round(float((b["high"] - max(b["close"], b["open"])) / rng * 100), 1) if rng > 0 else None,
            "entry_lower_wick_pct": round(float((min(b["close"], b["open"]) - b["low"]) / rng * 100), 1) if rng > 0 else None,
            "entry_tick_volume":  int(b["tick_volume"]),
            "entry_spread_pts":   int(b["spread"]),
        }
    else:
        candle = {}

    a15 = atr(frames["M15"])
    a15v = float(a15[frames["M15"]["time"] <= t_in].iloc[-1]) if len(a15) else np.nan

    # INSTRUMENTATION, NOT A TRADE.
    #
    # A commission-measurement exercise opened and closed positions immediately to
    # read the fee actually charged. Those rows are real MT5 positions and belong in
    # the history, but they are not decisions and must never enter a performance
    # statistic. On 2026-08-01 they nearly produced a wrong conclusion: 13 of the 33
    # "trades" in the current config were fee tests with 0.0 minutes duration, which
    # dragged the apparent win rate from 10% down to 6% and made the sample look four
    # standard errors worse than it was.
    #
    # They are tagged rather than dropped, because the fees they measured are the
    # reason they exist. Every analysis must filter on this column.
    cmt = ((e.comment or "") + " " + (x.comment or "")).lower()
    is_instr = ("fee test" in cmt or "fee" in cmt and "close" in cmt
                or getattr(e, "magic", 0) == 990909)

    row = {
        "position_id": pid,
        "instrumentation": is_instr,
        "opened": t_in.isoformat(), "closed": t_out.isoformat(),
        "duration_s": int(dur_s), "duration_min": round(dur_s / 60, 1),
        "side": "BUY" if is_buy else "SELL",
        "volume": e.volume,
        "entry": e.price, "exit": x.price,
        "pnl": round(pnl, 2), "won": pnl > 0,
        "move_pts": round(move, 1),
        "move_pct": round(move / e.price * 100, 4),
        "move_in_atr15": round(move / a15v, 2) if a15v and np.isfinite(a15v) else None,
        "velocity_pts_min": round(move / (dur_s / 60), 1) if dur_s > 0 else None,
        "mfe_pts": round(float(mfe), 1) if np.isfinite(mfe) else None,
        "mae_pts": round(float(mae), 1) if np.isfinite(mae) else None,
        "exit_reason": (x.comment or "").strip(),
        "hour": t_in.hour, "weekday": t_in.day_name(),
        "spread_at_entry": round(si.spread * si.point, 2),
        **candle,
    }
    for lbl in ("M5", "M15", "H1", "H4"):
        if frames[lbl] is not None:
            row.update(state_at(frames[lbl], t_in, lbl))
    # was the trade WITH or AGAINST each timeframe?
    for lbl in ("M5", "M15", "H1", "H4"):
        k = f"{lbl}_vs_ema21"
        if k in row:
            row[f"{lbl}_aligned"] = (row[k] == "above") == is_buy
    rows.append(row)

mt5.shutdown()

if not rows:
    print("no new closed trades")
else:
    df = pd.DataFrame(rows)
    if os.path.exists(JOURNAL) and not REBUILD:
        df = pd.concat([pd.read_csv(JOURNAL), df], ignore_index=True)
    df.to_csv(JOURNAL, index=False)
    print(f"journal: +{len(rows)} trade(s) -> {len(df)} total")

if os.path.exists(JOURNAL):
    j = pd.read_csv(JOURNAL)
    print(f"\n{len(j)} trades | {j.won.sum()} won | net {j.pnl.sum():+.2f}")
    pd.set_option("display.width", 220)
    print(j[["opened", "side", "entry", "exit", "pnl", "duration_min", "move_in_atr15",
             "H1_vs_ema21", "M15_structure", "H1_aligned", "exit_reason"]]
          .to_string(index=False))
    print("\nNOTE: too few trades to draw conclusions. This accumulates; do not")
    print("feed it to the decider until the sample is large enough to be real.")
