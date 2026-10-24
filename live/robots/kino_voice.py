"""kino_voice.py (2026-10-24, Kino v2 engine 1 - see KINO_V2_ENGINES.md): one voice, one bubble.

The owner read 40 hours of chats as a stranger: pairs of messages within a minute (a guess, then the measured answer),
"Petite nuance / je me corrige / fausse alerte" as new bubbles, the same sermon ten times, the same closing formula, the same
text in two chats. One cause: the quick turn, the build turn, the claim auditor, the fact checker and the events all append
bubbles on their own. Here one thing owns every bubble Kino sends:

  post(c, m)  -> what to do with an "ai" message about to be appended to chat c
     ("append", m)          a new bubble
     ("edit", i, m)         the message at index i was rewritten in place (merge or correction) - nothing new appended
     ("drop", why)          not sent at all

  rules
    merge        a build/follow reply arriving within WINDOW s of a quick reply to the SAME member message becomes one
                 bubble: a hedge ("à vue de nez", "je regarde") is replaced, a real sentence is kept and the result follows
    correction   the auditor's or fact checker's correction rewrites the contradicted sentence inside the bubble it
                 corrects (marked fixed) - never "Petite nuance" as a new bubble; a bubble already fixed is left alone;
                 an old bubble (member replied since, or > 30 min) gets the correction as a plain new bubble
    duplicate    an own message that says what another chat of the same member already got in the last 30 min is dropped
    told         robots/kino_told.json: the sermon lines ("un test passé n'est pas une promesse", "3-4 semaines de
                 fantôme", "c'est ta décision"...) counted per member; said twice in 7 days = removed from the next say
                 unless the member asked about it
    closer       "Mon avis : / Honnêtement, / Franchement," opening the LAST sentence of 3 messages in a row: the opener
                 word goes, the content stays
    budget       own bubbles (events) with no member reply in between: at most 3 per hour per chat

  every decision -> robots/voice.log (the scorecard counts them: merges, fixes, duplicates, sermon cuts, budget drops)
"""
import io, json, os, re, threading, time

HERE = os.path.dirname(os.path.abspath(__file__))
TOLD = os.path.join(HERE, "kino_told.json")
LOG = os.path.join(HERE, "voice.log")
_LOCK = threading.Lock()
WINDOW = 120
DUP_WIN = 1800
FIX_WIN = 1800
BUDGET = 3
RECENT = None            # set by the server: RECENT(uid, cid) -> [(t, text)] Kino's texts in the member's OTHER chats (last 30 min)
PRESENT = None           # set by the server: PRESENT(uid) -> bool, they are in the app (engine 5: budget 5/h instead of 3)

HEDGE = re.compile(r"(à vue de nez|je (regarde|vérifie|jette un [oœ]e?il|te sors|me renseigne|vais (regarder|vérifier|voir)|m'y mets|m'en occupe)|"
                   r"deux secondes|un instant|je te (le )?dis (juste après|dans|tout de suite)|je reviens|i['’]?m (checking|looking|pulling|on it)|"
                   r"let me (check|look|pull)|one sec|back (with|in))", re.I)
SERMON = {
    "test_not_promise": re.compile(r"test (passé|réussi)[^.!?]{0,40}(pas|jamais) une promesse|(pas|jamais) une promesse", re.I),
    "ghost_weeks": re.compile(r"(3|trois)\s?(à|-|a|ou)\s?(4|quatre) semaines|(trois|3)[ -](4|quatre)?\s?semaines (de |en )?(fantôme|ghost)|"
                             r"semaines (de |en )?(fantôme|ghost)", re.I),
    "your_decision": re.compile(r"c'est (toi qui décide|ta décision)|ta décision|your (call|decision)", re.I),
    "account_safe": re.compile(r"ton compte (réel )?(n'est pas touché|reste intact|n'est jamais touché)|your (real )?account (is|stays) (untouched|intact)", re.I),
    "nothing_alone": re.compile(r"rien ne (part|se lance) (tout )?seul|nothing (starts|goes live) (on its own|by itself)", re.I),
    "not_measured": re.compile(r"(c'est|c'est une|une) intuition,? pas (du |une )?mesur|pas (du )?mesuré|not measured", re.I),
    "password": re.compile(r"avec ton mot de passe|with your (trading )?password", re.I),
}
ASKED = {
    "test_not_promise": r"promesse|promise|garanti|sûr",
    "ghost_weeks": r"fantôme|ghost|semaine|week|combien de temps|how long",
    "your_decision": r"décide|decide|je veux|je vais|on le met|put it|lance",
    "account_safe": r"compte|account|argent|money|réel|real",
    "nothing_alone": r"automatique|tout seul|alone|live|auto",
    "not_measured": r"mesur|preuve|proof|sûr|certain",
    "password": r"mot de passe|password|compte|account",
}
CLOSER = re.compile(r"^(mon avis( franc)?\s?:\s?|honnêtement[,:]\s?|franchement[,:]\s?|my (honest )?(take|view)\s?:\s?|honestly[,:]\s?)", re.I)
_SENT = re.compile(r"(?<=[.!?])\s+")


def _log(cid, what, why=""):
    try:
        io.open(LOG, "a", encoding="utf-8").write("%s %s %s | %s\n" % (time.strftime("%m-%d %H:%M:%S"), cid, what, str(why)[:160].replace("\n", " ")))
    except Exception:
        pass


def _words(t):
    return set(w for w in re.findall(r"[a-zà-ÿ0-9]{3,}", str(t or "").lower()))


def _overlap(a, b):
    A, B = _words(a), _words(b)
    return len(A & B) / max(1, min(len(A), len(B))) if A and B else 0.0


def _sentences(t):
    return [s for s in _SENT.split(str(t or "").strip()) if s.strip()]


def _told_load():
    try:
        return json.load(open(TOLD, encoding="utf-8"))
    except Exception:
        return {}


def _told_save(d):
    tmp = TOLD + ".%d.tmp" % threading.get_ident()
    io.open(tmp, "w", encoding="utf-8").write(json.dumps(d, ensure_ascii=False, indent=1))
    for _ in range(20):
        try:
            os.replace(tmp, TOLD)
            return
        except PermissionError:
            time.sleep(0.05)
    os.replace(tmp, TOLD)


def told_block(uid, lang="fr"):
    """for the prompt: the lines this member has heard enough (count >= 2 in 7 days)"""
    d = _told_load().get(str(uid)) or {}
    now = time.time()
    hot = [k for k, v in d.items() if int(v.get("n") or 0) >= 2 and now - float(v.get("last") or 0) < 7 * 86400]
    if not hot:
        return ""
    names = {"test_not_promise": "a passed test is not a promise", "ghost_weeks": "the 3-4 weeks of ghost", "your_decision": "it is their decision",
             "account_safe": "their real account is untouched", "nothing_alone": "nothing goes live on its own", "not_measured": "it is an intuition, not measured",
             "password": "with their password"}
    return "ALREADY SAID ENOUGH (they heard each of these at least twice this week - do not say them again unless they ask): %s." % "; ".join(names.get(k, k) for k in hot)


def _cut_told(uid, text, last_user, cid):
    """count the sermon lines in the text; remove a sentence whose line was already told twice this week, unless asked"""
    if not text or not uid:
        return text
    d = _told_load()
    u = d.setdefault(str(uid), {})
    now = time.time()
    S = _sentences(text)
    out, cut = [], []
    for s in S:
        keep = True
        for key, rx in SERMON.items():
            if not rx.search(s):
                continue
            v = u.setdefault(key, {"n": 0, "last": 0})
            fresh = now - float(v.get("last") or 0) < 7 * 86400
            n = int(v.get("n") or 0) if fresh else 0
            asked = bool(re.search(ASKED.get(key, r"$^"), str(last_user or ""), re.I))
            if n >= 2 and not asked and len(S) > 1:
                keep = False
                cut.append(key)
            else:
                v["n"], v["last"] = n + 1, now
            break
        if keep:
            out.append(s)
    if cut:
        _log(cid, "TOLD_CUT", ",".join(cut))
        try:
            _told_save(d)
        except Exception:
            pass
        return " ".join(out).strip() or text
    try:
        _told_save(d)
    except Exception:
        pass
    return text


def _cut_closer(text, prev_ai_texts, cid):
    """the same opener word closing three messages in a row: keep the sentence, drop the formula"""
    S = _sentences(text)
    if not S or not CLOSER.match(S[-1]):
        return text
    n = 0
    for pt in prev_ai_texts[-3:]:
        ps = _sentences(pt)
        if ps and CLOSER.match(ps[-1]):
            n += 1
    if n >= 2:
        S[-1] = CLOSER.sub("", S[-1], count=1)
        S[-1] = S[-1][:1].upper() + S[-1][1:]
        _log(cid, "CLOSER_CUT")
        return " ".join(S)
    return text


def post(c, m):
    """the decision for an 'ai' message m about to join chat c (see module doc)"""
    msgs = c.get("msgs") or []
    cid, uid = c.get("id"), c.get("uid")
    now = float(m.get("t") or time.time())
    text = str(m.get("text") or "")
    lu_i = next((i for i in range(len(msgs) - 1, -1, -1) if msgs[i].get("role") == "user"), None)
    lu = msgs[lu_i] if lu_i is not None else None
    ai_after = [(i, x) for i, x in enumerate(msgs) if x.get("role") == "ai" and (lu_i is None or i > lu_i)]
    # -- correction / fact fix: rewrite the bubble it contradicts -----------------------------------------------
    if m.get("correction") or m.get("fix"):
        tgt = None
        for i in range(len(msgs) - 1, -1, -1):
            x = msgs[i]
            if x.get("role") == "user":
                break                                # they replied since: the old bubble was read, say it plainly
            if x.get("role") == "ai" and not x.get("correction") and not x.get("fix") and x.get("text") and now - float(x.get("t") or 0) < FIX_WIN:
                tgt = i
                break
        if tgt is not None:
            x = msgs[tgt]
            if x.get("fixed"):
                _log(cid, "FIX_SKIPPED", "bubble already fixed once")
                return ("drop", "already fixed")
            S = _sentences(x["text"])
            claims = [str(k) for k in (m.get("claims") or []) if k]
            best, bi = 0.0, len(S) - 1
            for j, s in enumerate(S):
                sc = max([_overlap(s, k) for k in claims] + [0.0]) if claims else _overlap(s, text)
                if any(k and k[:40].lower() in s.lower() for k in claims):
                    sc = 2.0
                if sc > best:
                    best, bi = sc, j
            _ct = re.sub(r"^(petite (correction|nuance|précision)|correction|précision|je me (corrige|reprends)|small (correction|fix)|quick fix)\s*[:,\-–]\s*",
                         "", text.strip(), flags=re.I)
            S[bi] = (_ct[:1].upper() + _ct[1:]) if _ct else text.strip()
            x["text"] = " ".join(S)
            x["fixed"] = 1
            x["fixed_t"] = int(now)
            _log(cid, "FIX_IN_PLACE", "%d/%d sentence replaced, score %.2f" % (bi + 1, len(S), best))
            return ("edit", tgt, x)
        _log(cid, "FIX_APPENDED", "no fresh bubble to edit")
        return ("append", m)
    # -- own-message budget ----------------------------------------------------------------------------------------
    if m.get("event") and not m.get("err"):
        own = 0
        for x in reversed(msgs):
            if x.get("role") == "user":
                break
            if x.get("role") == "ai" and x.get("event") and now - float(x.get("t") or 0) < 3600:
                own += 1
        _bud = BUDGET
        try:
            if PRESENT is not None and PRESENT(uid):
                _bud = 5
        except Exception:
            pass
        if own >= _bud:
            _log(cid, "DROP_BUDGET", "%d own bubbles in the hour, no reply" % own)
            return ("drop", "budget")
        try:                                   # engine 5 (kino_spark): the same subject twice today is enough
            import kino_spark as _KSv
            if _KSv.repeat_block(uid, text, cid):
                return ("drop", "topic repeat")
        except Exception:
            pass
    # -- cross-chat duplicate ---------------------------------------------------------------------------------------
    if RECENT is not None and len(text) >= 60:
        try:
            for t_, tx in RECENT(uid, cid) or []:
                if now - float(t_ or 0) < DUP_WIN and _overlap(text, tx) >= 0.8:
                    _log(cid, "DROP_DUP", tx[:80])
                    return ("drop", "said in another chat")
        except Exception:
            pass
    # -- told + closer ------------------------------------------------------------------------------------------------
    prev_ai = [str(x.get("text") or "") for x in msgs if x.get("role") == "ai" and x.get("text")][-3:]
    if text and not m.get("err"):
        text = _cut_told(uid, text, (lu or {}).get("text"), cid)
        text = _cut_closer(text, prev_ai, cid)
        m["text"] = text
    # -- merge: build/follow reply onto the quick reply of the same member message ----------------------------------
    if m.get("follow") and lu is not None and ai_after:
        qi, q = ai_after[-1]
        if q.get("quick") and not q.get("event") and now - float(q.get("t") or 0) < WINDOW and not q.get("fixed"):
            qt = str(q.get("text") or "")
            if not text.strip():
                return ("append", m)
            if HEDGE.search(qt) and len(qt) <= 260 or _overlap(qt, text) >= 0.6:
                q["text"] = text
                how = "hedge replaced" if HEDGE.search(qt) else "repeat replaced"
            else:
                q["text"] = qt.rstrip() + "\n\n" + text.strip()
                how = "result appended"
            for k in ("made", "chips", "link", "ready", "tools", "probs", "rev", "own"):
                if m.get(k):
                    q[k] = m[k]
            q["merged"] = 1
            q["t"] = int(now)
            _log(cid, "MERGE", how)
            return ("edit", qi, q)
    if m.get("event") and text:
        try:
            import kino_spark as _KSn
            _KSn.note_topic(uid, text, "own", cid)
        except Exception:
            pass
    return ("append", m)


def counts(day_label):
    """for the scorecard: the day's decisions"""
    out = {"merge": 0, "fix": 0, "dup": 0, "told": 0, "closer": 0, "budget": 0}
    try:
        for l in io.open(LOG, encoding="utf-8").read().splitlines():
            if not l.startswith(day_label):
                continue
            for k, tag in (("merge", " MERGE "), ("fix", " FIX_IN_PLACE "), ("dup", " DROP_DUP "), ("told", " TOLD_CUT "), ("closer", " CLOSER_CUT "), ("budget", " DROP_BUDGET ")):
                if tag in l:
                    out[k] += 1
    except Exception:
        pass
    return out


def bubbles_per_turn(msgs, since=None):
    """how many Kino bubbles answer one member message on average (target 1.0)"""
    n = turns = 0
    cur = None
    for x in msgs or []:
        if since and float(x.get("t") or 0) < since:
            continue
        if x.get("role") == "user":
            if cur is not None:
                turns += 1; n += cur
            cur = 0
        elif x.get("role") == "ai" and cur is not None and not x.get("event"):
            cur += 1
    if cur is not None:
        turns += 1; n += cur
    return round(n / turns, 2) if turns else None
