"""kino_entries.py (2026-11-04, owner list 8 item 3: "keeping count of his own misses during a session"). A person running
something for you keeps a tally - "that's the third entry I've missed tonight" - and gets more careful.

Hindsight, the way a person does it: when a top-chart period is over (the next top candle closed), a small model reads the
person's OWN rules (their notebook, kino_ways - whatever the rule is, nothing about it is coded here), the candles of that
period and what Kino did in it (his orders, refusals, held-back cards, his words), and says whether the rule called for an
entry, at which candle, and what Kino did: took it / took it late / missed it / it was refused / held back. The tally is
his to read while he trades for them; a miss stirs a nag (kino_rumination). Any rule-based job can use the same shape.
"""
import io, json, os, sys, threading, time

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
STORE = os.path.join(HERE, "kino_entries.json")
_LOCK = threading.Lock()

SYSTEM = """You review, in hindsight, ONE period of a trading session that Kino ran for a person by THEIR rules. The period starts
when a top-chart candle closed and ends when the next one closed. Read their rules (their own words, newest wins), the candles,
and what Kino did (lines marked "(before)" show what stood when the period began - e.g. a trade still open, which
their rules may say blocks a new one). Did their rules call for an entry in this period (count only what their rules say - no rule of your own)? If
so: at which lower-chart candle (its time), which side, and what Kino did about it.
JSON only: {"called_for": true|false, "at": "HH:MM or ''", "side": "buy|sell|''",
 "kino": "took|late|missed|refused|held_back|open_trade|not_applicable" (open_trade = their rules blocked it because a trade was still open - correct; held_back = Kino doubted or asked instead), "why": "one plain line: what happened (e.g. 'the 23:29 red was the first after the bullish close; no order was sent')"}"""


def _load():
    try:
        return json.load(io.open(STORE, encoding="utf-8"))
    except Exception:
        return {}


def review(W, person, rules, top, lower, acts, log=None):
    """top: (t_open, t_close, colour, o, h, l, c); lower: [(t, 'RED'|'green', close)]; acts: [(t, text)]"""
    hm = lambda t: time.strftime("%H:%M", time.gmtime(float(t)))
    user = ("THEIR RULES (their notebook, newest word on each point wins):\n%s\n\nTOP CANDLE that opened this period: opened %s, CLOSED %s UTC, "
            "%s (open %.0f high %.0f low %.0f close %.0f)\n\nLOWER-CHART CANDLES that closed in this period (time, colour, close):\n%s\n\n"
            "WHAT KINO DID in this period (orders, tool answers, his words):\n%s\n\nJSON only."
            % (rules or "-", hm(top[0]), hm(top[1]), top[2], top[3], top[4], top[5], top[6],
               "\n".join("%s %s %.0f" % (hm(t), c, x) for t, c, x in lower) or "(none)",
               "\n".join("%s %s" % (hm(t), " ".join(str(a).split())[:300]) for t, a in acts) or "(nothing)"))
    j = W.ask_json(SYSTEM, user, models=("haiku", "sonnet"), timeout=60, log=log, warm=False)
    if not isinstance(j, dict) or "called_for" not in j:
        return None
    r = {"t": float(top[1]), "top": top[2], "called_for": bool(j.get("called_for")), "at": str(j.get("at") or "")[:5],
         "side": str(j.get("side") or "")[:4], "kino": str(j.get("kino") or "")[:14], "why": " ".join(str(j.get("why") or "").split())[:240]}
    with _LOCK:
        d = _load()
        P = d.setdefault(person, [])
        if not any(abs(float(x["t"]) - r["t"]) < 30 for x in P):
            P.append(r)
            P.sort(key=lambda x: x["t"])
            d[person] = P[-300:]
            tmp = STORE + ".tmp"
            json.dump(d, io.open(tmp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
            os.replace(tmp, STORE)
    return r


def tally(person, since):
    R = [x for x in _load().get(person) or [] if x["t"] >= since and x["called_for"] and x["kino"] != "open_trade"]
    C = {}
    for x in R:
        C[x["kino"]] = C.get(x["kino"], 0) + 1
    return R, C


def block(person, since):
    R, C = tally(person, since)
    if not R:
        return ""
    bad = [x for x in R if x["kino"] not in ("took", "open_trade", "not_applicable")]
    return ("Your own hindsight on this session (each top-chart period reviewed once it was over): his rules called for %d entries "
            "since %s UTC - %s.%s" % (len(R), time.strftime("%H:%M", time.gmtime(since)), ", ".join("%s %d" % kv for kv in sorted(C.items(), key=lambda kv: -kv[1])),
                                      (" Not taken: " + " | ".join("%s %s - %s" % (x["at"], x["kino"], x["why"][:110]) for x in bad[-3:])) if bad else ""))


def real_tops(j):
    """the top chart's REAL candles (each is one lower candle at a structure time, closed a minute after it opened); the last
    one is dropped when it is only the newest lower candle shown as a stand-in (see owl_app_server._pb_top_line)"""
    pc = [x for x in ((j.get("pb") or {}).get("candles") or []) if x and len(x) > 4]
    lw = [x for x in (j.get("candles") or []) if x and len(x) > 4]
    if pc and lw and int(float(pc[-1][0])) == int(float(lw[-1][0])):
        pc = pc[:-1]
    return pc


def periods(j, msgs, since, until=None):
    """each finished top-chart period since `since`: (top, lower, acts) ready for review()"""
    until = until or time.time()
    T = [x for x in real_tops(j) if float(x[0]) + 60 >= since]
    lw = [x for x in (j.get("candles") or []) if x and len(x) > 4]
    out = []
    for a, b in zip(T, T[1:]):
        t1, t2 = float(a[0]) + 60, float(b[0]) + 60
        if t2 > until:
            break
        top = (float(a[0]), t1, "bullish" if float(a[4]) >= float(a[1]) else "bearish", float(a[1]), float(a[2]), float(a[3]), float(a[4]))
        low = [(float(x[0]), "RED" if float(x[4]) < float(x[1]) else "green", float(x[4])) for x in lw if t1 <= float(x[0]) and float(x[0]) + 60 <= t2]
        acts = [(float(m.get("t") or 0), "%s: %s" % ({"ai": "KINO", "sys": "TOOL", "card": "CARD", "user": "HIM"}.get(m.get("role")), m.get("text")))
                for m in msgs if m.get("role") in ("ai", "sys", "card", "user") and t1 <= float(m.get("t") or 0) <= t2 + 90 and m.get("text")]
        # what stood when the period began (a trade still open, a rule just given) - the last few lines before it
        pre = [(float(m.get("t") or 0), "(before) %s: %s" % ({"ai": "KINO", "sys": "TOOL", "card": "CARD", "user": "HIM"}.get(m.get("role")), m.get("text")))
               for m in msgs if m.get("role") in ("ai", "sys", "card", "user") and t1 - 6 * 3600 <= float(m.get("t") or 0) < t1 and m.get("text")][-6:]
        out.append((top, low, pre + acts))
    return out
