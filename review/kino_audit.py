"""Kino humanity audit (owner 2026-10-20: "keep monitoring our chat to make sure it's really behaving human like - a
digital being - e.g. can it take initiative, not always ask me for permission").

Reads the conversations of the last N hours (read only) and scores Kino on what a person would notice:
  permission  messages that only ask "should I / tu veux que / X ou Y ?"         (lower is better)
  question    messages ending with a question                                   (lower is better, < 40 %)
  own         messages Kino sent on its own (inner voice, follow-on, promise...)  (higher is better)
  standing    permission asked AFTER the member said to go on without asking    (must be 0)
  lang        language switches inside one conversation                         (should be 0)
  long        messages over 450 characters                                      (lower is better)
  latency     first words / full reply from robots/kino_timing.log
Usage: python review/kino_audit.py [hours=6] [uid=kino]"""
import json, os, re, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
LIVE = os.path.join(os.path.dirname(HERE), "live")
sys.path.insert(0, os.path.join(LIVE, "robots"))
import robot_chat as RC

H = float(sys.argv[1]) if len(sys.argv) > 1 else 6
UID = sys.argv[2] if len(sys.argv) > 2 else "kino"
since = time.time() - H * 3600
CH = os.path.join(LIVE, "robots", "chats")
FR = re.compile(r"\b(je|tu|le|la|les|est|pas|que|pour|avec|ça|une)\b", re.I)
EN = re.compile(r"\b(the|is|and|you|that|with|for|it's|this|was)\b", re.I)


def lang(t):
    f, e = len(FR.findall(t)), len(EN.findall(t))
    return "fr" if f > e + 1 else "en" if e > f + 1 else None


tot = {"ai": 0, "perm": 0, "q": 0, "own": 0, "standing": 0, "lang": 0, "long": 0}
ex = {"perm": [], "standing": [], "lang": []}
for f in sorted(os.listdir(CH)):
    if not f.endswith(".json"):
        continue
    try:
        c = json.load(open(os.path.join(CH, f), encoding="utf-8"))
    except Exception:
        continue
    if c.get("uid") != UID:
        continue
    M = [m for m in c.get("msgs") or [] if int(m.get("t") or 0) >= since and m.get("role") in ("user", "ai")]
    go_on_t = None
    last_lang = None
    for m in c.get("msgs") or []:
        if m.get("role") == "user" and re.search(r"without (my|asking)|sans (me )?demander|keep going|continue sans|do what you think|fais comme tu", str(m.get("text") or ""), re.I):
            go_on_t = int(m.get("t") or 0)
    for m in M:
        t = str(m.get("text") or "")
        if m["role"] == "user":
            lg = lang(t)
            if lg:
                last_lang = lg
            continue
        tot["ai"] += 1
        if RC.PERMISSION.search(t):
            tot["perm"] += 1
            ex["perm"].append(t[-120:])
            if go_on_t and int(m.get("t") or 0) > go_on_t:
                tot["standing"] += 1
                ex["standing"].append(t[-120:])
        if t.rstrip().endswith("?"):
            tot["q"] += 1
        if m.get("event"):
            tot["own"] += 1
        if len(t) > 450:
            tot["long"] += 1
        lg = lang(t)
        if lg and last_lang and lg != last_lang:
            tot["lang"] += 1
            ex["lang"].append(t[:80])

n = max(1, tot["ai"])
print("KINO AUDIT - %s, last %.0f h, %d Kino messages" % (UID, H, tot["ai"]))
print("  permission asked : %d (%.0f %%)%s" % (tot["perm"], 100.0 * tot["perm"] / n, "   <- too many" if tot["perm"] / n > 0.15 else ""))
print("  after 'go on'    : %d%s" % (tot["standing"], "   <- ignores their instruction" if tot["standing"] else ""))
print("  ends with ?      : %.0f %%%s" % (100.0 * tot["q"] / n, "   <- interview-like" if tot["q"] / n > 0.4 else ""))
print("  on its own       : %d (%.0f %%)" % (tot["own"], 100.0 * tot["own"] / n))
print("  language switch  : %d" % tot["lang"])
print("  long (>450 ch)   : %d" % tot["long"])
try:
    T = []
    for ln in open(os.path.join(LIVE, "robots", "kino_timing.log"), encoding="utf-8"):
        p = ln.split()
        if "ev=-" in ln:
            T.append((float(p[4].split("=")[1]), float(p[5].split("=")[1])))
    T = T[-60:]
    if T:
        fw = sorted(x[0] for x in T if x[0] >= 0)
        tt = sorted(x[1] for x in T)
        print("  first words      : median %.1f s, p90 %.1f s (%d replies)" % (fw[len(fw) // 2], fw[int(len(fw) * 0.9)], len(fw)) if fw else "")
        print("  full reply       : median %.1f s, p90 %.1f s" % (tt[len(tt) // 2], tt[int(len(tt) * 0.9)]))
except Exception:
    pass
for k in ("standing", "perm", "lang"):
    for e in ex[k][-3:]:
        print("   e.g. %s: ...%s" % (k, e.replace("\n", " ")))
