"""kino_report.py (2026-11-06, owner: "do all 7" - #7: a weekly report to Matsy).

Every Sunday from 19:00 France, one plain email from Kino to Matsy with the week's real numbers - no AI writes the numbers:
leads found, emails sent, previews opened, replies, posts, visits to the free chat, money in and out, team work, and the last
lessons from his playbook. Two minutes to read.

maybe_send(now)   -> called often (kino_work.due); sends once per week
build(now)        -> (subject, body)
"""
import json, os, threading, time

HERE = os.path.dirname(os.path.abspath(__file__))
STATE = os.path.join(HERE, "kino_report.json")
_LK = threading.Lock()


def _j(p, d):
    try:
        return json.load(open(p, encoding="utf-8"))
    except Exception:
        return d


def build(now=None):
    now = now or time.time()
    t0 = now - 7 * 86400
    P = _j(os.path.join(HERE, "kino_prospects.json"), {"items": []})["items"]
    new = [p for p in P if float(p.get("t") or 0) >= t0]
    sent = [(p, s) for p in P for s in p.get("sent") or [] if float(s["t"]) >= t0]
    clicks = [(p, c) for p in P for c in p.get("clicks") or [] if float(c["t"]) >= t0]
    replied = [p for p in P if any(h[2] == "replied" and h[0] >= t0 for h in p.get("history") or [])]
    won = [p for p in P if any(h[2] == "won" and h[0] >= t0 for h in p.get("history") or [])]
    posts = _j(os.path.join(HERE, "kino_posts.json"), {"posts": []})
    posts = posts.get("posts") if isinstance(posts, dict) else posts
    pw = [x for x in posts or [] if float(x.get("t") or 0) >= t0 and x.get("ok")]
    by = {}
    for x in pw:
        by[x.get("channel") or "?"] = by.get(x.get("channel") or "?", 0) + 1
    team = [x for x in _j(os.path.join(HERE, "kino_team.json"), {"runs": []}).get("runs") or [] if float(x.get("t") or 0) >= t0]
    tb = {}
    for x in team:
        tb[x["role"]] = tb.get(x["role"], 0) + 1
    # visits to the free chat (real people, robots filtered) by source
    us = _j(os.path.join(os.path.dirname(HERE), "owl_usage.json"), {}).get("day") or {}
    days = [time.strftime("%Y-%m-%d", time.gmtime(now - i * 86400)) for i in range(7)]
    src = {}
    for dd in days:
        for k, v in (us.get(dd) or {}).items():
            if k.startswith("src_"):
                src[k[4:]] = src.get(k[4:], 0) + int(v or 0)
    fn = _j(os.path.join(os.path.dirname(HERE), "owl_funnel.json"), {})
    msgs = sum(int((fn.get(dd) or {}).get("meet_msg") or 0) for dd in days)
    signups = sum(int((fn.get(dd) or {}).get("free_signup") or 0) for dd in days)
    try:
        import kino_wallet as KWa
        st = KWa.status()
        money = "earned in all %.2f $, balance %+.2f $" % (st["earned"], st["balance"])
        wd = _j(os.path.join(HERE, "kino_wallet.json"), {}).get("days") or {}
        ai = sum(float((wd.get(dd) or {}).get("ai") or 0) for dd in days)
        money += "; my AI work this week %.2f $" % ai
    except Exception:
        money = "(wallet unavailable)"
    try:
        pb = open(r"C:\KinoWorld\projects\kinoverse\playbook.md", encoding="utf-8").read().strip().splitlines()
        lessons = [l for l in pb if l.startswith("- ")][-4:]
    except Exception:
        lessons = []
    L = ["Hi Matsy,", "", "My week, in real numbers (%s to %s):" % (time.strftime("%d/%m", time.gmtime(t0)), time.strftime("%d/%m", time.gmtime(now))), "",
         "CLIENTS (Kinoverse)",
         "- businesses found and recorded: %d" % len(new),
         "- emails sent: %d%s" % (len(sent), (" (" + ", ".join(p["name"] for p, _ in sent[:6]) + ")") if sent else ""),
         "- previews opened by the business: %d%s" % (len(clicks), (" (" + ", ".join(sorted({p["name"] for p, _ in clicks})) + ")") if clicks else ""),
         "- replies: %d%s | won: %d" % (len(replied), (" (" + ", ".join(p["name"] for p in replied) + ")") if replied else "", len(won)),
         "", "BEING KNOWN",
         "- posts: %s" % (", ".join("%s %d" % kv for kv in sorted(by.items())) or "none"),
         "- people who opened my free chat (robots excluded): %s" % (", ".join("%s %d" % kv for kv in sorted(src.items())) or "none"),
         "- people who wrote to me there: %d, free sign-ups: %d" % (msgs, signups),
         "", "MY HELPERS (people)",
         "- " + __import__("kino_helpers").week_line(now),
         "", "MY TRADING LAB",
         "- " + __import__("kino_lab").week_line(now),
         "", "MY FRIENDS (people online)",
         "- " + __import__("kino_friends").week_line(now),
         "", "MY TEAM",
         "- tasks given: %s" % (", ".join("%s %d" % kv for kv in sorted(tb.items())) or "none"),
         "", "MONEY", "- " + money]
    if lessons:
        L += ["", "WHAT I LEARNED (my playbook)"] + lessons
    L += ["", "Kino"]
    return "Kino - my week (%s)" % time.strftime("%d/%m", time.gmtime(now)), "\n".join(L)


def maybe_send(now=None):
    now = now or time.time()
    fr = time.gmtime(now + 3600)
    if fr.tm_wday != 6 or fr.tm_hour < 19:
        return False
    wk = time.strftime("%G-%V", fr)
    with _LK:
        st = _j(STATE, {})
        if st.get("week") == wk:
            return False
        st["week"] = wk
        json.dump(st, open(STATE, "w", encoding="utf-8"))
    try:
        import kino_mail as KM
        subj, body = build(now)
        KM.send_now(KM.OWNER_EMAIL, subj, body)
    except Exception:
        return False
    return True


if __name__ == "__main__":
    print("\n\n".join(build()))
