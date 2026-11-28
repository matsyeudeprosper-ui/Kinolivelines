"""kino_watch_gate.py (2026-11-28, owner: "why 30 min... how does it work for a human? better, tokens low")

A person who looks after a friend's conversations does not re-read them on a clock: they look once a talk has ENDED,
right away when something went WRONG, and now and then when it has been quiet too long. This gate costs no AI - it reads
files only - and tells the watcher (Claude on a /loop) whether a full watch (review/kino_watch.py) is worth his tokens.

    python review/kino_watch_gate.py   -> "QUIET (...)" or "GO: reason; reason"
"""
import calendar, glob, json, os, time

LIVE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROB = os.path.join(LIVE, "robots")
STATE = os.path.join(os.path.dirname(LIVE), "study", "kino_watch_state.json")
TALK_OVER_MIN = 15        # a talk is over when nobody wrote for this long - then it is read as a whole
HEARTBEAT_H = 4           # quiet this long: one look anyway (silence can be the bug - no own messages, a dead loop)
ERR_WORDS = ("FAIL", "RuntimeError", "Traceback", "no answer")

now = time.time()
try:
    since = float(json.load(open(STATE, encoding="utf-8")).get("t") or 0)
except Exception:
    since = 0
why = []

# 1. a conversation moved since the last watch: read it once it is over (or now, if Kino wrote on his own)
ended, live, own = 0, 0, 0
for f in glob.glob(os.path.join(ROB, "chats", "*.json")):
    if os.path.getmtime(f) <= since:
        continue
    try:
        c = json.load(open(f, encoding="utf-8"))
    except Exception:
        continue
    new = [m for m in c.get("msgs") or [] if float(m.get("t") or 0) > since and (m.get("text") or m.get("role") == "user")]
    if not new:
        continue
    # his own = not an answer: flagged as an event, or nobody wrote to him in the 30 min before (job news is not flagged)
    T = [m for m in c.get("msgs") or [] if m.get("text") and m.get("role") in ("user", "ai")]
    for i, m in enumerate(T):
        if m.get("role") == "ai" and float(m.get("t") or 0) > since:
            lu = max([float(x.get("t") or 0) for x in T[:i] if x.get("role") == "user"] or [0])
            if m.get("event") or float(m.get("t") or 0) - lu > 1800:
                own += 1
                break
    if now - max(float(m.get("t") or 0) for m in new) >= TALK_OVER_MIN * 60:
        ended += 1
    else:
        live += 1
if own:
    why.append("%d chat(s) where Kino wrote on his own" % own)
if ended:
    why.append("%d talk(s) ended" % ended)

# 2. something broke since the last watch (his brain failed, a crash)
try:
    with open(os.path.join(ROB, "kino_one.log"), "rb") as fh:
        fh.seek(max(0, os.path.getsize(fh.name) - 60000))
        tail = fh.read().decode("utf-8", "replace").splitlines()
    yr = time.strftime("%Y")
    bad = 0
    for ln in tail:
        try:
            t = calendar.timegm(time.strptime(yr + "-" + ln[:14], "%Y-%m-%d %H:%M:%S"))   # the log is UTC
        except Exception:
            continue
        if t > since and any(w in ln for w in ERR_WORDS):
            bad += 1
    if bad:
        why.append("%d brain error(s)" % bad)
except Exception:
    pass

# 3. the heartbeat: a long silence is looked at too
if now - since >= HEARTBEAT_H * 3600:
    why.append("%.1f h since the last look" % ((now - since) / 3600))

if why:
    print("GO: " + "; ".join(why))
else:
    print("QUIET (%d talk(s) still going, last look %.0f min ago)" % (live, (now - since) / 60))
