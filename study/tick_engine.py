"""ONE chronological bid/ask tick engine, THREE independently evolving arms
(ChatGPT review 13 brief). Development only, dataset b window, no live change.

Arms (same opportunity clock, own state each):
  baseline   - the account's frozen package, entry at the signal (market order)
  delayed    - the nominated candidate: in debt (> $0.50) the MAIN waits at the
               recovery midpoint of the frozen setup (original stop / target /
               lot); one pending setup; no other signal while it waits
  half_main  - original-entry MAIN at half lot in debt (floored 0.01): control

Signals: confirmed closed M1 bars -> the harness's raw opportunity stream
(OPPHOOK: every engine signal with its path-independent facts) and per-bar
facts (BARHOOK: protected-dot touch re-arm, nervosity). Each arm applies the
harness's path gates in the harness's order: position / pending open, kill,
awake, used-level dedupe, storm / movement, debt continuation allowance (flip
re-arms; a dot touch re-arms one), day cap (waived in debt), then sizing with
the LIVE-order limits at the EXECUTION quote (min balance, risk fit on the
current balance, 10% ceiling on the final lot - refuse), S_MIN_DIST on the
executable geometry.

Execution (declared): bot-triggered market orders. Eligibility = bar close +
SIGNAL_MS; an order placed at tick k fills at the first tick >= t_k + EXEC_MS on
the executable side (buy ask / sell bid); broker geometry at the fill quote
(stop beyond the exit quote, target not yet reached) else REJECT, recorded.
Barriers after the fill: first tick whose EXIT side (buy bid / sell ask) crosses
the stop or the target; a tick through both = stop. Adds (bullets): triggered
when the exit... no - when the ENTRY side reaches the midpoint (buy ask <= mid),
FUNDED AND RESERVED at that tick with that moment's debt / jar / streak /
nervosity (the harness's own arithmetic), filled at the next executable quote
after EXEC_MS, exiting on the main's barrier, booked apart. Costs: bid/ask
embed the spread; drag per lot on every leg at exit. End of window: open
positions marked at the last in-window quote; pending setups counted.
Coverage: the largest incoming tick gap met during every pending / open state
is recorded; trades with a gap > GAP_MS are flagged (money shown with and without).
    python tick_engine.py [regime ...]   (default: infinity first, then all)
"""
import sys, os, json, bisect, math, time, hashlib, statistics
import numpy as np
from datetime import datetime, timezone
sys.argv_saved = list(sys.argv); sys.argv = ["x"]
src = open(r"C:\Projects\KinoliveLines\study\manifest_runner.py", encoding="utf-8").read().split("REGIMES = [")[0]
ns = {"__file__": r"C:\Projects\KinoliveLines\study\manifest_runner.py"}; exec(src, ns)
H, man, R, META, effective_cfg = ns["H"], ns["man"], ns["R"], ns["META"], ns["effective_cfg"]
H.DIRGATE = None
PR = man["arms"]["baseline"]["package_regimes"]
B = H.B
SIGNAL_MS = 1000; EXEC_MS = 1000; GAP_MS = 30000; GAP_FLAG_MS = 5000
S_MIN_DIST = float(B.S_MIN_DIST); BLOT = H.BLOT; JAR_SKIM, JAR_STAKE, JAR_DEBT_MULT, JAR_FLOOR_CAP, CHEST_CAP = H.JAR_SKIM, H.JAR_STAKE, H.JAR_DEBT_MULT, H.JAR_FLOOR_CAP, H.CHEST_CAP
REGIMES = {"infinity": 175.70, "u224016179": 267.42, "bos": 360.37, "reference_uncapped": 1000.0}
TICKS = r"C:\Projects\KinoliveLines\study\ticks"


def load_ticks():
    tman = json.load(open(os.path.join(TICKS, "manifest.json"))); sym = tman["symbol"]
    parts = []
    for k in sorted(tman["days"]):
        if not tman["days"][k].get("n"): continue
        fn = os.path.join(TICKS, "%s_%s.npz" % (sym, k))
        if hashlib.sha256(open(fn, "rb").read()).hexdigest()[:16] != tman["days"][k]["sha256"]:
            raise SystemExit("hash mismatch %s" % k)
        parts.append(np.load(fn))
    TM = np.concatenate([p["time_msc"] for p in parts]).astype(np.int64); BID = np.concatenate([p["bid"] for p in parts]); ASK = np.concatenate([p["ask"] for p in parts])
    o = np.argsort(TM, kind="stable"); TM, BID, ASK = TM[o], BID[o], ASK[o]
    ok = np.isfinite(BID) & np.isfinite(ASK) & (BID > 0) & (ASK >= BID)
    T0 = int(R["time"][0]) * 1000; END = int(META["closed_bar_cutoff"]) * 1000
    win = ok & (TM >= T0) & (TM < END)
    return TM[win], BID[win], ASK[win], int((~ok).sum()), END


def streams(cfg):
    """raw opportunities + per-bar facts from the harness (path-independent; kill off so nothing truncates)"""
    opps, bars = [], {}
    H.OPPHOOK = lambda o: opps.append(dict(o))
    H.BARHOOK = lambda b: bars.__setitem__(b["t"], (b["touched"], b["nv"]))
    H.TRACE = None; H.simulate(R, 7.0, H.cfg_strict(dict(cfg, kill_net=0.0)))
    H.OPPHOOK = None; H.BARHOOK = None
    return opps, bars


class Arm:
    def __init__(self, name, cfg, mode, bars):
        self.name, self.c, self.mode, self.bars = name, cfg, mode, bars
        c = cfg
        self.LOT0 = float(c["lot"]); self.bal = float(c["balance"]); self.scale = bool(c.get("scale_lot", 1)) and self.bal > 0
        self.ratio = (self.bal / float(c["scale_ref"])) if (self.scale and float(c["scale_ref"]) > 0) else 1.0
        self.LOT = max(0.01, math.floor(self.LOT0 * self.ratio / 0.01) * 0.01) if self.scale else self.LOT0
        self.day_cap_eff = float(c["day_cap"]) * self.ratio
        self.rr, self.NB, self.K = float(c["rr"]), int(c["bullets"]), int(c["k_streak"])
        self.run = self.pk = 0.0; self.streak = 0; self.wins = 0; self.chest = 0.0
        self.day_key = None; self.day_profit = 0.0; self.day_n = 0
        self.used_hi = self.used_lo = None; self.last_flip_t = None; self.cont_left = 0; self.dead = False
        self.pos = None; self.pend = None; self.order = None      # order = dict(due_ms, kind: main|bullet, ...)
        self.pnls, self.trades, self.events = [], [], []
        self.eq_pk = 0.0; self.mtm_dd = 0.0; self.cc_dd_live = 0.0
        self.n = {"signals": 0, "skipped_open": 0, "skipped_pending": 0, "skipped_dead": 0, "not_awake": 0, "dedupe": 0, "weather": 0, "debt_gate": 0, "day_cap": 0,
                  "min_balance": 0, "fit_refuse": 0, "hard_cap": 0, "min_dist": 0, "orders": 0, "fills": 0, "reject_geom": 0, "setups": 0, "missed_win": 0,
                  "reject_after_stop_print": 0, "adds_triggered": 0, "adds_filled": 0, "adds_rejected": 0, "kills": 0, "trades_gap_flag": 0, "trades_gap_unresolved": 0,
                  "wait_s": [], "open_at_end": 0, "pending_at_end": 0}

    # ---------- day roll (UTC day of the tick), same arithmetic as the harness
    def roll(self, t_ms):
        dk = datetime.fromtimestamp(t_ms / 1000.0, tz=timezone.utc).strftime("%Y-%m-%d")
        if dk != self.day_key:
            self.day_key = dk; self.day_profit = 0.0; self.day_n = 0
            if self.c.get("scale_daily") and self.scale and float(self.c["scale_ref"]) > 0:
                r = (self.bal + self.run) / float(self.c["scale_ref"])
                self.LOT = max(0.01, math.floor(self.LOT0 * r / 0.01) * 0.01); self.day_cap_eff = float(self.c["day_cap"]) * r

    def debt(self): return max(0.0, self.pk - self.run)

    # ---------- a signal becomes eligible (tick k is the first at/after eligibility)
    def signal(self, o, k, TM, BID, ASK):
        c = self.c; t = o["t"]; self.n["signals"] += 1
        if self.pos is not None or self.order is not None: self.n["skipped_open"] += 1; return
        if self.pend is not None: self.n["skipped_pending"] += 1; return
        if self.dead: self.n["skipped_dead"] += 1; return
        if c["kill_net"] and self.run <= float(c["kill_net"]):
            self.dead = True; self.n["kills"] += 1; self.events.append({"t": t, "ev": "KILL", "run": round(self.run, 2)}); return
        if not o["awake"]: self.n["not_awake"] += 1; return
        d, slp, flip, lvl = o["d"], o["slp"], o["flip"], o["lvl"]
        if not flip:
            if (d == 1 and self.used_hi == lvl) or (d == -1 and self.used_lo == lvl): self.n["dedupe"] += 1; return
            if d == 1: self.used_hi = lvl
            else: self.used_lo = lvl
        if o["mv2"] is not None:
            if o["nv"] >= float(c["storm"]) or (c["movement"] and o["mv2"] < 1): self.n["weather"] += 1; return
            if c["nerv_gate"] and o["nv"] > 1.0: self.n["weather"] += 1; return
        debt_now = self.debt()
        if flip:
            self.last_flip_t = t; self.cont_left = int(c["n_cont"])
        elif debt_now > 0.5 and c.get("debt_gate", 1):
            if self.cont_left > 0 and self.last_flip_t is not None: self.cont_left -= 1
            else: self.n["debt_gate"] += 1; return
        if self.day_cap_eff and self.day_profit >= self.day_cap_eff and debt_now <= 0.5: self.n["day_cap"] += 1; return
        # signal quote: the eligibility tick (frozen geometry for the candidate; the immediate arms re-derive at the fill)
        e0 = ASK[k] if d == 1 else BID[k]
        lot = self.LOT
        if self.mode == "half" and debt_now > 0.5:
            lot = max(0.01, math.floor(lot * 0.5 / 0.01 + 1e-9) * 0.01)
        dist0 = abs(e0 - slp)
        if dist0 <= S_MIN_DIST: self.n["min_dist"] += 1; return
        setup = {"t": t, "d": d, "slp": float(slp), "e0": float(e0), "dist0": float(dist0), "tp0": float(e0 + d * self.rr * dist0), "mid0": float(e0 - d * dist0 / 2.0),
                 "lot_req": lot, "nv": o["nv"], "k_sig": k, "gap_max": 0, "flip": flip}
        if self.mode == "delayed" and debt_now > 0.5:
            self.pend = setup; self.n["setups"] += 1
            self.events.append({"t": t, "ev": "PENDING", "mid": round(setup["mid0"], 2), "sl": round(slp, 2), "tp": round(setup["tp0"], 2), "lot": lot})
            return
        self.order = {"kind": "main", "due": int(TM[k]) + EXEC_MS, "setup": setup, "frozen": False}; self.n["orders"] += 1

    # ---------- sizing / limits at the execution quote (the live enter() order)
    def size_at_fill(self, setup, fill_px, frozen):
        c = self.c; d = setup["d"]; bal_now = self.bal + self.run
        if float(c["min_balance"]) and bal_now < float(c["min_balance"]): self.n["min_balance"] += 1; return None
        lot = setup["lot_req"]
        if frozen:
            sl, tp, dist = setup["slp"], setup["tp0"], setup["dist0"]; risk_dist = abs(fill_px - sl)
        else:
            sl = setup["slp"]; dist = abs(fill_px - sl); tp = fill_px + d * self.rr * dist; risk_dist = dist
            if dist <= S_MIN_DIST: self.n["min_dist"] += 1; return None
        if c["risk_fit"]:
            fit = bal_now * float(c["risk_fit"]) / 100.0
            if risk_dist * lot > fit:
                lot = math.floor((fit / risk_dist) / 0.01) * 0.01
                if lot < 0.01: self.n["fit_refuse"] += 1; return None
        if float(c["hard_cap_pct"]) > 0 and risk_dist * lot > float(c["hard_cap_pct"]) * bal_now: self.n["hard_cap"] += 1; return None
        mid = setup["mid0"] if frozen else fill_px - d * dist / 2.0
        return {"d": d, "e": float(fill_px), "sl": float(sl), "tp": float(tp), "dist": float(dist), "mid": float(mid), "lot": float(lot), "risk_dist": float(risk_dist),
                "t": setup["t"], "nv": setup["nv"], "frozen": frozen, "fill_k": None, "adds": [], "add_order": None, "add_done": False, "gap_max": setup.get("gap_max", 0), "e0": setup["e0"]}

    # ---------- per tick
    def tick(self, k, TM, BID, ASK, gap_in):
        t_ms = int(TM[k]); b, a = BID[k], ASK[k]
        # pending setup (delayed arm)
        if self.pend is not None:
            p = self.pend; d = p["d"]; p["gap_max"] = max(p["gap_max"], gap_in)
            xq = b if d == 1 else a; eq = a if d == 1 else b
            if (d == 1 and xq >= p["tp0"]) or (d == -1 and xq <= p["tp0"]):
                self.n["missed_win"] += 1; self.events.append({"t": p["t"], "ev": "MISSED_WIN", "at": t_ms, "tp": round(p["tp0"], 2)}); self.pend = None
            else:
                if (d == 1 and xq <= p["slp"]) or (d == -1 and xq >= p["slp"]): p["stop_printed"] = True
                if (d == 1 and eq <= p["mid0"]) or (d == -1 and eq >= p["mid0"]):
                    # review 14, declared rule: the bot checks the attached stop BEFORE submitting -
                    # a stop already breached on the trigger quote means no order (cancelled, counted);
                    # a breach DURING the 1 s execution latency is the fill-quote rejection below
                    if (d == 1 and p["slp"] >= xq) or (d == -1 and p["slp"] <= xq):
                        self.n["cancel_stop_before_submission"] = self.n.get("cancel_stop_before_submission", 0) + 1
                        self.events.append({"t": p["t"], "ev": "CANCEL_STOP_BREACHED", "at": t_ms, "exit_q": round(xq, 2), "sl": round(p["slp"], 2)}); self.pend = None
                    else:
                        if p.get("stop_printed"):
                            self.n["trigger_after_earlier_stop_print"] = self.n.get("trigger_after_earlier_stop_print", 0) + 1
                        self.n["wait_s"].append(round((t_ms - (p["t"] + 60) * 1000) / 1000.0))
                        self.order = {"kind": "main", "due": t_ms + EXEC_MS, "setup": p, "frozen": True}; self.n["orders"] += 1; self.pend = None
        # orders due
        if self.order is not None and t_ms >= self.order["due"]:
            od = self.order; self.order = None; s = od["setup"]; d = s["d"]
            if od["kind"] == "main":
                fill_px = a if d == 1 else b; xq = b if d == 1 else a
                sl, tp = (s["slp"], s["tp0"]) if od["frozen"] else (s["slp"], None)
                bad = (d == 1 and sl >= xq) or (d == -1 and sl <= xq) or (tp is not None and ((d == 1 and tp <= xq) or (d == -1 and tp >= xq)))
                if bad:
                    self.n["reject_geom"] += 1
                    if s.get("stop_printed"): self.n["reject_after_stop_print"] += 1
                    self.events.append({"t": s["t"], "ev": "REJECT_GEOM", "at": t_ms, "fill_q": round(fill_px, 2), "sl": round(sl, 2)})
                else:
                    pos = self.size_at_fill(s, fill_px, od["frozen"])
                    if pos is not None:
                        if not od["frozen"] and ((d == 1 and pos["tp"] <= xq) or (d == -1 and pos["tp"] >= xq)):
                            self.n["reject_geom"] += 1
                        else:
                            pos["fill_k"] = k; pos["fill_ms"] = t_ms; self.pos = pos; self.n["fills"] += 1; self.day_n += 1
                            self.events.append({"t": s["t"], "ev": "FILL", "at": t_ms, "e": round(pos["e"], 2), "sl": round(pos["sl"], 2), "tp": round(pos["tp"], 2), "lot": pos["lot"], "frozen": od["frozen"], "debt": round(self.debt(), 2)})
                            if od["frozen"]:
                                self.try_adds(k, TM, BID, ASK)      # the midpoint IS the add trigger for the delayed main
            else:   # bullet order
                p = self.pos
                if p is not None and p["d"] == d:
                    fill_px = a if d == 1 else b; xq = b if d == 1 else a
                    # review 14: the add carries the parent's stop and target - the same executable
                    # geometry as the MAIN at its fill quote; a parent already stopped / targeted on
                    # this quote rejects the add (the parent closes on this same tick below)
                    if (d == 1 and (p["sl"] >= xq or p["tp"] <= xq)) or (d == -1 and (p["sl"] <= xq or p["tp"] >= xq)):
                        self.n["adds_rejected_geom"] = self.n.get("adds_rejected_geom", 0) + od["n"]
                        self.events.append({"t": p["t"], "ev": "ADD_REJECT_GEOM", "at": t_ms, "n": od["n"], "exit_q": round(xq, 2), "sl": round(p["sl"], 2), "tp": round(p["tp"], 2)})
                    else:
                        p["adds"].append({"e": float(fill_px), "lot": BLOT, "n": od["n"], "at": t_ms}); self.n["adds_filled"] += od["n"]
                        self.events.append({"t": p["t"], "ev": "ADD_FILL", "at": t_ms, "n": od["n"], "e": round(fill_px, 2)})
                else:
                    self.n["adds_rejected"] += od["n"]
        # open position
        p = self.pos
        if p is not None:
            d = p["d"]; p["gap_max"] = max(p["gap_max"], gap_in)
            if not p["add_done"] and self.order is None:
                eq = a if d == 1 else b
                if (d == 1 and eq <= p["mid"]) or (d == -1 and eq >= p["mid"]):
                    self.try_adds(k, TM, BID, ASK)
            xq = b if d == 1 else a
            # review 14: marked equity at EVERY quote, the closing quote included, then the
            # realised equity after the close and its costs
            eq_now = self.run + d * (xq - p["e"]) * p["lot"] + sum(d * (xq - ad["e"]) * ad["lot"] * ad["n"] for ad in p["adds"])
            self.eq_pk = max(self.eq_pk, eq_now); self.mtm_dd = max(self.mtm_dd, self.eq_pk - eq_now)
            hit_sl = (d == 1 and xq <= p["sl"]) or (d == -1 and xq >= p["sl"])
            hit_tp = (d == 1 and xq >= p["tp"]) or (d == -1 and xq <= p["tp"])
            if hit_sl or hit_tp:
                self.close(p, xq, t_ms, bool(hit_tp and not hit_sl), both=bool(hit_tp and hit_sl))
                self.eq_pk = max(self.eq_pk, self.run); self.mtm_dd = max(self.mtm_dd, self.eq_pk - self.run)
        else:
            self.eq_pk = max(self.eq_pk, self.run); self.mtm_dd = max(self.mtm_dd, self.eq_pk - self.run)

    def try_adds(self, k, TM, BID, ASK):
        """fund and reserve the bullets at the TRIGGER tick with that moment's state (harness arithmetic)"""
        p = self.pos; p["add_done"] = True
        c = self.c; debt = self.debt(); self.n["adds_triggered"] += 1
        if not (debt > 0.5 and self.streak < self.K and self.NB > 0): return
        nv = self.bars.get(int(TM[k]) // 60000 * 60, (False, p["nv"]))[1]     # nervosity of the current bar (falls back to entry)
        if c["jar"]:
            r001 = p["dist"] * BLOT; gain001 = self.rr * r001
            by_budget = int((self.chest * JAR_STAKE) // r001) if r001 > 0 else 0
            by_debt = int(math.ceil(debt / gain001)) if gain001 > 0 else 0
            nb = 0 if nv > 1.0 else max(0, min(self.NB, by_budget, by_debt))
        else:
            nb = self.NB
        if nb:
            self.order = {"kind": "bullet", "due": int(TM[k]) + EXEC_MS, "setup": {"d": p["d"]}, "n": nb}
            self.events.append({"t": p["t"], "ev": "ADD_RESERVED", "at": int(TM[k]), "n": nb, "debt": round(debt, 2), "chest": round(self.chest, 2), "nv": round(nv, 2)})

    def close(self, p, xq, t_ms, win, both=False):
        c = self.c; d = p["d"]; lot = p["lot"]
        pts = d * (xq - p["e"]); before = self.run
        self.run += pts * lot
        nb = sum(ad["n"] for ad in p["adds"]); bmoney = 0.0
        for ad in p["adds"]:
            bm = d * (xq - ad["e"]) * ad["lot"] * ad["n"]; bmoney += bm; self.run += bm
        if nb: self.run -= H.drag_cost(c, BLOT * nb)
        if c["jar"]:
            if nb and bmoney < 0: self.chest = max(0.0, self.chest + bmoney)
            if win: self.chest += JAR_SKIM * (pts * lot)
            if self.run > self.pk: self.chest = min(CHEST_CAP, self.chest + (self.run - self.pk))
            self.chest = min(self.chest, max(JAR_FLOOR_CAP, JAR_DEBT_MULT * max(0.0, self.pk - self.run)))
        self.run -= H.drag_cost(c, lot)
        pnl = self.run - before; self.day_profit += pnl; self.pnls.append(round(pnl, 2))
        self.streak = 0 if win else self.streak + 1; self.wins += 1 if win else 0
        self.pk = max(self.pk, self.run)
        rec = {"t": p["t"], "tc": t_ms, "d": d, "e": round(p["e"], 2), "e0": round(p["e0"], 2), "sl": round(p["sl"], 2), "tp": round(p["tp"], 2), "lot": lot, "win": win,
               "pnl": round(pnl, 2), "pnl_main": round(pts * lot - H.drag_cost(c, lot), 2), "pnl_add": round(bmoney - (H.drag_cost(c, BLOT * nb) if nb else 0.0), 2),
               "adds": nb, "risk": round(p["risk_dist"] * lot, 2), "frozen": p["frozen"], "gap_max_ms": p["gap_max"], "fill_ms": p.get("fill_ms"),
               "add_fills": [{"e": round(ad["e"], 2), "n": ad["n"], "at": ad["at"]} for ad in p["adds"]]}
        if p["gap_max"] > GAP_FLAG_MS: self.n["trades_gap_flag"] += 1
        if p["gap_max"] > GAP_MS: self.n["trades_gap_unresolved"] += 1
        self.trades.append(rec); self.pos = None
        if both: self.n["same_tick_both_barriers"] = self.n.get("same_tick_both_barriers", 0) + 1
        self.events.append({"t": p["t"], "ev": "CLOSE", "at": t_ms, "win": win, "both_barriers_same_tick": both, "pnl": round(pnl, 2), "run": round(self.run, 2), "debt": round(self.debt(), 2)})

    def finish(self, TM, BID, ASK, END):
        k = len(TM) - 1; mtm = 0.0
        if self.pos is not None:
            p = self.pos; d = p["d"]; xq = BID[k] if d == 1 else ASK[k]
            mtm = d * (xq - p["e"]) * p["lot"] + sum(d * (xq - ad["e"]) * ad["lot"] * ad["n"] for ad in p["adds"]); self.n["open_at_end"] = 1
            self.eq_pk = max(self.eq_pk, self.run + mtm); self.mtm_dd = max(self.mtm_dd, self.eq_pk - (self.run + mtm))
        if self.pend is not None: self.n["pending_at_end"] = 1
        if self.order is not None: self.n["order_at_end"] = 1
        return mtm


def dd_of(seq):
    c = pk = dd = 0.0
    for p in seq:
        c += p; pk = max(pk, c); dd = max(dd, pk - c)
    return dd


def run_regime(uid, drag, TM, BID, ASK, END, opps, bars):
    cfg, rep = effective_cfg(PR[uid], REGIMES[uid], drag)
    arms = [Arm("baseline", cfg, "base", bars), Arm("delayed", cfg, "delayed", bars), Arm("half_main", cfg, "half", bars)]
    elig = [((o["t"] + 60) * 1000 + SIGNAL_MS, o) for o in opps]; ei = 0
    # bar closes in order: the protected-dot touch re-arms one continuation (harness rule), applied
    # at the bar's close, before that bar's signal is judged
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
    for arm in arms:
        mtm_open = arm.finish(TM, BID, ASK, END)
        tr = arm.trades; T1 = int(TM[-1]); TMID = (int(TM[0]) + T1) // 2
        out[arm.name] = {"net": round(arm.run, 2), "net_with_open_mtm": round(arm.run + mtm_open, 2), "cc_dd": round(dd_of(arm.pnls), 2), "mtm_dd": round(arm.mtm_dd, 2),
                         "trades": len(tr), "wins": arm.wins, "pnl_main": round(sum(x["pnl_main"] for x in tr), 2), "pnl_add": round(sum(x["pnl_add"] for x in tr), 2),
                         "risk_main": round(sum(x["risk"] for x in tr), 2), "adds": sum(x["adds"] for x in tr), "later_half": round(sum(x["pnl"] for x in tr if x["tc"] >= TMID), 2),
                         "lots": {str(l): sum(1 for x in tr if x["lot"] == l) for l in sorted(set(x["lot"] for x in tr))},
                         "gap_flagged_trades": arm.n["trades_gap_flag"], "gap_unresolved_trades": arm.n["trades_gap_unresolved"],
                         "net_excl_unresolved": round(sum(x["pnl"] for x in tr if x["gap_max_ms"] <= GAP_MS), 2),
                         "wait_s_median": (sorted(arm.n["wait_s"])[len(arm.n["wait_s"]) // 2] if arm.n["wait_s"] else None),
                         "counts": {k: v for k, v in arm.n.items() if k != "wait_s"}, "trades_list": tr, "events": arm.events[:400]}
    return out, rep


if __name__ == "__main__":
    want = sys.argv_saved[1:] or ["infinity", "u224016179", "bos", "reference_uncapped"]
    TM, BID, ASK, n_bad, END = load_ticks()
    print("ticks in window", len(TM), "invalid", n_bad, flush=True)
    res = {"generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "dataset": META["sha256"], "signal_ms": SIGNAL_MS, "exec_ms": EXEC_MS, "gap_ms": GAP_MS, "rows": {}}
    outp = r"C:\Projects\KinoliveLines\study\tick_engine.json"
    try: res["rows"] = json.load(open(outp))["rows"]
    except Exception: pass
    for uid in want:
        cfg0, _ = effective_cfg(PR[uid], REGIMES[uid], 0.0)
        opps, bars = streams(cfg0)
        print("%s: opportunities %d, bar facts %d" % (uid, len(opps), len(bars)), flush=True)
        for drag in (0.0, 0.35):
            t0 = time.time(); out, rep = run_regime(uid, drag, TM, BID, ASK, END, opps, bars)
            res["rows"]["%s|%.2f" % (uid, drag)] = {"effective": rep, "arms": out}
            for name, a in out.items():
                c = a["counts"]
                print("%-18s drag %.2f %-9s | net %8.2f (+open %8.2f) cc_dd %7.2f mtm_dd %7.2f | trades %3d wins %3d main %8.2f adds %7.2f (%d) risk %7.0f | later %7.2f | sig %d skip open/pend %d/%d awake %d dedupe %d weather %d debtgate %d daycap %d | fills %d rej %d minbal %d fit %d cap %d | setups %d missed %d wait med %s | gap flag %d unres %d | kills %d | %.0fs" % (
                    uid, drag, name, a["net"], a["net_with_open_mtm"], a["cc_dd"], a["mtm_dd"], a["trades"], a["wins"], a["pnl_main"], a["pnl_add"], a["adds"], a["risk_main"], a["later_half"],
                    c["signals"], c["skipped_open"], c["skipped_pending"], c["not_awake"], c["dedupe"], c["weather"], c["debt_gate"], c["day_cap"], c["fills"], c["reject_geom"], c["min_balance"], c["fit_refuse"], c["hard_cap"],
                    c["setups"], c["missed_win"], a["wait_s_median"], a["gap_flagged_trades"], a["gap_unresolved_trades"], c["kills"], time.time() - t0), flush=True)
            json.dump(res, open(outp, "w"), indent=1)
    print("DONE", flush=True)
