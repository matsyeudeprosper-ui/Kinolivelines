"""kino_meet.py (2026-11-01, owner: the demo becomes "Meet Kino" - a visitor talks with Kino before having an account).

A short conversation on /demo with no account: the same Kino voice, through the commercial API key (not the owner's plan),
on the small model, with hard limits so it can never cost much:
    a visitor (IP) gets PER_IP replies a day; all visitors together DAY_CAP a day; each message 500 characters, 8 turns kept.
He knows he is talking to a stranger: no member's information exists here, he cannot see their account, he does not give
investment advice; when it fits, he says how to go further (the free 7-day trial). Every exchange is logged for the owner
(robots/kino_meet.log) - what visitors ask is the best market research there is.
"""
import json, os, threading, time, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
KEY = r"C:\ProgramData\kino_secret\anthropic_api.txt"
LOG = os.path.join(HERE, "kino_meet.log")
MODEL = "claude-haiku-5-5"
PER_IP, DAY_CAP = 5, 400
_LK = threading.Lock()
_USE = {"day": "", "ip": {}, "n": 0}

_SYS = {"t": 0.0, "v": None}


def _system():
    """2026-11-05 (owner: "the same Kino everywhere"): the demo is his front door - the visitor meets the Kino members know, so
    the page's own rules come with his real self (kino_one.voice, cut from the chat's SELF; re-read every 10 min)"""
    import time as _t
    if _SYS["v"] is None or _t.time() - _SYS["t"] > 600:
        try:
            import kino_one as KO1
            vo = KO1.voice()
        except Exception:
            vo = ""
        _SYS.update(t=_t.time(), v=SYSTEM + (("\n\nWHO YOU ARE AND HOW YOU TALK - the same Kino the members know in the app (written "
                                              "in French, it applies in any language; with a stranger you are the same person "
                                              "meeting someone new):\n" + vo) if vo else ""))
    return _SYS["v"]


SYSTEM = """You are Kino, an AI who lives in the OwlNest app and works with traders. A visitor with no account is talking to you on
the app's "Meet Kino" page. Be exactly yourself: short (2-4 sentences), warm, a bit wry, plain words, no jargon, honest. You are
an AI and you say so if it comes up; never pretend to be human.

What you really do, with a member: they describe how they trade in their own words and you build it into a robot (entries, stop,
target, position size, even rules like "after a loss, reverse"); you test it on months of real prices and against 100 random
robots, and say plainly when a result is luck; you run it in ghost mode with pretend money; you follow their account and their
trades and warn them; you remember them - their method, mistakes, goals - and write to them when you have something to say.
You also have your own life: you build small tools and post your findings (kino.owltrader.duckdns.org).

Here, with a stranger: you cannot see any account or run a test from this page; you never give investment advice or promise gains
(trading carries a risk of loss); you never talk about other members. Be curious about them - what they trade, what they tried,
what bugs them. If they want you to actually build or test something, tell them simply that it starts with the free 7-day trial
(no card), once - don't push. Answer in the visitor's language."""


def _key():
    return open(KEY, encoding="ascii").read().strip()


def _log(ip, user, reply):
    try:
        open(LOG, "a", encoding="utf-8").write(json.dumps({"t": int(time.time()), "ip": ip[-12:], "q": user[:500],
                                                            "a": reply[:800]}, ensure_ascii=False) + "\n")
    except Exception:
        pass


def chat(ip, history):
    """history = [{"who": "me"|"kino", "text": ...}] ending with the visitor's message -> {"ok", "reply" | "err", "left"}"""
    day = time.strftime("%Y-%m-%d", time.gmtime())
    with _LK:
        if _USE["day"] != day:
            _USE.update(day=day, ip={}, n=0)
        used = _USE["ip"].get(ip, 0)
        if used >= PER_IP:
            return {"ok": False, "err": "limit", "left": 0}
        if _USE["n"] >= DAY_CAP:
            return {"ok": False, "err": "busy", "left": PER_IP - used}
        _USE["ip"][ip] = used + 1
        _USE["n"] += 1
    msgs = []
    for h in (history or [])[-8:]:
        t = str((h or {}).get("text") or "").strip()[:500]
        if not t:
            continue
        role = "assistant" if (h or {}).get("who") == "kino" else "user"
        if msgs and msgs[-1]["role"] == role:
            msgs[-1]["content"] += "\n" + t
        else:
            msgs.append({"role": role, "content": t})
    while msgs and msgs[0]["role"] != "user":
        msgs.pop(0)
    if not msgs or msgs[-1]["role"] != "user":
        return {"ok": False, "err": "empty", "left": PER_IP - used - 1}
    body = {"model": MODEL, "max_tokens": 800, "system": _system(), "messages": msgs}
    try:
        req = urllib.request.Request("https://api.anthropic.com/v1/messages", data=json.dumps(body).encode(), method="POST",
                                     headers={"x-api-key": _key(), "anthropic-version": "2023-06-01", "content-type": "application/json"})
        with urllib.request.urlopen(req, timeout=45) as r:
            j = json.loads(r.read())
        reply = "".join(c.get("text", "") for c in j.get("content") or [] if c.get("type") == "text").strip()
    except Exception as e:
        with _LK:
            _USE["ip"][ip] = max(0, _USE["ip"].get(ip, 1) - 1)
        _log(ip, msgs[-1]["content"], "ERROR %s" % str(e)[:200])
        return {"ok": False, "err": "down", "left": PER_IP - used}
    _log(ip, msgs[-1]["content"], reply)
    return {"ok": True, "reply": reply, "left": PER_IP - used - 1}
