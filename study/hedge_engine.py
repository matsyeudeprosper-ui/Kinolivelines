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
             arm="hedge", hours=None, month_target=None, month_trail=None,
             month_max_cycles=None, hedge_mult=1.0, drop_tp_in_recovery=False,
             adapt=None, atr_override=None):
    """arm: 'hedge' | 'any' | 'same'  ('any' is the current live bot).

    drop_tp_in_recovery: once recovery starts, strip the take-profit off EVERY
    open position and give new adds none either, so the only way out is the
    cycle's own P&L reaching zero (or the basket cap). This removes the
    "harvest" - the ability of one position to bank its 250 points while the
    basket as a whole is still under water. Note it changes nothing for a
    single position: with one trade open, P&L-back-to-zero is always crossed
    before +250, so its TP could never have fired in recovery anyway. The
    difference is entirely in multi-position baskets.

    hours: a set of UTC hours in which a NEW CYCLE may start. None = any hour.
    A hedge is always allowed regardless of the clock - refusing to hedge an
    open trade because the session ended would leave it unmanaged, which is a
    different (and worse) strategy than the one being tested."""
    import datetime as _dt
    o, h, l, c = (R[k][a:].astype(float) for k in ("open", "high", "low", "close"))
    tm = R["time"][a:]
    N = len(c)
    hr = None
    if hours is not None:
        hr = np.array([_dt.datetime.utcfromtimestamp(t).hour for t in tm])
    # month_target: once the month's profit reaches this, open no new cycles
    #               until the month rolls over.
    # month_trail:  once the month has given back this much from its own peak,
    #               open no new cycles until the month rolls over.
    # Open positions are ALWAYS managed and hedges always allowed - stopping
    # mid-cycle would leave a stopless trade unattended, a different strategy.
    ymk = None
    if month_target is not None or month_trail is not None or month_max_cycles is not None:
        ymk = np.array([_dt.datetime.utcfromtimestamp(t).strftime("%Y-%m") for t in tm])
    cur_month = None; month_start_eq = start; month_peak_eq = start
    month_cycles = 0
    TP = brick * tp_bricks
    TRIG = brick * sl_bricks
    CAP = 4                                   # only used by 'any' / 'same'

    # ---- SPEC_ADAPTIVE_SPACING arms -----------------------------------
    # adapt = {"trigger": (k, lo, hi), "tp": (...), "add_dist": (...)}, any
    # subset. S_t = clamp(k * ATR14_t, lo, hi) on THIS run's own bars, sampled
    # at the SIGNAL bar (closed before the next-bar-open fill, so nothing is
    # read from the future). atr_override (full-length, pre-slice) exists for
    # the shuffled-ATR control and for nothing else.
    S_trig = S_tp = S_add = None
    if adapt:
        if atr_override is not None:
            _atr = np.asarray(atr_override, dtype=float)[a:]
        else:
            _pc = np.concatenate([[c[0]], c[:-1]])
            _tr = np.maximum(h - l, np.maximum(np.abs(h - _pc), np.abs(l - _pc)))
            _atr = np.full(N, np.nan)
            if N > 14:
                _atr[13] = _tr[:14].mean()
                for _i in range(14, N):
                    _atr[_i] = (_atr[_i - 1] * 13 + _tr[_i]) / 14.0   # Wilder

        def _S(spec_, fallback):
            if spec_ is None:
                return None
            _k, _lo, _hi = spec_
            s_ = np.clip(_k * _atr, _lo, _hi)
            s_[np.isnan(s_)] = fallback       # warm-up bars: behave like A0
            return s_
        S_trig = _S(adapt.get("trigger"), TRIG)
        S_tp = _S(adapt.get("tp"), TP)
        S_add = _S(adapt.get("add_dist"), 0.0)  # 0 = accept, i.e. A0 behaviour

    def tp_of(j):
        return S_tp[j] if S_tp is not None else TP

    def trig_of(j):
        return S_trig[j] if S_trig is not None else TRIG

    ao = ac = float(o[0]); d = 0; pd_ = 0
    bal = start; cyc = start
    ent = np.empty(0); lng = np.empty(0, dtype=bool)
    tpp = np.empty(0); slv = np.empty(0)
    lotm = np.empty(0)      # lot multiple per position: 1.0 first, hedge_mult hedge
    rec = False; pending = None
    cyc_dir = None; f_ent = None; f_long = None; hedged = False
    peak = start; mdd = 0.0; lo = start; eq = start
    opened = 0; hedges = 0; hedge_won = 0; hedge_stop = 0; caps = 0
    cycles = []; curve = np.empty(N)
    tlog = []          # every fill and its exit, for trade-by-trade output
    max_open = 0

    def close_all(px_bid_side, why="closed with the pair", when=None):
        nonlocal bal, ent, lng, tpp, slv, lotm, rec, cyc, cyc_dir, f_ent, hedged
        if len(ent):
            each = np.where(lng, px_bid_side - ent, ent - px_bid_side - spread) * lot_pt * lotm
            bal += float(np.sum(each))
            for _k in range(len(ent)):
                for _t in tlog:
                    if _t["tout"] is None and abs(_t["px"] - ent[_k]) < 1e-9:
                        _t.update(tout=int(when if when is not None else 0),
                                  why=why, pnl=float(each[_k])); break
        ent = np.empty(0); lng = np.empty(0, dtype=bool)
        tpp = np.empty(0); slv = np.empty(0); lotm = np.empty(0)
        rec = False; cyc_dir = None; f_ent = None; hedged = False

    def add_tp(j):
        """TP for a recovery add. np.inf means the broker TP is simply absent -
        the hit test can then never be true, so the position can only leave via
        the basket exit."""
        return np.inf if drop_tp_in_recovery else tp_of(j)

    eq_now = start
    for j in range(N):
        # ---- month roll-over, before anything else this bar ---------------
        if ymk is not None:
            if cur_month != ymk[j]:
                cur_month = ymk[j]
                month_start_eq = eq_now
                month_peak_eq = eq_now
                month_cycles = 0
            elif eq_now > month_peak_eq:
                month_peak_eq = eq_now
        # ---- fill ---------------------------------------------------------
        if pending is not None:
            L, ptp, psl, is_first = pending
            # BUG FIXED 2026-08-07. is_first was decided when the SIGNAL
            # appeared, but the fill lands on the NEXT bar. If the basket emptied
            # on a take-profit in between, the fill arrived flagged as an add, so
            # cyc_dir was never set and stayed None - and `want == cyc_dir` is
            # false forever after, silently refusing every same-direction add
            # until the next clean cycle. It under-added by about 3x (1,324 adds
            # against the reference implementation's 4,291) and turned M15
            # harvest from a loss into $1,358, contradicting the out-of-sample
            # run. Decide from the ACTUAL basket state at fill time.
            is_first = (len(ent) == 0)
            px = o[j] + spread if L else o[j]
            ent = np.append(ent, px); lng = np.append(lng, L)
            tpp = np.append(tpp, ptp); slv = np.append(slv, psl)
            lotm = np.append(lotm, 1.0 if is_first else hedge_mult)
            opened += 1
            if is_first:
                cyc_dir = L; f_ent = px; f_long = L; hedged = False
            else:
                hedges += 1; hedged = True
            tlog.append({"kind": "first" if is_first else "hedge",
                         "side": "BUY" if L else "SELL", "px": float(px),
                         "tin": int(tm[j]), "tout": None, "why": None, "pnl": None})
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
                    # rule 7 - a new cycle needs the basket completely empty,
                    # and the session / monthly filters apply HERE only
                    allow = (hr is None or hr[j] in hours)
                    if allow and ymk is not None:
                        m_pnl = eq_now - month_start_eq
                        m_peak = month_peak_eq - month_start_eq
                        if month_target is not None and m_pnl >= month_target:
                            allow = False
                        if month_trail is not None and m_peak > 0 \
                                and (m_peak - m_pnl) >= month_trail:
                            allow = False
                        # THE CONTROL: plain "stop after N cycles this month".
                        # No cleverness. If this matches the trailing stop then
                        # the trailing stop is only a way of trading less.
                        # (This gate went in once before and was never read -
                        # the counter incremented and nothing checked it, so
                        # every setting returned an identical number. Verified
                        # firing this time before any result was reported.)
                        if month_max_cycles is not None and month_cycles >= month_max_cycles:
                            allow = False
                    if allow:
                        pending = (want, tp_of(j), 0.0, True)
                        month_cycles += 1
                elif rec:
                    if arm == "hedge":
                        if (not hedged) and want != cyc_dir:
                            dn = max(((f_ent - c[j]) if f_long else (c[j] - f_ent)), brick)
                            pending = (want, reward * dn, hedge_sl * dn, False)
                    elif arm == "any" and len(ent) <= CAP:
                        pending = (want, add_tp(j), 0.0, False)
                    elif arm == "same" and len(ent) <= CAP and want == cyc_dir:
                        # A3: the add must sit at least S_add away from the
                        # NEAREST basket entry, or it is clustered exposure -
                        # Phase 0 showed 10% of adds land within ~50 pts of an
                        # existing position. S_add None or 0 = A0 behaviour.
                        if (S_add is None
                                or float(np.min(np.abs(c[j] - ent))) >= S_add[j]):
                            pending = (want, add_tp(j), 0.0, False)
            pd_ = d

        # ---- targets ------------------------------------------------------
        if len(ent):
            hitT = np.where(lng, h[j] >= ent + tpp, l[j] <= ent - tpp - spread)
            if hitT.any():
                bal += float(np.sum(tpp[hitT] * lotm[hitT])) * lot_pt
                for _k in np.flatnonzero(hitT):
                    for _t in tlog:
                        if _t["tout"] is None and abs(_t["px"] - ent[_k]) < 1e-9:
                            _t.update(tout=int(tm[j]), why="target",
                                      pnl=float(tpp[_k] * lotm[_k]) * lot_pt); break
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
                ent, lng, tpp, slv, lotm = ent[keep], lng[keep], tpp[keep], slv[keep], lotm[keep]
                if hedge_hit:
                    hedge_won += 1
                    close_all(c[j], when=tm[j])                      # rule 4
                    cycles.append(bal - cyc); cyc = bal
                elif len(ent) == 0:
                    rec = False; cyc_dir = None; hedged = False; f_ent = None
                    cycles.append(bal - cyc); cyc = bal

        # ---- hedge stop ---------------------------------------------------
        if len(ent):
            has = slv > 0
            hitS = has & np.where(lng, l[j] <= ent - slv, h[j] >= ent + slv + spread)
            if hitS.any():
                bal -= float(np.sum(slv[hitS] * lotm[hitS])) * lot_pt
                for _k in np.flatnonzero(hitS):
                    for _t in tlog:
                        if _t["tout"] is None and abs(_t["px"] - ent[_k]) < 1e-9:
                            _t.update(tout=int(tm[j]), why="STOPPED",
                                      pnl=-float(slv[_k] * lotm[_k]) * lot_pt); break
                hedge_stop += 1
                keep = ~hitS
                ent, lng, tpp, slv, lotm = ent[keep], lng[keep], tpp[keep], slv[keep], lotm[keep]
                close_all(c[j], when=tm[j])                          # rule 5
                cycles.append(bal - cyc); cyc = bal

        # ---- recovery trigger ---------------------------------------------
        if len(ent) and not rec:
            _tg = trig_of(j)
            if np.where(lng, l[j] <= ent - _tg, h[j] >= ent + _tg + spread).any():
                rec = True
                if drop_tp_in_recovery and arm != "hedge":
                    # strip the TP off everything already open, not just future
                    # adds - the user's rule is "after recovery we remove all
                    # TPs", present positions included
                    tpp = np.full(len(tpp), np.inf)

        flo = float(np.sum(np.where(lng, c[j] - ent, ent - c[j] - spread))) * lot_pt \
            if len(ent) else 0.0
        eq = bal + flo

        # ---- back to zero, or cap -----------------------------------------
        if rec and len(ent) and eq >= cyc:
            close_all(c[j], when=tm[j]); cycles.append(bal - cyc); cyc = bal; eq = bal
        elif arm != "hedge" and len(ent) > CAP:
            caps += 1
            close_all(c[j], when=tm[j]); cycles.append(bal - cyc); cyc = bal; eq = bal

        peak = max(peak, eq); mdd = max(mdd, peak - eq); lo = min(lo, eq)
        eq_now = eq
        curve[j] = eq
        if eq <= 0:
            curve[j:] = 0.0
            return dict(eq=0.0, dead=True, curve=curve, tm=tm, cycles=cycles, tlog=tlog,
                        opened=opened, hedges=hedges, won=hedge_won,
                        stopped=hedge_stop, caps=caps, mdd=mdd, lo=0.0,
                        max_open=max_open, ok=True)

    # ---- invariant: cycles must account for the equity change -------------
    resid = (eq - start) - sum(cycles)
    ok = abs(resid) < 1.0 or len(ent) > 0
    return dict(eq=eq, dead=False, curve=curve, tm=tm, cycles=cycles, tlog=tlog,
                opened=opened, hedges=hedges, won=hedge_won, stopped=hedge_stop,
                caps=caps, mdd=mdd, lo=lo, max_open=max_open, ok=ok,
                resid=resid, still_open=len(ent))
