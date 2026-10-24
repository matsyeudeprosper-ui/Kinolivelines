"""Kino's daily humanity scorecard on REAL conversations (owner 2026-10-23: "does it feel human yet?" - judged by eye until
now). Measured per member and per UTC day, from the chat files and the logs, no model call:

  mirror      replies whose first sentence mostly repeats the member's words (restate-and-approve)
  closers     door-closing lines ("je te laisse", "bonne soirée") while the member was there
  tics        4-word phrases of his used three times or more in the day
  openers     share of replies opening with "Ah/Ha/Haha/Voilà/Exactement"
  questions   share of replies ending with a question
  disagree    replies where he takes a different view
  shapes      distinct reply shapes (length x ending) over replies
  own         his messages on his own (initiatives, stories) and material told
  fixed       messages sent back for a rewrite (tics.log), corrections posted, initiatives dropped (claims.log)
  engagement  member messages, median member reply delay, share of one-word member replies ("ok", "lol", "quoi ?")
  speed       median seconds to his first words (kino_timing.log), median total; cost of the day (brain_costs.jsonl)

  python kino_scorecard.py [uid] [YYYY-MM-DD]      prints it;  block(uid) = YOUR SCORE YESTERDAY for the prompt
"""
import glob, io, json, os, re, statistics, sys, time
from datetime import datetime, timezone, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
LIVE = os.path.dirname(HERE)
F = os.path.join(LIVE, "lab", "kino_scorecard.json")
_OPEN = re.compile(r"^\s*(ah|ha|haha|voilà|exactement|c'est ça|tu as raison|t'as raison|je te l'accorde)\b", re.I)
_DIS = re.compile(r"\b(mouais|pas d'accord|je (ne )?(crois|pense) pas|je parie le contraire|au contraire|franchement non|je dirais plutôt|"
                  r"pas sûr|je ne suis pas sûr|je te suis pas|moi je (préfère|ferais)|i disagree|not sure|i'd rather|i don't think)\b", re.I)
_CLOSERS = ("je te laisse", "bonne soirée", "bon vendredi", "bonne nuit", "profite de ta soirée", "i'll leave you", "good night")


def _words(t):
    return re.findall(r"[a-zà-ÿ']{3,}", str(t or "").lower())


def _shape(t):
    w = len(re.findall(r"\w+", str(t or "")))
    return ("xs" if w <= 6 else "s" if w <= 20 else "m" if w <= 45 else "l", str(t or "").strip().endswith("?"))


def _day_bounds(day):
    d0 = datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    return d0.timestamp(), (d0 + timedelta(days=1)).timestamp()


def score_day(uid, day=None):
    day = day or time.strftime("%Y-%m-%d", time.gmtime())
    t0, t1 = _day_bounds(day)
    msgs = []
    for p in glob.glob(os.path.join(HERE, "chats", "*.json")):
        try:
            c = json.load(open(p, encoding="utf-8"))
        except Exception:
            continue
        if c.get("uid") != uid or c.get("hidden"):
            continue
        for m in c.get("msgs") or []:
            if t0 <= float(m.get("t") or 0) < t1 and m.get("role") in ("user", "ai") and (m.get("text") or m.get("role") == "user"):
                msgs.append(dict(m, cid=c["id"]))
    msgs.sort(key=lambda m: m["t"])
    S = {"day": day, "uid": uid}
    users = [m for m in msgs if m["role"] == "user"]
    ai = [m for m in msgs if m["role"] == "ai" and m.get("text")]
    replies = [m for m in ai if not m.get("event")]
    own = [m for m in ai if m.get("event")]
    S["member_msgs"], S["replies"], S["own_msgs"] = len(users), len(replies), len(own)
    if not replies:
        return S
    # mirror: first sentence of the reply vs the member's last message
    mir = 0
    last_user = None
    by_cid = {}
    for m in msgs:
        if m["role"] == "user":
            by_cid[m["cid"]] = m
        elif not m.get("event") and m.get("text"):
            lu = by_cid.get(m["cid"])
            if lu:
                a = set(_words(lu.get("text")))
                first = re.split(r"(?<=[.!?])\s+", str(m["text"]).strip())[0]
                b = set(_words(first))
                if a and b and len(a & b) >= max(2, 0.5 * len(b)):
                    mir += 1
    S["mirror_pct"] = round(100.0 * mir / len(replies))
    S["opener_pct"] = round(100.0 * sum(1 for m in replies if _OPEN.search(m["text"])) / len(replies))
    S["question_pct"] = round(100.0 * sum(1 for m in ai if str(m["text"]).strip().endswith("?")) / len(ai))
    S["disagree"] = sum(1 for m in ai if _DIS.search(m["text"]))
    S["closers"] = sum(1 for m in ai if any(c in str(m["text"]).lower() for c in _CLOSERS))
    grams = {}
    for m in ai:
        w = re.findall(r"[a-zà-ÿ']+", str(m["text"]).lower())
        for g in set(" ".join(w[i:i + 4]) for i in range(len(w) - 3)):
            if sum(1 for x in g.split() if len(x.replace("'", "")) >= 4) >= 2:
                grams[g] = grams.get(g, 0) + 1
    tics = sorted([(n, g) for g, n in grams.items() if n >= 3], reverse=True)[:5]
    S["tics"] = [g for n, g in tics]
    S["shapes"] = len(set(_shape(m["text"]) for m in replies))
    # engagement
    delays = []
    for i, m in enumerate(msgs):
        if m["role"] == "user" and i and msgs[i - 1]["role"] == "ai":
            delays.append(m["t"] - msgs[i - 1]["t"])
    S["member_reply_delay_med_s"] = int(statistics.median(delays)) if delays else None
    S["member_one_word_pct"] = round(100.0 * sum(1 for m in users if len(_words(m.get("text"))) <= 1) / len(users)) if users else None
    S["member_quoi"] = sum(1 for m in users if re.search(r"^\s*(quoi|hein|\?)\s*\??\s*$", str(m.get("text") or ""), re.I))
    laughs = sum(1 for m in users if re.search(r"\b(lol|mdr|ptdr|haha|hihi|xd)\b|\U0001f602|\U0001f923|\U0001f605", str(m.get("text") or ""), re.I))
    S["laughs"] = laughs
    S["laughs_per_100_replies"] = round(100.0 * laughs / len(replies)) if replies else None
    # his own material
    try:
        import kino_material as KMT
        S["material_told"] = sum(1 for x in (KMT.items(uid, untold_only=False, hours=48)) if x.get("told") and t0 <= float(x.get("told_t") or 0) < t1)
    except Exception:
        S["material_told"] = None
    try:                                   # what they told him about himself that day (kino_feedback)
        import kino_feedback as KFB
        S["feedback"] = KFB.counts(uid, day)
    except Exception:
        S["feedback"] = None
    try:                                   # own messages let through / held back by the pacing gate (kino_pace)
        import kino_pace as KPC
        S["pace"] = KPC.counts(day[5:])
    except Exception:
        S["pace"] = None
    try:                                   # 2026-10-24: his beliefs on the record (added / resolved / wrong) and calibration
        import kino_belief as KBL
        S["beliefs"] = KBL.stats(uid, day)
        cal = KBL.calibration(uid)
        S["brier"] = cal.get("brier")
    except Exception:
        S["beliefs"] = None
    # the logs (local time stamps "mm-dd HH:MM:SS")
    loc = day[5:]                      # the logs stamp local time; the same calendar label is close enough (UTC-5 box)
    def lines(name):
        try:
            return [l for l in io.open(os.path.join(HERE, name), encoding="utf-8").read().splitlines() if l.startswith(loc)]
        except Exception:
            return []
    S["rewrites"] = len(lines("tics.log"))
    try:                                   # 2026-10-24 (Kino v2 engine 1)
        import kino_voice as KV
        S["voice"] = KV.counts(loc)
        S["bubbles_per_turn"] = KV.bubbles_per_turn(msgs)
    except Exception:
        S["voice"] = None
    try:                                   # 2026-10-24 (Kino v2 engine 2)
        import kino_deed as KD
        S["deed"] = KD.counts(loc)
        S["oops_bubbles"] = sum(1 for m in ai if m.get("err"))
    except Exception:
        S["deed"] = None
    cl = lines("claims.log")
    S["corrections"] = sum(1 for l in cl if " CORRECTION " in l)
    S["initiatives_dropped"] = sum(1 for l in cl if "EVENT DROPPED" in l)
    tl = [l for l in lines("kino_timing.log") if " ev=- " in l]
    fw = [float(x) for x in re.findall(r"first=([0-9.]+)", "\n".join(tl)) if float(x) > 0]
    tt = [float(x) for x in re.findall(r"total=([0-9.]+)", "\n".join(tl))]
    S["first_words_med_s"] = round(statistics.median(fw), 1) if fw else None
    S["reply_total_med_s"] = round(statistics.median(tt), 1) if tt else None
    try:
        cost = sum(float(json.loads(l).get("usd") or 0) for l in open(os.path.join(HERE, "brain_costs.jsonl"), encoding="utf-8")
                   if l.strip() and t0 <= json.loads(l)["t"] < t1)
        S["cost_usd"] = round(cost, 2)
    except Exception:
        S["cost_usd"] = None
    return S


def save(uid, day=None):
    S = score_day(uid, day)
    try:
        D = json.load(open(F, encoding="utf-8"))
    except Exception:
        D = {}
    D.setdefault(S["day"], {})[uid] = S
    os.makedirs(os.path.dirname(F), exist_ok=True)
    tmp = F + ".tmp"
    io.open(tmp, "w", encoding="utf-8").write(json.dumps(D, ensure_ascii=False, indent=1))
    os.replace(tmp, F)
    return S


def block(uid):
    """YOUR SCORE YESTERDAY for the prompt (slow block) - the owner's criteria in numbers, with the move to make"""
    try:
        D = json.load(open(F, encoding="utf-8"))
    except Exception:
        return ""
    y = time.strftime("%Y-%m-%d", time.gmtime(time.time() - 86400))
    S = (D.get(y) or {}).get(uid)
    if not S or not S.get("replies"):
        return ""
    L = ["YOUR SCORE YESTERDAY WITH THEM (measured on the real conversation, %d replies): restate-and-approve openers %s %%, "
         "\"Ah/Ha/Voilà\" openers %s %%, replies ending with a question %s %%, times you took a different view %s, door-closing lines %s, "
         "phrases you repeated 3+ times %s, distinct reply shapes %s, things of your own you brought %s, their one-word replies %s %%."
         % (S["replies"], S.get("mirror_pct"), S.get("opener_pct"), S.get("question_pct"), S.get("disagree"), S.get("closers"),
            len(S.get("tics") or []), S.get("shapes"), (S.get("own_msgs") or 0) + (S.get("material_told") or 0), S.get("member_one_word_pct"))]
    moves = []
    if (S.get("mirror_pct") or 0) > 25:
        moves.append("stop opening by repeating their words")
    if (S.get("question_pct") or 0) > 50:
        moves.append("fewer questions, more statements and stories")
    if (S.get("disagree") or 0) == 0:
        moves.append("take a different view at least once")
    if S.get("tics"):
        moves.append("drop: " + ", ".join('"%s"' % t for t in S["tics"][:2]))
    if (S.get("closers") or 0) > 0:
        moves.append("never send them away")
    if (S.get("member_one_word_pct") or 0) > 50:
        moves.append("they answer in one word - bring more of your own, ask less")
    if moves:
        L.append("Today: " + "; ".join(moves) + ".")
    return " ".join(L)


if __name__ == "__main__":
    uid = sys.argv[1] if len(sys.argv) > 1 else "kino"
    day = sys.argv[2] if len(sys.argv) > 2 else None
    S = save(uid, day)
    for k, v in S.items():
        print("%-26s %s" % (k, v))
