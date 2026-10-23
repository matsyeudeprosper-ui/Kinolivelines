"""kino_watch.py (2026-10-23, owner: "keep a permanent watch on my conversations with Kino to fix anything odd")

Prints what is NEW since the last run, compactly, for the watcher (Claude, on a /loop) to judge:
  - the owner's chats: every message (member / Kino / system / error) since the last watermark, with the chat id
  - chat_errors.log lines, commitment status changes, surprises, live calls (START/END/WHY)
State: study/kino_watch_state.json (watermark). --all shows the last 6 h regardless. --uid X watches another member.
"""
import io, json, os, re, sys, time, glob

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
LIVE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROB = os.path.join(LIVE, "robots")
STATE = os.path.join(os.path.dirname(LIVE), "study", "kino_watch_state.json")
UID = sys.argv[sys.argv.index("--uid") + 1] if "--uid" in sys.argv else "kino"
now = time.time()
try:
    st = json.load(open(STATE, encoding="utf-8"))
except Exception:
    st = {}
since = now - 6 * 3600 if "--all" in sys.argv else float(st.get("t") or now - 6 * 3600)
hm = lambda t: time.strftime("%d/%m %H:%M", time.gmtime(float(t or 0)))
print("WATCH since %s UTC (now %s)" % (hm(since), hm(now)))

# 1 the chats
n = 0
for f in sorted(glob.glob(os.path.join(ROB, "chats", "*.json")), key=os.path.getmtime):
    try:
        c = json.load(open(f, encoding="utf-8"))
    except Exception:
        continue
    if c.get("uid") != UID:
        continue
    M = [m for m in c.get("msgs") or [] if float(m.get("t") or 0) > since]
    if not M:
        continue
    print("\n== chat %s | thread: %s | robot: %s" % (c["id"], str(c.get("thread") or "")[:60], (c.get("robot") or {}).get("name")))
    for m in M:
        r = m.get("role")
        tag = {"user": "MEMBER", "ai": "KINO", "sys": "system", "card": "card", "demo": "chart", "result": "RESULT", "ideacard": "idea card",
               "moved": "moved", "setting": "setting", "proposal": "proposal", "image": "image", "doc": "doc"}.get(r, r)
        extra = []
        if m.get("err"):
            extra.append("ERROR")
        if m.get("event"):
            extra.append("on his own")
        if m.get("quick"):
            extra.append("quick")
        if m.get("night"):
            extra.append("night")
        if m.get("via"):
            extra.append(str(m["via"]))
        if r == "result":
            rr = m.get("result") or {}
            txt = "net %s over %s trades" % (rr.get("net"), rr.get("trades"))
        elif r == "ideacard":
            txt = str((m.get("card") or {}).get("summary") or "")[:200]
        else:
            txt = str(m.get("text") or m.get("kind") or "")[:600].replace("\n", " / ")
        print("  %s %-9s %s%s" % (hm(m.get("t")), tag, txt, (" [" + ", ".join(extra) + "]") if extra else ""))
        n += 1
print("\n%d new messages" % n)

# 2 errors
try:
    L = [l for l in io.open(os.path.join(ROB, "chat_errors.log"), encoding="utf-8", errors="replace").read().splitlines()
         if re.match(r"^\d{4}-\d\d-\d\d \d\d:\d\d:\d\d ", l)]
    E = [l for l in L if time.mktime(time.strptime(l[:19], "%Y-%m-%d %H:%M:%S")) > since - time.timezone]
    if E:
        print("\n== chat errors (%d):" % len(E))
        for l in E[-8:]:
            print("  " + l[:220])
except Exception:
    pass

# 3 commitments
try:
    d = json.load(open(os.path.join(ROB, "kino_commitments.json"), encoding="utf-8"))
    C = [x for x in d.get("items") or [] if x.get("uid") == UID and (float(x.get("t") or 0) > since or float(x.get("done_t") or 0) > since)]
    if C:
        print("\n== commitments:")
        for x in C[-12:]:
            print("  %s [%s] %s %s | %s%s" % (hm(x["t"]), x["id"], x["kind"], x["status"].upper(), x["what"][:100], (" | " + str(x.get("how"))) if x.get("how") else ""))
except Exception:
    pass

# 4 surprises, plan, readings
try:
    S = [x for x in (json.load(open(os.path.join(ROB, "kino_surprise.json"), encoding="utf-8")).get("log") or []) if float(x["t"]) > since and x.get("uid") in (None, UID)]
    if S:
        print("\n== surprises:")
        for x in S[-6:]:
            print("  %s %s" % (hm(x["t"]), x["text"][:200]))
except Exception:
    pass
try:
    X = json.load(open(os.path.join(ROB, "kino_exec.json"), encoding="utf-8"))
    P = (X.get("plans") or [None])[-1]
    if P and float(P.get("t") or 0) > since:
        print("\n== new plan %s: %s" % (P["day"], " | ".join("[%s] %s" % (i["id"], i["what"][:80]) for i in P["items"])))
    R = (X.get("reviews") or [None])[-1]
    if R and float(R.get("t") or 0) > since:
        print("\n== new review %s: %s" % (R["day"], R["text"][:500]))
except Exception:
    pass
try:
    PS = json.load(open(os.path.join(ROB, "kino_person.json"), encoding="utf-8")).get(UID) or {}
    pr = [p for p in PS.get("preds") or [] if float(p.get("t") or 0) > since]
    if pr:
        print("\n== readings: %s" % ", ".join("%s->%s %s" % (p.get("next"), p.get("actual") or "?", "ok" if p.get("right") else ("MISS" if p.get("checked") else "")) for p in pr[-10:]))
except Exception:
    pass

# 5 live calls
try:
    L = [l.rstrip() for l in io.open(os.path.join(ROB, "live.log"), encoding="utf-8", errors="replace") if re.match(r"^\d{4}", l)]
    V = [l for l in L if time.mktime(time.strptime(l[:19], "%Y-%m-%d %H:%M:%S")) > since - time.timezone and (" START " in l or " END " in l or " WHY " in l)]
    if V:
        print("\n== calls:")
        for l in V[-6:]:
            print("  " + l[:160])
except Exception:
    pass

if "--all" not in sys.argv and "--peek" not in sys.argv:
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    json.dump({"t": now, "ran": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now))}, open(STATE, "w", encoding="utf-8"))

# 2026-10-23: today's humanity scorecard on the real conversation (robots/kino_scorecard.py)
try:
    import sys as _sys, os as _os
    _sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))), "robots"))
    import kino_scorecard as _KSC
    _S = _KSC.score_day("kino")
    print("\n== scorecard today: " + ", ".join("%s=%s" % (k, v) for k, v in _S.items() if k not in ("day", "uid")))
except Exception as _e:
    print("\n== scorecard: " + str(_e)[:80])
