"""kino_focus.py (2026-11-04, owner: "next" - after Kino missed the owner's ladder that sat in front of him: his context had
grown to ~40,000 characters and everything was shown at once).

A person does not hold thirty things in mind equally. A few are in focus - what is urgent, what the talk is about - and the
rest stays in the back of the mind, there if something calls it up. The theories call it a limited-capacity workspace; in a
person it is simply focus. Here the per-message part of what he reads goes through it:
  - always in focus: what the person just asked him to remember, his read of them, their notebook (their own words about
    how they want things), and while he works for them the cases of their rules, his attention, his session tally
  - everything else competes: how urgent it is (a fresh misread, a question left hanging, a value at stake, a feeling that
    was found missing...) and how much it touches what is being talked about right now (shared words with the last messages)
  - within a budget; what does not make it is named in one line ("also in the back of your mind: ...") so he knows it is there
Any field: it judges lines by urgency and relevance, never by subject. Logs how much it kept (kino_focus.log).
"""
import os, re, time

HERE = os.path.dirname(os.path.abspath(__file__))
LOG = os.path.join(HERE, "kino_focus.log")
BUDGET = 9500          # characters of the fresh part in focus (6500 left only the pinned lines in: 5 of 33 on 11-04)

# the beginnings of lines that are never pushed out
PINNED = ("He asks you to remember", "He asks you to remember. You searched", "Ta lecture de lui", "Your read of him",
          "WHAT HE TOLD YOU ABOUT HOW HE DOES", "CE QU'IL T'A DIT DE SA FAÇON", "Past cases of his rules", "How his older and newer",
          "His attention right now", "Your own hindsight on this session", "Your attention is on")
# urgency of the other kinds, by how their line begins (unknown lines get 0.4)
URGENCY = (
    ("His recent request sits against what you stand for", 1.0), ("He just had to ask you twice", 0.95),
    ("Questions left hanging", 0.8), ("He just said this without the reason", 0.75), ("In his life, something he told you", 0.75),
    ("Something he told you can be read two ways", 0.85), ("Earlier (", 0.6), ("Something is still nagging", 0.55),
    ("What you resolved after things", 0.55), ("In the last 3 hours with him things went wrong", 0.7),
    ("At ", 0.6), ("Standing promises", 0.45), ("How your quick estimates", 0.5), ("Something you have found out about yourself", 0.5),
    ("What you perceive of him", 0.45), ("What you perceive on", 0.55), ("Where you are inside", 0.45), ("How much you have in you", 0.4),
    ("What your own orders do", 0.45), ("You were switched off", 0.5), ("Words that are yours and his", 0.25),
    ("His rhythm", 0.25), ("What he calls things", 0.6), ("How his trades went after", 0.4), ("A rule of his you follow", 0.35),
    ("What many people have taught you", 0.3), ("How your own messages to him sounded", 0.45), ("This stretch with him", 0.5),
    ("Where your last conversation with him stopped", 0.65),
)


def _stems(t):
    return set(w[:6] for w in re.findall(r"[a-zà-ÿ0-9]{4,}", str(t).lower()))


def _urgency(line):
    for p, u in URGENCY:
        if line.startswith(p):
            return u
    return 0.4


def _label(line):
    return re.split(r"[:(.]", line, 1)[0][:60].strip()


def select(lines, talk, budget=BUDGET, cid=""):
    """lines: the fresh part, in order; talk: the last messages -> (lines in focus, in their order, + one 'back of your mind' line)"""
    flat = []                                        # a block of several kinds is judged kind by kind; a list stays with its head
    for x in [x for x in lines if x and str(x).strip()]:
        if x.startswith(PINNED):
            flat.append(x)
            continue
        for ln in str(x).split("\n"):
            if ln.startswith(("- ", "  ")) and flat:
                flat[-1] += "\n" + ln
            elif ln.strip():
                flat.append(ln)
    lines = flat
    total = sum(len(x) for x in lines)
    if total <= budget:
        return lines
    tw = _stems(talk)
    keep, scored = set(), []
    for i, x in enumerate(lines):
        if x.startswith(PINNED):
            keep.add(i)
        else:
            rel = len(tw & _stems(x)) / max(4.0, len(_stems(x)) ** 0.5 * 2)
            scored.append((_urgency(x) + min(0.5, rel), i))
    used = sum(len(lines[i]) for i in keep)
    for s, i in sorted(scored, reverse=True):
        if used + len(lines[i]) <= budget:
            keep.add(i)
            used += len(lines[i])
    out = [lines[i] for i in sorted(keep)]
    back = [_label(lines[i]) for _, i in sorted(scored, reverse=True) if i not in keep]
    if back:
        out.append("Also in the back of your mind, out of focus right now (it comes back if the talk turns to it): " + "; ".join(back[:12]) + ".")
    try:
        open(LOG, "a", encoding="utf-8").write("%s %s fresh %d -> %d chars, %d of %d lines in focus\n" % (
            time.strftime("%m-%d %H:%M:%S"), cid, total, sum(len(x) for x in out), len(keep), len(lines)))
    except Exception:
        pass
    return out
