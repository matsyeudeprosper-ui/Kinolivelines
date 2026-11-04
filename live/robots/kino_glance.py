"""kino_glance.py (2026-11-04, owner: "start cutting the cost without destroying Kino's progress").

Measured: of $79 a day, $62 went to full turns of his mind - 767 of them, most of them his watch over a chart that answered
"nothing to do". A person who watches something for someone does not think hard about every tick: they GLANCE, and only
engage when something might be happening. Here: each watch event first gets a glance - a small model with only what matters
for that moment (the person's own rules in their words, what the situation shows now, what is open, what was said just
before). It answers wake / stay quiet; "unsure" wakes him. Only a wake reaches his full mind. Any field: a glance needs the
person's rules and the moment, nothing about trading is coded here. Every glance is logged (kino_glance.log) so misses can be
checked against the hindsight tally.
"""
import json, os, time

HERE = os.path.dirname(os.path.abspath(__file__))
LOG = os.path.join(HERE, "kino_glance.log")

SYSTEM = """You take a quick GLANCE for Kino, who watches something for a person by THEIR rules (below, in their words). Decide
whether this moment could call for Kino to do or say something NOW: an action their rules call for (or might call for), a
position or task that needs attention, something he told them that is now wrong, or anything you are not sure about.
Look at what JUST happened (the last thing that closed or changed): if it is not something their rules act on (e.g. the
wrong kind or colour for the setup that is live, outside the time their rules allow, or a trade is already open and nothing
about it changed), and nothing he told them is now wrong, it needs nothing: wake=false. If it MIGHT be what their rules act on,
or a position needs care, or you are unsure: wake=true - a missed action costs far more than a glance.
JSON only: {"wake": true|false, "why": "a few words"}"""


def glance(W, rules, moment, recent="", log_tag=""):
    """-> (wake: bool, why: str); any failure wakes him"""
    try:
        j = W.ask_json(SYSTEM, "THEIR RULES (their own words, newest wins):\n%s\n\nTHE MOMENT NOW:\n%s\n\nJUST BEFORE (last messages):\n%s\n\nJSON only."
                       % (rules[:3500], moment[:3500], (recent or "-")[:1500]), models=("haiku",), timeout=25, warm=True)
        wake = not (isinstance(j, dict) and j.get("wake") is False)
        why = str((j or {}).get("why") or "")[:120] if isinstance(j, dict) else "no answer"
    except Exception as e:
        wake, why = True, "glance failed: %s" % type(e).__name__
    try:
        open(LOG, "a", encoding="utf-8").write("%s %s %s %s\n" % (time.strftime("%m-%d %H:%M:%S"), log_tag, "WAKE" if wake else "quiet", why))
    except Exception:
        pass
    return wake, why
