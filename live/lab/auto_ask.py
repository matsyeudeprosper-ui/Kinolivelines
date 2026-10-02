"""A clue that is ready asks the chercheur by itself (owner 2026-10-02).

The clues ("pistes") are counted from the real trades every time the lab
loads: eleven fixed cuts, each labelled "pas assez de trades" (< 30),
"a verifier" (both halves of the period agree) or "pas net". Until now a
clue only became an idea if a person tapped "Demander au chercheur" on it.
This opens that ask automatically, signed "labo", for every clue that has
reached "a verifier" and has not been asked about - so the chain clue ->
idea -> test -> twin -> robot has nobody in it.

The chercheur's mission already makes it answer every open ask the same
night: a proposal to test, or a plain reason why not yet.

    python lab/auto_ask.py          # open the asks that are due
    python lab/auto_ask.py --dry    # say what it would do, write nothing

Runs from run_chercheur.ps1 after the researcher and before the session.
"""
import io
import json
import os
import sys
import time
from datetime import datetime, timezone

LAB = os.path.dirname(os.path.abspath(__file__))
LIVE = os.path.dirname(LAB)
ASKS = os.path.join(LAB, "asks.json")
REASK_DAYS = 14          # an answered clue may be asked again after this, with more trades
DRY = "--dry" in sys.argv


def _lj(p, d):
    try:
        return json.load(io.open(p, encoding="utf-8"))
    except Exception:
        return d


def _sj(p, obj):
    tmp = p + ".tmp"
    io.open(tmp, "w", encoding="utf-8").write(json.dumps(obj, ensure_ascii=False, indent=1))
    os.replace(tmp, p)


def due(cands, asks, today):
    """The clues to ask about tonight: ready, and not already in the
    chercheur's hands."""
    out = []
    for c in cands:
        if c.get("label") != "a_tester":
            continue
        mine = sorted((a for a in asks if a.get("seed") == c.get("id")), key=lambda a: a.get("date", ""))
        last = mine[-1] if mine else None
        if last and last.get("status") in ("open", "proposed"):
            continue
        if last and last.get("status") == "answered":
            try:
                age = (datetime.strptime(today, "%Y-%m-%d") - datetime.strptime(last.get("date", today), "%Y-%m-%d")).days
            except Exception:
                age = 0
            if age < REASK_DAYS:
                continue
        out.append(c)
    return out


def main():
    sys.path.insert(0, LIVE)
    import owl_app_server as S          # the same cuts the lab shows
    cands = S.lab_candidates(S._journal_unique())
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    doc = _lj(ASKS, {"asks": []})
    asks = doc.setdefault("asks", [])
    todo = due(cands, asks, today)
    ready = [c["id"] for c in cands if c.get("label") == "a_tester"]
    print(f"clues: {len(cands)}, ready: {ready or 'none'}, to ask tonight: {[c['id'] for c in todo] or 'none'}")
    if DRY or not todo:
        return 0
    for c in todo:
        asks.append({"id": f"ask_{int(time.time())}_{c['id']}", "seed": c["id"],
                     "seed_fr": c.get("name_fr", c["id"]), "seed_en": c.get("name_en", c["id"]),
                     "by": "labo", "date": today,
                     "note": (f"{c.get('n')} trades, {c.get('win')} % gagnés contre {c.get('rest_win')} % pour les autres ; "
                              f"les deux moitiés sont d’accord."),
                     "status": "open"})
        print(f"asked: {c['id']} ({c.get('n')} trades, {c.get('win')} % vs {c.get('rest_win')} %)")
    _sj(ASKS, doc)
    return 0


if __name__ == "__main__":
    sys.exit(main())
