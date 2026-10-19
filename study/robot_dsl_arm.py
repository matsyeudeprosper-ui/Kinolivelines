"""The bench's interpreter of the piece language (live/robots/robot_dsl.py) - owner 2026-10-13, step 2.

DslArm = RobotArm (the proof bench: tick engine, live gate order, adaptive cap, sticky pullback structure) plus
pieces written as rules:
  entry  : a signal whose break is not the robot's event (BOS only / CHoCH only) is not an entry for this robot -
           it still closes an open trade on a CHoCH against it when the exit says so
  filter : checked where the live bot checks its weather brakes (after the pullback filter, before the day cap)
  stop   : replaces the protected point given to the setup (protected + buffer, the break candle, a fixed distance)
  exit   : target N x risk or none, CHoCH, a time limit, a breakeven move - the first that happens
With no rule pieces a DslArm is exactly a RobotArm (checked: the Owl reproduces the proof bench).

2026-10-19 FORMULA pieces (live/robots/robot_expr.py): a formula filter is checked at the signal's candle (its side),
a formula stop gives the stop price at that candle (a stop on the wrong side or unknown = no trade), a formula exit
closes the trade at the close of the first candle where it is true. The formulas are computed once per arm over
the whole bar array (E.R, re-pointed by market packs), with the eyes' facts from the opportunity stream.
A formula ENTRY is not handled here: robot_runner.robot_opps() turns it into the robot's own opportunity stream.
"""
import os, sys
import numpy as np
import tick_engine as E
from robot_choch_exit import RobotArm, FAR
sys.path.insert(0, os.path.join(r"C:\Projects\KinoliveLines\live", "robots"))
import robot_expr as X


class DslArm(RobotArm):
    def __init__(self, name, cfg, bars, S, dsl=None, **kw):
        opps = kw.pop("opps", None)              # the eyes' breaks, for formulas that read them
        dsl = dsl or {}
        ex = dsl.get("exit")
        if ex is not None:
            kw["exit"] = "choch" if ex.get("choch") else "target"
        super().__init__(name, cfg, bars, S, **kw)
        self.dsl = dsl
        self.n.update({"dsl_entry_skip": 0, "dsl_filter": 0, "dsl_time_exits": 0, "dsl_breakevens": 0,
                       "dsl_stop_bad": 0, "dsl_formula_exits": 0})
        self._fx = None; self._xi = 0
        if self._uses_formulas():
            self._prepare(opps, S)

    def _uses_formulas(self):
        d = self.dsl
        return any(f.get("kind") == "formula" for f in d.get("filters") or []) or (d.get("stop") or {}).get("kind") == "formula"             or bool((d.get("exit") or {}).get("close_buy") or (d.get("exit") or {}).get("close_sell"))

    def _prepare(self, opps, S):
        """every formula of this robot computed once over the bar array"""
        R = E.R
        B = X.Bars.from_rates(R, X.eyes_from_opps(opps or [], len(R), S))
        T = lambda f: X.truth(f, B) if f else None
        V = lambda f: X.evaluate(f, B) if f else None
        self._fx = {"filters": {j: (T(f.get("buy")), T(f.get("sell"))) for j, f in enumerate(self.dsl.get("filters") or []) if f.get("kind") == "formula"}}
        st = self.dsl.get("stop") or {}
        if st.get("kind") == "formula":
            self._fx["stop"] = (V(st.get("buy")), V(st.get("sell")))
        ex = self.dsl.get("exit") or {}
        if ex.get("close_buy") or ex.get("close_sell"):
            self._fx["exit"] = (T(ex.get("close_buy")), T(ex.get("close_sell")))
            self._close_ms = (np.asarray(R["time"], dtype=np.int64) + 60) * 1000

    # ---- entry + stop
    def _entry_ok(self, o):
        en = self.dsl.get("entry")
        if not en or en.get("event") in ("any", "formula"):     # a formula entry made its own stream (robot_opps)
            return True
        return bool(o["flip"]) if en["event"] == "choch" else not o["flip"]

    def _with_stop(self, o):
        st = self.dsl.get("stop")
        if not st:
            return o
        d = o["d"]; o2 = dict(o)
        if st["kind"] == "protected":
            o2["slp"] = float(o["slp"]) - d * float(st.get("buffer") or 0)
        elif st["kind"] == "break_candle":
            i = int(o["i"])
            ext = float(E.R["low"][i]) if d == 1 else float(E.R["high"][i])
            o2["slp"] = ext - d * float(st.get("buffer") or 0)
        elif st["kind"] == "fixed":
            o2["slp"] = float(o["cl"]) - d * float(st["points"])
        elif st["kind"] == "formula":
            arr = self._fx["stop"][0 if d == 1 else 1]
            px = float(arr[int(o["i"])]) if arr is not None else float("nan")
            if px != px or d * (float(o["cl"]) - px) <= 0:
                return None                          # unknown, or on the wrong side of the entry: no trade
            o2["slp"] = px
        return o2

    def signal(self, o, k, TM, BID, ASK):
        if self._entry_ok(o):
            o2 = self._with_stop(o)
            if o2 is None:
                self.n["dsl_stop_bad"] += 1; return
            return RobotArm.signal(self, o2, k, TM, BID, ASK)
        self.n["dsl_entry_skip"] += 1
        p = self.pos      # not an entry for this robot - a CHoCH against an open trade still closes it
        if p is not None and self.exit_mode in ("choch", "target_choch") and o["flip"] and o["d"] == -p["d"]:
            d = p["d"]; xq = BID[k] if d == 1 else ASK[k]
            prof = d * (xq - p["e"]) * p["lot"] + sum(d * (xq - ad["e"]) * ad["lot"] * ad["n"] for ad in p["adds"])
            self.n["choch_exits"] += 1; self.n["choch_exit_wins"] += 1 if prof > 0 else 0
            self.close(p, xq, int(TM[k]), prof > 0)

    # ---- filters, at the live bot's weather position
    def late_gates(self, o, debt_now):
        if super().late_gates(o, debt_now):
            return True
        for j, f in enumerate(self.dsl.get("filters") or []):
            k = f["kind"]; ok = True
            if k == "hours":
                ok = f["from"] <= int(o["hour"]) < f["to"]
            elif k == "weekdays":
                ok = int(o["weekday"]) in f["days"]
            elif k == "pace":
                nv = float(o["nv"])
                ok = (f["min"] is None or nv >= f["min"]) and (f["max"] is None or nv <= f["max"])
            elif k == "moves":
                ok = o["mv2"] is None or int(o["mv2"]) >= f["min"]
            elif k == "formula":
                fb, fs = self._fx["filters"][j]
                arr = fb if o["d"] == 1 else fs
                ok = arr is None or bool(arr[int(o["i"])])
            if not ok:
                self.n["dsl_filter"] += 1
                return True
        return False

    # ---- exit: no target, time limit, breakeven
    def size_at_fill(self, setup, fill_px, frozen):
        pos = super().size_at_fill(setup, fill_px, frozen)
        ex = self.dsl.get("exit")
        if pos is not None and ex is not None and ex.get("target") is None:
            pos["tp"] = pos["e"] + pos["d"] * FAR
        return pos

    def tick(self, k, TM, BID, ASK, gap_in):
        if self._fx is not None and "exit" in self._fx:
            t_ms = int(TM[k]); CM = self._close_ms
            while self._xi < len(CM) and CM[self._xi] <= t_ms:
                i = self._xi; self._xi += 1
                p = self.pos
                if p is None or p.get("fill_ms") is None or int(p["fill_ms"]) >= int(CM[i]):
                    continue
                arr = self._fx["exit"][0 if p["d"] == 1 else 1]
                if arr is not None and arr[i]:
                    d = p["d"]; xq = BID[k] if d == 1 else ASK[k]
                    prof = d * (xq - p["e"]) * p["lot"] + sum(d * (xq - ad["e"]) * ad["lot"] * ad["n"] for ad in p["adds"])
                    self.n["dsl_formula_exits"] += 1
                    self.close(p, xq, t_ms, prof > 0)
        p = self.pos; ex = self.dsl.get("exit")
        if p is not None and ex is not None and p.get("fill_ms") is not None:
            t_ms = int(TM[k]); d = p["d"]; xq = BID[k] if d == 1 else ASK[k]
            if ex.get("time_min") and t_ms - int(p["fill_ms"]) >= int(ex["time_min"]) * 60000:
                prof = d * (xq - p["e"]) * p["lot"] + sum(d * (xq - ad["e"]) * ad["lot"] * ad["n"] for ad in p["adds"])
                self.n["dsl_time_exits"] += 1
                self.close(p, xq, t_ms, prof > 0)
            elif ex.get("breakeven_at") and not p.get("be") and d * (xq - p["e"]) >= float(ex["breakeven_at"]) * float(p["risk_dist"]):
                p["sl"] = p["e"]; p["be"] = True; self.n["dsl_breakevens"] += 1
        super().tick(k, TM, BID, ASK, gap_in)
