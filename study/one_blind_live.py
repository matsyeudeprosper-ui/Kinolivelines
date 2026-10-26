"""one_blind_live.py - the fair blind test (2026-10-25): old Kino and the one mind answer THE SAME messages at THE SAME moment,
on the test account (std), so both read identical facts. Writes live/robots/one_blind.json for /<owner token>/blind.

python study/one_blind_live.py            (about 10 minutes: the old brain takes 15-40 s a reply)
"""
import json, os, random, sys, time, urllib.request

LIVE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "live")
OUT = os.path.join(LIVE, "robots", "one_blind.json")
U = json.load(open(os.path.join(LIVE, "owl_nest_users.json"), encoding="utf-8"))
TOK = [u for u in U if u["id"] == "std"][0]["token"]
BASE = "http://127.0.0.1:8787/%s/" % TOK

# the owner's own phrasings, taken from his chats
SCRIPTS = [["Hi"], ["ça va ?"], ["il en est où le robot ?"], ["pourquoi il perd autant ?"], ["Lol"],
           ["tu fais quoi quand je suis pas là ?"], ["Tu as un cerveau"], ["franchement je suis crevé ce soir"],
           ["tu me conseilles quoi pour demain ?"], ["Why is it failing to hit just 0.8 tp"],
           ["il a fait combien cette semaine ?", "ok"], ["je pense arrêter le trading"]]


def P(a, b):
    return json.loads(urllib.request.urlopen(urllib.request.Request(BASE + a, data=json.dumps(b).encode(), headers={"Content-Type": "application/json"}), timeout=150).read())


def G(cid):
    j = json.loads(urllib.request.urlopen(BASE + "chat_get?id=" + cid, timeout=150).read())
    return (j.get("chat") or j).get("msgs") or []


def talk(brain, msgs):
    j = P("chat_start", {"lang": "fr", **({"brain": brain} if brain else {})})
    cid = (j.get("chat") or {}).get("id") or j.get("id")
    t0 = time.time()                                    # let the opening greeting land first (both brains write one)
    while time.time() - t0 < 60 and not [m for m in G(cid) if m.get("role") == "ai"]:
        time.sleep(1)
    time.sleep(3)
    last = None
    for t in msgs:
        n0 = len([m for m in G(cid) if m.get("role") == "ai"])
        ts = time.time()
        P("chat_send", {"id": cid, "text": t})
        while time.time() - ts < 120:
            time.sleep(1)
            ai = [m for m in G(cid) if m.get("role") == "ai"]
            if len(ai) > n0:
                time.sleep(4)                           # a second bubble may follow
                ai = [m for m in G(cid) if m.get("role") == "ai" and float(m.get("t") or 0) >= ts]
                last = ("\n\n".join(str(m.get("text") or "") for m in ai), time.time() - ts)
                break
        time.sleep(2)
    return cid, last


cases = []
json.dump({"made": time.time(), "state": "building", "cases": []}, open(OUT, "w", encoding="utf-8"))
for _w in range(60):                                    # the app must be up
    try:
        urllib.request.urlopen(BASE + "chat_list", timeout=10).read(); break
    except Exception:
        time.sleep(5)


def safe(brain, sc):
    for _k in range(2):
        try:
            return talk(brain, sc)
        except Exception as e:
            print("retry", brain, sc, type(e).__name__, flush=True)
            time.sleep(10)
    return None, None


for i, sc in enumerate(SCRIPTS):
    oc, old = safe(None, sc)
    nc, new = safe("one", sc)
    if not old or not new:
        print("skip", sc, bool(old), bool(new), flush=True)
        continue
    ctx = [{"who": "lui", "text": x} for x in sc[:-1]]
    cases.append({"id": "live_%d_%d" % (int(time.time()), i), "t": time.time(), "ctx": ctx, "msg": sc[-1], "old": old[0][:1200], "new": new[0][:1200],
                  "old_s": round(old[1], 1), "new_s": round(new[1], 1), "new_is": random.choice(["A", "B"]), "chats": [oc, nc]})
    json.dump({"made": time.time(), "state": "building", "cases": cases}, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("%d/%d  old %.0f s | new %.0f s  %s" % (i + 1, len(SCRIPTS), old[1], new[1], sc[-1]), flush=True)
json.dump({"made": time.time(), "state": "ready", "cases": cases}, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("ready", len(cases))
