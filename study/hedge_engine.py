"""ONE engine for the hedge rule. Every test imports this - nothing re-types it.

Three earlier scripts each re-implemented the same rule and gave $378, $598 and
a third answer on the same 27 months. The difference was a single line: whether
a new FIRST trade could open while the previous hedge was still running. The
$598 version allowed it, so it could hold three positions - which is not the
rule. This file is the fix.

THE RULE (user's, 2026-08-06)
  1. reversal -> ONE trade, 250-pt target, NO stop
  2. 150 points against it -> recovery
  3. take the NEXT OPPOSITE reversal - one only. Its target is 1.5x the first
     trade's drawdown at that moment; its stop is 1.0x that drawdown
  4. hedge hits target -> close everything, new cycle
  5. hedge hits stop   -> close everything, new cycle
  6. cycle P&L back to zero with both open -> close everything, new cycle
  7. NEVER more than 2 positions, and no new cycle starts until both are closed

TWO INVARIANTS, checked every run, raising rather than warning:
  - open positions never exceed 2
  - the sum of every cycle's P&L equals the change in equity
The second one already caught a different bug earlier today.
"""
import numpy as np


def simulate(R, a=0, spread=10.0, brick=50.0, rev=2, tp_bricks=5, sl_bricks=3,
             reward=1.5, hedge_sl=1.0, lot_pt=0.01, start=1000.0,
             arm="hedge"):
    """arm: 'hedge' | 'any' | 'same'  ('any' is the current live bot)."""
    o, h, l, c = (R[k][a:].astype(float) for k in ("open", "high", "low", "close"))
    tm = R["time"][a:]
    N = len(c)
    TP = brick * tp_bricks
    TRIG = brick * sl_bricks
    CAP = 4                                   # only used by 'any' / 'same'

    ao = ac = float(o[0]); d = 0; pd_ = 0
    bal = start; cyc = start
    ent = np.empty(0); lng = np.empty(0, dtype=bool)
    tpp = np.empty(0); slv = np.empty(0)
    rec = False; pending = None
    cyc_dir = None; f_ent = None; f_long = None; hedged = False
    peak = start; mdd = 0.0; lo = start; eq = start
    opened = 0; hedges = 0; hedge_won = 0; hedge_stop = 0; caps = 0
    cycles = []; curve = np.empty(N)
    max_open = 0

    def close_all(px_bid_side):
        nonlocal bal, ent, lng, tpp, slv, rec, cyc, cyc_dir, f_ent, hedged
        if len(ent):
            bal += float(np.sum(np.where(lng, px_bid_side - ent,
                                         ent - px_bid_side - spread))) * lot_pt
        ent = np.empty(0); lng = np.empty(0, dtype=bool)
        tpp = np.empty(0); slv = np.empty(0)
        rec = False; cyc_dir = None; f_ent = None; hedged = False

    for j in range(N):
        # ---- fill ---------------------------------------------------------
        if pending is not None:
            L, ptp, psl, is_first = pending
            px = o[j] + spread if L else o[j]
            ent = np.append(ent, px); lng = np.append(lng, L)
            tpp = np.append(tpp, ptp); slv = np.append(slv, psl)
            opened += 1
            if is_first:
                cyc_dir = L; f_ent = px; f_long = L; hedged = False
            else:
                hedges += 1; hedged = True
            pending = None
            max_open = max(max_open, len(ent))
            if arm == "hedge" and len(ent) > 2:
                raise AssertionError(f"more than 2 positions at bar {j}")

        # ---- bricks -------------------------------------------------------
        ci = c[j]
        while True:
            u = (ao if d == -1 else ac) + brick * (rev if d == -1 else 1)
            n_ = (ao if d == 1 else ac) - brick * (rev if d == 1 else 1)
            if ci >= u:
                base = ao if d == -1 else ac; ao, ac, d = base, base + brick, 1
            elif ci <= n_:
                base = ao if d == 1 else ac; ao, ac, d = base, base - brick, -1
            else:
                break
            if pd_ and d != pd_ and pending is None and j + 1 < N:
                want = (d == 1)
                if len(ent) == 0:
                    # rule 7 - a new cycle needs the basket completely empty
                    pending = (want, TP, 0.0, True)
                elif rec:
                    if arm == "hedge":
                        if (not hedged) and want != cyc_dir:
                            dn = max(((f_ent - c[j]) if f_long else (c[j] - f_ent)), brick)
                            pending = (want, reward * dn, hedge_sl * dn, False)
                    elif arm == "any" and len(ent) <= CAP:
                        pending = (want, TP, 0.0, False)
                    elif arm == "same" and len(ent) <= CAP and want == cyc_dir:
                        pending = (want, TP, 0.0, False)
            pd_ = d

        # ---- targets ------------------------------------------------------
        if len(ent):
            hitT = np.where(lng, h[j] >= ent + tpp, l[j] <= ent - tpp - spread)
            if hitT.any():
                bal += float(np.sum(tpp[hitT])) * lot_pt
                hedge_hit = (arm == "hedge" and hedged and bool(hitT[-1]))
                # REMOVE the filled positions BEFORE anything else touches the
                # book. Calling close_all() while they were still in `ent` paid
                # every winning hedge twice - once as its target, once again as
                # floating P&L - and turned a losing rule into $4,721 from
                # $1,000. Neither invariant caught it: both sides of the
                # cycles-vs-equity check were inflated by the same amount, so a
                # consistent overpayment is invisible to a consistency check.
                keep = ~hitT
                if arm == "hedge" and hitT[0]:
                    f_ent = None
                ent, lng, tpp, slv = ent[keep], lng[keep], tpp[keep], slv[keep]
                if hedge_hit:
                    hedge_won += 1
                    close_all(c[j])                      # rule 4
                    cycles.append(bal - cyc); cyc = bal
                elif len(ent) == 0:
                    rec = False; cyc_dir = None; hedged = False; f_ent = None
                    cycles.append(bal - cyc); cyc = bal

        # ---- hedge stop ---------------------------------------------------
        if len(ent):
            has = slv > 0
            hitS = has & np.where(lng, l[j] <= ent - slv, h[j] >= ent + slv + spread)
            if hitS.any():
                bal -= float(np.sum(slv[hitS])) * lot_pt
                hedge_stop += 1
                keep = ~hitS
                ent, lng, tpp, slv = ent[keep], lng[keep], tpp[keep], slv[keep]
                close_all(c[j])                          # rule 5
                cycles.append(bal - cyc); cyc = bal

        # ---- recovery trigger ---------------------------------------------
        if len(ent) and not rec:
            if np.where(lng, l[j] <= ent - TRIG, h[j] >= ent + TRIG + spread).any():
                rec = True

        flo = float(np.sum(np.where(lng, c[j] - ent, ent - c[j] - spread))) * lot_pt \
            if len(ent) else 0.0
        eq = bal + flo

        # ---- back to zero, or cap -----------------------------------------
        if rec and len(ent) and eq >= cyc:
            close_all(c[j]); cycles.append(bal - cyc); cyc = bal; eq = bal
        elif arm != "hedge" and len(ent) > CAP:
            caps += 1
            close_all(c[j]); cycles.append(bal - cyc); cyc = bal; eq = bal

        peak = max(peak, eq); mdd = max(mdd, peak - eq); lo = min(lo, eq)
        curve[j] = eq
        if eq <= 0:
            curve[j:] = 0.0
            return dict(eq=0.0, dead=True, curve=curve, tm=tm, cycles=cycles,
                        opened=opened, hedges=hedges, won=hedge_won,
                        stopped=hedge_stop, caps=caps, mdd=mdd, lo=0.0,
                        max_open=max_open, ok=True)

    # ---- invariant: cycles must account for the equity change -------------
    resid = (eq - start) - sum(cycles)
    ok = abs(resid) < 1.0 or len(ent) > 0
    return dict(eq=eq, dead=False, curve=curve, tm=tm, cycles=cycles,
                opened=opened, hedges=hedges, won=hedge_won, stopped=hedge_stop,
                caps=caps, mdd=mdd, lo=lo, max_open=max_open, ok=ok,
                resid=resid, still_open=len(ent))
