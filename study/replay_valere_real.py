"""Mike / GPT 2026-10-11: Valère's REAL account (nest u224016179, login 224016179, Exness-MT5Real30 BTCUSD) replayed
on HIS OWN bid/ask ticks from the bot's first start (2026-09-14 22:46:39 UTC, $210.00) to the last available tick.

Four hypothetical arms, every one cold-flat at the real start with the real balance, on one clock:
  actual_rules         : the rules the bot ACTUALLY ran, as they changed over the period (git-dated schedule below),
                         with the bot's recorded DOWNTIME (no entries while it was not running) and the recorded
                         manual override (the 2026-10-10 07:05 UTC "continue today" switch) - the BASELINE to be
                         compared with the real ledger
  actual_rules_filter  : exactly the same + Mike's trend / last-BOS filter with the missing-structure pause
  today_rules          : today's package (valere_cap3 snapshot) throughout, no filter, same downtime      } reported
  today_rules_filter   : today's package + the filter                                                     } apart
Engine conventions: live gate order, adaptive daily cap where the schedule says so, causal + sticky pullback structure
with an 8000-bar warm-up on Valère's own bars, both cost bases (his spread alone; + $0.35 per 0.02 lot nominated).
Not modelled (reported as residuals): the internal-structure entries the bot took 2026-09-19 -> 09-30 (1 real trade),
touch entries (none occurred), the real broker's fills / slippage, the bot's exact sizing at each moment.
    python replay_valere_real.py
Results: study/replay_valere_real.json + review/valere_replay_*.csv (sanitised per-trade lists)
"""
import sys, os, json, time, pickle, hashlib, inspect, csv, calendar, collections
ARGS = list(sys.argv); sys.argv = ["x"]
sys.path.insert(0, r"C:\Projects\KinoliveLines\study"); sys.path.insert(0, r"C:\Projects\KinoliveLines\live")
import numpy as np
import tick_engine as E
from tick_engine_matrix import PolicyArm, summarise
from tick_engine_pbgate import PbGateArm
import tick_engine_pbgate_sticky as K
import owl_chart_feed as F
HERE = os.path.dirname(os.path.abspath(__file__)); REVIEW = os.path.join(os.path.dirname(HERE), "review")
UID = "u224016179"; LOGIN = 224016179
START = "2026-09-14T22:46:39"; BAL0 = 210.0
CACHE = os.path.join(HERE, "pb_state_sticky_cache_valere_own.pkl"); OUT = os.path.join(HERE, "replay_valere_real.json")
WIN = F.RAW_BARS


def utc(s): return calendar.timegm(time.strptime(s, "%Y-%m-%dT%H:%M:%S"))


# ------------------------------------------------------------------ the rules as they entered the bot (git dates, UTC)
# fields are the engine's config keys; cap_rule / touch_rearm / nb / k are arm attributes
SCHEDULE = [
    (utc("2026-09-14T22:46:39"), {"day_cap": 3.0, "cap_rule": "waiver", "debt_gate": 0, "n_cont": 0, "jar": 0, "k_streak": 99, "storm": 99.0, "risk_fit": 0.0, "hard_cap_pct": 0.0, "scale_daily": 0},
     "start: $3 cap waived in debt, no recovery restriction, no jar, no streak limit, no storm rule, fixed 0.02 lot"),
    (utc("2026-09-15T22:05:18"), {"hard_cap_pct": 0.10}, "2412dad: no trade may risk more than 10 % of the balance"),
    (utc("2026-09-16T21:09:47"), {"jar": 1}, "e1a5260/5c9ccde: tab-and-jar recovery on (skim 50 %)"),
    # 2026-10-15 fidelity diagnostic: the nervosity brake ("trop nerveux") was ON from the restart that loaded ab1bebc/
    # c752a7c until the restart that loaded the "sans frein" package (its first and last refusals: 09-19 15:42 / 09-22 02:13)
    (utc("2026-09-18T08:45:55"), {"nerv_gate": 1}, "ab1bebc/c752a7c loaded at the 08:45 restart: nervosity brake ON (no entry above 1.0x)"),
    (utc("2026-09-22T14:37:51"), {"nerv_gate": 0}, "restart with the package's 'sans frein nervosite': brake OFF"),
    (utc("2026-09-21T09:02:45"), {"storm": 1.85}, "b944516: storm exception, no entry at nervosity >= 1.85"),
    (utc("2026-09-23T12:51:03"), {"k_streak": 2}, "fed021c: no recovery bullets after 2 straight losses"),
    (utc("2026-09-24T04:18:58"), {"scale_daily": 1}, "1e75d50: lot and day cap scaled with the balance (ref 200) at each day roll"),
    (utc("2026-09-24T11:25:14"), {"cap_rule": "adaptive"}, "db3db14/db1a3e3: adaptive debt-day cap replaces the unlimited waiver (bonus capped 5x)"),
    (utc("2026-09-24T19:38:18"), {"debt_gate": 1, "n_cont": 0}, "87646f1: in debt, FLIP-BOS entries only"),
    (utc("2026-09-25T14:05:04"), {"n_cont": 1}, "827fb9c: one continuation after the flip during recovery"),
    (utc("2026-09-27T00:47:54"), {"touch_rearm": 1}, "8fe4f35: a touch of the protected dot re-arms the one continuation"),
    (utc("2026-10-01T12:46:40"), {"risk_fit": 3.0}, "43b4092: 3 % per-trade risk ceiling (valere_cap3)"),
    (utc("2026-10-10T08:49:22"), {"gmode": "trend"}, "2b1a602 loaded at the 08:49 restart: pullback-direction gate ON (first refusal 10:08)"),
    (utc("2026-10-10T07:05:31"), {"cap_rule": "off"}, "RECORDED MANUAL OVERRIDE: 'continue today' switch, cap lifted until 23:59 UTC"),
    # 2026-10-15 fidelity diagnostic: until 9ff36ce the bot read the feed's running moves_2h, which had already counted the
    # flip being traded (48ea5b2 made the FEED window strict on 09-22, but the counter it published still included the
    # signal's own mark by the time the bot read it - the 10-12 race). The journal confirms it: 15 real FLIP-BOS entries
    # with movement_count 1-2 where the strict count is 0. Plain BOS are unaffected (marks are flips only).
    (utc("2026-10-12T07:09:27"), {"flip_counts_itself": 0}, "9ff36ce: movement gate strictly BEFORE the signal candle - a flip no longer counts itself"),
]
NOT_MODELLED = ["internal-structure entries ON 2026-09-19 20:01 -> 2026-09-30 17:58 UTC (the engine has no internal path; the real account took 1 such trade, -11.95)",
                "touch entries (enabled on the account; none fired in the period)",
                "recovery adds were placed at the BOS entry before 2026-09-20 12:46 UTC and at the midpoint after; the engine always uses the midpoint",
                "the nervosity brake: today's package has it OFF; the engine runs it OFF throughout (the bot's package history before 09-21 is not reconstructed)",
                "the real broker's fills, slippage, swap and commission; the bot's exact lot arithmetic at each entry"]


def downtime_windows(min_gap_s=300):
    """[(start, end)] when the bot was NOT running: the gap between the last log line before a restart and the restart"""
    from datetime import datetime
    L = open(r"C:\Projects\KinoliveLines\live\bos_bot_valere.log", encoding="utf-8", errors="replace").read().splitlines()
    def ts(l):
        try: return datetime.fromisoformat(l[:32].split(" ")[0]).timestamp()
        except Exception: return None
    prev = None; out = []
    for l in L:
        t = ts(l)
        if t is None: continue
        if "BOS-BOT starting" in l and prev is not None and t - prev > min_gap_s: out.append((prev, t))
        prev = t
    return out


class RealArm(PbGateArm):
    """a pullback-gate arm that follows a dated rule schedule and the bot's downtime"""
    def __init__(self, name, cfg, bars, mode, states, schedule=None, downtime=None, touch_rearm=True, **kw):
        super().__init__(name, cfg, bars, mode, states, **kw)
        self.schedule = sorted(schedule or [], key=lambda x: x[0]); self.sched_i = 0; self.downtime = downtime or []; self.touch_rearm = touch_rearm
        # the real bot's movement gate counted a flip's own break until 9ff36ce (see SCHEDULE); an arm with a dated
        # schedule starts that way, an arm without one runs today's strict rule
        self.flip_counts_itself = bool(schedule)
        self.n.update({"bot_down": 0, "rule_steps": 0})
        self.applied = []

    def apply(self, ts, ch, why):
        for k, v in ch.items():
            if k == "cap_rule": self.cap_rule = v
            elif k == "touch_rearm": self.touch_rearm = bool(v)
            elif k == "flip_counts_itself": self.flip_counts_itself = bool(v)
            elif k == "gmode": self.gmode = v
            elif k == "k_streak": self.c["k_streak"] = v; self.K = int(v)
            elif k == "bullets": self.c["bullets"] = v; self.NB = int(v)
            elif k == "scale_daily":
                self.c["scale_daily"] = v; self.scale = bool(v) and self.bal > 0
                if v:   # from now on the lot and the cap follow the balance at each day roll (live: recomputed at the roll)
                    r = (self.bal + self.run) / float(self.c["scale_ref"]); self.ratio = r
                    self.LOT = max(0.01, int((self.LOT0 * r) / 0.01 + 1e-9) * 0.01); self.day_cap_eff = float(self.c["day_cap"]) * r
            else: self.c[k] = v
        self.n["rule_steps"] += 1; self.applied.append({"t": ts, "changes": ch, "why": why})

    def roll(self, t_ms):
        while self.sched_i < len(self.schedule) and self.schedule[self.sched_i][0] * 1000 <= t_ms:
            ts, ch, why = self.schedule[self.sched_i]; self.apply(ts, ch, why); self.sched_i += 1
        super().roll(t_ms)

    def signal(self, o, k, TM, BID, ASK):
        t_ms = int(TM[k])
        for a, b in self.downtime:
            if a * 1000 <= t_ms < b * 1000: self.n["bot_down"] += 1; return
        if self.flip_counts_itself and o.get("flip") and o.get("mv2") is not None:
            o = dict(o, mv2=int(o["mv2"]) + 1)
        return super().signal(o, k, TM, BID, ASK)


def merged_ticks(dirs, t0_ms, end_ms):
    TMs, Bs, As = [], [], []; bad = 0
    for d in dirs:
        if not os.path.exists(os.path.join(d, "manifest.json")): continue
        a = E.load_ticks(d, t0_ms, end_ms); TMs.append(a[0]); Bs.append(a[1]); As.append(a[2]); bad += a[3]
    TM = np.concatenate(TMs); BID = np.concatenate(Bs); ASK = np.concatenate(As)
    o = np.argsort(TM, kind="stable"); TM, BID, ASK = TM[o], BID[o], ASK[o]
    keep = np.concatenate([[True], np.diff(TM) > 0]); return TM[keep], BID[keep], ASK[keep], bad


def coverage(TM, start_s, end_s):
    covd = {}; dd = start_s - start_s % 86400
    while dd < end_s:
        lo, hi = max(dd, start_s) * 1000, min(dd + 86400, end_s) * 1000; sel = (TM >= lo) & (TM < hi); t = TM[sel]
        mins = int((hi - lo) // 60000) or 1; buckets = len(np.unique((t - lo) // 60000)) if len(t) else 0
        gaps = np.diff(t) if len(t) > 1 else np.array([0]); mg = max(int(gaps.max()) if len(t) > 1 else 0, int(t[0] - lo) if len(t) else int(hi - lo), int(hi - t[-1]) if len(t) else 0)
        covd[time.strftime("%Y-%m-%d", time.gmtime(dd))] = {"minute_share": round(buckets / mins, 4), "max_gap_s": round(mg / 1000.0, 1), "ticks": int(len(t)), "covered": bool(buckets / mins >= 0.97 and mg <= 120000)}
        dd += 86400
    return covd


def sticky_states(RW, off, opp_idx, fp):
    try:
        cached = pickle.load(open(CACHE, "rb"))
        if cached.get("fingerprint") == fp and all(i in cached["states"] for i in opp_idx): print("structure cache reused", fp, flush=True); return cached["states"]
    except Exception:
        pass
    S = set(); states = {}; t0 = time.time(); want = set(opp_idx)
    for i in range(WIN - 1, len(RW)):
        kept = F.build(RW[i - WIN + 1:i + 1])
        if len(kept) < 3: continue
        bk = []; dots, marks, trend, *_ = F.engine(kept, brk_out=bk)
        if trend: dots = [d for d in dots if d[2] == trend]
        S |= {t for t in ({d[0] for d in dots} | {m[0] for m in marks} | {b[0] for b in bk}) if t < kept[-1][0]}
        S = {t for t in S if t >= kept[0][0]}
        j = i - off
        if j in want:
            try: states[j] = K.pb_view_sticky(kept, dots, marks, bk, S)
            except Exception: states[j] = (0, 0, None, None)
        if (i - WIN + 1) % 4000 == 0: print("causal sticky walk %d / %d (%.0fs)" % (i - WIN + 1, len(RW) - WIN + 1, time.time() - t0), flush=True)
    pickle.dump({"fingerprint": fp, "states": states}, open(CACHE, "wb")); return states


def run(arms, TM, BID, ASK, END, opps, bars, start_ms):
    elig = [((o["t"] + 60) * 1000 + E.SIGNAL_MS, o) for o in opps if (o["t"] + 60) * 1000 + E.SIGNAL_MS >= start_ms]; ei = 0
    touches = sorted((t * 1000 + 60000, 1) for t, (touched, nv) in bars.items() if touched); ti = 0
    n = len(TM); prev = int(start_ms)
    for kk in range(n):
        t_ms = int(TM[kk]); gap_in = t_ms - prev; prev = t_ms
        for arm in arms: arm.roll(t_ms)
        while ti < len(touches) and touches[ti][0] <= t_ms:
            ti += 1
            for arm in arms:
                if getattr(arm, "touch_rearm", True) and arm.last_flip_t is not None and arm.cont_left < int(arm.c["n_cont"]): arm.cont_left = min(int(arm.c["n_cont"]), arm.cont_left + 1)
        while ei < len(elig) and elig[ei][0] <= t_ms:
            o = elig[ei][1]; ei += 1
            for arm in arms: arm.signal(o, kk, TM, BID, ASK)
        for arm in arms: arm.tick(kk, TM, BID, ASK, gap_in)
    T1 = int(TM[-1]); TMID = (int(start_ms) + T1) // 2
    out = {}
    for arm in arms:
        out[arm.name] = summarise(arm, TM, BID, ASK, END, TMID)
        out[arm.name]["open_at_cutoff"] = ({"d": arm.pos["d"], "e": round(arm.pos["e"], 2), "lot": arm.pos["lot"], "adds": len(arm.pos["adds"]), "mtm": round(out[arm.name]["net_with_open_mtm"] - out[arm.name]["net"], 2)} if arm.pos else None)
        out[arm.name]["rule_steps_applied"] = getattr(arm, "applied", [])
    return out


def ledger(cut_s):
    d = json.load(open(r"C:\Projects\KinoliveLines\live\lab\wealth\%s.json" % UID, encoding="utf-8"))
    legs = [t for t in d["trades"] if t[0] <= cut_s]
    grp = []
    for t in sorted(legs):
        if grp and abs(t[0] - grp[-1]["tc"]) <= 90 and t[3] == grp[-1]["d"]: grp[-1]["pnl"] += t[1]; grp[-1]["legs"] += 1; grp[-1]["lot"] += t[2]
        else: grp.append({"tc": t[0], "d": t[3], "pnl": t[1], "legs": 1, "lot": t[2], "minutes": t[4]})
    def st(rows, key):
        pn = [r[key] if isinstance(r, dict) else r[1] for r in rows]; w = sum(1 for p in pn if p > 0); gw = sum(p for p in pn if p > 0); gl = -sum(p for p in pn if p < 0); c = pk = dd = 0.0
        for p in pn: c += p; pk = max(pk, c); dd = max(dd, pk - c)
        return {"n": len(pn), "winners_net_positive": w, "win_rate": round(w / len(pn), 4) if pn else None, "profit_factor": round(gw / gl, 3) if gl else None, "net": round(sum(pn), 2), "closed_dd": round(dd, 2)}
    return {"era": d["era"], "bal_start": d["bal_start"], "balance_now": d["balance"], "flows": d["flows"], "others": d["others"],
            "legs": st(legs, 1), "grouped": st(grp, "pnl"), "groups_with_adds": sum(1 for g in grp if g["legs"] > 1),
            "first_close": legs[0][0] if legs else None, "last_close": legs[-1][0] if legs else None, "lots": sorted(set(round(t[2], 2) for t in legs)),
            "after_cutoff": {"legs": len(d["trades"]) - len(legs), "net": round(sum(t[1] for t in d["trades"] if t[0] > cut_s), 2)}, "groups": grp}


def write_csvs(res):
    os.makedirs(REVIEW, exist_ok=True)
    for drag, row in res["rows"].items():
        for name, a in row["arms"].items():
            fn = os.path.join(REVIEW, "valere_replay_%s_drag%s.csv" % (name, drag.replace(".", "")))
            with open(fn, "w", newline="", encoding="utf-8") as fh:
                w = csv.writer(fh); w.writerow(["signal_utc", "entry_utc", "exit_utc", "side", "lot", "entry", "stop", "target", "adds", "pnl_main", "pnl_adds", "pnl", "win", "gap_flag"])
                for t in a["trades_list"]:
                    w.writerow([time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(t["t"])), time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime((t.get("fill_ms") or 0) / 1000)) if t.get("fill_ms") else "",
                                time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(t["tc"] / 1000)), "BUY" if t["d"] == 1 else "SELL", t["lot"], t["e"], t["sl"], t["tp"], t["adds"], t["pnl_main"], t["pnl_add"], t["pnl"], int(t["win"]), int(t["gap_max_ms"] > 5000)])
    with open(os.path.join(REVIEW, "valere_actual_ledger_grouped.csv"), "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh); w.writerow(["close_utc", "side", "legs", "lots_total", "pnl", "minutes_open_first_leg"])
        for g in res["actual_ledger"]["groups"]: w.writerow([time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(g["tc"])), "BUY" if g["d"] == 1 else "SELL", g["legs"], round(g["lot"], 2), round(g["pnl"], 2), g["minutes"]])


def match(engine_trades, groups, tol_s=600):
    """pair engine trades with real grouped trades by close time (+/- tol) and side"""
    used = set(); pairs = []; un_e = []
    for t in engine_trades:
        best = None; bd = tol_s + 1
        for i, g in enumerate(groups):
            if i in used or g["d"] != t["d"]: continue
            dd = abs(g["tc"] - t["tc"] / 1000)
            if dd < bd: bd, best = dd, i
        if best is not None: used.add(best); pairs.append((t, groups[best], bd))
        else: un_e.append(t)
    un_g = [g for i, g in enumerate(groups) if i not in used]
    return {"paired": len(pairs), "engine_only": len(un_e), "real_only": len(un_g), "paired_pnl_engine": round(sum(p[0]["pnl"] for p in pairs), 2), "paired_pnl_real": round(sum(p[1]["pnl"] for p in pairs), 2),
            "engine_only_pnl": round(sum(t["pnl"] for t in un_e), 2), "real_only_pnl": round(sum(g["pnl"] for g in un_g), 2), "median_close_offset_s": (sorted(p[2] for p in pairs)[len(pairs) // 2] if pairs else None)}


if __name__ == "__main__":
    K.install_nopause_gate()
    start_s = utc(START); start_ms = start_s * 1000
    bm = json.load(open(os.path.join(HERE, "bars_%s.json" % UID))); RB = np.load(os.path.join(HERE, "bars_%s.npz" % UID))["R"]
    assert int(RB["time"][0]) <= start_s - WIN * 60, "bars must start at least 8000 minutes before the bot start"
    dirs = [os.path.join(HERE, "ticks_%s" % UID), os.path.join(HERE, "ticks_%s_forward" % UID)]
    TM, BID, ASK, n_bad = merged_ticks(dirs, start_ms, 4_000_000_000_000)
    if not len(TM): raise SystemExit("no ticks of the account in the period")
    END = int(TM[-1]) + 1; end_s = END // 1000
    RB = RB[RB["time"] < end_s]
    first_tick_s = int(TM[0]) // 1000
    print("period %s -> %s UTC | own ticks %d (first %s), invalid dropped %d | bars %d (%s -> %s)" % (time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(start_s)), time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(end_s)),
          len(TM), time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(first_tick_s)), n_bad, len(RB), bm["first_utc"], bm["last_utc"]), flush=True)
    covd = coverage(TM, start_s, end_s); n_cov = sum(1 for v in covd.values() if v["covered"]); print("coverage %d / %d days" % (n_cov, len(covd)), flush=True)
    down = downtime_windows(); down_s = sum(b - a for a, b in down)
    # opportunities on the account's own bars, with the warm-up inside the same array
    k0 = int(np.searchsorted(RB["time"], start_s - WIN * 60)); R_all = RB[k0:]; W_off = int(np.searchsorted(R_all["time"], start_s)) - WIN + 1
    cfg_snap, rep = E.effective_cfg(E.PR[UID], BAL0, 0.0); opps, bars = E.streams(cfg_snap, R_all)
    fp = hashlib.sha256((bm["sha256"] + str(WIN) + hashlib.sha256(open(F.__file__, "rb").read()).hexdigest() + inspect.getsource(K.pb_view_sticky) + inspect.getsource(sticky_states)).encode()).hexdigest()[:16]
    S_idx = sticky_states(R_all, 0, [o["i"] for o in opps if (o["t"] + 60) * 1000 + E.SIGNAL_MS >= start_ms], fp)
    S = {o["t"]: S_idx.get(o["i"], (0, 0, None, None)) for o in opps}
    n_sc = sum(1 for o in opps if (o["t"] + 60) * 1000 + E.SIGNAL_MS >= start_ms)
    print("opportunities in the period %d; with a pullback trend %d; bot downtime %d windows, %.1f h" % (n_sc, sum(1 for o in opps if (o["t"] + 60) * 1000 + E.SIGNAL_MS >= start_ms and S[o["t"]][0] != 0), len(down), down_s / 3600), flush=True)
    res = {"generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "account": {"nest_id": UID, "login": LOGIN, "server": "Exness-MT5Real30", "symbol": bm["symbol"], "package_today": E.PR[UID].get("label")},
           "period": {"start_utc": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(start_s)), "end_utc": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(end_s)), "first_own_tick_utc": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(first_tick_s)), "days": round((end_s - start_s) / 86400, 2)},
           "quotes": {"source": "the account's OWN terminal (Exness-MT5Real30 BTCUSD), bid/ask ticks", "ticks": int(len(TM)), "invalid_dropped": n_bad, "coverage": covd, "days_covered": n_cov},
           "bars": bm, "structure_fingerprint": fp, "schedule": [{"t_utc": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(t)), "changes": c, "why": w} for t, c, w in SCHEDULE],
           "downtime": {"windows": [(time.strftime("%Y-%m-%d %H:%M", time.gmtime(a)), time.strftime("%Y-%m-%d %H:%M", time.gmtime(b)), round((b - a) / 60)) for a, b in down], "hours": round(down_s / 3600, 1)},
           "not_modelled": NOT_MODELLED, "assumptions": ["cold-flat at the bot's first start with $210.00; no deposits / withdrawals (none happened)",
                                                         "signals during the bot's recorded downtime are not traded by any arm; open positions keep running (the broker held them)",
                                                         "the recorded manual override is modelled as 'no daily cap' from 2026-10-10 07:05 UTC to the cutoff; the today_rules arms have NO override",
                                                         "today's package = the valere_cap3 snapshot; its only difference from today's live dials is the pullback gate, which is the filter arm"],
           "actual_ledger": ledger(end_s), "rows": {}}
    cfg_start = dict(cfg_snap); cfg_start.update({"day_cap": 3.0, "debt_gate": 0, "n_cont": 0, "jar": 0, "k_streak": 99, "storm": 99.0, "risk_fit": 0.0, "hard_cap_pct": 0.0, "scale_daily": 0})
    for drag in (0.0, 0.35):
        cs, _ = E.effective_cfg(E.PR[UID], BAL0, drag); c0 = dict(cs); c0.update({"day_cap": 3.0, "debt_gate": 0, "n_cont": 0, "jar": 0, "k_streak": 99, "storm": 99.0, "risk_fit": 0.0, "hard_cap_pct": 0.0, "scale_daily": 0})
        t0 = time.time()
        arms = [RealArm("actual_rules", c0, bars, "none", S, schedule=SCHEDULE, downtime=down, touch_rearm=False, order="live", cap_rule="waiver"),
                RealArm("actual_rules_filter", dict(c0), bars, "trend", S, schedule=SCHEDULE, downtime=down, touch_rearm=False, order="live", cap_rule="waiver"),
                RealArm("today_rules", dict(cs), bars, "none", S, schedule=[], downtime=down, touch_rearm=True, order="live", cap_rule="adaptive"),
                RealArm("today_rules_filter", dict(cs), bars, "trend", S, schedule=[], downtime=down, touch_rearm=True, order="live", cap_rule="adaptive")]
        out = run(arms, TM, BID, ASK, END, opps, bars, start_ms)
        res["rows"]["%.2f" % drag] = {"arms": out, "match_vs_ledger": {n: match(out[n]["trades_list"], res["actual_ledger"]["groups"]) for n in out}}
        for name, a in out.items():
            c = a["counts"]
            print("drag %.2f %-20s | net %8.2f (+open %6.2f) cc_dd %7.2f mtm_dd %7.2f | trades %3d wins %3d wr %s pf %s | h1 %7.2f h2 %7.2f | pb refused dir %d wrong %d none %d nolast %d | weather %d debt-gate %d day-cap %d bot-down %d | match: paired %d engine-only %d real-only %d | %.0fs" % (
                drag, name, a["net"], a["net_with_open_mtm"] - a["net"], a["cc_dd"], a["mtm_dd"], a["trades"], a["wins"], a["win_rate"], a["profit_factor"], a["first_half"], a["later_half"],
                c.get("pb_against_structure", 0), c.get("pb_paused_wrong_side", 0), c.get("pb_no_structure", 0), c.get("pb_no_last_bos", 0), c.get("weather", 0), c.get("debt_gate", 0), c.get("day_cap", 0), c.get("bot_down", 0),
                res["rows"]["%.2f" % drag]["match_vs_ledger"][name]["paired"], res["rows"]["%.2f" % drag]["match_vs_ledger"][name]["engine_only"], res["rows"]["%.2f" % drag]["match_vs_ledger"][name]["real_only"], time.time() - t0), flush=True)
        json.dump(res, open(OUT, "w"), indent=1)
    write_csvs(res)
    print("DONE", flush=True)
