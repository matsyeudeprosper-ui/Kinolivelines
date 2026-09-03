"""PULLBACK-RETEST entry (user's idea, 2026-08-13) - first-pass measurement,
NOT yet a preregistered/validated spec. Same harness as renko_clean.py
(bricks, TP, recovery, cap - all byte-identical, already invariant-checked
there) with only the entry SIGNAL swapped.

Rule (user's own words): "buy when price pulled back at least 1 brick, then
return to hit the last high. for sell, mirror."

Implementation: same renko walk as renko_clean (price-scaled 50-pt-equivalent
brick, reversal=2). A swing HIGH is the last brick close of an up-run,
confirmed the instant the down-reversal brick prints - which by construction
has already pulled back >=2 bricks (REV=2) from that high, satisfying "at
least 1, could be more" for free. From confirmation on, watch every bar's
intrabar high; the FIRST time price touches back up to that swing high ->
BUY signal on that bar (consumed - won't refire until a fresh swing high
forms and gets retested again). Swing LOW is the mirror, fires SELL when
price returns down to touch it.

This is NOT the same as SPEC_HHLL_RENKO (a FILTER that gates whether to take
that day's reversal-brick trade) or MEASURE_BOS_RETRACE (measured raw
continuation-after-break statistics). This is a standalone entry trigger
that generally fires on DIFFERENT bars than the native reversal signal -
usually several bars after the reversal that created the swing, once price
has round-tripped back to it.
"""
import numpy as np
import MetaTrader5 as mt5
from datetime import datetime

PCT, SPCT = 50.0 / 64000.0, 10.0 / 64000.0
REV, TPB, SLB, CAP, PT, START = 2, 5, 3, 4, 0.01, 1000.0
FROM = datetime(2022, 1, 1)

mt5.initialize(path=r"C:\Program Files\MetaTrader 5\terminal64.exe")
r = mt5.copy_rates_from_pos("BTCUSDm", mt5.TIMEFRAME_H1, 0, 80000)
mt5.shutdown()
keep = r["time"] >= FROM.timestamp()
r = r[keep]
o, h, l, c = (r[k].astype(float) for k in ("open", "high", "low", "close"))
tm = r["time"]; N = len(c)
ym = np.array([datetime.utcfromtimestamp(t).strftime("%Y-%m") for t in tm])
yr = np.array([datetime.utcfromtimestamp(t).strftime("%Y") for t in tm])
span = (tm[-1] - tm[0]) / 86400 / 365
print(f"bars {N}   {datetime.utcfromtimestamp(tm[0]):%Y-%m-%d} -> "
      f"{datetime.utcfromtimestamp(tm[-1]):%Y-%m-%d}   ({span:.1f} years)")


def signals_reversal():
    """A0 - the live bot's actual signal: every reversal brick."""
    revs = {}; ao = ac = float(o[0]); d = 0; pd_ = 0
    for i in range(N):
        B = c[i] * PCT
        while True:
            up = (ao if d == -1 else ac) + B * (REV if d == -1 else 1)
            dn = (ao if d == 1 else ac) - B * (REV if d == 1 else 1)
            if c[i] >= up:
                base = ao if d == -1 else ac; ao, ac, d = base, base + B, 1
            elif c[i] <= dn:
                base = ao if d == 1 else ac; ao, ac, d = base, base - B, -1
            else:
                break
            if pd_ and d != pd_:
                revs.setdefault(i, d)
            pd_ = d
    return revs


def signals_pullback_retest():
    """F - the new idea: swing high/low confirmed, then wait for the retest."""
    sigs = {}; ao = ac = float(o[0]); d = 0
    last_high = None; last_low = None
    for i in range(N):
        B = c[i] * PCT
        while True:
            up = (ao if d == -1 else ac) + B * (REV if d == -1 else 1)
            dn = (ao if d == 1 else ac) - B * (REV if d == 1 else 1)
            if c[i] >= up:
                if d == -1:
                    last_low = ac      # down-run just ended: confirm swing low
                base = ao if d == -1 else ac; ao, ac, d = base, base + B, 1
            elif c[i] <= dn:
                if d == 1:
                    last_high = ac     # up-run just ended: confirm swing high
                base = ao if d == 1 else ac; ao, ac, d = base, base - B, -1
            else:
                break
        if last_high is not None and h[i] >= last_high:
            sigs.setdefault(i, 1); last_high = None
        if last_low is not None and l[i] <= last_low:
            sigs.setdefault(i, -1); last_low = None
    return sigs


def signals_random(n_target, seed):
    """R - rate-matched random control: n_target signals at uniform random
    bars, alternating direction has no meaning here since run() treats each
    signal's direction independently; assign direction by coin flip."""
    rng = np.random.default_rng(seed)
    idx = rng.choice(N - 1, size=min(n_target, N - 1), replace=False)
    dirs = rng.choice([1, -1], size=len(idx))
    return dict(zip(idx.tolist(), dirs.tolist()))


def run(REVS, cap=CAP):
    bal = START; cyc = START
    ent = np.empty(0); lng = np.empty(0, dtype=bool); tpp = np.empty(0); slv = np.empty(0)
    rec = False; in_cycle = False; pending = None
    peak = START; mdd = 0.0; mddp = 0.0; lo = START; eq = START
    opened = skipped = pend_at_end = 0
    tpwins = 0; maxbask = 0; basket_bars = 0
    by_exit = {"tp": [], "recovered": [], "forced": []}
    bask_start = None; bask_lens = []
    eq_month = {}; eq_year = {}; dead = None
    for j in range(N):
        B = c[j] * PCT; SP = c[j] * SPCT
        if pending is not None:
            L, a, b = pending
            if len(ent) == 0:
                bask_start = j; in_cycle = True
            ent = np.append(ent, o[j] + SP if L else o[j]); lng = np.append(lng, L)
            tpp = np.append(tpp, a); slv = np.append(slv, b)
            opened += 1; maxbask = max(maxbask, len(ent)); pending = None
        if j in REVS and j + 1 < N:
            if len(ent) == 0 or (rec and len(ent) <= cap):
                pending = ((REVS[j] == 1), B * TPB, B * SLB)
            else:
                skipped += 1
        if len(ent):
            basket_bars += 1
            hit = np.where(lng, h[j] >= ent + tpp, l[j] <= ent - tpp - SP)
            if hit.any():
                bal += float(np.sum(tpp[hit])) * PT
                tpwins += int(hit.sum())
                ent, lng, tpp, slv = ent[~hit], lng[~hit], tpp[~hit], slv[~hit]
        if len(ent) and not rec:
            if np.where(lng, l[j] <= ent - slv, h[j] >= ent + slv + SP).any():
                rec = True
        flo = float(np.sum(np.where(lng, c[j] - ent, ent - c[j] - SP)) * PT) if len(ent) else 0.0
        eq = bal + flo
        closed = None
        if rec and len(ent) and eq >= cyc:
            closed = "recovered"
        elif len(ent) > cap:
            closed = "forced"
        if closed:
            by_exit[closed].append(eq - cyc); in_cycle = False; bal = eq
            ent = np.empty(0); lng = np.empty(0, dtype=bool)
            tpp = np.empty(0); slv = np.empty(0); eq = bal
            if bask_start is not None:
                bask_lens.append(j - bask_start); bask_start = None
        if len(ent) == 0:
            if in_cycle and closed is None:
                by_exit["tp"].append(bal - cyc); in_cycle = False
                if bask_start is not None:
                    bask_lens.append(j - bask_start); bask_start = None
            rec = False
            cyc = bal
        peak = max(peak, eq); mdd = max(mdd, peak - eq)
        mddp = max(mddp, (peak - eq) / peak * 100); lo = min(lo, eq)
        eq_month[ym[j]] = eq; eq_year[yr[j]] = eq
        if eq <= 0:
            dead = j; break
    if pending is not None:
        pend_at_end = 1
    unfillable = sum(1 for q in REVS if q + 1 >= N)
    stuck = len(ent)
    return dict(eq=eq, lo=lo, mdd=mdd, mddp=mddp, dead=dead, opened=opened,
                skipped=skipped, tpwins=tpwins, maxbask=maxbask, by_exit=by_exit,
                bask_lens=bask_lens, basket_bars=basket_bars,
                unfillable=unfillable, pend=pend_at_end, stuck=stuck,
                nsig=len(REVS))


def report(name, z):
    be = z["by_exit"]
    allc = np.array(be["tp"] + be["recovered"] + be["forced"]) if (be["tp"] or be["recovered"] or be["forced"]) else np.array([0.0])
    nc = len(allc)
    print(f"\n--- {name} ---")
    print(f"  signals {z['nsig']:>6}   opened {z['opened']:>6}   skipped {z['skipped']:>6}   "
          f"cycles {nc:>6}")
    print(f"  ended ${z['eq']:>9,.2f} ({100*(z['eq']/START-1):+.1f}%)   "
          f"lowest ${z['lo']:>8,.2f}   worst dd ${z['mdd']:>8,.2f} ({z['mddp']:.1f}%)")
    if z["dead"] is not None:
        print(f"  *** DIED bar {z['dead']} ({datetime.utcfromtimestamp(tm[z['dead']]):%Y-%m-%d}) ***")
    for k, nm in (("tp", "TP"), ("recovered", "recovered"), ("forced", "cap/forced")):
        v = be[k]
        print(f"  {nm:<10} {len(v):>5} ({100*len(v)/max(1,nc):>3.0f}%)  avg ${np.mean(v) if v else 0:>+7.2f}")
    print(f"  expectancy/cycle ${allc.mean():>+7.2f}   worst cycle ${allc.min():>+8.2f}")
    tot = z["opened"] + z["skipped"] + z["unfillable"] + z["pend"]
    ok = (tot == z["nsig"]) or z["dead"] is not None
    print(f"  invariant (opened+skipped+unfillable+pending==signals): {'OK' if ok else 'MISMATCH ' + str(tot) + ' vs ' + str(z['nsig'])}")
    return allc


print("\n" + "=" * 70)
print("A0 - live bot (every reversal brick)")
print("=" * 70)
zA = run(signals_reversal())
allA = report("A0 reversal", zA)

print("\n" + "=" * 70)
print("F - pullback >=1 brick then retest the last high/low")
print("=" * 70)
REVS_F = signals_pullback_retest()
zF = run(REVS_F)
allF = report("F pullback-retest", zF)

print("\n" + "=" * 70)
print("R - random control, rate-matched to F's signal count (3 seeds)")
print("=" * 70)
Rres = []
for seed in (0, 1, 2):
    zR = run(signals_random(len(REVS_F), seed))
    Rres.append(zR)
    report(f"R seed {seed}", zR)

eqR_mean = np.mean([z["eq"] for z in Rres])
print("\n" + "=" * 70)
print("SUMMARY")
print("=" * 70)
print(f"  A0 (all reversals, {zA['nsig']} signals):     ${zA['eq']:>9,.2f}")
print(f"  F  (pullback-retest, {zF['nsig']} signals):   ${zF['eq']:>9,.2f}")
print(f"  R  (random, matched count, avg of 3):    ${eqR_mean:>9,.2f}")
print(f"\n  F vs A0: {zF['eq']-zA['eq']:+,.2f}     F vs R: {zF['eq']-eqR_mean:+,.2f}")
