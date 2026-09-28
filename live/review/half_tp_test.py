"""Owner 2026-09-28: "replay Valere's trades to see what would have happened
if we took only half of the 0.8 TP" - i.e. a target at 0.4 x the risk.

Part 1 - the REAL positions of Valere's account (broker deal history on its
terminal, 36 positions since 14/09): for each, walk the M1 bars after the
entry and ask which came first, the stop or the half target (entry +/- 0.4 x
stop distance). A bar touching both counts as a loss (conservative). Wins
pay 0.4 x dist x lots minus the spread; losses keep their real amount.

Part 2 - the full 41.7-day replay (same harness as the other tests) with
B.RR = 0.4 against the deployed 0.8, plus 0.6 and 1.0 for context.

    python review/half_tp_test.py [spread]
"""
import bisect
import json
import os
import re
import sys
from collections import defaultdict
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
LIVE = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, LIVE)
_A = sys.argv[1:]
sys.argv = ["half_tp_test"]

import MetaTrader5 as mt5              # noqa: E402
import structure_bos_bot as B          # noqa: E402
B.say = lambda *a, **k: None

SPREAD = float(_A[0]) if _A else 7.0
TERM_VALERE = r"C:\NestTerminals\u224016179\terminal64.exe"
LOG = os.path.join(LIVE, "bos_bot_valere.log")
SYMBOL = "BTCUSD"
SINCE = datetime(2026, 9, 13, tzinfo=timezone.utc)
HALF = 0.5   # of the 0.8 R target


# ---------------------------------------------------------------- part 1
def real_positions():
    entries = []
    for line in open(LOG, encoding="utf-8", errors="replace"):
        m = re.match(r'^(\S+) ([A-Z-]+) ENTRY: (BUY|SELL) ([\d.]+) @ ~([\d.]+) SL ([\d.]+) TP ([\d.]+)', line)
        if m:
            entries.append({"t": datetime.fromisoformat(m.group(1)).timestamp(), "kind": m.group(2),
                            "sl": float(m.group(6)), "tp": float(m.group(7))})
    if not mt5.initialize(path=TERM_VALERE):
        raise SystemExit("MT5 (Valere terminal): " + str(mt5.last_error()))
    now = datetime.now(timezone.utc)
    deals = mt5.history_deals_get(SINCE, now) or []
    pos = defaultdict(lambda: {"in": None, "out": None, "p": 0.0, "lots": 0.0, "dir": None, "e": None})
    for d in deals:
        if d.symbol != SYMBOL:
            continue
        P = pos[d.position_id]
        if d.entry == 0:
            if P["in"] is None or d.time < P["in"]:
                P["in"] = d.time; P["e"] = d.price; P["dir"] = 1 if d.type == 0 else -1
            P["lots"] += d.volume
        else:
            P["out"] = max(P["out"] or 0, d.time)
        P["p"] += d.profit + d.swap + d.commission
    mt5.symbol_select(SYMBOL, True)
    R = mt5.copy_rates_range(SYMBOL, mt5.TIMEFRAME_M1, SINCE, now)
    mt5.shutdown()
    times = [int(r["time"]) for r in R]
    out = []
    for P in pos.values():
        if P["in"] is None or P["out"] is None:
            continue
        ent = min(entries, key=lambda e: abs(e["t"] - P["in"]))
        if abs(ent["t"] - P["in"]) > 120:              # a catch-up add: same SL as the main entry before it
            ent = max((e for e in entries if e["t"] <= P["in"]), key=lambda e: e["t"], default=ent)
        d, e, sl = P["dir"], P["e"], ent["sl"]
        dist = abs(e - sl)
        half_tp = e + d * (B.RR * HALF) * dist
        i = bisect.bisect_right(times, P["in"])
        res = None
        while i < len(R) and int(R[i]["time"]) <= P["out"] + 3600 * 12:
            h, l = float(R[i]["high"]), float(R[i]["low"])
            hit_sl = (l <= sl) if d == 1 else (h >= sl)
            hit_tp = (h >= half_tp) if d == 1 else (l <= half_tp)
            if hit_sl:
                res = "loss"; break
            if hit_tp:
                res = "win"; break
            i += 1
        if res is None:
            res = "win" if P["p"] > 0 else "loss"    # never resolved in the window: keep the real outcome
        new_p = ((B.RR * HALF) * dist - SPREAD) * P["lots"] if res == "win" else P["p"]
        out.append({"t": P["in"], "real": P["p"], "half": new_p, "res": res, "lots": P["lots"], "dist": dist})
    out.sort(key=lambda x: x["t"])
    return out


def part1():
    rows = real_positions()
    real = sum(r["real"] for r in rows); half = sum(r["half"] for r in rows)
    rw = sum(1 for r in rows if r["real"] > 0); hw = sum(1 for r in rows if r["res"] == "win")
    print(f"PART 1 - Valere's real positions since 14/09: {len(rows)}")
    print(f"  as traded (TP 0.8 R)   : {rw} wins / {len(rows)-rw} losses, net {real:+.2f}")
    print(f"  half target (TP 0.4 R) : {hw} wins / {len(rows)-hw} losses, net {half:+.2f}   ({half-real:+.2f})")
    flipped = [r for r in rows if r["real"] <= 0 and r["res"] == "win"]
    print(f"  losses that would have become wins at the half target: {len(flipped)}"
          + (" -> " + ", ".join(f"{datetime.fromtimestamp(r['t'], timezone.utc):%d/%m %H:%M} ({r['real']:+.2f} -> {r['half']:+.2f})" for r in flipped) if flipped else ""))
    print("\n  date (UTC)     lots   dist   real     half   result@half")
    for r in rows:
        print(f"  {datetime.fromtimestamp(r['t'], timezone.utc):%d/%m %H:%M}  {r['lots']:.2f}  {r['dist']:5.0f}  {r['real']:+7.2f}  {r['half']:+7.2f}   {r['res']}")


# ---------------------------------------------------------------- part 2
LOT = 0.02
BLOT = 0.01
NB = 3.0
K = 2
N_CONT = 1


def bars(n=60000):
    u = next(x for x in json.load(open(os.path.join(LIVE, "owl_nest_users.json"), encoding="utf-8")) if x["id"] == "std")
    if not mt5.initialize(path=u["terminal"]):
        raise SystemExit(f"MT5: {mt5.last_error()}")
    sym = "BTCUSD" if mt5.symbol_info("BTCUSD") else "BTCUSDm"
    R = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_M1, 0, n)
    mt5.shutdown()
    return sym, R


def simulate(R, spread, rr):
    eng = B.Struct(); eng.quiet = True
    rng = [float(r["high"]) - float(r["low"]) for r in R]
    flips, marks = [], []
    prev = 0; used_hi = used_lo = None; pos = None
    run = pk = 0.0; streak = 0; curve = []; day_key = None
    last_flip_t = None; cont_left = 0; n_trades = wins = 0
    for i, bar in enumerate(R):
        t = int(bar["time"])
        o, h, l, c = (float(bar["open"]), float(bar["high"]), float(bar["low"]), float(bar["close"]))
        dk = datetime.fromtimestamp(t, tz=timezone.utc).strftime("%Y-%m-%d")
        if dk != day_key:
            day_key = dk; curve.append(run)
        if pos:
            d, e, sl, tp, dist, mid, hit_mid = pos
            if not hit_mid and ((l <= mid) if d == 1 else (h >= mid)):
                hit_mid = True; pos = (d, e, sl, tp, dist, mid, hit_mid)
            hit_sl = (l <= sl) if d == 1 else (h >= sl)
            hit_tp = (h >= tp) if d == 1 else (l <= tp)
            if hit_sl or hit_tp:
                win = bool(hit_tp and not hit_sl)
                pts = (rr * dist - spread) if win else -(dist + spread)
                debt = max(0.0, pk - run)
                run += pts * LOT
                fire = debt > 0.5 and streak < K
                if fire and hit_mid:
                    bpts = ((1.3 * dist - spread) if win else -(dist / 2.0 + spread))
                    run += bpts * BLOT * NB
                streak = 0 if win else streak + 1
                wins += 1 if win else 0
                pk = max(pk, run); pos = None
        touched = False
        if eng.trend == 1 and eng.prot_lo is not None:
            touched = l <= eng.prot_lo[1] <= c
        elif eng.trend == -1 and eng.prot_hi is not None:
            touched = c <= eng.prot_hi[1] <= h
        sig = eng.step(t, o, h, l, c)
        if eng.trend != prev and eng.trend != 0:
            flips.append(t); prev = eng.trend
        if sig is not None:
            marks.append(t)
        if touched and last_flip_t is not None and cont_left < N_CONT:
            cont_left = min(N_CONT, cont_left + 1)
        if sig is None or pos:
            continue
        if not any(f > t - B.AWAKE_WIN for f in flips):
            continue
        d, slp = sig
        flip = bool(flips) and flips[-1] == t
        if not flip:
            lvl = eng.hi_v if d == 1 else eng.lo_v
            if (d == 1 and used_hi == lvl) or (d == -1 and used_lo == lvl):
                continue
            if d == 1:
                used_hi = lvl
            else:
                used_lo = lvl
        if i >= 1440:
            nv = (sorted(rng[i-60:i])[30] / max(sorted(rng[i-1440:i])[720], 1e-9))
            mv2 = (bisect.bisect_left(marks, t) - bisect.bisect_left(marks, t - 7200))
            if nv >= B.NERV_STORM or mv2 < 1:
                continue
        debt_now = max(0.0, pk - run)
        if flip:
            last_flip_t = t; cont_left = N_CONT
        elif debt_now > 0.5:
            if cont_left > 0 and last_flip_t is not None:
                cont_left -= 1
            else:
                continue
        dist = abs(c - slp)
        if dist <= B.S_MIN_DIST or dist * LOT > B.MAX_RISK_PCT * 230.0:
            continue
        tp = c + d * rr * dist
        pos = (d, c, float(slp), tp, dist, c - d * dist / 2.0, False)
        n_trades += 1
    dd = pk2 = worst = 0.0
    for v in curve:
        pk2 = max(pk2, v); dd = min(dd, v - pk2); worst = max(worst, pk2 - v)
    return dict(net=run, maxdd=dd, worst_debt=worst, trades=n_trades, wr=(wins / n_trades * 100 if n_trades else 0.0))


def run_for(R, label):
    print(f"\n  {label}  {len(R)/1440:.1f} days, spread {SPREAD:.0f}")
    print(f"  {'target':<26}{'trades':>7}{'win%':>7}{'net $':>9}{'max DD':>9}{'worst debt':>11}")
    base = None
    for rr in (0.8, 0.4, 0.6, 1.0):
        r = simulate(R, SPREAD, rr)
        if base is None:
            base = r
        lab = ("A  deployed TP 0.8 R" if rr == 0.8 else f"B  TP {rr} R" + ("  (half)" if rr == 0.4 else ""))
        print(f"  {lab:<26}{r['trades']:>7}{r['wr']:>6.1f}%{r['net']:>9.2f}{r['maxdd']:>9.2f}{r['worst_debt']:>11.2f}"
              + ("" if rr == 0.8 else f"   ({r['net']-base['net']:+.2f} net, {r['worst_debt']-base['worst_debt']:+.2f} worst debt vs A)"))


def main():
    part1()
    print("\nPART 2 - full replay, target as a fraction of the risk")
    sym, R = bars()
    run_for(R, f"{sym} FULL PERIOD")
    print("\n  HALVES (each independently)")
    mid = len(R) // 2
    run_for(R[:mid], "FIRST HALF")
    run_for(R[mid:], "SECOND HALF")
    print()


if __name__ == "__main__":
    main()
