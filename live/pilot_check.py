"""Multi-broker pilot (owner 2026-10-16): connect a pilot demo's OWN portable terminal and run the broker
readiness check on it. Credentials from the git-ignored owl_secrets.json ("pilot_<broker>"); never printed.
    python live/pilot_check.py [pilot_pepperstone|pilot_forexcom]   -> nest_data/<key>.broker.json
If the server NAME is unknown to the terminal, the broker's address (key "server_addr") is tried next.
"""
import json, os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import MetaTrader5 as mt5
import broker_profile as BP

DIR = os.path.dirname(os.path.abspath(__file__))
KEY = sys.argv[1] if len(sys.argv) > 1 else "pilot_pepperstone"
P = json.load(open(os.path.join(DIR, "owl_secrets.json"), encoding="utf-8"))[KEY]
ok = False
for srv in [P["server"]] + ([P["server_addr"]] if P.get("server_addr") else []):
    t0 = time.time()
    ok = mt5.initialize(path=P["terminal"], login=int(P["login"]), password=P["password"], server=srv, timeout=180000)
    print(("connected via %r" % srv if ok else "connect failed via %r: %s" % (srv, mt5.last_error())) + " in %.0fs" % (time.time() - t0), flush=True)
    if ok:
        break
    mt5.shutdown()
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
json.dump(p, open(os.path.join(DIR, "nest_data", KEY + ".broker.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print(json.dumps({k: v for k, v in p.items() if k not in ("checks",)}, indent=1, ensure_ascii=False))
for c in p["checks"]:
    print(("PASS " if c["ok"] else ("FAIL " if c["block"] else "note ")) + c["en"] + ("" if c["ok"] else "   -> " + c["fix"]))
print("READY" if okr else "NOT READY: " + ", ".join(bad))
