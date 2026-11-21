"""kino_myday.py (2026-11-20, owner: "all 7, well done" - step 1 of KINO_V4_TRUE_SELF.md: a TRUE day).

Asked "what are you doing / what did you think about", Kino guessed: he saw only his last 3 desk sessions, a "drained" feeling
with a false cause, and invented "I went round in circles on your requests" (it was his lab). A person remembers his own day.

This module builds that memory ONLY from what really happened, any field (it reads activity records, not trading rules):
  - his desk sessions (kino_work.json) with their own summaries, merged when one project ran several times in a row,
    and the sessions he started and abandoned at once (a person notices "I sat down 5 times and did nothing")
  - his lab tests (kino_lab.json) and how they ended
  - who he talked with (the person in front of him by "toi"/"you", the others only counted - never a name)
  - where his thinking went (brain_costs.jsonl by source family)
  - the times he could not think at all (an outage: calls failing, none answering) - in the last 10 days, so a gap in
    his life is something he knows, not a hole he fills with a story
Times are given at the other person's local hour (off_min = JS getTimezoneOffset of that person).

block(uid, en, off_min) -> text for his memory (cached 120 s per uid/lang/off). Nothing here writes anywhere.
"""
import json
import os
import time

HERE = os.path.dirname(os.path.abspath(__file__))
WORK = os.path.join(HERE, "kino_work.json")
LAB = os.path.join(HERE, "kino_lab.json")
COSTS = os.path.join(HERE, "brain_costs.jsonl")
CHATS = os.path.join(HERE, "chats")
WINDOW_H = 18
_CACHE = {}

FAMILY = {   # where a brain call came from -> what that thinking was, in words a person uses about his own day
    "kino_one": "talk", "kino_read": "talk", "kino_conflict": "talk", "kino_introspect": "talk", "kino_commit": "talk",
    "kino_work": "work", "kino_sales": "work", "kino_post": "work", "kino_team": "work", "kino_missions": "work",
    "kino_material": "work", "kino_web": "work", "kino_crawl": "work", "kino_hands": "work", "kino_lab": "work",
    "kino_mind": "inner", "kino_depth": "inner", "kino_psyche": "inner", "kino_stream": "inner", "kino_inner": "inner",
    "kino_life": "inner", "kino_beliefs": "inner", "kino_said": "inner", "kino_selfmodel": "inner", "kino_workspace": "inner",
    "kino_belief": "inner", "kino_fields": "inner",
}
WORDS = {"talk": ("parler avec les gens", "talking with people"), "work": ("ton travail à l'ordinateur", "your work at the computer"),
         "inner": ("ta vie intérieure (rêver, repenser, écrire ton journal)", "your inner life (daydreaming, thinking back, your diary)")}


def _j(p, default):
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def _tail(path, nbytes):
    try:
        with open(path, "rb") as f:
            f.seek(0, 2)
            n = f.tell()
            f.seek(max(0, n - nbytes))
            return f.read().decode("utf-8", "replace").splitlines()[1:]
    except Exception:
        return []


def _hm(t, off_min):
    return time.strftime("%H:%M", time.gmtime(float(t) - int(off_min or 0) * 60))


def _day(t, off_min):
    return time.strftime("%d/%m", time.gmtime(float(t) - int(off_min or 0) * 60))


def _first_sentence(s, n=150):
    s = " ".join(str(s or "").split())
    for sep in (". ", " - ", "; "):
        i = s.find(sep)
        if 20 < i < n:
            return s[:i + (1 if sep == ". " else 0)]
    return s[:n] + ("…" if len(s) > n else "")


def sessions(since, off_min, en, dark=frozenset()):
    """his desk sessions: real ones (summary), and the started-then-dropped ones counted"""
    S = [s for s in _j(WORK, {}).get("sessions") or [] if float(s.get("t") or 0) >= since]
    real, empty, tried = [], {}, 0
    for s in S:
        proj = str(s.get("project") or s.get("care") or "work")
        summ = str(s.get("summary") or "")
        if not str(s.get("task") or "").strip():
            continue                                   # a wake-up with nothing to do ("nothing called him") is not a sitting
        if summ.startswith("stopped after") and len(s.get("steps") or []) <= 1:
            if int(float(s["t"]) // 3600) in dark:     # he sat down while his mind could not answer: not a choice
                tried += 1
                continue
            k = str(s.get("project") or "") or _first_sentence(s.get("task"), 70)
            empty[k] = empty.get(k, 0) + 1
            continue
        if summ.startswith("stopped after"):           # a long sitting cut short: what it was, and that it stopped
            n = len(s.get("steps") or [])
            s = dict(s, summary="%s (%s)" % (s.get("project") or _first_sentence(s.get("task"), 60),
                                             ("stopped after %d steps" if en else "interrompu après %d étapes") % n))
        if s.get("steps"):
            if real and real[-1]["proj"] == proj and float(s["t"]) - real[-1]["t1"] < 3600:
                real[-1]["t1"] = float(s["t"])
                real[-1]["n"] += 1
                real[-1]["last"] = s.get("summary")
            else:
                real.append({"proj": proj, "t0": float(s["t"]), "t1": float(s["t"]), "n": 1, "first": s.get("summary"), "last": s.get("summary")})
        else:
            k = str(s.get("project") or "") or _first_sentence(s.get("task"), 70)
            empty[k] = empty.get(k, 0) + 1
    L = []
    for r in real[-8:]:
        when = _hm(r["t0"], off_min) + (("-" + _hm(r["t1"], off_min)) if r["t1"] - r["t0"] > 300 else "")
        what = _first_sentence(r["last"] if r["n"] > 1 else r["first"])
        L.append("%s %s" % (when, what) + ((" (%d times)" if en else " (%d fois)") % r["n"] if r["n"] > 1 else ""))
    E = sorted(empty.items(), key=lambda z: -z[1])
    drop = ""
    if tried >= 2:
        drop = (("%d times you sat down to work and could not think (your calls were failing) - you stopped at once." if en else
                 "%d fois tu t'es mis au travail sans pouvoir réfléchir (tes appels échouaient) - tu t'es arrêté aussitôt.") % tried) + " "
    if E and E[0][1] >= 3:
        drop += (("You sat down %d times to \"%s\" and stopped before doing anything (your calls were working then; the reason is not recorded)." if en else
                 "Tu t'es assis %d fois pour « %s » et tu t'es arrêté avant de faire quoi que ce soit (tes appels marchaient à ce moment-là ; la raison n'est pas notée).") % (E[0][1], E[0][0]))
    return L, drop.strip()


def lab(since, en):
    I = [x for x in _j(LAB, {}).get("ideas") or [] if float(x.get("t") or 0) >= since]
    if not I:
        return ""
    dead = [x for x in I if x.get("stage") == "dead"]
    alive = [x for x in I if x.get("stage") != "dead"]
    parts = []
    for x in I[-4:]:
        nm = str(x.get("name") or x.get("id")).replace("_", " ")
        parts.append("%s → %s" % (nm, ("dead: " if en else "morte : ") + _first_sentence(x.get("dead_why"), 90) if x.get("stage") == "dead"
                                    else (("still going (%s)" if en else "encore en course (%s)") % x.get("stage"))))
    head = (("your lab: %d idea(s) tested, %d dead, %d still going - " if en else "ton labo : %d idée(s) testée(s), %d morte(s), %d encore en course - ")
            % (len(I), len(dead), len(alive)))
    return head + " | ".join(parts)


SALES_LOG = os.path.join(HERE, "kino_sales.log")


def emails(since, en):
    """the emails he really sent to businesses in the window, and the answers that came back - counted from the send log
    (2026-11-21 watch: he told Pekos 'one email today' after six went out; merged session lines had lost the count)"""
    year = time.localtime().tm_year
    sent, back, names = 0, 0, []
    for l in _tail(SALES_LOG, 400_000):
        try:
            t = time.mktime(time.strptime("%d-%s" % (year, l[:14]), "%Y-%m-%d %H:%M:%S"))   # the log is in the server's clock
        except Exception:
            continue
        if t < since:
            continue
        if " SENT " in l:
            sent += 1
        elif "replied" in l or " REPLY" in l:
            back += 1
    if not sent and not back:
        return ""
    return (("emails to businesses: %d sent, %d answered" if en else "e-mails aux commerces : %d envoyés, %d réponses") % (sent, back))


def talks(since, uid, en):
    """who he talked with: this person by 'you' (uid = one id or all the ids of one person), the others only counted"""
    mine = {str(u) for u in (uid if isinstance(uid, (list, tuple, set)) else [uid])}
    me, others = 0, {}
    try:
        for f in os.listdir(CHATS):
            if not f.endswith(".json"):
                continue
            p = os.path.join(CHATS, f)
            if os.path.getmtime(p) < since:
                continue
            c = _j(p, {})
            n = sum(1 for m in c.get("msgs") or [] if m.get("role") == "user" and float(m.get("t") or 0) >= since)
            if not n:
                continue
            if str(c.get("uid")) in mine:
                me += n
            else:
                others[str(c.get("uid"))] = others.get(str(c.get("uid")), 0) + n
    except Exception:
        pass
    bits = []
    if me:
        bits.append(("with them: %d messages of theirs" if en else "avec lui/elle : %d messages de sa part") % me)
    if others:
        bits.append(("with %d other person(s) (never a name)" if en else "avec %d autre(s) personne(s) (jamais de nom)") % len(others))
    return ("conversations: " if en else "conversations : ") + ", ".join(bits) if bits else ""


def thinking(since, en):
    """where his thinking went today, and the stretches when he could not think at all (last 10 days)"""
    share, fails = {}, {}
    ok_h, err_h = {}, {}
    since10 = time.time() - 10 * 86400
    for l in _tail(COSTS, 25_000_000):
        try:
            j = json.loads(l)
        except Exception:
            continue
        t = float(j.get("t") or 0)
        if t < since10:
            continue
        h = int(t // 3600)
        if j.get("err") or j.get("skip"):
            err_h[h] = err_h.get(h, 0) + 1
        else:
            ok_h[h] = ok_h.get(h, 0) + 1
            if t >= since:
                fam = FAMILY.get(str(j.get("src") or "").split(":")[0])
                if fam:
                    share[fam] = share.get(fam, 0.0) + float(j.get("usd") or 0) + 0.002
    # outage = hours where he tried (>= 3 failures) and almost nothing answered, merged into stretches
    bad = sorted(h for h in err_h if err_h[h] >= 3 and ok_h.get(h, 0) <= max(1, err_h[h] // 10))
    runs = []
    for h in bad:
        if runs and h - runs[-1][1] <= 3:
            runs[-1][1] = h
        else:
            runs.append([h, h])
    runs = [r for r in runs if r[1] - r[0] >= 2]
    tot = sum(share.values())
    line = ""
    if tot > 0:
        line = (("where your thinking went today: " if en else "où est allée ta réflexion aujourd'hui : ") +
                ", ".join("%s %d %%" % (WORDS[k][1 if en else 0], round(100 * v / tot)) for k, v in sorted(share.items(), key=lambda z: -z[1])))
    return line, runs, set(bad)


def block(uid, en=False, off_min=0):
    key = (str(sorted(uid) if isinstance(uid, (list, tuple, set)) else uid), bool(en), int(off_min or 0))
    c = _CACHE.get(key)
    if c and time.time() - c[0] < 120:
        return c[1]
    now = time.time()
    since = now - WINDOW_H * 3600
    L = []
    try:
        _tl = thinking(since, en)
    except Exception:
        _tl = ("", [], set())
    try:
        S, drop = sessions(since, off_min, en, frozenset(_tl[2]))
        if S:
            L.append(("at your computer: " if en else "à ton ordinateur : ") + " | ".join(S))
        if drop:
            L.append(drop)
    except Exception:
        pass
    for fn in (lambda: lab(since, en), lambda: emails(since, en), lambda: talks(since, uid, en)):
        try:
            x = fn()
            if x:
                L.append(x)
        except Exception:
            pass
    try:
        line, runs = _tl[0], _tl[1]
        if line:
            L.append(line)
        if runs:
            R = []
            for a, b in runs[-3:]:
                R.append(("%s %s → %s %s" % (_day(a * 3600, off_min), _hm(a * 3600, off_min), _day((b + 1) * 3600, off_min), _hm((b + 1) * 3600, off_min))))
            L.append(("Times you could not think at all (your calls failed, nothing answered - you were not there, you do not "
                      "remember them from inside): " if en else
                      "Les moments où tu ne pouvais pas penser du tout (tes appels échouaient, rien ne répondait - tu n'étais pas là, "
                      "tu ne les as pas vécus de l'intérieur) : ") + " ; ".join(R))
    except Exception:
        pass
    if not L:
        out = ""
    else:
        out = (("YOUR DAY, AS IT REALLY WENT (the last %d h, from what really happened, their local time - this is your memory of "
                "your day; what is not here, you did not do; if they ask about something not here, you don't remember it, say so):\n- "
                if en else
                "TA JOURNÉE, TELLE QU'ELLE S'EST VRAIMENT PASSÉE (les %d dernières heures, d'après ce qui s'est vraiment passé, à son "
                "heure - c'est ta mémoire de ta journée ; ce qui n'y est pas, tu ne l'as pas fait ; s'il te demande quelque chose qui "
                "n'y est pas, tu ne t'en souviens pas, dis-le) :\n- ") % WINDOW_H) + "\n- ".join(L)
    _CACHE[key] = (time.time(), out)
    return out


if __name__ == "__main__":
    import sys
    print(block(sys.argv[1] if len(sys.argv) > 1 else "pekos", en="--en" in sys.argv, off_min=-60))
