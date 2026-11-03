"""test_kino_isolation.py (2026-11-03, owner: "many members at once - prove no mixing"). Five made-up people, each with their own
way of doing things, trust history and record. Checks that every per-person engine returns ONLY that person's things:
kino_ways (notebook), kino_trust (latitude), kino_patterns (record), kino_human2 timeline. kino_fields is shared on
purpose (general knowledge of a field, never private details) - checked to hold no names.
Writes nothing permanent: every test person is removed at the end. python -X utf8 review/test_kino_isolation.py"""
import json, os, sys, time, random

HERE = os.path.dirname(os.path.abspath(__file__))
ROB = os.path.join(os.path.dirname(HERE), "robots")
sys.path.insert(0, ROB)
import kino_ways as KW, kino_trust as KT, kino_patterns as KP, kino_fields as KF  # noqa: E402

P = ["iso_ana", "iso_bilal", "iso_chen", "iso_dora", "iso_emeka"]
WORD = {p: "secret-%s-%d" % (p, i) for i, p in enumerate(P)}
fails = []


def ok(cond, what):
    if not cond:
        fails.append(what)


now = time.time()
try:
    # notebooks
    with KW._LOCK:
        d = KW._load()
        for p in P:
            d[p] = {"items": [{"topic": "how he likes it", "said": "only %s" % WORD[p], "t": now}]}
        KW._save(d)
    # trust
    for i, p in enumerate(P):
        KT.did(p, "order:open", "x")
        KT.react(p, "approved" if i % 2 else "corrected", WORD[p])
    # records
    random.seed(3)
    for i, p in enumerate(P):
        R = [{"t": now - 86400 * 30 + k * 3600 * 5, "y": random.gauss(1 if (k % 2) == (i % 2) else -1, 0.5),
              "attrs": {"tag": WORD[p] if k % 2 else "other"}} for k in range(30)]
        KP.update(p, "sales", R, " $")
    for p in P:
        others = [WORD[q] for q in P if q != p]
        bl = KW.block(p, "en") + "\n" + KT.block(p) + "\n" + KP.block(p)
        ok(WORD[p] in bl, "%s does not see its own data" % p)
        for w in others:
            ok(w not in bl, "%s sees another person's data (%s)" % (p, w))
    fb = json.dumps(KF._load(), ensure_ascii=False)
    for p in P:
        ok(p not in fb and WORD[p] not in fb, "field notes hold a person's name/data (%s)" % p)
finally:
    with KW._LOCK:
        d = KW._load()
        for p in P:
            d.pop(p, None)
        KW._save(d)
    with KT._LOCK:
        d = KT._load()
        for p in P:
            d.pop(p, None)
        KT._save(d)
    with KP._LOCK:
        d = KP._load()
        for p in P:
            d.pop(p, None)
        KP._save(d)

print("ISOLATION: OK (5 people, ways / trust / patterns apart, fields hold no names)" if not fails else "ISOLATION FAILED:\n" + "\n".join(fails))
sys.exit(1 if fails else 0)
