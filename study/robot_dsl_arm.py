"""The bench's interpreter of the piece language (live/robots/robot_dsl.py) - owner 2026-10-13, step 2.

DslArm = RobotArm (the proof bench: tick engine, live gate order, adaptive cap, sticky pullback structure) plus
pieces written as rules:
  entry  : a signal whose break is not the robot's event (BOS only / CHoCH only) is not an entry for this robot -
           it still closes an open trade on a CHoCH against it when the exit says so
  filter : checked where the live bot checks its weather brakes (after the pullback filter, before the day cap)
  stop   : replaces the protected point given to the setup (protected + buffer, the break candle, a fixed distance)
  exit   : target N x risk or none, CHoCH, a time limit, a breakeven move - the first that happens
With no rule pieces a DslArm is exactly a RobotArm (checked: the Owl reproduces the proof bench).
"""
import tick_engine as E
from robot_choch_exit import RobotArm, FAR


class DslArm(RobotArm):
    def __init__(self, name, cfg, bars, S, dsl=None, **kw):
        dsl = dsl or {}
        ex = dsl.get("exit")
        if ex is not None:
            kw["exit"] = "choch" if ex.get("choch") else "target"
        super().__init__(name, cfg, bars, S, **kw)
        self.dsl = dsl
        self.n.update({"dsl_entry_skip": 0, "dsl_filter": 0, "dsl_time_exits": 0, "dsl_breakevens": 0})

    # ---- entry + stop
    def _entry_ok(self, o):
        en = self.dsl.get("entry")
        if not en or en.get("event") == "any":
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
        return o2

    def signal(self, o, k, TM, BID, ASK):
        if self._entry_ok(o):
            return RobotArm.signal(self, self._with_stop(o), k, TM, BID, ASK)
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
        for f in self.dsl.get("filters") or []:
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
