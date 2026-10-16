"""Multi-broker pilot (owner 2026-10-16): connect the Pepperstone demo's OWN portable terminal and run the broker
readiness check on it. Credentials from the git-ignored owl_secrets.json ("pilot_pepperstone"); never printed.
    python live/pilot_check.py            -> nest_data/pilot_pepperstone.broker.json
"""
import json, os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import MetaTrader5 as mt5
import broker_profile as BP

DIR = os.path.dirname(os.path.abspath(__file__))
P = json.load(open(os.path.join(DIR, "owl_secrets.json"), encoding="utf-8"))["pilot_pepperstone"]
t0 = time.time()
ok = mt5.initialize(path=P["terminal"], login=int(P["login"]), password=P["password"], server=P["server"], timeout=180000)
print("connected" if ok else "connect failed %s" % (mt5.last_error(),), "in %.0fs" % (time.time() - t0), flush=True)
if not ok:
    sys.exit(1)
ai = mt5.account_info()
print("account %s @ %s (%s) %s, leverage 1:%s, margin mode %s" % (ai.login, ai.server, ai.company, ai.currency, ai.leverage, ai.margin_mode), flush=True)
cands = [s.name for s in (mt5.symbols_get() or []) if "BTC" in s.name.upper()]
print("Bitcoin-like symbols:", cands[:12], flush=True)
p = BP.profile(mt5)
mt5.shutdown()
okr, bad = BP.ready(p)
p.update({"ready": okr, "blocking": bad, "checks": BP.checks(p)})
json.dump(p, open(os.path.join(DIR, "nest_data", "pilot_pepperstone.broker.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print(json.dumps({k: v for k, v in p.items() if k not in ("checks",)}, indent=1, ensure_ascii=False))
for c in p["checks"]:
    print(("PASS " if c["ok"] else ("FAIL " if c["block"] else "note ")) + c["en"] + ("" if c["ok"] else "   -> " + c["fix"]))
print("READY" if okr else "NOT READY: " + ", ".join(bad))
