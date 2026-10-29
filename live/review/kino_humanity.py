"""kino_humanity.py (2026-10-29, owner: "your recommendation - go") - is Kino talking more like a person? Measured, not felt.

Baseline (2026-10-28, owner's main thread, 48 h before the v3 engines): 42 own messages, 57 words per message vs his 25,
a question in 10 of 154 messages, "R" 36x, "your rule" 16x.

    python review/kino_humanity.py [--hours 48] [--uid std]      -> one block of numbers, and a line in study/kino_humanity.csv
"""
import collections, csv, glob, io, json, os, re, sys, time

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
LIVE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
H = float(sys.argv[sys.argv.index("--hours") + 1]) if "--hours" in sys.argv else 48.0
UID = sys.argv[sys.argv.index("--uid") + 1] if "--uid" in sys.argv else "std"
try:
    P = json.load(open(os.path.join(LIVE, "robots", "persons.json"), encoding="utf-8"))
except Exception:
    P = {}
ROOT = P.get(UID, UID)
UIDS = {ROOT} | {u for u, r in P.items() if r == ROOT}
now = time.time()
M = []
for f in glob.glob(os.path.join(LIVE, "robots", "chats", "*.json")):
    try:
        c = json.load(open(f, encoding="utf-8"))
    except Exception:
        continue
    if c.get("uid") not in UIDS:
        continue
    M += [dict(m, _cid=c.get("id")) for m in c.get("msgs") or [] if now - float(m.get("t") or 0) < H * 3600]
M.sort(key=lambda m: float(m.get("t") or 0))
ai = [m for m in M if m.get("role") == "ai" and m.get("text")]
own = [m for m in ai if m.get("event")]
rep = [m for m in ai if not m.get("event")]
us = [m for m in M if m.get("role") == "user" and m.get("text")]
w = lambda t: len(str(t).split())
avg = lambda L: round(sum(L) / len(L), 1) if L else 0
txt = " ".join(str(m["text"]) for m in ai)
nums = len(re.findall(r"\d+(?:[.,]\d+)?", txt))
# replies to a closing ("cool", "ok", "thx"...): did he answer within 5 min?
closings, answered = 0, 0
for i, m in enumerate(M):
    if m.get("role") == "user" and re.fullmatch(r"\s*(ok|okay|cool|thx|thanks|merci|nice|yep|i see|ah ok|ha ok|lol)[.!]*\s*", str(m.get("text") or "").lower()):
        closings += 1
        nxt = next((x for x in M[i + 1:] if x.get("role") in ("ai", "user")), None)
        if nxt and nxt.get("role") == "ai" and float(nxt.get("t") or 0) - float(m.get("t") or 0) < 300:
            answered += 1
# repeated 4-word phrases within the same hour (a repeat a person would not make)
seen, repeats = {}, 0
for m in ai:
    t = float(m.get("t") or 0)
    ws = re.findall(r"[a-zà-ÿ0-9']+", str(m["text"]).lower())
    for i in range(len(ws) - 3):
        g = " ".join(ws[i:i + 4])
        if g in seen and t - seen[g] < 3600 and not re.search(r"\d", g):
            repeats += 1
        seen[g] = t
R = {
    "hours": H, "his_msgs": len(us), "kino_replies": len(rep), "kino_own": len(own),
    "kino_words": avg([w(m["text"]) for m in ai]), "his_words": avg([w(m["text"]) for m in us]),
    "question_pct": round(100 * sum(1 for m in ai if "?" in str(m["text"])) / max(1, len(ai))),
    "numbers_per_msg": round(nums / max(1, len(ai)), 1),
    "R_count": len(re.findall(r"\b\d*\.?\d+R\b|\bR\b", txt)), "your_rule": len(re.findall(r"your rule|ta règle|tes règles|your rules", txt, re.I)),
    "closings": closings, "closings_answered": answered, "same_hour_repeats": repeats,
}
print("KINO HUMANITY (%s, last %d h): %d of his messages | Kino: %d replies + %d on his own" % (ROOT, H, R["his_msgs"], R["kino_replies"], R["kino_own"]))
print("  words per message: Kino %s vs him %s | a question in %s%% | numbers per message %s" % (R["kino_words"], R["his_words"], R["question_pct"], R["numbers_per_msg"]))
print("  'R' %d, 'your rule' %d | closings answered %d of %d | 4-word repeats within the hour %d" % (
    R["R_count"], R["your_rule"], R["closings_answered"], R["closings"], R["same_hour_repeats"]))
print("  baseline 10-28: own 42/48h, words 57 vs 25, question 6%, R 36, your rule 16")
out = os.path.join(os.path.dirname(LIVE), "study", "kino_humanity.csv")
new = not os.path.exists(out)
with open(out, "a", newline="", encoding="utf-8") as f:
    wr = csv.DictWriter(f, fieldnames=["t"] + list(R))
    if new:
        wr.writeheader()
    wr.writerow(dict(R, t=time.strftime("%Y-%m-%d %H:%M")))
