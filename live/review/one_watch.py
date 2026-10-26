"""one_watch.py - live feed of the owner's green (one mind) chats for the humanity watch (2026-10-26).
Prints one line per new message from him or from Kino, Kino's lines with first-word / total seconds from kino_one.log.
python review/one_watch.py [uid]   (runs until killed; polls every 2 s)"""
import glob, io, json, os, sys, time

LIVE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHATS = os.path.join(LIVE, "robots", "chats")
LOG = os.path.join(LIVE, "robots", "kino_one.log")
uid = sys.argv[1] if len(sys.argv) > 1 else "kino"
seen = {}
t_start = time.time()


def timing(cid, txt):
    try:
        for ln in reversed(io.open(LOG, encoding="utf-8", errors="replace").read().splitlines()[-80:]):
            if cid in ln and " TURN " in ln and txt[:40] in ln:
                a = ln.split("first=")[1].split()[0]
                b = ln.split("total=")[1].split()[0]
                r = ln.split("retry=")[1].split()[0]
                return " [first %ss, total %ss%s]" % (a, b, ", figure retry" if r == "True" else "")
    except Exception:
        pass
    return ""


while True:
    try:
        for p in glob.glob(os.path.join(CHATS, "*.json")):
            if os.path.getmtime(p) < t_start - 5:
                continue
            try:
                c = json.load(open(p, encoding="utf-8"))
            except Exception:
                continue
            if c.get("uid") != uid or c.get("brain") != "one":
                continue
            cid = c["id"]
            M = [m for m in c.get("msgs") or [] if m.get("role") in ("user", "ai") and str(m.get("text") or "").strip()]
            k = seen.get(cid)
            if k is None:
                k = len([m for m in M if float(m.get("t") or 0) < t_start])
            for m in M[k:]:
                who = "LUI " if m["role"] == "user" else ("KINO" + ("(own)" if m.get("event") else ""))
                txt = str(m["text"]).replace("\n", " / ")
                extra = timing(cid, str(m["text"]).replace("\n", " | ")) if m["role"] == "ai" else ""
                print("%s %s %s: %s%s" % (time.strftime("%H:%M:%S", time.gmtime(float(m["t"]))), cid[-6:], who, txt[:700], extra), flush=True)
            seen[cid] = len(M)
    except Exception as e:
        print("watch error %s" % e, flush=True)
    time.sleep(2)
