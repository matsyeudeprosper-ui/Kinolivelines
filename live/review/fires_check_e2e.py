import json, time, urllib.request, os, sys
LIVE = r"C:\Projects\KinoliveLines\live"
U = json.load(open(os.path.join(LIVE, "owl_nest_users.json"), encoding="utf-8"))
U = U.get("users", U) if isinstance(U, dict) else U
tok = next(u.get("token") for u in U if u.get("id") == "kino")
src = json.load(open(os.path.join(LIVE, "robots", "chats", "kino_1792607513975.json"), encoding="utf-8"))
cid = "kino_t%d_9999999999999" % int(time.time())
c = {k: v for k, v in src.items() if k not in ("msgs", "check", "test")}
c["id"] = cid; c["msgs"] = [m for m in src["msgs"] if m.get("role") in ("user", "ai")][-4:]
p = os.path.join(LIVE, "robots", "chats", cid + ".json")
json.dump(c, open(p, "w", encoding="utf-8"), ensure_ascii=False)
def post(fn, body):
    rq = urllib.request.Request("http://127.0.0.1:8787/%s/%s" % (tok, fn), data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(rq, timeout=120).read().decode())
try:
    print("robot:", c["robot"].get("name"), c["robot"].get("market"))
    print("1 test before check ->", post("chat_test", {"id": cid}))
    r = post("chat_fires", {"id": cid}); print("2 fires ->", r)
    cc = json.load(open(p, encoding="utf-8")); m = cc["msgs"][-1]
    print("   msg:", m.get("kind"), m.get("check"), "moments", len(m.get("moments") or []), "count", m.get("count"), "per_day", m.get("per_day"),
          [(time.strftime("%m-%d %H:%M", time.gmtime(x["t"])), x["side"], x.get("after")) for x in m["moments"]])
    print("3 test while open ->", post("chat_test", {"id": cid}))
    for j in range(r["n"] - 1): post("chat_fires_vote", {"id": cid, "j": j, "yes": 1})
    print("4 last vote NO ->", post("chat_fires_vote", {"id": cid, "j": r["n"] - 1, "yes": 0}))
    print("5 test with a no ->", post("chat_test", {"id": cid}))
    print("6 last vote YES ->", post("chat_fires_vote", {"id": cid, "j": r["n"] - 1, "yes": 1}))
    cc = json.load(open(p, encoding="utf-8")); cc["robot"]["market"] = "USTEC"; json.dump(cc, open(p, "w", encoding="utf-8"), ensure_ascii=False)
    print("7 market changed -> test ->", post("chat_test", {"id": cid}))
    print("8 original chat_check still works ->", post("chat_check", {"type": "exit", "rule": {"target": 1}}))
finally:
    os.remove(p); print("test chat removed")
