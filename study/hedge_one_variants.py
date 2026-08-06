"""ONE opposite hedge. If it stops out, close everything and start again.

USER'S RULE, refined
  1. first trade: 250-pt target, no stop, 150-pt recovery trigger
  2. on the trigger, take the NEXT opposite-direction reversal - one only
  3. that hedge targets 1.5x the first trade's drawdown, and risks 1.0x it
  4. hedge hits target -> the cycle is now positive, close everything
  5. hedge hits its stop -> CLOSE EVERYTHING, take the loss, new cycle
  6. no further adds - the basket can never exceed 2 positions

This is a completely different risk shape from the current design. The basket is
bounded at two, and rule 5 is a real exit rather than a cap that only fires when
a fifth position is wanted. Maximum loss per cycle is defined in advance.

VARIANTS
  1 hedge, SL 1.0x   the rule as described
  1 hedge, SL 1.5x   a wider stop on the hedge, since 1.0x sits close
  1 hedge, no SL     no forced exit - for contrast, shows what rule 5 is worth

Both windows: M1 and the clean M15.
"""
import numpy as np
import MetaTrader5 as mt5

SPREAD = 10.0
BRICK, REV = 50.0, 2
TP, SL, PT, START = 250.0, 150.0, 0.01, 1000.0

mt5.initialize(path=r"C:\Program Files\MetaTrader 5\terminal64.exe")
DATA = {"M1": mt5.copy_rates_from_pos("BTCUSDm", mt5.TIMEFRAME_M1, 0, 80000),
        "M15": mt5.copy_rates_from_pos("BTCUSDm", mt5.TIMEFRAME_M15, 0, 80000)}
mt5.shutdown()


def run(R, sl_mult, reward=1.5):
    """sl_mult: stop on the hedge as a multiple of the drawdown. 0 = no stop."""
    o, h, l, c = (R[k].astype(float) for k in ("open", "high", "low", "close"))
    N = len(c)
    ao = ac = float(o[0]); d = 0; pd_ = 0
    bal = START; cyc = START
    # cycle state: at most the first trade + one hedge
    f_ent = f_long = None
    hg_ent = hg_long = hg_tp = hg_sl = None
    rec = False; pending = None
    cycles = []; hedged = 0; stopped = 0; hedge_won = 0
    peak = START; mdd = 0.0; eq = START; lo = START
    for j in range(N):
        if pending is not None:
            kind, L, ptp, psl = pending
            px = o[j] + SPREAD if L else o[j]
            if kind == "first":
                f_ent, f_long = px, L
            else:
                hg_ent, hg_long, hg_tp, hg_sl = px, L, ptp, psl
                hedged += 1
            pending = None
        ci = c[j]
        while True:
            u = (ao if d == -1 else ac) + BRICK * (REV if d == -1 else 1)
            n_ = (ao if d == 1 else ac) - BRICK * (REV if d == 1 else 1)
            if ci >= u:
                base = ao if d == -1 else ac; ao, ac, d = base, base + BRICK, 1
            elif ci <= n_:
                base = ao if d == 1 else ac; ao, ac, d = base, base - BRICK, -1
            else:
                break
            if pd_ and d != pd_ and pending is None and j + 1 < N:
                want = (d == 1)
                if f_ent is None:
                    pending = ("first", want, TP, 0.0)
                elif rec and hg_ent is None and want != f_long:
                    dn = ((f_ent - c[j]) if f_long else (c[j] - f_ent))
                    dn = max(dn, BRICK)
                    pending = ("hedge", want, reward * dn, sl_mult * dn)
            pd_ = d

        def cyc_pnl(px):
            t = 0.0
            if f_ent is not None:
                t += ((px - f_ent) if f_long else (f_ent - px - SPREAD)) * PT
            if hg_ent is not None:
                t += ((px - hg_ent) if hg_long else (hg_ent - px - SPREAD)) * PT
            return t

        # first trade's own target
        if f_ent is not None:
            if (h[j] >= f_ent + TP) if f_long else (l[j] <= f_ent - TP - SPREAD):
                bal += TP * PT
                f_ent = None
                if hg_ent is None:
                    cycles.append(TP * PT); rec = False; cyc = bal
        # hedge target / stop
        if hg_ent is not None:
            hitT = (h[j] >= hg_ent + hg_tp) if hg_long else (l[j] <= hg_ent - hg_tp - SPREAD)
            hitS = (hg_sl > 0) and ((l[j] <= hg_ent - hg_sl) if hg_long
                                    else (h[j] >= hg_ent + hg_sl + SPREAD))
            if hitS:                       # rule 5 - close EVERYTHING, reset
                bal -= hg_sl * PT
                if f_ent is not None:
                    bal += ((c[j] - f_ent) if f_long else (f_ent - c[j] - SPREAD)) * PT
                stopped += 1
                cycles.append(bal - cyc)
                f_ent = hg_ent = None; rec = False; cyc = bal
            elif hitT:
                bal += hg_tp * PT
                if f_ent is not None:
                    bal += ((c[j] - f_ent) if f_long else (f_ent - c[j] - SPREAD)) * PT
                hedge_won += 1
                cycles.append(bal - cyc)
                f_ent = hg_ent = None; rec = False; cyc = bal
        # recovery trigger on the first trade
        if f_ent is not None and not rec:
            if (l[j] <= f_ent - SL) if f_long else (h[j] >= f_ent + SL + SPREAD):
                rec = True
        # cycle back to zero with both still open
        flo = cyc_pnl(c[j])
        eq = bal + flo
        if rec and (f_ent is not None or hg_ent is not None) and eq >= cyc:
            bal = eq; cycles.append(0.0)
            f_ent = hg_ent = None; rec = False; cyc = bal; eq = bal
        peak = max(peak, eq); mdd = max(mdd, peak - eq); lo = min(lo, eq)
        if eq <= 0:
            return dict(eq=0.0, dead=True, hedged=hedged, stopped=stopped,
                        hw=hedge_won, mdd=mdd, lo=0.0, n=len(cycles))
    return dict(eq=eq, dead=False, hedged=hedged, stopped=stopped,
                hw=hedge_won, mdd=mdd, lo=lo, n=len(cycles))


for tf in ("M1", "M15"):
    R = DATA[tf]
    mon = (R["time"][-1] - R["time"][0]) / 86400 / 30.4
    tag = "direction work done here" if tf == "M1" else "CLEAN window"
    print("=" * 82)
    print(f"{tf}   {mon:.1f} months   ({tag})")
    print("=" * 82)
    print(f"{'arm':<24}{'final':>12}{'lowest':>10}{'drawdn':>9}"
          f"{'hedges/mo':>11}{'hedge won':>11}{'stopped':>9}")
    for sm, nm in ((1.0, "1 hedge, SL 1.0x"), (1.5, "1 hedge, SL 1.5x"),
                   (0.0, "1 hedge, no SL")):
        z = run(R, sm)
        end = "DIED" if z["dead"] else f"${z['eq']:,.2f}"
        tot = max(1, z["hedged"])
        print(f"{nm:<24}{end:>12}{'$%.0f'%z['lo']:>10}{z['mdd']:>9.2f}"
              f"{z['hedged']/mon:>11.0f}{f'{100*z[chr(104)+chr(119)]/tot:.0f}%':>11}"
              f"{f'{100*z[chr(115)+chr(116)+chr(111)+chr(112)+chr(112)+chr(101)+chr(100)]/tot:.0f}%':>9}")
    print()
