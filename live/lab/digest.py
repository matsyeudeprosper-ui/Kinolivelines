"""The week in five lines (2026-10-03, owner): on Sunday night the lab
tells what it learned this week - ideas tested, what died, what runs,
what the builder delivered, what the researcher now holds - as a card on
the Labo and one push. The owner forgets across weeks; the lab must not.

    python lab/digest.py            # write lab/digest.json + push
    python lab/digest.py --dry      # print only
"""
import io
import json
import os
import sys
from datetime import datetime, timezone, timedelta

LAB = os.path.dirname(os.path.abspath(__file__))
LIVE = os.path.dirname(LAB)
OUT = os.path.join(LAB, "digest.json")
DRY = "--dry" in sys.argv


def _lj(name, d):
    try:
        return json.load(io.open(os.path.join(LAB, name), encoding="utf-8"))
    except Exception:
        return d


def _in(d, start, end):
    d = str(d or "")[:10]
    return bool(d) and start <= d <= end


def _t(x, en):
    return (x.get("title_en") or x.get("title_fr") or x.get("id") or "") if en else (x.get("title_fr") or x.get("title_en") or x.get("id") or "")


def _lower(s):
    return s[:1].lower() + s[1:] if s else s


def build(today=None):
    today = today or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    start = (datetime.strptime(today, "%Y-%m-%d") - timedelta(days=6)).strftime("%Y-%m-%d")
    # 1. verdicts of the week: every id tested, its best verdict
    best = {}
    try:
        for ln in io.open(os.path.join(LAB, "auto_history.jsonl"), encoding="utf-8").read().splitlines():
            try:
                r = json.loads(ln)
            except Exception:
                continue
            if not _in(r.get("d"), start, today):
                continue
            v = r.get("verdict") or "C"
            rank = {"A": 3, "B": 2}.get(v, 1)
            if rank > best.get(r.get("id"), 0):
                best[r.get("id")] = rank
    except Exception:
        pass
    nA = sum(1 for v in best.values() if v == 3)
    nB = sum(1 for v in best.values() if v == 2)
    # 2. the researcher's new ideas
    props = [p for p in _lj("proposals.json", {}).get("proposals", []) if _in(p.get("date"), start, today)]
    # 3. twins and the lab's robot
    tw = _lj("twins.json", {}).get("twins", [])
    started = [t for t in tw if _in(t.get("started"), start, today)]
    lost = [t for t in tw if _in(t.get("stopped"), start, today) and t.get("reason") == "duel_lost"]
    went_in = [t for t in tw if _in(t.get("deployed"), start, today)]
    came_out = [t for t in tw if _in(t.get("reverted"), start, today)]
    retired = [t for t in tw if _in(t.get("retired"), start, today) and t.get("status") == "retired"]
    pk = {}
    try:
        pk = json.load(io.open(os.path.join(LIVE, "owl_packages.json"), encoding="utf-8"))["packages"].get("labo") or {}
    except Exception:
        pass
    inside = pk.get("_deployed")
    # 4. builder and critic
    rq = _lj("requests.json", {}).get("requests", [])
    built = [r for r in rq if r.get("status") == "built" and _in(r.get("built_date"), start, today)]
    declined = [r for r in rq if r.get("status") == "declined" and _in(r.get("date"), start, today)]
    cr = _lj("critiques.json", {})
    cr = cr.get("critiques", cr) if isinstance(cr, dict) else cr
    blocked = [c for c in (cr or []) if isinstance(c, dict) and c.get("verdict") == "bloque" and _in(c.get("date"), start, today)]
    # 5. what the researcher holds (the latest night's first belief)
    N = _lj("chercheur_latest.json", {})
    bel = (N.get("beliefs") or [{}])[0] if N.get("beliefs") else {}
    nights = len([f for f in os.listdir(os.path.join(LAB, "notes")) if start <= f[:10] <= today]) if os.path.isdir(os.path.join(LAB, "notes")) else 0

    def lines(en):
        L = []
        n = len(best)
        if n:
            L.append((f"This week the lab tested {n} ideas over {nights} nights: {nA} better on both halves, {nB} a little better, {n - nA - nB} no."
                      if en else f"Cette semaine le labo a testé {n} idées en {nights} nuits : {nA} mieux sur les deux moitiés, {nB} un peu mieux, {n - nA - nB} non."))
        else:
            L.append("This week the lab had no night run." if en else "Cette semaine le labo n’a pas eu de nuit.")
        if props:
            ex = " ; ".join("« " + _t(p, en) + " »" for p in props[:2])
            L.append((f"The researcher proposed {len(props)} new idea{'s' if len(props) > 1 else ''}, e.g. {ex}."
                      if en else f"Le chercheur a proposé {len(props)} nouvelle{'s' if len(props) > 1 else ''} idée{'s' if len(props) > 1 else ''}, par exemple {ex}."))
        else:
            L.append("The researcher proposed no new idea." if en else "Le chercheur n’a proposé aucune nouvelle idée.")
        if started or lost or went_in or came_out or retired:
            bits = []
            if started:
                bits.append((f"{len(started)} twin{'s' if len(started) > 1 else ''} started" if en else f"{len(started)} jumeau{'x' if len(started) > 1 else ''} lancé{'s' if len(started) > 1 else ''}"))
            if retired:
                bits.append((f"{len(retired)} set aside by Kino" if en else f"{len(retired)} mis de côté par Kino"))
            if lost:
                bits.append((f"{len(lost)} lost the duel" if en else f"{len(lost)} a perdu le duel" if len(lost) == 1 else f"{len(lost)} ont perdu le duel"))
            if went_in:
                bits.append((f"{len(went_in)} went into the lab’s robot" if en else f"{len(went_in)} entrée{'s' if len(went_in) > 1 else ''} dans le robot du labo"))
            if came_out:
                bits.append((f"{len(came_out)} came back out" if en else f"{len(came_out)} ressortie{'s' if len(came_out) > 1 else ''}"))
            L.append(("Twins: " if en else "Jumeaux : ") + ", ".join(bits) + ".")
        elif inside:
            L.append((f"The lab’s robot is trying « {_t(inside, en)} » since {inside.get('date')}." if en
                      else f"Le robot du labo essaie « {_t(inside, en)} » depuis le {inside.get('date')}."))
        else:
            L.append("No twin this week: no idea held two nights in a row." if en else "Aucun jumeau cette semaine : aucune idée n’a tenu deux nuits de suite.")
        if built or declined or blocked:
            bits = []
            if built:
                bits.append((f"the builder delivered {', '.join('« ' + _t(r, en) + ' »' for r in built[:2])}" if en
                             else f"le constructeur a livré {', '.join('« ' + _t(r, en) + ' »' for r in built[:2])}"))
            if declined:
                bits.append((f"declined {len(declined)}" if en else f"en a décliné {len(declined)}"))
            if blocked:
                bits.append((f"the critic said no to {len(blocked)}" if en else f"le critique a dit non à {len(blocked)}"))
            s = " ; ".join(bits)
            L.append(s[:1].upper() + s[1:] + ".")
        else:
            L.append("The builder and the critic had nothing to do." if en else "Le constructeur et le critique n’ont rien eu à faire.")
        b = (bel.get("en") or bel.get("fr")) if en else (bel.get("fr") or bel.get("en"))
        if b:
            L.append(("What the researcher now holds: " if en else "Ce que le chercheur tient maintenant : ") + _lower(str(b).strip()))
        return L

    return {"week_end": today, "from": start, "t": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "fr": lines(False), "en": lines(True),
            "counts": {"tested": len(best), "A": nA, "B": nB, "proposals": len(props), "twins_started": len(started),
                       "twins_lost": len(lost), "went_in": len(went_in), "came_out": len(came_out), "built": len(built)}}


def main():
    d = build()
    for x in d["fr"]:
        print("-", x)
    if DRY:
        return 0
    tmp = OUT + ".tmp"
    io.open(tmp, "w", encoding="utf-8").write(json.dumps(d, ensure_ascii=False, indent=1))
    os.replace(tmp, OUT)
    try:
        sys.path.insert(0, LAB)
        import twin_judge as TJ
        TJ.emit("digest",
                ("\U0001f4d2 Le labo : la semaine en cinq lignes", (d["fr"][0] + " " + d["fr"][1])[:220]),
                ("\U0001f4d2 The lab: the week in five lines", (d["en"][0] + " " + d["en"][1])[:220]), members=True)
    except Exception as e:
        print("push:", e)
    return 0


if __name__ == "__main__":
    sys.exit(main())
