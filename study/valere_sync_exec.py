"""Valère fidelity - SYNCHRONISED EXECUTION: same decision, same state -> same trade?

Same synchronisation as valere_sync_decisions.py (real debt, pot, day result, streak, cap history, open position at
every signal), plus, when the REAL bot entered at that signal, the engine is allowed to enter too with the real lot
and the real balance; every other order is cancelled. Each pair is then compared: lot, main result, adds, exit.

    python study/valere_sync_exec.py   -> study/valere_sync_exec.json + review/valere_sync_exec.csv
"""
import sys, os, json, time, csv, re, bisect, statistics as stt
sys.argv = ["x"]
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(ROOT, "live"))
import numpy as np
import replay_valere_real as V
import valere_decision_table as DT
import valere_sync_decisions as SD
E, K, F = V.E, V.K, V.F


def main():
    K.install_nopause_gate()
    start_s = V.utc(V.START); start_ms = start_s * 1000
    bm = json.load(open(os.path.join(HERE, "bars_%s.json" % V.UID))); RB = np.load(os.path.join(HERE, "bars_%s.npz" % V.UID))["R"]
    dirs = [os.path.join(HERE, "ticks_%s" % V.UID), os.path.join(HERE, "ticks_%s_forward" % V.UID)]
    TM, BID, ASK, _ = V.merged_ticks(dirs, start_ms, 4_000_000_000_000)
    END = int(TM[-1]) + 1; end_s = END // 1000
    RB = RB[RB["time"] < end_s]
    down = V.downtime_windows()
    k0 = int(np.searchsorted(RB["time"], start_s - V.WIN * 60)); R_all = RB[k0:]
    cfg_snap, _ = E.effective_cfg(E.PR[V.UID], V.BAL0, 0.0); opps, bars = E.streams(cfg_snap, R_all)
    import hashlib, inspect
    fp = hashlib.sha256((bm["sha256"] + str(V.WIN) + hashlib.sha256(open(F.__file__, "rb").read()).hexdigest() + inspect.getsource(K.pb_view_sticky) + inspect.getsource(V.sticky_states)).encode()).hexdigest()[:16]
    S_idx = V.sticky_states(R_all, 0, [o["i"] for o in opps if (o["t"] + 60) * 1000 + E.SIGNAL_MS >= start_ms], fp)
    S = {o["t"]: S_idx.get(o["i"], (0, 0, None, None)) for o in opps}
    cs, _ = E.effective_cfg(E.PR[V.UID], V.BAL0, 0.0); c0 = dict(cs)
    c0.update({"day_cap": 3.0, "debt_gate": 0, "n_cont": 0, "jar": 0, "k_streak": 99, "storm": 99.0, "risk_fit": 0.0, "hard_cap_pct": 0.0, "scale_daily": 0})
    arm = V.RealArm("sync_exec", c0, bars, "none", S, schedule=V.SCHEDULE, downtime=down, touch_rearm=False, order="live", cap_rule="waiver")
    L, groups, J = DT.real_side(end_s)
    LL = DT.log_lines()
    debt_chest, day_profit, streak, in_pos, history, cap_at = SD.real_state_tools(LL, groups, end_s)
    # real balance timeline: start-up lines + day-roll lines + journal entries
    bals = []
    for t, x in LL:
        m = re.search(r"starting on \d+ balance ([0-9.]+)", x) or re.search(r"\(balance \$([0-9.]+) vs", x)
        if m:
            bals.append((t, float(m.group(1))))
    for j in J:
        if j["bal"]:
            bals.append((j["te"], j["bal"]))
    bals.sort(); bt = [t for t, _ in bals]

    def bal_at(t):
        i = bisect.bisect_right(bt, t) - 1
        return bals[i][1] if i >= 0 else V.BAL0

    G = sorted(groups, key=lambda g: g["te"])
    want = {}                                        # signal minute -> real group it became
    orig = arm.signal
    pair = {}

    def real_group(t, d):
        for i, g in enumerate(G):
            if g["d"] == d and -30 <= g["te"] - t <= 180 and i not in pair.values():
                return i
        return None

    def synced(o, k, TM_, BID_, ASK_):
        t = int(o["t"]) + 60
        dbt, chest = debt_chest(t)
        arm.run = 0.0; arm.pk = dbt or 0.0; arm.chest = chest or 0.0
        arm.day_profit = day_profit(t); arm.streak = streak(t); arm.debt_day_pnls = history(t); arm.day_cap_eff = cap_at(t)
        gi = real_group(t, o["d"])
        held = arm.pos if (arm.pos is not None and "e" in arm.pos) else None
        busy = in_pos(t)
        arm.pos = {"busy": True} if (busy or held) else None
        arm.pend = None; arm.dead = False
        if gi is not None:
            g = G[gi]; arm.LOT = g.get("main_lot") or g["lot"]
        arm.bal = bal_at(t)
        prev_order = arm.order if (arm.order is not None and arm.order.get("kind") == "bullet") else None
        arm.order = None
        orig(o, k, TM_, BID_, ASK_)
        if arm.order is not None and arm.order.get("kind") == "main" and gi is not None:
            pair[int(o["t"])] = gi                     # same decision on both sides: let it trade
        else:
            arm.order = prev_order                     # keep a reserved add of the open trade, drop anything new
        arm.pos = held
    arm.signal = synced
    t0 = time.time()
    V.run([arm], TM, BID, ASK, END, opps, bars, start_ms)
    print("synced execution pass: %d paired entries, %d engine trades closed, %.0fs" % (len(pair), len(arm.trades), time.time() - t0), flush=True)

    rows = []
    for tr in arm.trades:
        gi = pair.get(int(tr["t"]))
        if gi is None:
            continue
        g = G[gi]
        rows.append({"entry_utc": DT.iso(g["te"]), "side": "BUY" if g["d"] == 1 else "SELL", "kind": g["kind"], "journal": g["journal"],
                     "real_lot": g.get("main_lot") or g["lot"], "eng_lot": tr["lot"],
                     "real_main": g.get("main_pnl"), "eng_main": tr["pnl_main"], "real_adds": g.get("add_pnl") if g["journal"] else None, "eng_adds": tr["pnl_add"],
                     "real_add_lots": "+".join("%.2f" % x for x in g["add_lots"]), "eng_adds_n": tr["adds"],
                     "real_pnl": round(g["pnl"], 2), "eng_pnl": tr["pnl"], "diff": round(g["pnl"] - tr["pnl"], 2),
                     "real_close": DT.iso(g["tc"]), "eng_close": DT.iso(tr["tc"] // 1000), "close_gap_s": int(tr["tc"] / 1000 - g["tc"]),
                     "real_win": g["pnl"] > 0, "eng_win": bool(tr["win"])})
    jr = [r for r in rows if r["journal"] and r["real_main"] is not None]
    print("\nPAIRED TRADES %d (journal detail on %d)" % (len(rows), len(jr)))
    print("  total: real %+.2f vs engine %+.2f  (gap %+.2f)" % (sum(r["real_pnl"] for r in rows), sum(r["eng_pnl"] for r in rows), sum(r["diff"] for r in rows)))
    print("  same outcome (win/loss) on %d of %d; same lot on %d of %d" % (sum(1 for r in rows if r["real_win"] == r["eng_win"]), len(rows),
          sum(1 for r in rows if abs(r["real_lot"] - r["eng_lot"]) < 1e-9), len(rows)))
    if jr:
        print("  journal trades: main real %+.2f vs engine %+.2f | adds real %+.2f (%d trades with adds) vs engine %+.2f (%d with adds)" % (
            sum(r["real_main"] for r in jr), sum(r["eng_main"] for r in jr), sum(r["real_adds"] or 0 for r in jr),
            sum(1 for r in jr if r["real_add_lots"]), sum(r["eng_adds"] for r in jr), sum(1 for r in jr if r["eng_adds_n"])))
    cg = [abs(r["close_gap_s"]) for r in rows]
    if cg:
        print("  close time gap: median %ds, within 5 s %d, within 60 s %d, over 10 min %d" % (stt.median(cg), sum(1 for v in cg if v <= 5), sum(1 for v in cg if v <= 60), sum(1 for v in cg if v > 600)))
    print("\n  biggest differences:")
    for r in sorted(rows, key=lambda r: -abs(r["diff"]))[:10]:
        print("   %s %-4s %-8s lot %.2f/%.2f adds %s/%s  real %+6.2f eng %+6.2f  close gap %ds" % (r["entry_utc"][5:16], r["side"], r["kind"], r["real_lot"], r["eng_lot"],
              r["real_add_lots"] or "-", r["eng_adds_n"], r["real_pnl"], r["eng_pnl"], r["close_gap_s"]))
    json.dump({"pairs": len(rows), "rows": rows}, open(os.path.join(HERE, "valere_sync_exec.json"), "w"), indent=1)
    with open(os.path.join(ROOT, "review", "valere_sync_exec.csv"), "w", encoding="utf-8", newline="") as f:
        if rows:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)


if __name__ == "__main__":
    main()
