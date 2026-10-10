"""Stage 1 (revised brief 2026-10-10): the fixed 12-cell development matrix on the three-arm
tick engine, run as 13 independently evolving arms on one clock (12 cells + the old half-MAIN
attribution control), per regime and cost basis. The engine itself is untouched (subclass).

  entry      : immediate | delay_debt (midpoint delay only while debt > $0.50 - the nominated
               candidate) | delay_always (midpoint delay for every eligible MAIN entry)
  allowance  : current (FLIP + 1 continuation, dot-touch re-arm, while in debt) | all_bos (every
               otherwise eligible confirmed MAIN BOS while in debt; all other gates kept)
  cap        : on (package day cap, waived in debt) | off (no realised-profit daily stop; day
               accounting and scaling unchanged)

Cells where the package already has no debt gate or no cap are duplicates and are marked so.
    python tick_engine_matrix.py [regime ...]      (rows cached per regime/drag in tick_engine_matrix.json)
"""
import sys, os, json, time, math, itertools
ARGS = list(sys.argv); sys.argv = ["x"]
sys.path.insert(0, r"C:\Projects\KinoliveLines\study")
import tick_engine as E
S_MIN_DIST, EXEC_MS, SIGNAL_MS = E.S_MIN_DIST, E.EXEC_MS, E.SIGNAL_MS
POLICIES = [{"entry": e, "allowance": a, "cap": c} for e in ("immediate", "delay_debt", "delay_always") for a in ("current", "all_bos") for c in ("on", "off")]
NAME = lambda p: "%s|%s|cap_%s" % (p["entry"], p["allowance"], p["cap"])


DEBT_CAP_MIN_SAMPLES, DEBT_CAP_WINDOW, DEBT_CAP_BONUS_MULT = 3, 40, 5   # structure_bos_bot.py constants, copied (change the two together)


class PolicyArm(E.Arm):
    """order (GPT review of reply 18, item 3):
         "review16" - kill, awake, dedupe, weather, allowance, day cap, geometry, hook   (the frozen study's convention)
         "live"     - the live enter() order: kill, awake, dedupe (the loop), allowance (consumed), the hook (pullback
                      filter), weather, day cap, geometry. A weather- or cap-refused signal has consumed the allowance,
                      exactly as live.
       cap_rule (item 1):
         "waiver"   - the harness mirror: no cap at all while debt > $0.50
         "adaptive" - live effective_cap_today(): in debt the cap is the sized cap + bonus, bonus = clamp(median of this
                      arm's own last 40 debt-day results, 0, 5 x cap); unrestricted only while fewer than 3 such days
                      exist (cold start, explicit); each arm keeps its own history (debt at day open, debt-day P&L)."""
    def __init__(self, name, cfg, policy, bars, order="review16", cap_rule="waiver"):
        super().__init__(name, cfg, "delayed" if policy["entry"] != "immediate" else "base", bars)
        self.policy = policy; self.gate_order = order; self.cap_rule = cap_rule
        self.debt_day_pnls = []; self.debt_at_day_open = 0.0
        self.n.update({"admitted_by_allowance": 0, "cap_waived_off": 0, "signals_in_debt": 0, "signals_out_debt": 0, "delayed_out_debt": 0, "delayed_in_debt": 0,
                       "cap_unrestricted_cold": 0, "cap_bonus_refusals": 0, "cap_plain_refusals": 0, "cap_bonus_passes": 0})
        self.admitted = []          # extra signals the all_bos allowance admitted: (t, ordinal since flip, debt at signal)

    def roll(self, t_ms):
        """the live day_roll(): at the UTC day change, a day that OPENED in debt records its realised P&L in the
        debt-day history (window 40); the debt at the new day's open is remembered for tomorrow's test"""
        before = self.day_key; day_profit_before = self.day_profit
        super().roll(t_ms)
        if self.day_key != before:
            if before is not None and self.debt_at_day_open > 0.5:
                self.debt_day_pnls.append(day_profit_before); del self.debt_day_pnls[:-DEBT_CAP_WINDOW]
            self.debt_at_day_open = self.debt()

    def cap_today(self, debt_now):
        """the enforced day target right now, or None = unrestricted (live effective_cap_today, adaptive rule)"""
        if not self.day_cap_eff: return None
        cap = float(self.day_cap_eff)
        if self.cap_rule == "adaptive":
            if debt_now > 0.5 and self.c.get("day_cap_waived", 1):
                vals = self.debt_day_pnls
                if len(vals) < DEBT_CAP_MIN_SAMPLES: return None
                sv = sorted(vals); n = len(sv); med = sv[n // 2] if n % 2 else (sv[n // 2 - 1] + sv[n // 2]) / 2.0
                return cap + min(max(0.0, med), DEBT_CAP_BONUS_MULT * cap)
            return cap
        return None if debt_now > 0.5 else cap        # "waiver": the harness mirror

    def cap_gate(self, debt_now):
        """True = refused by the day cap"""
        p = self.policy
        if not self.day_cap_eff: return False
        if p["cap"] == "off":
            if self.day_profit >= float(self.day_cap_eff): self.n["cap_waived_off"] += 1
            return False
        cap = self.cap_today(debt_now)
        if cap is None:
            if debt_now > 0.5 and self.cap_rule == "adaptive": self.n["cap_unrestricted_cold"] += 1
            return False
        if self.day_profit >= cap:
            self.n["day_cap"] += 1
            if debt_now > 0.5 and self.cap_rule == "adaptive": self.n["cap_bonus_refusals"] += 1
            else: self.n["cap_plain_refusals"] += 1
            return True
        if debt_now > 0.5 and self.cap_rule == "adaptive" and self.day_profit >= float(self.day_cap_eff): self.n["cap_bonus_passes"] += 1
        return False

    # review 16: ONE ordered pipeline for every arm, no double mutation:
    #   state checks (position / pending / dead)  ->  ordinary gates WITH their state updates
    #   (kill, awake, used-level dedupe, weather, continuation allowance, day cap)  ->  geometry
    #   ->  the arm's gate hook (Compte pause, pullback gate, thinning: see subclasses)  ->  setup.
    # Frozen convention: a signal refused by the HOOK has already consumed the used level and the
    # continuation allowance exactly as the live enter() does before its late gates; nothing else.
    def ordinary_gates(self, o, k, TM, BID, ASK):
        """apply the ordinary gates and their state updates; returns debt_now or None (refused)"""
        c = self.c; t = o["t"]; p = self.policy
        if c["kill_net"] and self.run <= float(c["kill_net"]):
            self.dead = True; self.n["kills"] += 1; self.events.append({"t": t, "ev": "KILL", "run": round(self.run, 2)}); return None
        if not o["awake"]: self.n["not_awake"] += 1; return None
        d, slp, flip, lvl = o["d"], o["slp"], o["flip"], o["lvl"]
        if not flip:
            if (d == 1 and self.used_hi == lvl) or (d == -1 and self.used_lo == lvl): self.n["dedupe"] += 1; return None
            if d == 1: self.used_hi = lvl
            else: self.used_lo = lvl
        if o["mv2"] is not None:
            if o["nv"] >= float(c["storm"]) or (c["movement"] and o["mv2"] < 1): self.n["weather"] += 1; return None
            if c["nerv_gate"] and o["nv"] > 1.0: self.n["weather"] += 1; return None
        debt_now = self.debt()
        self.n["signals_in_debt" if debt_now > 0.5 else "signals_out_debt"] += 1
        # the ARM's eligible-signal ordinal since its last flip (1 = the flip itself); signals that this
        # arm skipped while a position or a setup was open are NOT counted - not the structural ordinal
        self.ord = (1 if flip else getattr(self, "ord", 0) + 1)
        if flip:
            self.last_flip_t = t; self.cont_left = int(c["n_cont"])
        elif debt_now > 0.5 and c.get("debt_gate", 1):
            if self.cont_left > 0 and self.last_flip_t is not None: self.cont_left -= 1
            elif p["allowance"] == "all_bos":
                self.n["admitted_by_allowance"] += 1; self.admitted.append({"t": t, "ordinal": self.ord, "debt": round(debt_now, 2)})
            else: self.n["debt_gate"] += 1; return None
        if self.cap_gate(debt_now): return None
        return debt_now

    def early_gates(self, o, k, TM, BID, ASK):
        """live order, part 1: kill, awake, dedupe (the bot's loop), then the recovery allowance (consumed inside
        enter() before anything else); returns debt_now or None"""
        c = self.c; t = o["t"]; p = self.policy
        if c["kill_net"] and self.run <= float(c["kill_net"]):
            self.dead = True; self.n["kills"] += 1; self.events.append({"t": t, "ev": "KILL", "run": round(self.run, 2)}); return None
        if not o["awake"]: self.n["not_awake"] += 1; return None
        d, slp, flip, lvl = o["d"], o["slp"], o["flip"], o["lvl"]
        if not flip:
            if (d == 1 and self.used_hi == lvl) or (d == -1 and self.used_lo == lvl): self.n["dedupe"] += 1; return None
            if d == 1: self.used_hi = lvl
            else: self.used_lo = lvl
        debt_now = self.debt()
        self.n["signals_in_debt" if debt_now > 0.5 else "signals_out_debt"] += 1
        self.ord = (1 if flip else getattr(self, "ord", 0) + 1)
        if flip:
            self.last_flip_t = t; self.cont_left = int(c["n_cont"])
        elif debt_now > 0.5 and c.get("debt_gate", 1):
            if self.cont_left > 0 and self.last_flip_t is not None: self.cont_left -= 1
            elif p["allowance"] == "all_bos":
                self.n["admitted_by_allowance"] += 1; self.admitted.append({"t": t, "ordinal": self.ord, "debt": round(debt_now, 2)})
            else: self.n["debt_gate"] += 1; return None
        return debt_now

    def late_gates(self, o, debt_now):
        """live order, part 2 (after the hook): weather, then the day cap; True = refused"""
        c = self.c
        if o["mv2"] is not None:
            if o["nv"] >= float(c["storm"]) or (c["movement"] and o["mv2"] < 1): self.n["weather"] += 1; return True
            if c["nerv_gate"] and o["nv"] > 1.0: self.n["weather"] += 1; return True
        return self.cap_gate(debt_now)

    def gate_hook(self, o, k, TM, BID, ASK, setup, debt_now):
        """the arm's late gate, immediately before the setup is created; True = go"""
        return True

    def signal(self, o, k, TM, BID, ASK):
        c = self.c; t = o["t"]; p = self.policy; self.n["signals"] += 1
        if self.pos is not None or self.order is not None: self.n["skipped_open"] += 1; return
        if self.pend is not None: self.n["skipped_pending"] += 1; return
        if self.dead: self.n["skipped_dead"] += 1; return
        d, slp, flip = o["d"], o["slp"], o["flip"]
        e0 = ASK[k] if d == 1 else BID[k]
        lot = self.LOT
        if self.gate_order == "live":
            debt_now = self.early_gates(o, k, TM, BID, ASK)
            if debt_now is None: return
            if not self.gate_hook(o, k, TM, BID, ASK, {"t": t, "d": d, "e0": float(e0), "slp": float(slp), "flip": flip}, debt_now): return
            if self.late_gates(o, debt_now): return
        else:
            debt_now = self.ordinary_gates(o, k, TM, BID, ASK)
            if debt_now is None: return
        dist0 = abs(e0 - slp)
        if dist0 <= S_MIN_DIST: self.n["min_dist"] += 1; return
        setup = {"t": t, "d": d, "slp": float(slp), "e0": float(e0), "dist0": float(dist0), "tp0": float(e0 + d * self.rr * dist0), "mid0": float(e0 - d * dist0 / 2.0),
                 "lot_req": lot, "nv": o["nv"], "k_sig": k, "gap_max": 0, "flip": flip, "debt_at_signal": round(debt_now, 2), "ordinal": self.ord}
        if self.gate_order != "live" and not self.gate_hook(o, k, TM, BID, ASK, setup, debt_now): return
        delay = p["entry"] == "delay_always" or (p["entry"] == "delay_debt" and debt_now > 0.5)
        if delay:
            self.pend = setup; self.n["setups"] += 1; self.n["delayed_in_debt" if debt_now > 0.5 else "delayed_out_debt"] += 1
            self.events.append({"t": t, "ev": "PENDING", "mid": round(setup["mid0"], 2), "sl": round(slp, 2), "tp": round(setup["tp0"], 2), "lot": lot, "debt": round(debt_now, 2)})
            return
        self.order = {"kind": "main", "due": int(TM[k]) + EXEC_MS, "setup": setup, "frozen": False}; self.n["orders"] += 1


def run_matrix(uid, drag, TM, BID, ASK, END, opps, bars):
    cfg, rep = E.effective_cfg(E.PR[uid], E.REGIMES[uid], drag)
    arms = [PolicyArm(NAME(p), cfg, p, bars) for p in POLICIES] + [E.Arm("half_main", cfg, "half", bars)]
    elig = [((o["t"] + 60) * 1000 + SIGNAL_MS, o) for o in opps]; ei = 0
    touches = sorted((t * 1000 + 60000, 1) for t, (touched, nv) in bars.items() if touched); ti = 0
    n = len(TM); prev = int(TM[0])
    for k in range(n):
        t_ms = int(TM[k]); gap_in = t_ms - prev; prev = t_ms
        for arm in arms: arm.roll(t_ms)
        while ti < len(touches) and touches[ti][0] <= t_ms:
            ti += 1
            for arm in arms:
                if arm.last_flip_t is not None and arm.cont_left < int(arm.c["n_cont"]):
                    arm.cont_left = min(int(arm.c["n_cont"]), arm.cont_left + 1)
        while ei < len(elig) and elig[ei][0] <= t_ms:
            o = elig[ei][1]; ei += 1
            for arm in arms: arm.signal(o, k, TM, BID, ASK)
        for arm in arms: arm.tick(k, TM, BID, ASK, gap_in)
    out = {}
    T1 = int(TM[-1]); TMID = (int(TM[0]) + T1) // 2
    dup = {"no_debt_gate": not cfg.get("debt_gate", 1), "no_cap": not bool(cfg["day_cap"])}
    for arm in arms:
        mtm_open = arm.finish(TM, BID, ASK, END); tr = arm.trades
        out[arm.name] = {"net": round(arm.run, 2), "net_with_open_mtm": round(arm.run + mtm_open, 2), "cc_dd": round(E.dd_of(arm.pnls), 2), "mtm_dd": round(arm.mtm_dd, 2),
                         "trades": len(tr), "wins": arm.wins, "pnl_main": round(sum(x["pnl_main"] for x in tr), 2), "pnl_add": round(sum(x["pnl_add"] for x in tr), 2),
                         "risk_main": round(sum(x["risk"] for x in tr), 2), "adds": sum(x["adds"] for x in tr),
                         "first_half": round(sum(x["pnl"] for x in tr if x["tc"] < TMID), 2), "later_half": round(sum(x["pnl"] for x in tr if x["tc"] >= TMID), 2),
                         "gap_flagged_trades": arm.n["trades_gap_flag"], "gap_unresolved_trades": arm.n["trades_gap_unresolved"],
                         "wait_s_median": (sorted(arm.n["wait_s"])[len(arm.n["wait_s"]) // 2] if arm.n["wait_s"] else None),
                         "counts": {k: v for k, v in arm.n.items() if k != "wait_s"}, "policy": getattr(arm, "policy", {"entry": "immediate", "allowance": "current", "cap": "on", "control": "half_main"}),
                         "admitted": getattr(arm, "admitted", [])[:200], "trades_list": tr, "events": arm.events[:300]}
        # money of the trades the all_bos allowance admitted (attribution inside the path, not standalone value)
        if getattr(arm, "admitted", None):
            at = {a["t"] for a in arm.admitted}
            out[arm.name]["admitted_money"] = {"n_traded": sum(1 for x in tr if x["t"] in at), "pnl": round(sum(x["pnl"] for x in tr if x["t"] in at), 2),
                                               "pnl_main": round(sum(x["pnl_main"] for x in tr if x["t"] in at), 2)}
    return out, rep, dup


def summarise(arm, TM, BID, ASK, END, TMID):
    """one arm's result row (review 17: shared by run_matrix's twin run_cells and the frozen runner)"""
    mtm_open = arm.finish(TM, BID, ASK, END); tr = arm.trades
    gw = sum(x["pnl"] for x in tr if x["pnl"] > 0); gl = -sum(x["pnl"] for x in tr if x["pnl"] < 0)
    row = {"net": round(arm.run, 2), "net_with_open_mtm": round(arm.run + mtm_open, 2), "cc_dd": round(E.dd_of(arm.pnls), 2), "mtm_dd": round(arm.mtm_dd, 2),
           "trades": len(tr), "wins": arm.wins, "win_rate": round(arm.wins / len(tr), 4) if tr else None,
           "profit_factor": (round(gw / gl, 3) if gl > 0 else (None if gw == 0 else float("inf"))), "gross_win": round(gw, 2), "gross_loss": round(gl, 2),
           "pnl_main": round(sum(x["pnl_main"] for x in tr), 2), "pnl_add": round(sum(x["pnl_add"] for x in tr), 2),
           "risk_main": round(sum(x["risk"] for x in tr), 2), "adds": sum(x["adds"] for x in tr),
           "first_half": round(sum(x["pnl"] for x in tr if x["tc"] < TMID), 2), "later_half": round(sum(x["pnl"] for x in tr if x["tc"] >= TMID), 2),
           "missed_winners": arm.n["missed_win"], "gap_flagged_trades": arm.n["trades_gap_flag"], "gap_unresolved_trades": arm.n["trades_gap_unresolved"],
           "wait_s_median": (sorted(arm.n["wait_s"])[len(arm.n["wait_s"]) // 2] if arm.n["wait_s"] else None),
           "counts": {k: v for k, v in arm.n.items() if k != "wait_s"}, "policy": getattr(arm, "policy", {"entry": "immediate", "allowance": "current", "cap": "on", "control": arm.name}),
           "admitted": getattr(arm, "admitted", [])[:200], "trades_list": tr, "events": arm.events[:300]}
    if getattr(arm, "admitted", None):
        at = {a["t"] for a in arm.admitted}
        row["admitted_money"] = {"n_traded": sum(1 for x in tr if x["t"] in at), "pnl": round(sum(x["pnl"] for x in tr if x["t"] in at), 2),
                                 "pnl_main": round(sum(x["pnl_main"] for x in tr if x["t"] in at), 2)}
    return row


def run_cells(uid, drag, TM, BID, ASK, END, opps, bars, cells, start_ms=None, balance=None, with_half=False):
    """review 17: the chosen cells (policy names, e.g. "delay_always|all_bos|cap_on") in SCORED mode with exactly
    tick_engine.run_regime's semantics - signals eligible before start_ms are not traded (structural warm-up only),
    the first incoming gap is measured from start_ms, every arm starts cold-flat, balance overrides the development one."""
    cfg, rep = E.effective_cfg(E.PR[uid], E.REGIMES[uid] if balance is None else balance, drag)
    pol = {NAME(p): p for p in POLICIES}
    arms = [PolicyArm(c, cfg, pol[c], bars) for c in cells] + ([E.Arm("half_main", cfg, "half", bars)] if with_half else [])
    elig = [((o["t"] + 60) * 1000 + SIGNAL_MS, o) for o in opps if start_ms is None or (o["t"] + 60) * 1000 + SIGNAL_MS >= start_ms]; ei = 0
    touches = sorted((t * 1000 + 60000, 1) for t, (touched, nv) in bars.items() if touched); ti = 0
    n = len(TM); prev = int(TM[0]) if start_ms is None else int(start_ms)
    for k in range(n):
        t_ms = int(TM[k]); gap_in = t_ms - prev; prev = t_ms
        for arm in arms: arm.roll(t_ms)
        while ti < len(touches) and touches[ti][0] <= t_ms:
            ti += 1
            for arm in arms:
                if arm.last_flip_t is not None and arm.cont_left < int(arm.c["n_cont"]):
                    arm.cont_left = min(int(arm.c["n_cont"]), arm.cont_left + 1)
        while ei < len(elig) and elig[ei][0] <= t_ms:
            o = elig[ei][1]; ei += 1
            for arm in arms: arm.signal(o, k, TM, BID, ASK)
        for arm in arms: arm.tick(k, TM, BID, ASK, gap_in)
    T1 = int(TM[-1]); TMID = ((int(TM[0]) if start_ms is None else int(start_ms)) + T1) // 2
    dup = {"no_debt_gate": not cfg.get("debt_gate", 1), "no_cap": not bool(cfg["day_cap"])}
    return {arm.name: summarise(arm, TM, BID, ASK, END, TMID) for arm in arms}, rep, dup


if __name__ == "__main__":
    want = ARGS[1:] or ["infinity", "u224016179", "bos", "reference_uncapped"]
    TM, BID, ASK, n_bad, END = E.load_ticks()
    print("ticks in window", len(TM), "invalid", n_bad, flush=True)
    outp = r"C:\Projects\KinoliveLines\study\tick_engine_matrix.json"
    res = {"generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "dataset": E.META["sha256"], "policies": [NAME(p) for p in POLICIES], "rows": {}}
    try: res["rows"] = json.load(open(outp))["rows"]
    except Exception: pass
    for uid in want:
        cfg0, _ = E.effective_cfg(E.PR[uid], E.REGIMES[uid], 0.0)
        opps, bars = E.streams(cfg0)
        print("%s: opportunities %d" % (uid, len(opps)), flush=True)
        for drag in (0.0, 0.35):
            key = "%s|%.2f" % (uid, drag)
            if key in res["rows"]:
                print(key, "(cached)", flush=True); continue
            t0 = time.time(); out, rep, dup = run_matrix(uid, drag, TM, BID, ASK, END, opps, bars)
            res["rows"][key] = {"effective": rep, "duplicates": dup, "arms": out}
            for name, a in out.items():
                c = a["counts"]
                print("%-18s drag %.2f %-32s | net %8.2f cc_dd %7.2f mtm_dd %7.2f | trades %3d wins %3d main %8.2f adds %6.2f | risk %6.0f | h1 %7.2f h2 %7.2f | setups %3d missed %3d | admitted %3d (%s) | capoff %3d | daycap %3d debtgate %3d | %.0fs" % (
                    uid, drag, name, a["net"], a["cc_dd"], a["mtm_dd"], a["trades"], a["wins"], a["pnl_main"], a["pnl_add"], a["risk_main"], a["first_half"], a["later_half"],
                    c.get("setups", 0), c.get("missed_win", 0), c.get("admitted_by_allowance", 0), (a.get("admitted_money") or {}).get("pnl", "-"), c.get("cap_waived_off", 0), c.get("day_cap", 0), c.get("debt_gate", 0), time.time() - t0), flush=True)
            json.dump(res, open(outp, "w"), indent=1)
    print("DONE", flush=True)
