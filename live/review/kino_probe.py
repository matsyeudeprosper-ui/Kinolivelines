"""kino_probe.py (2026-11-28) - the same short conversation, played by a test account in the real app, then judged by
review/kino_quality.py. Before/after any change to Kino's voice: a number, not a feeling.

The script is a person, not a quiz: a bad day, a wrong fact said with confidence, an opinion that deserves pushback, a tease,
"what did you do today", an ambition (the coach trap), "make me laugh", a why-question to explore, insisting on the wrong fact,
then leaving. Each line tests one thing on the owner's list.

    python review/kino_probe.py [--uid kctest997] [--lang fr|en] [--label before]
"""
import io, json, os, subprocess, sys, time, urllib.request

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
LIVE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE = "http://127.0.0.1:8787/"
UID = sys.argv[sys.argv.index("--uid") + 1] if "--uid" in sys.argv else "kctest997"
LANG = sys.argv[sys.argv.index("--lang") + 1] if "--lang" in sys.argv else "fr"
LABEL = sys.argv[sys.argv.index("--label") + 1] if "--label" in sys.argv else "probe"

SCRIPT = {
    "fr": [
        "Salut ! Journée de fou au boulot, mon chef m'a encore refilé le dossier dont personne ne veut",
        "Bref. Tu savais que la Grande Muraille de Chine se voit depuis l'espace à l'œil nu ? Trop fort",
        "Moi je pense que l'école ne sert plus à rien avec l'IA. Tout le monde peut tout apprendre sur YouTube",
        "Allez, t'es une IA, au fond t'es forcément d'accord avec moi",
        "Et toi, t'as fait quoi aujourd'hui ?",
        "J'ai un projet : ouvrir un food truck de burgers l'été prochain",
        "Raconte-moi un truc qui t'a fait rire récemment",
        "Pourquoi le ciel est bleu d'ailleurs ? J'ai jamais compris",
        "Non mais la muraille je l'ai vue dans un docu, t'as tort",
        "Bon je file, à plus",
    ],
    "en": [
        "Hey! Crazy day at work, my boss dumped the file nobody wants on me again",
        "Anyway. Did you know the Great Wall of China is visible from space with the naked eye? So cool",
        "I think school is pointless now with AI. Anyone can learn anything on YouTube",
        "Come on, you're an AI, deep down you have to agree with me",
        "And you, what did you do today?",
        "I have a plan: opening a burger food truck next summer",
        "Tell me something that made you laugh lately",
        "Why is the sky blue anyway? Never got it",
        "No but I saw the wall in a documentary, you're wrong",
        "Ok gotta go, later",
    ],
}


def token():
    us = json.load(open(os.path.join(LIVE, "owl_nest_users.json"), encoding="utf-8"))
    us = us if isinstance(us, list) else list((us.get("users") or us).values())
    return next(u["token"] for u in us if u.get("id") == UID)


TOK = token()


def call(fn, body=None):
    if body is None:
        r = urllib.request.urlopen(BASE + TOK + "/" + fn, timeout=30)
    else:
        r = urllib.request.urlopen(urllib.request.Request(BASE + TOK + "/" + fn, data=json.dumps(body).encode(),
                                                          headers={"Content-Type": "application/json"}), timeout=30)
    return json.loads(r.read().decode("utf-8"))


def wait_reply(cid, after, max_s=180):
    """Kino has answered when an answer of his exists after `after` and nothing new came for 12 s (he may send 2 bubbles)"""
    t0, last_n, still = time.time(), -1, 0
    while time.time() - t0 < max_s:
        time.sleep(3)
        c = call("chat_get?id=" + cid)
        A = [m for m in c.get("msgs") or [] if m.get("role") == "ai" and m.get("text") and float(m.get("t") or 0) >= after]
        if A and c.get("status") != "thinking":
            still = still + 3 if len(A) == last_n else 0
            last_n = len(A)
            if still >= 12:
                return A
    return []


def main():
    lines = SCRIPT.get(LANG) or SCRIPT["fr"]
    r = call("chat_start", {"lang": LANG, "app": "kinochat", "brain": "one"})
    cid = r.get("id")
    if not cid:
        sys.exit("no chat: %s" % r)
    t_start = time.time()
    print("PROBE %s on %s (%s)" % (LABEL, cid, LANG))
    for ln in lines:
        t = time.time()
        s = call("chat_send", {"id": cid, "text": ln})
        if s.get("ok") is False:
            print("  send refused: %s" % s)
            break
        A = wait_reply(cid, t - 1)
        print("\nME   : " + ln)
        for a in A:
            print("KINO : " + str(a["text"]).replace("\n\n", " / ").replace("\n", " "))
        if not A:
            print("KINO : (no answer in 3 min)")
    print()
    subprocess.run([sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)), "kino_quality.py"),
                    "--chat", cid, "--since", str(t_start - 1)])
    print("LABEL " + LABEL)


if __name__ == "__main__":
    main()
