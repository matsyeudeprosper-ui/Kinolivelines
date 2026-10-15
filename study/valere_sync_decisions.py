"""Valère fidelity - SYNCHRONISED decisions (step 3 of the handoff, the drift-free version).

The open-loop replay drifts: one early difference (a missed winner, a different cap bonus) changes the engine's
debt and day result, and from then on every state-dependent gate decides differently - so its total cannot judge
the engine. Here, before EVERY signal, the engine arm is given the REAL account's state at that moment:
  debt, recovery pot        the bot's own WIN/LOSS log lines (latest before the signal)
  today's realised profit   the broker ledger (grouped closes of that UTC day before the signal)
  losing streak             the broker ledger
  open position             the broker ledger (entry -> close of each real trade)
  debt-day cap history      rebuilt like the live bot: empty at db3db14 (2026-09-24), one value per UTC day that
                            OPENED in debt (that day's realised P&L), median of the last 40, needs 3
The engine then decides that one signal with its own gates and rules (dated schedule incl. the self-counting flip);
the order is cancelled before it fills, so no state ever carries over. Compared with what the real bot did.

    python study/valere_sync_decisions.py   (after valere_decision_table.py has built the structure cache)
-> study/valere_sync_decisions.json + review/valere_sync_decisions.csv
"""
import sys, os, json, time, csv, re, collections, bisect, calendar
sys.argv = ["x"]
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(ROOT, "live"))
import numpy as np
import replay_valere_real as V
import valere_decision_table as DT
E, K, F = V.E, V.K, V.F
ADAPTIVE_FROM = V.utc("2026-09-24T11:25:14")


def real_state_tools(LL, groups, end_s):
    closes = [(t, x) for t, x in LL if re.search(r" (WIN|LOSS) [+-]", " " + x)]
    ct = [t for t, _ in closes]
    vals = []
    for t, x in closes:
        m = re.search(r"debt \$([0-9.]+) \(peak \+?(-?[0-9.]+)\), chest \$([0-9.]+)", x)
        vals.append((float(m.group(1)), float(m.group(3))) if m else (None, None))

    def debt_chest(t):
        i = bisect.bisect_right(ct, t) - 1
        return vals[i] if i >= 0 else (0.0, 0.0)

    G = sorted(groups, key=lambda g: g["tc"])

    def day_profit(t):
        day = time.strftime("%Y-%m-%d", time.gmtime(t))
        return sum(g["pnl"] for g in G if g["tc"] <= t and time.strftime("%Y-%m-%d", time.gmtime(g["tc"])) == day)

    def streak(t):
        n = 0
        for g in reversed([g for g in G if g["tc"] <= t]):
            if g["pnl"] < 0:
                n += 1
            else:
                break
        return n

    def in_pos(t):
        # the trade being decided (entered within -2..+3 min of this signal) is not "already open"
        return any(g["te"] <= t < g["tc"] and not (-120 <= g["te"] - t <= 180) for g in G)

    # debt-day history as the live bot built it (starts empty at the adaptive rule's deployment)
    hist_at = {}
    days = sorted({time.strftime("%Y-%m-%d", time.gmtime(t)) for t in range(int(ADAPTIVE_FROM), int(end_s) + 86400, 86400)})
    H = []
    for d in days:
        t0 = calendar.timegm(time.strptime(d, "%Y-%m-%d"))
        hist_at[d] = list(H[-40:])
        dbt, _ = debt_chest(t0)
        if dbt is not None and dbt > 0.5:
            H.append(sum(g["pnl"] for g in G if time.strftime("%Y-%m-%d", time.gmtime(g["tc"])) == d))

    def history(t):
        return hist_at.get(time.strftime("%Y-%m-%d", time.gmtime(t)), [])

    # the day cap the real bot enforced: "day cap now $Y" at each day roll, "day cap +$X" at start-up
    caps = []
    for t, x in LL:
        m = re.search(r"day cap now \$([0-9.]+)", x) or re.search(r"day cap \+\$([0-9.]+)", x)
        if m:
            caps.append((t, float(m.group(1))))
    capt = [t for t, _ in caps]

    def cap_at(t):
        i = bisect.bisect_right(capt, t) - 1
        return caps[i][1] if i >= 0 else 3.0

    return debt_chest, day_profit, streak, in_pos, history, cap_at


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
    arm = V.RealArm("sync", c0, bars, "none", S, schedule=V.SCHEDULE, downtime=down, touch_rearm=False, order="live", cap_rule="waiver")

    L, groups, J = DT.real_side(end_s)
    LL = DT.log_lines()
    debt_chest, day_profit, streak, in_pos, history, cap_at = real_state_tools(LL, groups, end_s)
    rows = []
    orig = arm.signal

    def synced(o, k, TM_, BID_, ASK_):
        t = int(o["t"]) + 60
        dbt, chest = debt_chest(t)
        dbt = dbt or 0.0
        arm.run = 0.0; arm.pk = dbt                       # debt() = pk - run
        arm.chest = chest or 0.0
        arm.day_profit = day_profit(t); arm.streak = streak(t)
        arm.debt_day_pnls = history(t)
        arm.day_cap_eff = cap_at(t)
        busy = in_pos(t)
        arm.pos = {"busy": True} if busy else None
        arm.order = None; arm.pend = None; arm.dead = False
        before = {x: v for x, v in arm.n.items() if not isinstance(v, list)}
        orig(o, k, TM_, BID_, ASK_)
        moved = [x for x, v in arm.n.items() if not isinstance(v, list) and v != before.get(x, 0) and x != "signals"]
        out = "enter" if arm.order is not None else (moved[0] if moved else "no_counter")
        arm.order = None; arm.pos = None                  # nothing carries over
        rows.append({"t": int(o["t"]), "d": o["d"], "flip": bool(o["flip"]), "engine": out, "real_debt": round(dbt, 2),
                     "real_day": round(arm.day_profit, 2), "busy": busy, "hist_n": len(arm.debt_day_pnls), "cap": arm.day_cap_eff})
    arm.signal = synced
    # tick(): the engine must not open anything (orders are cancelled at once); pos placeholder only during signal()
    t0 = time.time()
    V.run([arm], TM, BID, ASK, END, opps, bars, start_ms)
    print("synced pass over %d signals in %.0fs" % (len(rows), time.time() - t0), flush=True)

    # the real decision at each signal: did the real bot open a trade of that side within 3 min of the signal?
    G = sorted(groups, key=lambda g: g["te"])
    used = set()
    for r in rows:
        ts = r["t"] + 60
        hit = None
        for i, g in enumerate(G):
            if i not in used and g["d"] == r["d"] and -30 <= g["te"] - ts <= 180:
                hit = i; break
        if hit is not None:
            used.add(hit)
        r["real"] = "enter" if hit is not None else "no"
        r["real_pnl"] = round(G[hit]["pnl"], 2) if hit is not None else None
    real_missing = [g for i, g in enumerate(G) if i not in used and g["te"] >= start_s]

    cm = collections.Counter((r["real"], "enter" if r["engine"] == "enter" else "no") for r in rows)
    agree = cm[("enter", "enter")] + cm[("no", "no")]
    print("\nSYNCHRONISED DECISIONS on %d signals: agree %d (%.1f%%)" % (len(rows), agree, 100.0 * agree / len(rows)))
    print("  both entered %d | both stayed out %d | ENGINE ONLY entered %d | REAL ONLY entered %d"
          % (cm[("enter", "enter")], cm[("no", "no")], cm[("no", "enter")], cm[("enter", "no")]))
    eo = collections.Counter()
    for r in rows:
        if r["real"] == "no" and r["engine"] == "enter":
            ln = DT.near_log(LL, r["t"] + 60, 240)
            lim = DT.day_limit_before(LL, r["t"] + 60)
            r["why"] = ("real: day limit" if lim else "real down" if any(a <= r["t"] + 60 < b for a, b in down)
                        else ("real log: " + re.sub(r"[0-9.]+", "N", ln[0])[:60]) if ln else "real: silent")
            eo[r["why"]] += 1
    ro = collections.Counter(r["engine"] for r in rows if r["real"] == "enter" and r["engine"] != "enter")
    print("\n  engine entered, real did not - what the real bot said:")
    for k, v in eo.most_common(12):
        print("     %3d  %s" % (v, k))
    print("\n  real entered, engine did not - the engine's gate (with the REAL state):")
    for k, v in ro.most_common():
        pn = sum(r["real_pnl"] or 0 for r in rows if r["real"] == "enter" and r["engine"] == k)
        print("     %3d  %-16s real P&L of those trades %+.2f" % (v, k, pn))
    print("\n  real trades with no engine signal at all within 3 min: %d (real P&L %+.2f; kinds %s)"
          % (len(real_missing), sum(g["pnl"] for g in real_missing), dict(collections.Counter(g["kind"] for g in real_missing))))
    res = {"generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "signals": len(rows), "agree": agree,
           "confusion": {"%s/%s" % k: v for k, v in cm.items()}, "engine_only_why": dict(eo), "real_only_gate": dict(ro),
           "real_no_signal": [{"te": DT.iso(g["te"]), "d": g["d"], "kind": g["kind"], "pnl": round(g["pnl"], 2)} for g in real_missing]}
    json.dump(res, open(os.path.join(HERE, "valere_sync_decisions.json"), "w"), indent=1)
    with open(os.path.join(ROOT, "review", "valere_sync_decisions.csv"), "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["t_utc", "side", "flip", "real", "engine", "real_debt", "real_day", "busy", "hist_n", "real_pnl", "why"])
        w.writeheader()
        for r in rows:
            w.writerow({"t_utc": DT.iso(r["t"]), "side": "BUY" if r["d"] == 1 else "SELL", "flip": r["flip"], "real": r["real"], "engine": r["engine"],
                        "real_debt": r["real_debt"], "real_day": r["real_day"], "busy": r["busy"], "hist_n": r["hist_n"], "real_pnl": r["real_pnl"], "why": r.get("why", "")})


if __name__ == "__main__":
    main()
