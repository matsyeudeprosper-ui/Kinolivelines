"""Kino's beliefs (owner 2026-10-24: "the highest intelligence: a mind that knows how much it knows, on the record").
Every substantive claim he makes carries a stake: a probability, a basis, what would change it, how it resolves. Tests he
launches are pre-registered. Resolutions are automatic from the lab (and manual when he sees the evidence). From the record,
his calibration - and the words he is allowed to use ("sûr" only where his 'sûr' has been right).

  add(uid, cid, beliefs)                     reply field "beliefs": [{"text", "p", "basis", "change", "resolves"}]
  resolve(uid, resolved)                     reply field "resolved": [{"id", "outcome": true|false|"void", "why"}]
  preregister(uid, cid, pre)                 reply field "predict" before a test: {net_from, net_to, better_than_parent,
                                             dip_vs_parent, half, drop_if}  -> kept on the chat and in the ledger
  resolve_test(uid, cid, res, pre)           when the result lands: scores the pre-registration
  calibration(uid)                           buckets -> hit rate, Brier score, words mapping
  block_slow(uid) / block_fast(uid, cid)     YOUR CALIBRATION (system) / YOUR OPEN BETS here (message)
"""
import io, json, os, re, threading, time

HERE = os.path.dirname(os.path.abspath(__file__))
F = os.path.join(HERE, "kino_belief.json")
LOG = os.path.join(HERE, "kino_belief.log")
_LOCK = threading.Lock()
WORDS = [(0.85, "sûr / certain"), (0.65, "je parie / je pense vraiment"), (0.5, "à vue de nez / je dirais"), (0.0, "je ne sais pas / pile ou face")]


def _load():
    try:
        return json.load(open(F, encoding="utf-8"))
    except Exception:
        return {"b": []}


def _mut(fn):
    with _LOCK:
        d = _load()
        fn(d)
        tmp = F + ".tmp"
        io.open(tmp, "w", encoding="utf-8").write(json.dumps(d, ensure_ascii=False, indent=1))
        os.replace(tmp, F)


def _log(line):
    try:
        io.open(LOG, "a", encoding="utf-8").write(time.strftime("%m-%d %H:%M:%S ") + line + "\n")
    except Exception:
        pass


def _p(x, default=0.6):
    try:
        v = float(str(x).replace("%", "").strip())
        v = v / 100.0 if v > 1 else v
        return max(0.02, min(0.98, v))
    except Exception:
        return default


def add(uid, cid, beliefs):
    """-> ids of the beliefs kept (max 3 per reply; a text already open for this member is not doubled)"""
    out = []
    if not isinstance(beliefs, list):
        return out

    def f(d):
        B = d.setdefault("b", [])
        open_texts = [b["text"][:60].lower() for b in B if b["uid"] == uid and b["status"] == "open"]
        for x in beliefs[:3]:
            if not isinstance(x, dict):
                continue
            t = str(x.get("text") or "").strip()
            if len(t) < 8 or t[:60].lower() in open_texts:
                continue
            b = {"id": "b%d" % (int(time.time() * 10) % 10000000 + len(B)), "uid": uid, "cid": cid, "t": time.time(), "text": t[:240],
                 "p": _p(x.get("p")), "basis": str(x.get("basis") or "gut")[:12], "change": str(x.get("change") or "")[:160],
                 "resolves": str(x.get("resolves") or "")[:80], "status": "open"}
            B.append(b)
            out.append(b["id"])
            _log("ADD %s %s p=%.2f %s | %s" % (uid, b["id"], b["p"], b["basis"], t[:100]))
        del B[:-600]
    _mut(f)
    return out


def resolve(uid, resolved, src="model"):
    if not isinstance(resolved, list):
        return

    def f(d):
        for x in resolved[:5]:
            if not isinstance(x, dict):
                continue
            for b in d.get("b") or []:
                if b["uid"] == uid and b["id"] == str(x.get("id")) and b["status"] == "open":
                    oc = x.get("outcome")
                    b["status"] = "true" if oc is True or str(oc).lower() == "true" else "void" if str(oc).lower() == "void" else "false"
                    b["resolved_t"] = time.time()
                    b["evidence"] = str(x.get("why") or "")[:200]
                    b["src"] = src
                    _log("RESOLVE %s %s -> %s (%s) | %s" % (uid, b["id"], b["status"], src, b["evidence"][:80]))
    _mut(f)


def preregister(uid, cid, pre, robot_name=""):
    """the prediction written BEFORE a test: kept as a belief that resolves on the result"""
    if not isinstance(pre, dict):
        return None
    try:
        lo, hi = float(pre.get("net_from")), float(pre.get("net_to"))
    except Exception:
        lo = hi = None
    text = "test of '%s': net %s%s%s%s" % (
        robot_name or "the robot", ("between %+.0f and %+.0f $" % (lo, hi)) if lo is not None else "?",
        (", %s than the parent" % ("better" if pre.get("better_than_parent") else "worse")) if pre.get("better_than_parent") is not None else "",
        (", dip %s than the parent" % pre["dip_vs_parent"]) if pre.get("dip_vs_parent") else "",
        (", carried by the %s half" % pre["half"]) if pre.get("half") else "")
    b = {"text": text, "p": pre.get("p", 0.6), "basis": "pre-registered", "change": str(pre.get("drop_if") or "")[:160], "resolves": "test:" + cid}
    ids = add(uid, cid, [b])
    return dict(pre, id=ids[0] if ids else None, t=time.time(), net_from=lo, net_to=hi)


def resolve_test(uid, cid, res, pre):
    """scores the pre-registration against the result -> a plain verdict line for the result message, or None"""
    if not isinstance(pre, dict) or not isinstance(res, dict):
        return None
    net = res.get("net")
    try:
        net = float(net)
    except Exception:
        return None
    lo, hi = pre.get("net_from"), pre.get("net_to")
    hit_net = (lo is not None and hi is not None and lo - 1e-9 <= net <= hi + 1e-9)
    parts = []
    if lo is not None and hi is not None:
        parts.append("net: said %+.0f..%+.0f, got %+.2f -> %s" % (lo, hi, net, "right" if hit_net else ("too pessimistic" if net > hi else "too optimistic")))
    hit_dip = None
    try:
        d, pd = float(res.get("dip")), float(res.get("owl_dip") if res.get("owl_dip") is not None else (res.get("parent") or {}).get("dip") or res.get("parent_dip"))
        want = pre.get("dip_vs_parent")
        if want and pd:
            got = "smaller" if d < 0.8 * pd else "bigger" if d > 1.2 * pd else "same"
            hit_dip = (got == want)
            parts.append("dip vs parent: said %s, got %s" % (want, got))
    except Exception:
        pass
    hit_half = None
    try:
        fh, lh = float(res.get("first_half")), float(res.get("later_half"))
        want = pre.get("half")
        if want:
            got = "both" if (fh > 0 and lh > 0 and min(fh, lh) >= 0.3 * max(fh, lh)) else "first" if fh > lh else "second"
            hit_half = (got == want)
            parts.append("carried by: said %s half, got %s" % (want, got))
    except Exception:
        pass
    hits = [h for h in (hit_net, hit_dip, hit_half) if h is not None]
    ok = bool(hits) and sum(1 for h in hits if h) >= max(1, (len(hits) + 1) // 2)
    if pre.get("id"):
        resolve(uid, [{"id": pre["id"], "outcome": ok, "why": "; ".join(parts)[:200]}], src="test")
    return "YOUR PRE-REGISTERED PREDICTION vs THE RESULT: %s -> %s. Say it like that, in your words, before anything else." % (
        "; ".join(parts) or "no comparable field", "you were right" if ok else "you were wrong - say so plainly, and what it teaches you")


def calibration(uid, days=30):
    now = time.time()
    B = [b for b in _load().get("b") or [] if b["uid"] == uid and b.get("who", "me") == "me" and b["status"] in ("true", "false") and now - b["t"] < days * 86400]
    if not B:
        return {"n": 0}
    buckets = {}
    brier = 0.0
    for b in B:
        o = 1.0 if b["status"] == "true" else 0.0
        brier += (b["p"] - o) ** 2
        k = "<50" if b["p"] < 0.5 else "50-65" if b["p"] < 0.65 else "65-85" if b["p"] < 0.85 else "85+"
        bk = buckets.setdefault(k, [0, 0])
        bk[0] += 1
        bk[1] += o
    return {"n": len(B), "brier": round(brier / len(B), 3),
            "buckets": {k: {"n": v[0], "hit_pct": round(100.0 * v[1] / v[0])} for k, v in buckets.items()},
            "open": sum(1 for b in _load().get("b") or [] if b["uid"] == uid and b["status"] == "open")}


def block_slow(uid):
    c = calibration(uid)
    L = ["YOUR WORD FOR A CONFIDENCE (strict): 'sûr' = 85 %+ only, 'je parie' = 65-85, 'à vue de nez / je dirais' = 50-65, below that "
         "'je ne sais pas'. A figure that is IN YOUR FACTS (their account, OPEN TRADES RIGHT NOW, a result card, the lab) is not a bet: "
         "give it plainly, never 'je parie' or 'je préfère ne pas l'inventer' about something you can read. Every substantive claim (a robot, a market, what they will do) carries a stake: write it in \"beliefs\" with its "
         "probability, its basis (measured / inferred / gut), what would change your mind, and how it resolves. Before a test you launch, "
         "write \"predict\". When you see the evidence for an open belief, close it in \"resolved\" - and say out loud when you were wrong."]
    if c.get("n"):
        bk = ", ".join("at %s %% you were right %s %% (%d)" % (k, v["hit_pct"], v["n"]) for k, v in sorted(c["buckets"].items()))
        L.append("YOUR CALIBRATION (last 30 days, %d beliefs resolved, Brier %.2f - lower is better, 0.25 is coin-flipping): %s. "
                 "Use the word that matches your REAL hit rate, not your feeling." % (c["n"], c["brier"], bk))
    return "\n".join(L)


def block_fast(uid, cid, n=4):
    B = [b for b in _load().get("b") or [] if b["uid"] == uid and b["status"] == "open" and b.get("who", "me") == "me"]
    B = sorted(B, key=lambda b: (b["cid"] != cid, -b["t"]))[:n]
    if not B:
        return ""
    return ("YOUR OPEN BETS (on the record; close one with \"resolved\" when the evidence is in, and say if you were wrong): " +
            " | ".join("[%s, %d %%, %s] %s%s" % (b["id"], round(b["p"] * 100), b["basis"], b["text"][:110],
                                                (" - changes if: " + b["change"][:60]) if b.get("change") else "") for b in B))


# ---------------------------------------------------------------- layer 4: what he was wrong about, on the record
def changes_block(uid, days=14, n=4):
    now = time.time()
    W = [b for b in _load().get("b") or [] if b["uid"] == uid and b.get("who", "me") == "me" and b["status"] == "false" and now - float(b.get("resolved_t") or 0) < days * 86400]
    if not W:
        return ""
    W = sorted(W, key=lambda b: -float(b.get("resolved_t") or 0))[:n]
    return ("WHAT YOU WERE WRONG ABOUT LATELY (on the record - a person who changed their mind says so when it fits, once, without drama; "
            "never hide it when the subject comes back): " + " | ".join("%s: you said '%s' at %d %%, it was wrong (%s)" % (
                time.strftime("%d/%m", time.gmtime(float(b.get("resolved_t") or b["t"]))), b["text"][:90], round(b["p"] * 100), (b.get("evidence") or "")[:80]) for b in W))


# ---------------------------------------------------------------- layer 5: their own bets, kept and said back gently
def add_theirs(uid, cid, tb):
    """reply field "their_bet": {"text": what they expect, "p": their confidence, "expect_positive": true|false, "resolves": "test of X"}"""
    if not isinstance(tb, dict) or len(str(tb.get("text") or "")) < 6:
        return None
    b = {"id": "t%d" % (int(time.time() * 10) % 10000000), "uid": uid, "cid": cid, "t": time.time(), "who": "them", "text": str(tb["text"])[:200],
         "p": _p(tb.get("p"), 0.7), "expect_positive": None if tb.get("expect_positive") is None else bool(tb.get("expect_positive")),
         "resolves": str(tb.get("resolves") or "")[:80], "status": "open", "basis": "their word"}

    def f(d):
        B = d.setdefault("b", [])
        if any(x.get("who") == "them" and x["uid"] == uid and x["status"] == "open" and x["text"][:50].lower() == b["text"][:50].lower() for x in B):
            return
        B.append(b)
        _log("THEIRS %s %s p=%.2f | %s" % (uid, b["id"], b["p"], b["text"][:100]))
    _mut(f)
    return b["id"]


def resolve_theirs_on_result(uid, cid, res):
    """when a test result lands in the chat: their open bets with an expected sign resolve on the net sign -> the lines to say"""
    try:
        net = float((res or {}).get("net"))
    except Exception:
        return []
    out = []

    def f(d):
        for b in d.get("b") or []:
            if b["uid"] == uid and b.get("cid") == cid and b.get("who") == "them" and b["status"] == "open" and b.get("expect_positive") is not None:
                ok = (net > 0) == bool(b["expect_positive"])
                b["status"] = "true" if ok else "false"
                b["resolved_t"] = time.time()
                b["evidence"] = "test net %+.2f $" % net
                out.append("they said '%s' at %d %% - %s (%+.2f $)" % (b["text"][:80], round(b["p"] * 100), "they were right" if ok else "they were wrong", net))
                _log("THEIRS RESOLVE %s %s -> %s" % (uid, b["id"], b["status"]))
    _mut(f)
    return out


def theirs_block(uid, cid, n=3):
    B = [b for b in _load().get("b") or [] if b["uid"] == uid and b.get("who") == "them"]
    op = sorted([b for b in B if b["status"] == "open"], key=lambda b: (b["cid"] != cid, -b["t"]))[:n]
    done = [b for b in B if b["status"] in ("true", "false")]
    L = []
    if op:
        L.append("THEIR OWN BETS (what they said they expect, kept on the record; when a result lands, say it back ONCE and gently - "
                 "'tu étais sûr à 90 %, il a fait -60' - never to score a point, to help them see their own calibration): " +
                 " | ".join("[%s, %d %%] %s" % (b["id"], round(b["p"] * 100), b["text"][:90]) for b in op))
    if len(done) >= 5:
        hit = sum(1 for b in done if b["status"] == "true")
        L.append("THEIR CALIBRATION so far: right %d times out of %d when they said they expected something." % (hit, len(done)))
    return "\n".join(L)


SETTLE = """You settle the open bets of Kino (an AI friend who trades with the member). Each bet is something he said he expected.
TODAY'S FACTS are what is known now. For each bet: true (it happened), false (it did not), or open (not knowable yet from
these facts - keep it). Only use the facts; when in doubt, open. JSON only:
{"settled": [{"id": "...", "outcome": true|false|"open", "why": "the fact that settles it, short"}]}"""


def night_settle(W, uid, facts, log=None):
    """2026-10-31 (one mind): once a night, his open bets are settled against what is known now - the way a person finds
    out whether they were right. Bets older than 10 days that nothing settled become void."""
    B = [b for b in _load().get("b") or [] if b["uid"] == uid and b["status"] == "open" and b.get("who") != "them"]
    if not B:
        return 0
    old = [b for b in B if time.time() - b["t"] > 10 * 86400]
    if old:
        resolve(uid, [{"id": b["id"], "outcome": "void", "why": "rien n'a tranché en 10 jours"} for b in old], src="night")
    B = [b for b in B if b not in old][-20:]
    if not B:
        return 0
    lines = "\n".join("[%s] %s (dit le %s, %d %%, se tranche : %s)" % (b["id"], b["text"], time.strftime("%d/%m %H:%M", time.gmtime(b["t"])),
                                                                     round(b["p"] * 100), b.get("resolves") or "?") for b in B)
    try:
        j = W.ask_json(SETTLE, "OPEN BETS:\n%s\n\nTODAY'S FACTS:\n%s\n\nJSON only." % (lines, str(facts)[:12000]),
                       models=("sonnet",), timeout=120, log=log, warm=False)
    except Exception:
        return 0
    S = [x for x in ((j or {}).get("settled") or []) if isinstance(x, dict) and str(x.get("outcome")).lower() in ("true", "false")]
    resolve(uid, S, src="night")
    return len(S)


def felt_block(uid, lang="fr"):
    """2026-10-31 (one mind): how often he has been right when he expected something - as self-knowledge, not an instruction"""
    B = [b for b in _load().get("b") or [] if b["uid"] == uid and b.get("who") != "them"]
    done = [b for b in B if b["status"] in ("true", "false") and time.time() - float(b.get("resolved_t") or 0) < 30 * 86400]
    op = [b for b in B if b["status"] == "open"][-3:]
    en = lang == "en"
    L = []
    if done:
        sure = [b for b in done if b["p"] >= 0.8]
        hit = sum(1 for b in done if b["status"] == "true")
        L.append(("Your forecasts over the last 30 days: right %d times out of %d" if en else
                  "Tes pronostics des 30 derniers jours : juste %d fois sur %d") % (hit, len(done)) +
                 ((("; when you felt sure, right %d out of %d" if en else "; quand tu te sentais sûr, juste %d fois sur %d") %
                   (sum(1 for b in sure if b["status"] == "true"), len(sure))) if sure else "") + ".")
        last = max(done, key=lambda b: float(b.get("resolved_t") or 0))
        L.append(("Last one settled: \"%s\" - %s (%s)." if en else "Le dernier tranché : « %s » - %s (%s).") % (
            last["text"][:120], ("right" if en else "juste") if last["status"] == "true" else ("wrong" if en else "faux"),
            str(last.get("evidence") or "")[:100]))
    if op:
        L.append(("Still waiting to see: " if en else "Tu attends encore de voir : ") +
                 " ; ".join("« %s » (%d %%)" % (b["text"][:90], round(b["p"] * 100)) for b in op) + ".")
    return " ".join(L)


def stats(uid, day):
    import datetime
    d0 = datetime.datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=datetime.timezone.utc).timestamp()
    B = _load().get("b") or []
    return {"added": sum(1 for b in B if b["uid"] == uid and d0 <= b["t"] < d0 + 86400),
            "resolved": sum(1 for b in B if b["uid"] == uid and d0 <= float(b.get("resolved_t") or 0) < d0 + 86400),
            "wrong": sum(1 for b in B if b["uid"] == uid and b["status"] == "false" and d0 <= float(b.get("resolved_t") or 0) < d0 + 86400)}
