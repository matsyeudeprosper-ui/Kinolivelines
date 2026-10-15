"""Valère fidelity diagnostic - step 2+3 of review/VALERE_FIDELITY_HANDOFF.md.

The baseline arm of replay_valere_real.py ("actual_rules", the rules the bot really ran, its downtime, his own
quotes, spread only) is rerun UNCHANGED, with one addition: every signal the engine sees is recorded with its
outcome (the gate counter that moved), so each real trade can be explained by what the engine did at that moment.

Then, without touching the model, the gap engine -> real is split by cause, in dollars:
  (a) paired trades   - same trade both sides: main-lot difference, adds difference
  (b) engine-only     - the engine traded, the real bot did not: what the bot's log said that minute
  (c) real-only       - the real bot traded, the engine did not: the engine's gate at that signal

    python study/valere_decision_table.py
-> review/valere_decision_table.csv (one line per trade, both sides) + study/valere_decision_table.json (by cause)
"""
import sys, os, json, time, csv, calendar, collections, re
sys.argv = ["x"]
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(ROOT, "live"))
import numpy as np
import replay_valere_real as V
E, K, F = V.E, V.K, V.F

LOG = os.path.join(ROOT, "live", "bos_bot_valere.log")
JOURNAL = os.path.join(ROOT, "live", "bos_journal_valere.csv")
OUT_CSV = os.path.join(ROOT, "review", "valere_decision_table.csv")
OUT_JSON = os.path.join(HERE, "valere_decision_table.json")
LOG_WORDS = ("refus", "skipped", "asleep", "dette", "LIMITE", "repli", "position", "ENTRY", "FAILED", "pause", "plafond", "orage", "storm", "attend")


def iso(s):
    return time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(s))


def ts_of(s):
    s = s.replace("Z", "+00:00")
    from datetime import datetime
    return datetime.fromisoformat(s).timestamp()


class Recorder:
    """wraps arm.signal: which gate counter moved = the signal's outcome"""
    SKIP = {"wait_s"}

    def __init__(self, arm):
        self.arm, self.rows, self.orig = arm, [], arm.signal
        arm.signal = self.signal

    def signal(self, o, k, TM, BID, ASK):
        a = self.arm
        before = {x: v for x, v in a.n.items() if x not in self.SKIP and not isinstance(v, list)}
        _d = a.debt()
        try:
            _cap = a.cap_today(_d)
        except Exception:
            _cap = "?"
        st = {"debt": round(_d, 2), "run": round(a.run, 2), "lot": a.LOT, "streak": a.streak, "cont_left": a.cont_left,
              "dayp": round(a.day_profit, 2), "cap": (round(_cap, 2) if isinstance(_cap, float) else _cap), "cap_rule": getattr(a, "cap_rule", ""),
              "debt_days": len(getattr(a, "debt_day_pnls", []))}
        r = self.orig(o, k, TM, BID, ASK)
        moved = [x for x, v in a.n.items() if x not in self.SKIP and not isinstance(v, list) and v != before.get(x, 0) and x != "signals"]
        outcome = "ordered" if "orders" in moved or "setups" in moved else (moved[0] if moved else "no_counter")
        self.rows.append(dict(t=int(o["t"]), d=o["d"], flip=bool(o["flip"]), lvl=o.get("lvl"), nv=round(float(o.get("nv") or 0), 2), mv2=o.get("mv2"), awake=o.get("awake"), outcome=outcome, **st))
        return r


def real_side(end_s):
    L = V.ledger(end_s)
    groups = L["groups"]
    J = []
    for r in csv.DictReader(open(JOURNAL, encoding="utf-8", errors="replace", newline="")):
        try:
            # add rows carry no entry time in the journal (only the exit) - keep them, they are matched by exit time
            J.append({"te": ts_of(r["entry_time_utc"]) if r.get("entry_time_utc") else None, "tx": ts_of(r["exit_time_utc"]) if r.get("exit_time_utc") else None,
                      "kind": r["kind"], "add": r["is_add"] == "True", "d": 1 if r["direction"] == "BUY" else -1, "lot": float(r["lot"]),
                      "debt": float(r["debt_at_entry"] or 0), "bal": float(r["balance_at_entry"] or 0), "pnl": float(r["profit_usd"] or 0),
                      "dist": float(r["dist_pts"] or 0)})
        except (ValueError, KeyError):
            continue
    for g in groups:
        g["te"] = g["tc"] - 60 * g["minutes"]
        js = [j for j in J if j["tx"] and abs(j["tx"] - g["tc"]) <= 120 and j["d"] == g["d"]]
        mains = [j for j in js if not j["add"]]
        g["kind"] = mains[0]["kind"] if mains else ("?" if g["tc"] >= min(j["te"] for j in J if j["te"]) else "pre-journal")
        if mains:
            g["te"] = mains[0]["te"]; g["main_lot"] = mains[0]["lot"]; g["main_pnl"] = mains[0]["pnl"]; g["debt"] = mains[0]["debt"]
        g["add_lots"] = [j["lot"] for j in js if j["add"]]
        g["add_pnl"] = round(sum(j["pnl"] for j in js if j["add"]), 2)
        g["journal"] = bool(js)
    return L, groups, J


def log_lines():
    out = []
    for l in open(LOG, encoding="utf-8", errors="replace"):
        try:
            out.append((ts_of(l[:32].split(" ")[0]), l.rstrip()[33:]))
        except Exception:
            continue
    return out


def day_limit_before(LL, t):
    day = time.strftime("%Y-%m-%d", time.gmtime(t))
    hit = [(tt, x) for tt, x in LL if tt <= t and time.strftime("%Y-%m-%d", time.gmtime(tt)) == day and "LIMITE DU JOUR" in x]
    return hit[-1][1] if hit else None


def real_debt_before(LL, t):
    for tt, x in reversed([(tt, x) for tt, x in LL if tt <= t]):
        m = re.search(r"debt \$([0-9.]+)", x)
        if m:
            return float(m.group(1))
    return None


def near_log(LL, t, w=150):
    return [x for tt, x in LL if abs(tt - t) <= w and any(k.lower() in x.lower() for k in LOG_WORDS)][:6]


def main():
    K.install_nopause_gate()
    start_s = V.utc(V.START); start_ms = start_s * 1000
    bm = json.load(open(os.path.join(HERE, "bars_%s.json" % V.UID))); RB = np.load(os.path.join(HERE, "bars_%s.npz" % V.UID))["R"]
    dirs = [os.path.join(HERE, "ticks_%s" % V.UID), os.path.join(HERE, "ticks_%s_forward" % V.UID)]
    TM, BID, ASK, n_bad = V.merged_ticks(dirs, start_ms, 4_000_000_000_000)
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
    arm = V.RealArm("actual_rules", c0, bars, "none", S, schedule=V.SCHEDULE, downtime=down, touch_rearm=False, order="live", cap_rule="waiver")
    rec = Recorder(arm)
    t0 = time.time()
    out = V.run([arm], TM, BID, ASK, END, opps, bars, start_ms)["actual_rules"]
    print("baseline rerun: net %.2f, %d trades (reply 21: +0.81, 85) in %.0fs" % (out["net"], out["trades"], time.time() - t0), flush=True)

    L, groups, J = real_side(end_s)
    LL = log_lines()
    ET = arm.trades
    # pair by side + close time (the replay's own rule), keep the offset
    used, pairs, e_only = set(), [], []
    for t in ET:
        best, bd = None, 601
        for i, g in enumerate(groups):
            if i in used or g["d"] != t["d"]:
                continue
            dd = abs(g["tc"] - t["tc"] / 1000)
            if dd < bd:
                bd, best = dd, i
        if best is not None:
            used.add(best); pairs.append((t, groups[best], bd))
        else:
            e_only.append(t)
    r_only = [g for i, g in enumerate(groups) if i not in used]

    sig = rec.rows

    def sig_near(t, d, w=240):
        c = [s for s in sig if s["d"] == d and abs(s["t"] + 60 - t) <= w]
        return min(c, key=lambda s: abs(s["t"] + 60 - t)) if c else None

    rows = []
    cause = {"paired": {"n": len(pairs), "real": 0.0, "engine": 0.0, "main_lot_gap": 0.0, "adds_gap": 0.0, "price_gap": 0.0},
             "engine_only": collections.defaultdict(lambda: {"n": 0, "pnl": 0.0}), "real_only": collections.defaultdict(lambda: {"n": 0, "pnl": 0.0})}
    for t, g, off in pairs:
        # the paired gap, split: (1) the main lot (engine trade re-sized to the real main lot), (2) adds, (3) the rest = price/fill/exit
        rl = g.get("main_lot") or g["lot"]
        e_main_at_real_lot = t["pnl_main"] * (rl / t["lot"]) if t["lot"] else t["pnl_main"]
        lot_gap = e_main_at_real_lot - t["pnl_main"]
        r_main = g.get("main_pnl", g["pnl"] - g.get("add_pnl", 0.0))
        adds_gap = g.get("add_pnl", 0.0) - t["pnl_add"]
        price_gap = r_main - e_main_at_real_lot
        c = cause["paired"]; c["real"] += g["pnl"]; c["engine"] += t["pnl"]; c["main_lot_gap"] += lot_gap; c["adds_gap"] += adds_gap; c["price_gap"] += price_gap
        rows.append({"type": "paired", "side": "BUY" if t["d"] == 1 else "SELL", "real_entry": iso(g["te"]), "engine_signal": iso(t["t"]), "close_offset_s": round(off),
                     "kind": g["kind"], "real_lot": rl, "engine_lot": t["lot"], "real_adds": "+".join("%.2f" % x for x in g["add_lots"]), "engine_adds": t["adds"],
                     "real_pnl": round(g["pnl"], 2), "engine_pnl": t["pnl"], "lot_gap": round(lot_gap, 2), "adds_gap": round(adds_gap, 2), "price_gap": round(price_gap, 2),
                     "real_debt": g.get("debt", ""), "why": ""})
    sig_at = {}
    for s_ in rec.rows:
        sig_at.setdefault((s_["t"], s_["d"]), s_)
    for t in e_only:
        ts_ = t["t"] + 60
        lines = near_log(LL, ts_, 300)
        down = any(a <= ts_ < b for a, b in V.downtime_windows())
        txt = " | ".join(lines)
        lim = day_limit_before(LL, ts_)
        inpos = any(g["te"] - 5 <= ts_ <= g["tc"] + 5 for g in groups)
        why = ("bot down" if down else "real: day limit reached earlier today" if lim
               else "real: already in a position" if inpos
               else "real: refused (log)" if re.search(r"refus|skipped|asleep|attend|pause", txt, re.I)
               else "real: entry failed" if "FAILED" in txt
               else "real: silent" if not lines else "real: other")
        es = sig_at.get((t["t"], t["d"]), {})
        rd = real_debt_before(LL, ts_)
        txt = ("engine debt %s, day %s, cap %s (%s, %s debt-days) | real debt %s | " % (es.get("debt"), es.get("dayp"), es.get("cap"), es.get("cap_rule"), es.get("debt_days"), rd)
               + (lim[:90] + " | " if lim else "") + txt)
        cause["engine_only"][why]["n"] += 1; cause["engine_only"][why]["pnl"] += t["pnl"]
        rows.append({"type": "engine_only", "side": "BUY" if t["d"] == 1 else "SELL", "real_entry": "", "engine_signal": iso(t["t"]), "close_offset_s": "",
                     "kind": "", "real_lot": "", "engine_lot": t["lot"], "real_adds": "", "engine_adds": t["adds"], "real_pnl": "", "engine_pnl": t["pnl"],
                     "lot_gap": "", "adds_gap": "", "price_gap": "", "real_debt": "", "why": why + (" :: " + txt[:300] if txt else "")})
    for g in r_only:
        s = sig_near(g["te"], g["d"])
        why = ("engine: no signal within 4 min" if s is None else "engine: " + s["outcome"])
        if g["kind"] == "INT":
            why = "internal entry (not modelled)"
        cause["real_only"][why]["n"] += 1; cause["real_only"][why]["pnl"] += g["pnl"]
        rows.append({"type": "real_only", "side": "BUY" if g["d"] == 1 else "SELL", "real_entry": iso(g["te"]), "engine_signal": iso(s["t"]) if s else "", "close_offset_s": "",
                     "kind": g["kind"], "real_lot": g.get("main_lot") or g["lot"], "engine_lot": "", "real_adds": "+".join("%.2f" % x for x in g["add_lots"]), "engine_adds": "",
                     "real_pnl": round(g["pnl"], 2), "engine_pnl": "", "lot_gap": "", "adds_gap": "", "price_gap": "", "real_debt": g.get("debt", ""),
                     "why": why + (" (engine debt %.2f, streak %d, cont %d)" % (s["debt"], s["streak"], s["cont_left"]) if s else "")})
    rows.sort(key=lambda r: r["real_entry"] or r["engine_signal"])
    with open(OUT_CSV, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)

    real_total = sum(g["pnl"] for g in groups); eng_total = sum(t["pnl"] for t in ET)
    res = {"generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "baseline_net": out["net"], "baseline_trades": out["trades"],
           "real_net": round(real_total, 2), "real_groups": len(groups), "engine_net": round(eng_total, 2), "gap": round(real_total - eng_total, 2),
           "signals": dict(collections.Counter(s["outcome"] for s in sig)),
           "paired": {k: (round(v, 2) if isinstance(v, float) else v) for k, v in cause["paired"].items()},
           "engine_only": {k: {"n": v["n"], "pnl": round(v["pnl"], 2)} for k, v in cause["engine_only"].items()},
           "real_only": {k: {"n": v["n"], "pnl": round(v["pnl"], 2)} for k, v in cause["real_only"].items()}}
    res["signal_rows"] = sig
    json.dump(res, open(OUT_JSON, "w"), indent=1)
    p = res["paired"]
    print("\nREAL %+.2f (%d trades)   ENGINE %+.2f (%d)   GAP %+.2f" % (real_total, len(groups), eng_total, len(ET), real_total - eng_total))
    print("signals seen by the engine:", res["signals"])
    print("\n(a) PAIRED %d: real %+.2f vs engine %+.2f -> gap %+.2f = main lot %+.2f + adds %+.2f + price/fill/exit %+.2f"
          % (p["n"], p["real"], p["engine"], p["real"] - p["engine"], p["main_lot_gap"], p["adds_gap"], p["price_gap"]))
    print("(b) ENGINE-ONLY (engine traded, real did not), by what the bot's log said:")
    for k, v in sorted(res["engine_only"].items(), key=lambda kv: kv[1]["pnl"]):
        print("     %-30s %3d trades  engine %+8.2f" % (k, v["n"], v["pnl"]))
    print("(c) REAL-ONLY (real traded, engine did not), by the engine's gate at that signal:")
    for k, v in sorted(res["real_only"].items(), key=lambda kv: -kv[1]["pnl"]):
        print("     %-36s %3d trades  real %+8.2f" % (k, v["n"], v["pnl"]))
    print("\n-> %s\n-> %s" % (OUT_CSV, OUT_JSON))


if __name__ == "__main__":
    main()
