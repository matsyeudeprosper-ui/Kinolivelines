import sys; sys.path.insert(0, r"C:\Projects\KinoliveLines\live\robots")
import robot_dsl as D
ok = 0; bad = 0
def chk(name, got, want):
    global ok, bad
    if got == want: ok += 1
    else: bad += 1; print("FAIL", name, got)
e = {"event": "formula", "buy": "cross_up(close, pdh)", "sell": None, "order": {"type": "limit", "buy": "close - atr(14)", "sell": None, "expire_min": 30}}
r = D.validate("entry", e); chk("entry+order ok", r[0], True); chk("order kept", r[1].get("order", {}).get("type"), "limit")
chk("bad order type", D.validate("entry", dict(e, order={"type": "market", "buy": "close"}))[0], False)
chk("bad order expire", D.validate("entry", dict(e, order={"type": "stop", "buy": "close", "expire_min": 2}))[0], False)
chk("bad order formula", D.validate("entry", dict(e, order={"type": "stop", "buy": "import os"}))[0], False)
chk("bos+order", D.validate("entry", {"event": "bos", "order": {"type": "stop", "sell": "low - 10"}})[1].get("order", {}).get("sell"), "low - 10")
chk("plain entry unchanged", D.validate("entry", {"event": "bos"}), (True, {"event": "bos"}))
x = {"target": 2, "choch": False, "time_min": None, "breakeven_at": None, "partial": {"at": 1, "pct": 50}, "trail": {"start": 1, "dist": 0.5}}
r = D.validate("exit", x); chk("exit ok", r[0], True); chk("partial", r[1]["partial"], {"at": 1.0, "pct": 50}); chk("trail", r[1]["trail"], {"start": 1.0, "dist": 0.5})
chk("partial >= target", D.validate("exit", dict(x, partial={"at": 2, "pct": 50}))[0], False)
chk("partial pct range", D.validate("exit", dict(x, partial={"at": 1, "pct": 95}))[0], False)
chk("trail alone", D.validate("exit", {"target": None, "trail": {"start": 1, "dist": 1}})[0], True)
chk("nothing", D.validate("exit", {"target": None})[0], False)
chk("old exit unchanged", D.validate("exit", {"target": 1, "choch": True}), (True, {"target": 1.0, "choch": True, "time_min": None, "breakeven_at": None}))
chk("needs live", D.needs_live_support({"entry": r and D.validate("entry", e)[1], "exit": D.validate("exit", x)[1]}), ["order", "partial", "trail"])
print(D.describe("entry", D.validate("entry", e)[1])[0])
print(D.describe("exit", D.validate("exit", x)[1])[0])
print(D.describe("exit", D.validate("exit", {"target": None, "trail": {"start": 1, "dist": 1}})[1])[0])
print("ok", ok, "fail", bad)
