"""SPEC_BIG_BRICK_GATE addendum 2 (2026-08-09): configuration pick for the
user-mandated demo deployment. Corrected setup per the user: base = the
normal harvest ($50 bricks on M1 closes, arm='same'), gate = big-brick
direction at 3x ($150) or 4x ($200). Pick rule, declared before running:
better mean vs A0 on M1 (the deployment timeframe), tie-break by M5.
M5/M15 shown for context. Not a survival test - the deployment decision is
already made; this only chooses the multiplier."""
import numpy as np
import MetaTrader5 as mt5
from hedge_engine import simulate

mt5.initialize(path=r"C:\Program Files\MetaTrader 5\terminal64.exe")
R1 = mt5.copy_rates_from_pos("BTCUSDm", mt5.TIMEFRAME_M1, 0, 80000)
R5 = mt5.copy_rates_from_pos("BTCUSDm", mt5.TIMEFRAME_M5, 0, 80000)
R15 = mt5.copy_rates_from_pos("BTCUSDm", mt5.TIMEFRAME_M15, 0, 80000)
mt5.shutdown()

ANCH = range(6)


def big_dir_masks(R, brick, rev=2):
    o = R["open"].astype(float)
    c = R["close"].astype(float)
    N = len(c)
    ao = ac = float(o[0])
    d = 0
    dirs = np.zeros(N, dtype=np.int8)
    for j in range(N):
        ci = c[j]
        while True:
            up = (ao if d == -1 else ac) + brick * (rev if d == -1 else 1)
            dn = (ao if d == 1 else ac) - brick * (rev if d == 1 else 1)
            if ci >= up:
                base = ao if d == -1 else ac
                ao, ac, d = base, base + brick, 1
            elif ci <= dn:
                base = ao if d == 1 else ac
                ao, ac, d = base, base - brick, -1
            else:
                break
        dirs[j] = d
    return dirs == 1, dirs == -1


def run6(R, **kw):
    rs = []
    for a in ANCH:
        r = simulate(R, a=a, arm="same", **kw)
        assert r["ok"], f"invariant failed anchor {a}"
        rs.append(r)
    return rs


def eqv(rs):
    return np.array([r["eq"] for r in rs])


picks = {}
for name, R in (("M1", R1), ("M5", R5), ("M15", R15)):
    months = (R["time"][-1] - R["time"][0]) / (86400 * 30.44)
    print(f"--- {name} ({months:.1f} months) ---")
    rs0 = run6(R)
    eq0 = eqv(rs0)
    print(f"  A0     mean {eq0.mean():9.2f}  dead {sum(r['dead'] for r in rs0)}/6")
    for brick in (150.0, 200.0):
        mb, ms = big_dir_masks(R, brick)
        rsF = run6(R, entry_filter=("mask", mb, ms))
        eqF = eqv(rsF)
        d = eqF - eq0
        se2 = 2 * d.std(ddof=1) / np.sqrt(6)
        opF = np.mean([r["opened"] for r in rsF])
        seen = sum(r["f_seen"] for r in rsF)
        passed = sum(r["f_pass"] for r in rsF)
        print(f"  F{brick:.0f}   mean {eqF.mean():9.2f}  dead {sum(r['dead'] for r in rsF)}/6  "
              f"cycles {opF:6.0f}  share {passed/seen:5.1%}  "
              f"vs A0 {d.mean():+9.2f}  2SE {se2:7.2f}  better {(d>0).sum()}/6")
        picks[(name, brick)] = float(d.mean())
    print()

m1_150, m1_200 = picks[("M1", 150.0)], picks[("M1", 200.0)]
if abs(m1_150 - m1_200) > 1e-9:
    win = 150 if m1_150 > m1_200 else 200
else:
    win = 150 if picks[("M5", 150.0)] >= picks[("M5", 200.0)] else 200
print(f"PICK (by M1 vs A0, tie-break M5): ${win} gate  "
      f"(M1: 150 -> {m1_150:+.2f}, 200 -> {m1_200:+.2f})")
