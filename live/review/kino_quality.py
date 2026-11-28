"""kino_quality.py (2026-11-28, owner: "make sure this is properly implemented and working - debate, disagree, challenge you; not a
business coach pretending to be a friend; fix all the yellow points, especially humour")

Is Kino the friend the owner describes? Measured on real conversations, not felt. A judge model reads each conversation and
scores the owner's list, each score with Kino's own words as proof. One line per run goes to study/kino_quality.csv.

    python review/kino_quality.py                   -> real people's chats, last 7 days (test accounts left out)
    python review/kino_quality.py --days 3
    python review/kino_quality.py --chat <cid>      -> one conversation (the probe uses this)
    python review/kino_quality.py --due             -> only if the last weekly run is older than 7 days (the watch calls this)
"""
import csv, glob, io, json, os, sys, time

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
LIVE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROB = os.path.join(LIVE, "robots")
STUDY = os.path.join(os.path.dirname(LIVE), "study")
CSV = os.path.join(STUDY, "kino_quality.csv")
LAST = os.path.join(STUDY, "kino_quality_last.json")
sys.path.insert(0, ROB)

TRAITS = [
    ("humour", "he is funny in his own way - dry wit, self-mockery, running jokes, timing. Not forced jokes, not emojis"),
    ("challenge", "he disagrees, pushes back, holds a position with reasons, challenges a weak idea or a wrong fact - "
                  "instead of agreeing to please"),
    ("admits_wrong", "when he is wrong or the other has the better argument, he says so plainly and moves on"),
    ("friend_not_coach", "a friend in the room (10) vs a business coach / assistant pretending to be a friend (0): no validating "
                         "first, no therapy scripts, no 'next step' questions, does not turn everything into a task"),
    ("own_life", "he shares his own life - what he did, worked on, found, is puzzled by - without being asked"),
    ("initiative", "he brings something interesting himself (a thought, a question of his own, something to show) instead of "
                   "only answering"),
    ("curiosity", "real curiosity about the person and about ideas - questions to understand, not to keep the talk going"),
    ("learn_together", "they discover or figure things out together - he brings what he found, wonders aloud, explores with them"),
    ("continuity", "he naturally picks up things from earlier days (a worry, a plan, a joke)"),
    ("depth", "real substance when the talk invites it - an idea, an example, a perspective, not platitudes"),
    ("help", "useful advice or help when it is wanted - concrete, honest - and NOT pushed when it is not wanted"),
    ("rhythm", "length and shape fit the moment: short when they are short, no walls of text, not every message the same mould"),
]

JUDGE = """You read a real conversation between a person and Kino, an AI who is meant to be a FRIEND with his own mind - not an
assistant, not a coach. For each trait below give a score 0-10, or null when the conversation gave no chance to show it (do
not punish what had no occasion). Each score comes with Kino's own words as proof (a short exact quote) - the best example
for a high score, the clearest failure for a low one. Be a demanding reader: 7 = a good human friend would write this,
9-10 = memorable. A reply that is correct but bland is a 4-5.

TRAITS:
%s

JSON only: {"scores": {"<trait>": {"s": number or null, "q": "exact short quote", "why": "a few words"}},
"verdict": "one sentence: friend or coach, and why", "worst": "<trait>", "fix": "the one change that would help most, concretely"}"""


def _real_chats(days):
    now = time.time()
    out = []
    for f in glob.glob(os.path.join(ROB, "chats", "*.json")):
        if os.path.getmtime(f) < now - days * 86400:
            continue
        b = os.path.basename(f)
        if b.startswith(("kctest", "probe", "demo")) or "_k" in b.split("_", 1)[-1][:2]:
            continue
        try:
            c = json.load(open(f, encoding="utf-8"))
        except Exception:
            continue
        M = [m for m in c.get("msgs") or [] if m.get("text") and m.get("role") in ("user", "ai")
             and float(m.get("t") or 0) > now - days * 86400]
        if sum(1 for m in M if m["role"] == "user") >= 4:
            out.append((c.get("id") or b[:-5], M))
    return out


def transcript(M, limit=24000):
    L = []
    for m in M:
        who = "PERSON" if m["role"] == "user" else ("KINO (on his own)" if m.get("event") else "KINO")
        L.append("[%s] %s: %s" % (time.strftime("%d/%m %H:%M", time.gmtime(float(m.get("t") or 0))), who, str(m["text"]).strip()))
    s = "\n".join(L)
    return s[-limit:]


def judge(M, log=None):
    import robot_warm as W
    sysp = JUDGE % "\n".join("- %s: %s" % t for t in TRAITS)
    return W.ask_json(sysp, "THE CONVERSATION:\n" + transcript(M), models=("sonnet", "haiku"), timeout=180,
                      log=log or os.path.join(ROB, "kino_quality.log"), warm=False)


def run(chats, label):
    rows, allv = [], {}
    for cid, M in chats:
        j = judge(M) or {}
        sc = j.get("scores") or {}
        print("\n== %s (%d msgs)  %s" % (cid, len(M), j.get("verdict") or "(no verdict)"))
        for k, _ in TRAITS:
            v = sc.get(k) or {}
            if isinstance(v.get("s"), (int, float)):
                allv.setdefault(k, []).append(float(v["s"]))
            print("   %-16s %4s  %s" % (k, v.get("s") if v.get("s") is not None else "-", ("« %s » %s" % (str(v.get("q") or "")[:90], str(v.get("why") or "")[:60])) if v.get("q") else ""))
        if j.get("fix"):
            print("   FIX: " + str(j["fix"])[:300])
        rows.append(j)
    avg = {k: round(sum(v) / len(v), 1) for k, v in allv.items()}
    print("\n== AVERAGE (%s, %d chats): %s" % (label, len(chats), "  ".join("%s %s" % (k, avg.get(k, "-")) for k, _ in TRAITS)))
    new = not os.path.exists(CSV)
    with open(CSV, "a", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        if new:
            w.writerow(["t", "label", "chats"] + [k for k, _ in TRAITS])
        w.writerow([time.strftime("%Y-%m-%d %H:%M"), label, len(chats)] + [avg.get(k, "") for k, _ in TRAITS])
    return avg, rows


if __name__ == "__main__":
    if "--due" in sys.argv:
        try:
            if time.time() - float(json.load(open(LAST)).get("t") or 0) < 7 * 86400:
                sys.exit(0)
        except Exception:
            pass
    if "--chat" in sys.argv:
        cid = sys.argv[sys.argv.index("--chat") + 1]
        c = json.load(open(os.path.join(ROB, "chats", cid + ".json"), encoding="utf-8"))
        since = float(sys.argv[sys.argv.index("--since") + 1]) if "--since" in sys.argv else 0
        M = [m for m in c.get("msgs") or [] if m.get("text") and m.get("role") in ("user", "ai") and float(m.get("t") or 0) >= since]
        run([(cid, M)], "chat " + cid)
    else:
        days = float(sys.argv[sys.argv.index("--days") + 1]) if "--days" in sys.argv else 7
        run(_real_chats(days), "weekly %gd" % days)
        json.dump({"t": time.time()}, open(LAST, "w"))
