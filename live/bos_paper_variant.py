"""A PAPER TWIN for one lab variant (2026-09-28, layer 3 of the chercheur).

    pythonw bos_paper_variant.py <variant id>

Reads its config from lab/twins.json (the same keys as lab/harness.py:
rr, n_cont, wait_min, ext_pts, skip_wd, skip_hours, size_hot, nerv_gate,
storm, lot) and trades it VIRTUALLY on the demo Pro price feed, next to the
real robot: same structure engine, same awake window, same storm and
movement gates (read from the feed's published state), entries on the
closed candle, one position at a time, exits judged on live ticks and swept
on the closed bar. No money, no orders. State: lab/twin_<id>_state.json,
log: lab/twin_<id>.log ("VT ..." lines like the flip+touch twin).
"""
import json
import os
import sys
import time
from datetime import datetime, timezone

import MetaTrader5 as mt5

VID = sys.argv[1] if len(sys.argv) > 1 else ""
sys.argv = [sys.argv[0], "paper"]
import structure_bos_bot as B              # noqa: E402

DIR = os.path.dirname(os.path.abspath(__file__))
LAB = os.path.join(DIR, "lab")
if not VID:
    raise SystemExit("usage: bos_paper_variant.py <variant id>")
LOG = os.path.join(LAB, f"twin_{VID}.log")
STATE = os.path.join(LAB, f"twin_{VID}_state.json")
FEED = os.path.join(DIR, "owl_chart_btc.json")
TERMINAL = r"C:\NestTerminals\u476954287\terminal64.exe"
LOGIN = 476954287
SERVER = "Exness-MT5Trial9"
SYMBOL = B.SYMBOL
CFG = {"rr": 0.8, "n_cont": 1, "wait_min": 0, "ext_pts": 0, "skip_wd": [], "skip_hours": [],
       "size_hot": 1.0, "nerv_gate": False, "storm": 1.85, "lot": 0.02, "debt_nerv_gate": False}
try:
    for t in json.load(open(os.path.join(LAB, "twins.json"), encoding="utf-8")).get("twins", []):
        if t.get("id") == VID:
            CFG.update({k: v for k, v in (t.get("cfg") or {}).items() if k in CFG})
except Exception:
    pass
RR, LOT = float(CFG["rr"]), float(CFG["lot"])


def say(msg):
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(f"{datetime.now(timezone.utc).isoformat()} {msg}\n")
    except Exception:
        pass


def load_state():
    try:
        return json.load(open(STATE, encoding="utf-8"))
    except Exception:
        return {"pos": None, "trades": [], "net": 0.0, "peak": 0.0, "last_bar": 0, "used_hi": None, "used_lo": None,
                "cont_left": 0, "last_flip": None, "last_close": None}


def save_state(st):
    tmp = STATE + ".tmp"
    for attempt in range(4):
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(st, f)
            os.replace(tmp, STATE)
            return
        except Exception:
            time.sleep(0.4 * (attempt + 1))


def feed():
    try:
        return json.load(open(FEED, encoding="utf-8"))
    except Exception:
        return {}


def main():
    assert mt5.initialize(path=TERMINAL, login=LOGIN, password=B.PASSWORD, server=SERVER, timeout=60000), "MT5 init failed"
    mt5.symbol_select(SYMBOL, True)
    eng = B.Struct()
    eng.quiet = True
    flips = []
    R = mt5.copy_rates_from_pos(SYMBOL, mt5.TIMEFRAME_M1, 1, B.SEED_BARS)
    assert R is not None and len(R) > 100, "no history"
    closes = []
    for r in R:
        _pt = eng.trend
        eng.step(int(r["time"]), float(r["open"]), float(r["high"]), float(r["low"]), float(r["close"]))
        closes.append(float(r["close"]))
        if eng.trend != _pt and eng.trend != 0 and _pt != 0:
            flips.append(int(r["time"]))
    flips = flips[-20:]
    closes = closes[-120:]
    st = load_state()
    st["last_bar"] = int(R["time"][-1])
    save_state(st)
    say(f"PAPER-VARIANT {VID} starting cfg {json.dumps(CFG)} | net so far {st['net']:+.2f} ({len(st['trades'])} trades)")

    def enter(d, slp, kind, tick, lot):
        e = tick.ask if d == 1 else tick.bid
        dist = abs(e - slp)
        if dist <= B.S_MIN_DIST:
            say(f"VT {kind} skipped: dot {dist:.0f}pts inside the spread zone")
            return
        tp = e + d * RR * dist
        st["pos"] = {"d": d, "e": e, "sl": round(slp, 2), "tp": round(tp, 2), "kind": kind, "t": time.time(), "lot": lot}
        save_state(st)
        say(f"VT {kind} ENTRY: {'BUY' if d == 1 else 'SELL'} {lot} @ ~{e:.2f} SL {slp:.2f} TP {tp:.2f} (risk ${dist * lot:.2f})")

    def close(px, why):
        p = st["pos"]
        pnl = round((px - p["e"]) * p["d"] * p.get("lot", LOT), 2)
        st["net"] = round(st["net"] + pnl, 2)
        st["peak"] = max(st.get("peak", 0.0), st["net"])
        st["trades"].append({"kind": p["kind"], "d": p["d"], "e": p["e"], "sl": p["sl"], "tp": p["tp"], "x": px,
                             "why": why, "pnl": pnl, "t_open": p["t"], "t_close": time.time()})
        st["pos"] = None
        st["last_close"] = time.time()
        save_state(st)
        n = len(st["trades"]); w = sum(1 for x in st["trades"] if x["pnl"] > 0)
        say(f"VT {'WIN' if pnl > 0 else 'LOSS'} {pnl:+.2f} ({p['kind']}, {why}) - twin net {st['net']:+.2f} ({n} trades, {w}W/{n - w}L)")

    while True:
        _to_min = 60.0 - (time.time() % 60.0) + 0.2
        time.sleep(min(_to_min, 1.0))
        try:
            tick = mt5.symbol_info_tick(SYMBOL)
            if tick is None:
                continue
            p = st.get("pos")
            if p:
                if p["d"] == 1:
                    if tick.bid <= p["sl"]:
                        close(tick.bid, "sl")
                    elif tick.bid >= p["tp"]:
                        close(p["tp"], "tp")
                else:
                    if tick.ask >= p["sl"]:
                        close(tick.ask, "sl")
                    elif tick.ask <= p["tp"]:
                        close(p["tp"], "tp")
            kb = mt5.copy_rates_from_pos(SYMBOL, mt5.TIMEFRAME_M1, 1, 2)
            if kb is None or len(kb) < 2:
                continue
            bar = kb[-1]
            bt = int(bar["time"])
            if bt == st.get("last_bar"):
                continue
            st["last_bar"] = bt
            closes.append(float(bar["close"])); del closes[:-120]
            p = st.get("pos")
            if p and p["t"] < bt + 60:
                _sp = float(bar["spread"]) * 0.01 if "spread" in bar.dtype.names else 0.0
                if p["d"] == 1:
                    if float(bar["low"]) <= p["sl"]:
                        close(p["sl"], "sl-bar")
                    elif float(bar["high"]) >= p["tp"]:
                        close(p["tp"], "tp-bar")
                else:
                    if float(bar["high"]) + _sp >= p["sl"]:
                        close(p["sl"], "sl-bar")
                    elif float(bar["low"]) + _sp <= p["tp"]:
                        close(p["tp"], "tp-bar")
            _pt = eng.trend
            _hv, _lv = eng.hi_v, eng.lo_v
            touched = False
            if eng.trend == 1 and eng.prot_lo is not None:
                touched = float(bar["low"]) <= eng.prot_lo[1] <= float(bar["close"])
            elif eng.trend == -1 and eng.prot_hi is not None:
                touched = float(bar["close"]) <= eng.prot_hi[1] <= float(bar["high"])
            sig = eng.step(bt, float(bar["open"]), float(bar["high"]), float(bar["low"]), float(bar["close"]))
            flip = eng.trend != _pt and eng.trend != 0 and _pt != 0
            if flip:
                flips.append(bt); del flips[:-20]
            if touched and st.get("last_flip") and st.get("cont_left", 0) < CFG["n_cont"]:
                st["cont_left"] = min(int(CFG["n_cont"]), st.get("cont_left", 0) + 1)
            save_state(st)
            if sig is None or st.get("pos") is not None:
                continue
            if not any(f > bt - B.AWAKE_WIN for f in flips):
                continue
            d, slp = sig
            if not flip:
                lvl = _hv if d == 1 else _lv
                if (d == 1 and st.get("used_hi") == lvl) or (d == -1 and st.get("used_lo") == lvl):
                    continue
                if d == 1:
                    st["used_hi"] = lvl
                else:
                    st["used_lo"] = lvl
            cj = feed()
            vn, vr = cj.get("vol_now"), cj.get("vol_ref")
            nv = (vn / max(vr, 1)) if vn and vr else 1.0
            if nv >= float(CFG["storm"]) or (cj.get("moves_2h") or 0) < 1:
                continue
            if CFG["nerv_gate"] and nv > 1.0:
                say(f"VT refuse: nerveux ({nv:.2f}x)"); continue
            if CFG["debt_nerv_gate"] and nv > 1.0 and max(0.0, st.get("peak", 0.0) - st["net"]) > 0.5:
                say(f"VT refuse: dans le rouge ET nerveux ({nv:.2f}x)"); continue
            g = datetime.fromtimestamp(bt, tz=timezone.utc)
            if CFG["wait_min"] and st.get("last_close") and time.time() - st["last_close"] < CFG["wait_min"] * 60:
                say("VT refuse: pause apres le trade precedent"); continue
            if CFG["ext_pts"] and len(closes) >= 61 and abs(closes[-1] - closes[-61]) > CFG["ext_pts"]:
                say("VT refuse: grosse envolee dans l'heure"); continue
            if CFG["skip_wd"] and g.weekday() in CFG["skip_wd"]:
                continue
            if CFG["skip_hours"] and g.hour in CFG["skip_hours"]:
                continue
            debt = max(0.0, st.get("peak", 0.0) - st["net"])
            if flip:
                st["last_flip"] = bt; st["cont_left"] = int(CFG["n_cont"])
            elif debt > 0.5:
                if st.get("cont_left", 0) > 0 and st.get("last_flip"):
                    st["cont_left"] -= 1
                else:
                    say("VT refuse: dette active, continuation deja prise"); continue
            lot = round(LOT * (float(CFG["size_hot"]) if nv >= 1.0 else 1.0), 2)
            tk = mt5.symbol_info_tick(SYMBOL)
            if tk is not None:
                enter(d, slp, "FLIP-BOS" if flip else "BOS", tk, max(0.01, lot))
        except Exception as e:
            say(f"ERROR {type(e).__name__}: {e}")
            time.sleep(30)


if __name__ == "__main__":
    main()
