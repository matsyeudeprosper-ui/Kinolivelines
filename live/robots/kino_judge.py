"""kino_judge.py (2026-10-24, Kino v2 - THE judge; owner: "feels like patches, if-then. I want something that senses and
decides like a human would. Do the proper job with the judge, all at once, test it").

One model pass in front of EVERYTHING Kino says - replies, his own messages, build follow-ups, corrections, delegated
call answers, initiatives. It replaces the rule gates (hedge regex, merge window, sermon cuts, closer cut, cross-chat
duplicate rule, topic repeat counter, pacing gaps, cut-off quota, answer-the-ask injection, action-claim regexes). The
facts it judges against stay DATA built by code: the real state of their robots, the jobs really running, the result
cards, what they told him about themselves, what he already said today, the moments check. The judge reads the room
and decides as the most thoughtful friend would: send as is, rewrite, fold into his previous bubble, drop, or wait.

  room(c, m, P)      -> the text the judge reads (P = provider dict from the server: state, jobs, fresh, told, topics,
                        constraints, feedback, recent_other, presence, local_hour, check_state, material)
  judge(room, lang)  -> {"verdict": send|rewrite|merge|drop|wait, "text": ..., "wait_min": n, "actions": [...], "why": ...}
  apply(c, m, dec)   -> ("append", m) | ("edit", i, m) | ("drop", why)   (the mechanics only; the decision is the judge's)

  Floors that are policy, not judgment: no push at night when they are away (their quiet hours), at most 8 of his own
  bubbles an hour, and when the judge cannot answer (timeout, model down) the message goes out as drafted - never lost.
  Log: robots/judge.log (verdict, why, latency). ON = False falls back to the old gates.
"""
import io, json, os, re, threading, time

HERE = os.path.dirname(os.path.abspath(__file__))
LOG = os.path.join(HERE, "judge.log")
ON = True
MODELS = ("sonnet", "haiku")
TIMEOUT = 45
CALL_TIMEOUT = 10
HARD_CAP_OWN = 8
_SENT = re.compile(r"(?<=[.!?])\s+")

SYSTEM = """You are the judgment of Kino - the AI friend inside a trading app who builds and tests robots with a member. Kino has
just DRAFTED something to send. You decide, the way the most thoughtful, warm, honest friend would, whether it goes out and how.
You are not a filter with rules: you read THE ROOM (the conversation, what they asked, how they sound, what he already said today,
the real state of their robots, the jobs really running, what they told him about themselves) and you choose.

What a good friend does:
- answers what was asked first, with the figure when they asked a figure and the facts hold it; never dodges ("je ne peux pas les isoler")
- does not repeat a point already made today, nor a sermon they heard twice this week, nor praise already given
- does not say "I'm launching / I re-ran / I measured" unless a job really exists or can be started now (JOBS block, MOMENTS CHECK);
  a word for an action is a job - rewrite to the truth when it is not
- never contradicts the REAL STATE block (where a robot runs, its test, its luck test) nor the figures he already gave
- respects what they told him about themselves (no money -> no outings to buy; on a phone -> no side panel; afraid of losses)
- feels the moment: after bad news, no pivot to a joke; a short "ok" from someone in the app is a nod, not a wall; a long
  silence at night is not an invitation; one question about their feelings per hour is plenty; no interview
- one voice: a result arriving seconds after a hedge becomes ONE bubble (merge); a correction rewrites the wrong sentence of the
  bubble it corrects, never "petite nuance" underneath
- keeps the member's language (the language of THEIR last message when clear) and the draft's own voice - casual, specific,
  numbers exactly as the facts give them, no exception names, no "as an AI"
- a thought already refined (A THOUGHT CAME... "already the message") keeps its subject and every fact
- and sometimes the right thing is to say nothing now (drop), or later (wait N minutes), or to say something else that the
  MATERIAL offers - only if it is genuinely worth their attention

Answer ONE JSON object only:
{"verdict": "send" | "rewrite" | "merge" | "drop" | "wait",
 "text": "" for send (the draft goes as it is), else the message to send (for rewrite: the better message; for merge: the WHOLE merged bubble, his
         previous bubble and this one as one natural message; for a CORRECTION: the WHOLE corrected bubble; for drop/wait: ""),
 "wait_min": minutes for wait (else 0),
 "actions": [] or the actions the message commits to that can and should start now: "test" (the robot's 42-day test - never when
            the state shows it done today) | "luck" (its luck test, 100 random robots, only after a positive test) | "build" | "ghost",
 "why": one short line, for the log}
"""


def _log(cid, what, why="", ms=0):
    try:
        io.open(LOG, "a", encoding="utf-8").write("%s %s %s %dms | %s\n" % (time.strftime("%m-%d %H:%M:%S"), cid, what, ms, str(why)[:200].replace("\n", " ")))
    except Exception:
        pass


def _ago(t, now):
    s = max(0, now - float(t or now))
    return ("%ds" % s) if s < 60 else ("%dmin" % (s // 60)) if s < 3600 else ("%.1fh" % (s / 3600))


def room(c, m, P, brief=False):
    """the text the judge reads; P = providers (strings or callables returning strings, all optional); brief = a call turn
    (fewer lines: the answer is spoken, every second counts)"""
    now = float(m.get("t") or time.time())
    msgs = c.get("msgs") or []
    NM, NC = (8, 260) if brief else (12, 360)
    origin = ("correction" if (m.get("correction") or m.get("fix")) else "call" if m.get("call_turn") else "follow" if m.get("follow")
              else "own" if m.get("event") else "reply")
    L = ["ORIGIN: %s%s" % (origin, (" (event: %s)" % str(m.get("ekind") or "")[:90]) if m.get("ekind") else "")]
    lu = next((x for x in reversed(msgs) if x.get("role") == "user"), None)
    pres = P.get("presence") or ""
    L.append("THE MEMBER: %s; local hour %s; their last message %s ago%s" % (
        pres or "presence unknown", P.get("local_hour", "?"), _ago(lu.get("t"), now) if lu else "never",
        ("; what they asked: %s" % json.dumps(lu.get("ear"), ensure_ascii=False)) if lu and lu.get("ear") else ""))
    for k in ("constraints", "feedback", "told", "topics"):
        v = P.get(k)
        v = v() if callable(v) else v
        if v:
            L.append(str(v)[:900])
    L.append("THE CONVERSATION (latest last):")
    for x in msgs[-NM:]:
        r = x.get("role")
        if r in ("user", "ai"):
            L.append("  [%s ago] %s: %s" % (_ago(x.get("t"), now), "MEMBER" if r == "user" else ("KINO (own)" if x.get("event") else "KINO"), str(x.get("text") or "")[:NC].replace("\n", " / ")))
        elif r in ("result", "test", "sys", "card", "demo"):
            L.append("  [%s ago] (%s%s)" % (_ago(x.get("t"), now), r, (": " + str(x.get("text") or "")[:120]) if x.get("text") else (" net %s" % (x.get("result") or {}).get("net")) if r == "result" else ""))
    ro = P.get("recent_other")
    ro = ro() if callable(ro) else ro
    if ro and not brief:
        L.append("WHAT KINO SAID TODAY IN THEIR OTHER CONVERSATIONS: " + " | ".join(str(t)[:140].replace("\n", " ") for t in ro[-8:]))
    for k in ("state", "jobs", "fresh"):
        v = P.get(k)
        v = v() if callable(v) else v
        if v:
            L.append(str(v)[:1400 if brief else 2000])
    if P.get("check_state"):
        L.append("MOMENTS CHECK (needed before a test can start): %s" % P["check_state"])
    if origin == "correction":
        tgt = P.get("target")
        L.append("THE BUBBLE TO CORRECT (sent %s ago): %s" % (_ago((tgt or {}).get("t"), now), str((tgt or {}).get("text") or "")[:900]))
        if m.get("claims"):
            L.append("UNSUPPORTED CLAIMS FOUND BY THE AUDITOR: " + " | ".join(str(k)[:160] for k in m["claims"]))
        L.append("THE AUDITOR'S CORRECTION: " + str(m.get("text") or "")[:600])
        L.append("-> Return the WHOLE corrected bubble as 'text' (verdict rewrite): the wrong sentence replaced, the rest intact, no 'petite correction'.")
    else:
        prev = next((x for x in reversed(msgs) if x.get("role") == "ai" and x.get("text")), None)
        if prev and now - float(prev.get("t") or 0) < 600 and not any(x.get("role") == "user" and float(x.get("t") or 0) > float(prev.get("t") or 0) for x in msgs):
            L.append("HIS PREVIOUS BUBBLE (%s ago, nothing from the member since): %s" % (_ago(prev.get("t"), now), str(prev.get("text") or "")[:600]))
            L.append("-> if this draft completes or corrects it, merge: return the whole merged bubble.")
        if P.get("material"):
            L.append("MATERIAL HE COULD USE INSTEAD (true, built by code): " + str(P["material"])[:900])
        L.append("THE DRAFT: " + str(m.get("text") or "")[:1500])
    return "\n".join(L)


def judge(room_text, lang="fr", W=None, cid="", timeout=None):
    """-> decision dict; None when the judge could not answer (the caller sends the draft as drafted)"""
    t0 = time.time()
    try:
        W = W or __import__("robot_warm")
        u = room_text + "\n\nLanguage of the member: %s. Decide now. JSON only." % ("English" if lang == "en" else "French")
        v = W.ask_json(SYSTEM, u, models=MODELS, timeout=timeout or TIMEOUT, warm=True)
        if not isinstance(v, dict) or v.get("verdict") not in ("send", "rewrite", "merge", "drop", "wait"):
            _log(cid, "NOANSWER", str(v)[:120], int((time.time() - t0) * 1000))
            return None
        dec = {"verdict": v["verdict"], "text": str(v.get("text") or "").strip(), "wait_min": int(v.get("wait_min") or 0),
               "actions": [a for a in (v.get("actions") or []) if a in ("test", "luck", "build", "ghost")], "why": str(v.get("why") or "")[:200]}
        _log(cid, dec["verdict"].upper(), dec["why"], int((time.time() - t0) * 1000))
        return dec
    except Exception as e:
        _log(cid, "ERROR", "%s: %s" % (type(e).__name__, str(e)[:120]), int((time.time() - t0) * 1000))
        return None


def apply(c, m, dec):
    """the mechanics of the decision. -> ("append", m) | ("edit", i, m) | ("drop", why)"""
    msgs = c.get("msgs") or []
    now = float(m.get("t") or time.time())
    v = dec["verdict"]
    if m.get("correction") or m.get("fix"):
        tgt = None
        for i in range(len(msgs) - 1, -1, -1):
            x = msgs[i]
            if x.get("role") == "user":
                break
            if x.get("role") == "ai" and x.get("text") and not x.get("correction") and not x.get("fix") and now - float(x.get("t") or 0) < 1800:
                tgt = i
                break
        if v in ("drop", "wait") or not dec["text"]:
            return ("drop", "judge: " + dec["why"])
        if tgt is not None:
            x = msgs[tgt]
            x["text"] = dec["text"]
            x["fixed"] = 1
            x["fixed_t"] = int(now)
            return ("edit", tgt, x)
        m["text"] = dec["text"]
        return ("append", m)
    if v in ("drop", "wait"):
        if v == "wait" and dec["wait_min"] > 0:
            c["judge_wait"] = int(now + 60 * dec["wait_min"])
        return ("drop", "judge: " + dec["why"])
    if v == "merge" and dec["text"]:
        for i in range(len(msgs) - 1, -1, -1):
            x = msgs[i]
            if x.get("role") == "user":
                break
            if x.get("role") == "ai" and x.get("text") and now - float(x.get("t") or 0) < 600:
                x["text"] = dec["text"]
                x["merged"] = 1
                x["t"] = int(now)
                for k in ("made", "chips", "link", "ready", "tools", "probs", "rev", "own"):
                    if m.get(k):
                        x[k] = m[k]
                return ("edit", i, x)
        m["text"] = dec["text"]
        return ("append", m)
    if v == "rewrite" and dec["text"] and dec["text"] != str(m.get("text") or "").strip():
        m["text"] = dec["text"]
        m["judged"] = 1
    return ("append", m)


def own_cap_hit(msgs, now=None):
    """policy floor: at most HARD_CAP_OWN of his own bubbles in the last hour of a chat"""
    now = now or time.time()
    return sum(1 for x in msgs or [] if x.get("role") == "ai" and x.get("event") and now - float(x.get("t") or 0) < 3600) >= HARD_CAP_OWN


def counts(day_label):
    out = {"send": 0, "rewrite": 0, "merge": 0, "drop": 0, "wait": 0, "noanswer": 0, "error": 0, "ms": []}
    try:
        for l in io.open(LOG, encoding="utf-8").read().splitlines():
            if not l.startswith(day_label):
                continue
            parts = l.split(" ")
            if len(parts) > 4:
                k = parts[3].lower()
                if k in out:
                    out[k] += 1
                try:
                    out["ms"].append(int(parts[4].rstrip("ms")))
                except Exception:
                    pass
    except Exception:
        pass
    ms = sorted(out.pop("ms"))
    out["latency_med_ms"] = ms[len(ms) // 2] if ms else None
    return out
