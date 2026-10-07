"""Forward logger (read-only, never trades): touches of the PULLBACK chart's
main levels, for the touch-rule forward test registered 2026-10-07.

Rule under test (owner): when price touches a main pullback-chart level
(next_bos, invalid = CHoCH level, flip_bos), the M1 bot trades only in that
direction until a level on the other side is touched.
Replay 1 Sep-7 Oct (study/pb_int_gate_fair.py): 119 of 204 trades, +104 vs
+154, worst drop -37 vs -98, but random-like in the 2nd half. Verdict after
~40 kept real trades: review/pb_touch_tracker.py. Do not retune.

Causal like the replay: the levels are frozen at the first read of each new
M1 bar (computed by the feed from closed bars only), then that bar's high/low
is watched against them. One row per level per bar, in pb_touch_events.csv.
"""
import csv, json, os, time
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
FEED = os.path.join(HERE, "owl_chart_btc.json")
OUT = os.path.join(HERE, "pb_touch_events.csv")
LOG = os.path.join(HERE, "pb_touch_logger.log")


def log(msg):
    with open(LOG, "a") as f:
        f.write(f"{datetime.now(timezone.utc).isoformat()} {msg}\n")


def main():
    new = not os.path.exists(OUT)
    f = open(OUT, "a", newline="")
    w = csv.writer(f)
    if new:
        w.writerow(["time_utc", "bar_t", "dir", "level_name", "level", "px_ref"])
        f.flush()
    log("start")
    bar_t, ref, done, last_ok = None, [], set(), 0
    while True:
        try:
            d = json.load(open(FEED))
            lv, pb = d.get("live"), d.get("pb") or {}
            if lv and pb:
                if lv[0] != bar_t:              # new bar: freeze levels now
                    bar_t, done = lv[0], set()
                    px = float(lv[1])           # the bar's open
                    ref = [(k, float(pb[k]), 1 if float(pb[k]) > px else -1, px)
                           for k in ("next_bos", "invalid", "flip_bos") if pb.get(k)]
                hi, lo = float(lv[2]), float(lv[3])
                for k, v, dr, px in ref:
                    if k in done:
                        continue
                    if (dr == 1 and hi >= v) or (dr == -1 and lo <= v):
                        w.writerow([datetime.now(timezone.utc).isoformat(), bar_t, dr, k, v, px])
                        f.flush(); done.add(k)
            if time.time() - last_ok > 3600:
                log(f"alive bar_t={bar_t} levels={len(ref)}"); last_ok = time.time()
        except Exception as e:
            log(f"ERROR {type(e).__name__}: {e}")
            time.sleep(5)
        time.sleep(1)


if __name__ == "__main__":
    main()
