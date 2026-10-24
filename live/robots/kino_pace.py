"""Kino's pacing (owner 2026-10-23 night: two messages of his own in sixteen minutes to a quiet member, answered "Ok. And?").
The tact of WHEN to speak on his own, read from the conversation itself, no model:

  - member first: they wrote in the last 4 min, or their last message is a question still unanswered -> no initiative
  - a gap between his own messages: 10 min by day, 20 min in their night (22h-07h local)
  - backoff: each own message that got no real answer (4+ words or a question within 15 min) doubles the gap; three in a
    row unanswered -> he waits for them to write
  - flat: two of their last three replies are one or two words and none is a question -> gap doubled
  - trade news (LIVE TRADE) only obeys "member first" and a 5-min gap; results, promises, follow-ons, research, commitments
    and the morning brief are never gated here

  gate(event, msgs, local_hour) -> (ok, why);  every decision is logged to robots/pace.log (measured in the scorecard)
"""
import io, os, re, time

HERE = os.path.dirname(os.path.abspath(__file__))
LOG = os.path.join(HERE, "pace.log")
DISCRETIONARY = ("YOUR INITIATIV", "A THOUGHT CAME", "INNER VOICE", "PROACTIVE CHECK", "GOAL STEP", "RESEARCH DIARY", "YOUR STORY")
NEWS = ("LIVE TRADE", "GUARDIAN", "LUCK TEST FINISHED", "LAB NEWS", "END OF DAY", "GHOST TRADE")
# 2026-10-24 06:00: seven messages of his own in six hours against three of the member's - trade comments, luck news and the
# guardian were "news" and never counted as unanswered. News still comes when it happens, but not to a wall: after three own
# messages with no real answer, news waits for the member too (a test THEY launched is posted as a result card regardless).
GAP_DAY, GAP_NIGHT, NEWS_GAP = 600, 1200, 300


def _words(t):
    return len(re.findall(r"\w+", str(t or "")))


def _real_answer(m):
    return m.get("role") == "user" and (_words(m.get("text")) >= 4 or str(m.get("text") or "").strip().endswith("?"))


def gate(event, msgs, local_hour=None, now=None, present=False):
    """present (2026-10-24, owner: "the voids are still much"): in the app or answered < 10 min -> gap 5 min, no flat doubling"""
    ev = str(event or "").upper()
    kind = "own" if ev.startswith(DISCRETIONARY) else "news" if ev.startswith(NEWS) else None
    if kind is None:
        return True, "not gated"
    now = now or time.time()
    M = [m for m in (msgs or []) if m.get("role") in ("user", "ai") and m.get("t")]
    users = [m for m in M if m["role"] == "user"]
    lu = users[-1] if users else None
    # member first
    if lu and now - float(lu["t"]) < 240:
        return False, "member wrote %d s ago" % (now - float(lu["t"]))
    if lu and str(lu.get("text") or "").strip().endswith("?") and not any(m["role"] == "ai" and not m.get("event") and m["t"] > lu["t"] for m in M):
        return False, "their question is still unanswered"
    own = [m for m in M if m["role"] == "ai" and m.get("event")]
    last_own = own[-1] if own else None
    if kind == "news":
        if last_own and now - float(last_own["t"]) < NEWS_GAP:
            return False, "news: last own message %d s ago" % (now - float(last_own["t"]))
        un = 0
        for m in reversed(M):
            if _real_answer(m):
                break
            if m["role"] == "ai" and m.get("event"):
                un += 1
        if un >= 3:
            return False, "news held: %d of your own already unanswered - wait for them" % un
        return True, "news ok"
    night = local_hour is not None and (local_hour >= 22 or local_hour < 7)
    gap = 300 if present else (GAP_NIGHT if night else GAP_DAY)
    # backoff: own messages since the last real answer from them
    unanswered = 0
    for m in reversed(M):
        if _real_answer(m):
            break
        if m["role"] == "ai" and m.get("event"):
            unanswered += 1
    if unanswered >= (4 if present else 3):
        return False, "%d of your own unanswered - wait for them" % unanswered
    gap *= 2 ** unanswered
    # flat member (not while they are here: "Ok" from someone in the app is a nod, not a wall)
    last3 = users[-3:]
    if not present and len(last3) >= 2 and sum(1 for m in last3 if _words(m.get("text")) <= 2) >= 2 and not any(str(m.get("text") or "").strip().endswith("?") for m in last3):
        gap *= 2
    gap = min(gap, 3 * 3600)
    if last_own and now - float(last_own["t"]) < gap:
        return False, "gap %d min not reached (%d min since your last own%s%s)" % (
            gap // 60, (now - float(last_own["t"])) // 60, ", %d unanswered" % unanswered if unanswered else "", ", night" if night else "")
    return True, "ok (gap %d min%s)" % (gap // 60, ", night" if night else "")


def decide(uid, cid, event, msgs, local_hour=None, present=False):
    ok, why = gate(event, msgs, local_hour, present=present)
    if present:
        why += " [present]"
    try:
        io.open(LOG, "a", encoding="utf-8").write("%s %s %s %s %s | %s\n" % (
            time.strftime("%m-%d %H:%M:%S"), uid, cid, "OK" if ok else "BLOCKED", str(event or "")[:22].replace(" ", "_"), why))
    except Exception:
        pass
    return ok, why


def counts(day_label):
    """for the scorecard: own messages let through / blocked that day (log stamps local time; same calendar label)"""
    out = {"ok": 0, "blocked": 0}
    try:
        for l in io.open(LOG, encoding="utf-8").read().splitlines():
            if l.startswith(day_label):
                out["ok" if " OK " in l else "blocked"] += 1
    except Exception:
        pass
    return out
