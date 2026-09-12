"""FORWARD OBSERVATION LEDGER for the BOS bot (2026-09-11, user request).

Informational only - nothing here touches trading. Every 30 s it rebuilds
`bos_forward_ledger.csv`, one row per closed or open trade since the
candle-close era started (2026-09-11 17:26 UTC), for two sources:

  live  = real account 223995441, from MT5 deal history (position_id
          join, magic 909101), entry kind from bos_bot.log, BASE trades
          only (KL-BOS-ADD deals are listed as kind ADD and excluded
          from the shadow sequence)
  twin  = bos_paper_touch_state.json (the flip+touch paper twin)

Per trade it records the two forward-observation variables the regime
pass left open (Owl/study/regime/REGIME.md):
  A. narrow_stop  = stop distance <= 98 points (train q25). Not acted on.
  B. shadow_state = NORMAL / REDUCED / PAUSED before the trade, from the
     rolling-20 sum of the source's own previous trades normalised to
     0.02 lot, thresholds frozen from the research train half:
     REDUCED below -15.65, PAUSED below -22.51, NORMAL again at/above
     +8.14. Seeded with the tick-backtest trades of the same rule set up
     to the switch (bos_shadow_seed.json) so the state is defined from
     the first forward trade. Not acted on.
"""
import csv
import datetime as dt
import json
import os
import re
import sys
import time

import MetaTrader5 as mt5

DIR = os.path.dirname(os.path.abspath(__file__))
LEDGER = os.path.join(DIR, "bos_forward_ledger.csv")
STATE = os.path.join(DIR, "bos_forward_observer.json")
LOG = os.path.join(DIR, "bos_forward_observer.log")
SEED = os.path.join(DIR, "bos_shadow_seed.json")
BOT_LOG = os.path.join(DIR, "bos_bot.log")
TWIN_STATE = os.path.join(DIR, "bos_paper_touch_state.json")
ERA_START = dt.datetime(2026, 9, 11, 17, 26, tzinfo=dt.timezone.utc)
TERMINAL = r"C:\NestTerminals\u223995441\terminal64.exe"
LOGIN = 223995441
SERVER = "Exness-MT5Real30"
MAGIC = 909101
NARROW_PTS = 98.0
N = 20
P10, P5, P50 = -15.65, -22.51, 8.14
BASE_LOT = 0.02
utc = dt.timezone.utc


def say(msg):
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(f"{dt.datetime.now(utc).isoformat()} {msg}\n")


def shadow_states(seed_pnls, trades):
    """trades: list of dicts with 'pnl_002' (None if open), chronological.
    Returns list of (state_before, rolling_sum_before)."""
    hist = list(seed_pnls)
    state = "NORMAL"
    outp = []
    for tr in trades:
        s = sum(hist[-N:]) if len(hist) >= N else None
        if s is not None:
            if state == "NORMAL":
                if s < P5:
                    state = "PAUSED"
                elif s < P10:
                    state = "REDUCED"
            elif state == "REDUCED":
                if s < P5:
                    state = "PAUSED"
                elif s >= P50:
                    state = "NORMAL"
            elif state == "PAUSED":
                if s >= P50:
                    state = "NORMAL"
                elif s >= P10:
                    state = "REDUCED"
        outp.append((state, s))
        if tr["pnl_002"] is not None:
            hist.append(tr["pnl_002"])
    return outp


PAT = re.compile(r"^(\S+) (FLIP-BOS|TOUCH|BOS) ENTRY: (BUY|SELL) ([\d.]+) @ ~([\d.]+) SL ([\d.]+) TP ([\d.]+)")


def log_entries():
    out = []
    try:
        for line in open(BOT_LOG, encoding="utf-8", errors="replace"):
            m = PAT.match(line.strip())
            if m:
                out.append((dt.datetime.fromisoformat(m[1]), m[2], float(m[5]), float(m[6]), float(m[7])))
    except FileNotFoundError:
        pass
    return out


def live_trades():
    deals = mt5.history_deals_get(ERA_START - dt.timedelta(hours=6), dt.datetime.now(utc) + dt.timedelta(days=1))
    if deals is None:
        return []
    pos = {}
    for d in deals:
        if d.magic != MAGIC:
            continue
        p = pos.setdefault(d.position_id, {})
        if d.entry == mt5.DEAL_ENTRY_IN:
            p["in"] = d
        else:
            p["out"] = d
    open_pos = {p.ticket: p for p in (mt5.positions_get() or []) if p.magic == MAGIC}
    ents = log_entries()
    rows = []
    for pid, p in pos.items():
        i = p.get("in")
        if i is None:
            continue
        ti = dt.datetime.fromtimestamp(i.time, utc)
        if ti < ERA_START:
            continue
        direction = "BUY" if i.type == mt5.DEAL_TYPE_BUY else "SELL"
        kind, sl, tp = "ADD" if i.comment.endswith("-ADD") else "UNMATCHED", None, None
        if kind != "ADD" and ents:
            best = min(ents, key=lambda e: abs((e[0] - ti).total_seconds()))
            if abs((best[0] - ti).total_seconds()) <= 60:
                kind, sl, tp = best[1], best[3], best[4]
        if sl is None and pid in open_pos:
            sl, tp = open_pos[pid].sl, open_pos[pid].tp
        if sl is None and p.get("out") is not None:
            m2 = re.search(r"\[(sl|tp) ([\d.]+)\]", p["out"].comment or "")
            if m2 and m2[1] == "sl":
                sl = float(m2[2])
        dist = abs(i.price - sl) if sl else None
        o = p.get("out")
        r = dict(source="live", era="candleclose", id=str(pid), open_time=ti.isoformat(timespec="seconds"),
                 kind=kind, dir=direction, lot=i.volume, entry=round(i.price, 2),
                 sl=round(sl, 2) if sl else "", tp=round(tp, 2) if tp else "",
                 stop_dist=round(dist, 2) if dist else "",
                 narrow_stop=(1 if (dist is not None and dist <= NARROW_PTS) else 0) if dist is not None else "",
                 close_time="", exit="", pnl="", pnl_002=None, t=ti.timestamp())
        if o is not None:
            net = o.profit + o.commission + o.swap
            r.update(close_time=dt.datetime.fromtimestamp(o.time, utc).isoformat(timespec="seconds"),
                     exit=round(o.price, 2), pnl=round(net, 2),
                     pnl_002=round(net / i.volume * BASE_LOT, 4) if kind != "ADD" else None)
        rows.append(r)
    rows.sort(key=lambda r: r["t"])
    return rows


def twin_trades():
    try:
        st = json.load(open(TWIN_STATE, encoding="utf-8"))
    except Exception:
        return []
    rows = []
    for k, x in enumerate(st.get("trades", [])):
        to = dt.datetime.fromtimestamp(x["t_open"], utc)
        if to < ERA_START:
            continue
        dist = abs(x["e"] - x["sl"])
        rows.append(dict(source="twin", era="candleclose", id=f"twin{k}", open_time=to.isoformat(timespec="seconds"),
                         kind=x["kind"], dir="BUY" if x["d"] == 1 else "SELL", lot=BASE_LOT, entry=round(x["e"], 2),
                         sl=x["sl"], tp=x["tp"], stop_dist=round(dist, 2), narrow_stop=1 if dist <= NARROW_PTS else 0,
                         close_time=dt.datetime.fromtimestamp(x["t_close"], utc).isoformat(timespec="seconds"),
                         exit=round(x["x"], 2), pnl=x["pnl"], pnl_002=x["pnl"], t=x["t_open"]))
    p = st.get("pos")
    if p:
        to = dt.datetime.fromtimestamp(p["t"], utc)
        dist = abs(p["e"] - p["sl"])
        rows.append(dict(source="twin", era="candleclose", id="twin_open", open_time=to.isoformat(timespec="seconds"),
                         kind=p["kind"], dir="BUY" if p["d"] == 1 else "SELL", lot=BASE_LOT, entry=round(p["e"], 2),
                         sl=p["sl"], tp=p["tp"], stop_dist=round(dist, 2), narrow_stop=1 if dist <= NARROW_PTS else 0,
                         close_time="", exit="", pnl="", pnl_002=None, t=p["t"]))
    rows.sort(key=lambda r: r["t"])
    return rows


COLS = ["source", "era", "id", "open_time", "kind", "dir", "lot", "entry", "sl", "tp", "stop_dist", "narrow_stop",
        "shadow_state_before", "rolling20_before", "close_time", "exit", "pnl", "pnl_002"]


def cycle(seed):
    live = live_trades()
    twin = twin_trades()
    base_live = [r for r in live if r["kind"] != "ADD"]
    st_live = shadow_states(seed["candleclose"], base_live)
    st_twin = shadow_states(seed["fliptouch"], twin)
    for r, (s, v) in zip(base_live, st_live):
        r["shadow_state_before"], r["rolling20_before"] = s, ("" if v is None else round(v, 2))
    for r in live:
        if r["kind"] == "ADD":
            r["shadow_state_before"], r["rolling20_before"] = "", ""
    for r, (s, v) in zip(twin, st_twin):
        r["shadow_state_before"], r["rolling20_before"] = s, ("" if v is None else round(v, 2))
    rows = sorted(live + twin, key=lambda r: r["t"])
    tmp = LEDGER + ".tmp"
    with open(tmp, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLS, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            rr = dict(r)
            rr["pnl_002"] = "" if rr["pnl_002"] is None else rr["pnl_002"]
            w.writerow(rr)
    os.replace(tmp, LEDGER)
    cur_live = st_live[-1][0] if st_live else "NORMAL"
    cur_twin = st_twin[-1][0] if st_twin else "NORMAL"
    # current state AFTER the last closed trade (what the next entry would see)
    nxt_live = shadow_states(seed["candleclose"], base_live + [dict(pnl_002=None)])[-1]
    nxt_twin = shadow_states(seed["fliptouch"], twin + [dict(pnl_002=None)])[-1]
    summary = dict(updated=dt.datetime.now(utc).isoformat(timespec="seconds"),
                   live=dict(trades=len(base_live), adds=len(live) - len(base_live),
                             net=round(sum(r["pnl"] for r in live if r["pnl"] != ""), 2),
                             net_002=round(sum(r["pnl_002"] for r in base_live if r["pnl_002"] is not None), 2),
                             narrow=sum(1 for r in base_live if r["narrow_stop"] == 1),
                             next_state=nxt_live[0], rolling20=nxt_live[1]),
                   twin=dict(trades=len(twin), net=round(sum(r["pnl"] for r in twin if r["pnl"] != ""), 2),
                             narrow=sum(1 for r in twin if r["narrow_stop"] == 1),
                             next_state=nxt_twin[0], rolling20=nxt_twin[1]))
    json.dump(summary, open(STATE, "w"), indent=1)
    return summary


def main():
    pwd = json.load(open(os.path.join(DIR, "owl_secrets.json"), encoding="utf-8"))["mt5_password"]
    assert mt5.initialize(path=TERMINAL, login=LOGIN, password=pwd, server=SERVER, timeout=60000), "MT5 init failed"
    seed = json.load(open(SEED, encoding="utf-8"))
    seed = {k: [x["pnl"] for x in v] for k, v in seed.items()}
    say(f"forward observer starting; seed candleclose {len(seed['candleclose'])} / fliptouch {len(seed['fliptouch'])}; "
        f"thresholds N={N} p10 {P10} p5 {P5} p50 {P50}; narrow <= {NARROW_PTS}")
    last = None
    once = "--once" in sys.argv
    while True:
        try:
            s = cycle(seed)
            key = (s["live"]["trades"], s["live"]["net"], s["twin"]["trades"], s["twin"]["net"])
            if key != last:
                say(f"live {s['live']['trades']} trades net {s['live']['net']:+.2f} (0.02-norm {s['live']['net_002']:+.2f}) "
                    f"narrow {s['live']['narrow']} next-state {s['live']['next_state']} r20 {s['live']['rolling20']} | "
                    f"twin {s['twin']['trades']} trades net {s['twin']['net']:+.2f} narrow {s['twin']['narrow']} "
                    f"next-state {s['twin']['next_state']} r20 {s['twin']['rolling20']}")
                last = key
        except Exception as e:
            say(f"ERROR {type(e).__name__}: {e}")
        if once:
            break
        time.sleep(30)


if __name__ == "__main__":
    main()
