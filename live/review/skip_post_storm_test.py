import bisect, json, os, random, statistics as st, sys
HERE = os.path.dirname(os.path.abspath(__file__))
LIVE = os.path.dirname(HERE)
sys.path.insert(0, LIVE)
_A = sys.argv[1:]
sys.argv = ["skip_post_storm_test"]
import MetaTrader5 as mt5
import structure_bos_bot as B
B.say = lambda *a, **k: None
SP = float(_A[0]) if _A else 7.0
LOT = B.BASE_LOT

def bars(n=60000):
    u = next(x for x in json.load(open(os.path.join(LIVE, "owl_nest_users.json"), encoding="utf-8")) if x["id"] == "std")
    if not mt5.initialize(path=u["terminal"]):
        raise SystemExit(f"MT5: {mt5.last_error()}")
    sym = "BTCUSD" if mt5.symbol_info("BTCUSD") else "BTCUSDm"
    R = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_M1, 0, n)
    mt5.shutdown()
    return sym, R

def replay(R, spread, skip_rule):
    """skip_rule=True: the first signal after a storm ends is NOT taken -
    the slot stays free for the next ordinary signal, matching what
    deploying the rule would actually do (not just tagging)."""
    eng = B.Struct(); eng.quiet = True
    rng = [float(r["high"]) - float(r["low"]) for r in R]
    flips, marks, trades = [], [], []
    prev = 0
    used_hi = used_lo = None
    pos = None
    storm_seen = False
    for i, bar in enumerate(R):
        t = int(bar["time"])
        o, h, l, c = (float(bar["open"]), float(bar["high"]), float(bar["low"]), float(bar["close"]))
        if pos:
            d, e, sl, tp, dist, tag = pos
            hs = (l <= sl) if d == 1 else (h >= sl)
            ht = (h >= tp) if d == 1 else (l <= tp)
            if hs or ht:
                w = bool(ht and not hs)
                pts = (B.RR * dist - spread) if w else -(dist + spread)
                trades.append({"t": t, "R": pts / dist, "win": w,
                               "usd": pts * LOT, "post_storm": tag})
                pos = None
        sig = eng.step(t, o, h, l, c)
        if eng.trend != prev and eng.trend != 0:
            flips.append(t); prev = eng.trend
        if sig is not None:
            marks.append(t)
        nv = None
        if i >= 1440:
            nv = sorted(rng[i-60:i])[30] / max(sorted(rng[i-1440:i])[720], 1e-9)
            if nv >= B.NERV_STORM:
                storm_seen = True
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
            if d == 1: used_hi = lvl
            else: used_lo = lvl
        if nv is not None:
            mv2 = bisect.bisect_left(marks, t) - bisect.bisect_left(marks, t - 7200)
            if nv >= B.NERV_STORM or mv2 < 1:
                continue
        dist = abs(c - slp)
        if dist <= B.S_MIN_DIST or dist * LOT > B.MAX_RISK_PCT * 230.0:
            continue
        tag = storm_seen
        storm_seen = False
        if skip_rule and tag:
            continue           # the rule: do not open this one at all
        tp = c + d * B.RR * dist
        pos = (d, c, float(slp), tp, dist, tag)
    return trades

def summ(tr):
    if not tr:
        return dict(n=0, per=0.0, wr=0.0, usd=0.0)
    r = [x["R"] for x in tr]
    return dict(n=len(tr), per=sum(r)/len(r),
               wr=100*sum(1 for x in tr if x["win"])/len(tr),
               usd=sum(x["usd"] for x in tr))

def main():
    sym, R = bars()
    days = len(R)/1440
    print(f"\n  {sym}  {days:.1f} days, spread {SP:.0f}\n")
    print("  1. THE RULE DEPLOYED - total effect, not just the tagged group")
    ANCH, step = 6, 600
    print(f"  {'':<14}{'take everything':>20}{'skip post-storm':>20}{'diff':>10}")
    diffs = []
    for a in range(ANCH):
        sub = R[a*step:]
        if len(sub) < 20000: break
        off = summ(replay(sub, SP, False))
        on = summ(replay(sub, SP, True))
        d = on["usd"] - off["usd"]
        diffs.append(d)
        print(f"  anchor {a:<7}${off['usd']:>8.2f} ({off['n']:>3}t)"
              f"   ${on['usd']:>8.2f} ({on['n']:>3}t)   ${d:>+7.2f}")
    print(f"\n  the rule beats doing nothing on {sum(1 for d in diffs if d>0)}/{len(diffs)} anchors\n")

    base_off = replay(R, SP, False)
    base_on = replay(R, SP, True)
    print(f"  full window: take everything ${summ(base_off)['usd']:+.2f} ({summ(base_off)['n']} trades)"
          f"   vs   skip rule ${summ(base_on)['usd']:+.2f} ({summ(base_on)['n']} trades)")

    print("\n  2. SPREAD")
    for sp in (0.0, 7.0, 15.0):
        off = summ(replay(R, sp, False))
        on = summ(replay(R, sp, True))
        print(f"    spread {sp:>4.0f}   take-all ${off['usd']:>8.2f}   skip-rule ${on['usd']:>8.2f}   diff ${on['usd']-off['usd']:>+7.2f}")

    print("\n  3. IS THE TAG REAL, OR WOULD ANY 44-TRADE SLICE LOOK THIS BAD?")
    tagged = [x for x in base_off if x["post_storm"]]
    real_mean = sum(x["R"] for x in tagged) / len(tagged)
    pool = [x["R"] for x in base_off]
    random.seed(11)
    hits = 0
    sims = 4000
    for _ in range(sims):
        if sum(random.sample(pool, len(tagged))) / len(tagged) <= real_mean:
            hits += 1
    print(f"    real post-storm mean: {real_mean:+.3f} R  (n={len(tagged)})")
    print(f"    random {len(tagged)}-trade draws from the same {len(pool)}, "
          f"at least as bad: {hits}/{sims} -> p={hits/sims:.3f}")
    print(f"    verdict: {'genuinely worse, not just an unlucky slice' if hits/sims < 0.05 else 'INSIDE what a random slice produces'}")
    print()

if __name__ == "__main__":
    main()
