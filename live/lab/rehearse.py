"""The rehearsal (2026-10-03, owner): the chain past "testee" - twin wins
its duel -> goes into the lab's robot -> is watched -> comes back out or
is confirmed -> the brake - had never fired for real. Every night, before
the judge runs, this drives one pretend winner through every gate in a
SANDBOX (copies of the files, a recorder instead of the bot restart) and
writes lab/rehearsal.json: which gate fired, which did not. A gate that
stops firing is reported the same night, not the night a real idea
needs it.

    python lab/rehearse.py          # run, write lab/rehearsal.json, exit 1 on a miss
"""
import io
import json
import os
import shutil
import sys
import tempfile
import time
from datetime import datetime, timezone

LAB = os.path.dirname(os.path.abspath(__file__))
LIVE = os.path.dirname(LAB)
sys.path.insert(0, LAB)
sys.path.insert(0, LIVE)
import twin_judge as TJ  # noqa: E402

OUT = os.path.join(LAB, "rehearsal.json")
REAL_QUEUE = TJ.QUEUE
NOW = time.time()
DAY = 86400.0
MIDNIGHT = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0).timestamp()


def _sj(p, obj):
    io.open(p, "w", encoding="utf-8").write(json.dumps(obj, ensure_ascii=False, indent=1))


def _lj(p, d):
    try:
        return json.load(io.open(p, encoding="utf-8"))
    except Exception:
        return d


class Box:
    """Everything the judge touches, redirected into one temp folder."""

    def __init__(self):
        self.dir = tempfile.mkdtemp(prefix="owl_rehearse_")
        self.restarts = 0
        self.kills = []
        self.real = []
        shutil.copy(os.path.join(LIVE, "owl_packages.json"), os.path.join(self.dir, "owl_packages.json"))
        TJ.LAB = self.dir
        TJ.PKG_FILE = os.path.join(self.dir, "owl_packages.json")
        TJ.TWINS = os.path.join(self.dir, "twins.json")
        TJ.DEC = os.path.join(self.dir, "decisions.json")
        TJ.REQ = os.path.join(self.dir, "requests.json")
        TJ.SEEN = os.path.join(self.dir, "events_seen.json")
        TJ.QUEUE = os.path.join(self.dir, "queue.json")
        TJ.PAUSE = os.path.join(self.dir, "pause.json")
        TJ.LABO_JOURNAL = os.path.join(self.dir, "bos_journal_labo.csv")
        TJ._restart_labo = self._restart
        TJ._kill_twin = self._kill
        TJ._real_rows = lambda since: [dict(r) for r in self.real if r["t"] >= since]
        TJ._strategy_uids = lambda: []
        _sj(TJ.TWINS, {"twins": []})
        _sj(TJ.DEC, {"decisions": {}})
        _sj(TJ.REQ, {"requests": []})

    def _restart(self):
        self.restarts += 1
        return ""

    def _kill(self, tid):
        self.kills.append(tid)

    def pkg(self):
        return _lj(TJ.PKG_FILE, {})["packages"][TJ.LABO_PKG]

    def twins(self):
        return _lj(TJ.TWINS, {"twins": []})["twins"]

    def decisions(self):
        return _lj(TJ.DEC, {"decisions": {}})["decisions"]

    def pushes(self):
        return [q.get("title", "") for q in _lj(TJ.QUEUE, [])]

    def clear_pushes(self):
        _sj(TJ.QUEUE, [])

    def twin(self, tid, cfg, n=30, net=40.0, worst=5.0, days_ago=20):
        """A running twin with `n` pretend trades: `net` in all, a hole of
        `worst` on the way. Its state file sits where the judge looks."""
        started = datetime.fromtimestamp(NOW - days_ago * DAY, timezone.utc).isoformat()
        doc = _lj(TJ.TWINS, {"twins": []})
        doc["twins"].append({"id": tid, "title_fr": "Essai " + tid, "title_en": "Trial " + tid, "cfg": dict(cfg, lot=0.02),
                             "verdict": "A", "started": started, "status": "running", "by": "chercheur"})
        _sj(TJ.TWINS, doc)
        _sj(os.path.join(self.dir, f"twin_{tid}_state.json"), {"trades": _series(n, net, worst, NOW - days_ago * DAY)})

    def real_rows(self, n=15, net=10.0, worst=8.0, days_ago=20):
        self.real = [{"t": x["t_close"], "pnl": x["pnl"], "lot": 0.02}
                     for x in _series(n, net, worst, NOW - days_ago * DAY)]

    def labo_journal(self, n, net, worst):
        # the watch starts at the deploy DATE (midnight UTC), so the
        # pretend trades of the lab's robot all fall inside today
        rows = _series(n, net, worst, MIDNIGHT)
        with io.open(TJ.LABO_JOURNAL, "w", encoding="utf-8", newline="") as f:
            f.write("entry_time_utc,exit_time_utc,is_add,lot,profit_usd\n")
            for r in rows:
                tx = datetime.fromtimestamp(r["t_close"], timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                f.write(f"{tx},{tx},False,0.02,{r['pnl']:.2f}\n")

    def close(self):
        shutil.rmtree(self.dir, ignore_errors=True)


def _series(n, net, worst, t0):
    """n closes, evenly spaced from t0 to now, that go down `worst` first
    and finish at `net`."""
    out = []
    span = max(1.0, NOW - t0 - 60)
    down = max(1, min(n // 3, n - 1)) if worst > 0 else 0
    rest = n - down
    for i in range(n):
        if i < down:
            pnl = -worst / down
        else:
            pnl = (net + worst) / rest
        out.append({"t_close": t0 + 60 + span * (i + 1) / n, "pnl": round(pnl, 2)})
    return out


def run():
    steps = []
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    def step(sid, fr, en, ok, detail=""):
        steps.append({"id": sid, "fr": fr, "en": en, "ok": bool(ok), "detail": str(detail)[:200]})

    # A. a twin wins its duel -> goes in
    B = Box()
    try:
        B.real_rows()
        B.twin("reh_win", {"rr": 0.9})
        TJ.judge()
        pk, tw = B.pkg(), B.twins()[0]
        ok = (tw.get("status") == "deployed" and pk.get("rr") == 0.9 and (pk.get("_deployed") or {}).get("id") == "reh_win"
              and "rr" in (pk.get("_previous") or {}) and B.restarts == 1 and B.kills == ["reh_win"]
              and B.decisions().get("reh_win", {}).get("d") == "yes" and any("entrée dans le robot" in t for t in B.pushes()))
        step("deploy", "Une idée gagne son duel et entre dans le robot du labo",
             "An idea wins its duel and goes into the lab’s robot", ok,
             f"status={tw.get('status')} rr={pk.get('rr')} previous={pk.get('_previous')} restarts={B.restarts} pushes={B.pushes()}")
        # B. watched, too early
        B.clear_pushes()
        TJ.judge()
        w = B.pkg().get("_watch") or {}
        step("watch_early", "Le robot du labo est surveillé dès le premier jour",
             "The lab’s robot is watched from day one", w.get("status") == "early" and w.get("id") == "reh_win",
             f"watch={w}")
        # C. behind the real robot -> the previous dials come back
        B.labo_journal(30, -20.0, 30.0)
        B.real = [dict(r, t=MIDNIGHT + 30 + i) for i, r in enumerate(B.real)]   # the real trades fall inside the watch window (today)
        TJ.judge()
        pk = B.pkg()
        ok = (pk.get("rr") != 0.9 and not pk.get("_deployed") and (pk.get("_reverted") or {}).get("id") == "reh_win"
              and B.restarts == 2 and B.twins()[0].get("status") == "reverted"
              and B.decisions().get("reh_win", {}).get("d") == "no" and any("ressortie" in t for t in B.pushes()))
        step("revert", "Derrière le vrai robot après 30 trades : les réglages d’avant reviennent tout seuls",
             "Behind the real robot after 30 trades: the previous dials come back by themselves", ok,
             f"rr={pk.get('rr')} reverted={(pk.get('_reverted') or {}).get('id')} restarts={B.restarts} status={B.twins()[0].get('status')} pushes={B.pushes()}")
    finally:
        B.close()

    # D. ahead in the robot -> confirmed, said once
    B = Box()
    try:
        B.real_rows()
        B.twin("reh_conf", {"rr": 0.9})
        TJ.judge()
        B.clear_pushes()
        B.labo_journal(30, 50.0, 3.0)
        B.real = [dict(r, t=MIDNIGHT + 30 + i) for i, r in enumerate(B.real)]
        TJ.judge()
        pk = B.pkg()
        first = pk.get("_confirmed") == today and pk.get("rr") == 0.9 and any("confirmée" in t for t in B.pushes())
        B.clear_pushes()
        TJ.judge()
        step("confirm", "Devant le vrai robot après 30 trades : confirmée, dit une seule fois",
             "Ahead of the real robot after 30 trades: confirmed, said once", first and not B.pushes(),
             f"confirmed={pk.get('_confirmed')} rr={pk.get('rr')} second_pushes={B.pushes()}")
    finally:
        B.close()

    # E. a dial the robot does not have -> the builder is asked, nothing goes in
    B = Box()
    try:
        B.real_rows()
        B.twin("reh_dial", {"wait_min": 10})
        TJ.judge()
        pk, tw = B.pkg(), B.twins()[0]
        rq = _lj(TJ.REQ, {"requests": []})["requests"]
        ok = (not pk.get("_deployed") and tw.get("deploy_failed") and B.restarts == 0
              and any(r.get("id") == "bot_wait_min" and r.get("by") == "labo" for r in rq)
              and any("ne peut pas entrer" in t for t in B.pushes()))
        step("missing_dial", "Un réglage que le robot n’a pas : rien n’entre, le constructeur est demandé",
             "A dial the robot lacks: nothing goes in, the builder is asked", ok,
             f"deploy_failed={tw.get('deploy_failed')} requests={[r.get('id') for r in rq]} restarts={B.restarts}")
    finally:
        B.close()

    # F. the brake: on -> a winner waits; an idea inside comes back out; off -> it goes in
    B = Box()
    try:
        B.real_rows()
        TJ.set_pause(True)
        B.twin("reh_brake", {"rr": 0.9})
        TJ.judge()
        pk, tw = B.pkg(), B.twins()[0]
        waits = (tw.get("status") == "running" and tw.get("waiting") == today and not pk.get("_deployed")
                 and B.restarts == 0 and any("attend" in t for t in B.pushes()))
        B.clear_pushes()
        TJ.judge()
        once = not B.pushes()
        step("brake_waits", "Frein tiré : une idée qui gagne attend, rien n’entre",
             "Brake on: a winner waits, nothing goes in", waits and once,
             f"status={tw.get('status')} waiting={tw.get('waiting')} deployed={pk.get('_deployed')} second_pushes={B.pushes()}")
        TJ.set_pause(False)
        TJ.judge()
        pk = B.pkg()
        went_in = (pk.get("_deployed") or {}).get("id") == "reh_brake" and B.restarts == 1
        B.clear_pushes()
        msg = TJ.set_pause(True)
        pk = B.pkg()
        out_again = (not pk.get("_deployed") and pk.get("rr") != 0.9 and (pk.get("_reverted") or {}).get("why") == "pause"
                     and B.restarts == 2 and B.twins()[0].get("status") == "paused" and any("pause" in t for t in B.pushes()))
        step("brake_out", "Frein relâché : elle entre ; frein tiré pendant qu’elle tourne : elle ressort",
             "Brake off: it goes in; brake on while it runs: it comes back out", went_in and out_again,
             f"went_in={went_in} msg={msg} rr={pk.get('rr')} restarts={B.restarts} pushes={B.pushes()}")
    finally:
        B.close()

    ok_all = all(s["ok"] for s in steps)
    doc = {"date": today, "t": datetime.now(timezone.utc).isoformat(timespec="seconds"), "ok": ok_all,
           "passed": sum(1 for s in steps if s["ok"]), "total": len(steps), "steps": steps}
    _sj(OUT, doc)
    for s in steps:
        print(("ok   " if s["ok"] else "MISS ") + s["id"] + ("" if s["ok"] else "  - " + s["detail"]))
    print(f"rehearsal: {doc['passed']}/{doc['total']}")
    if not ok_all:
        # Kino only, through the real queue (the sandboxes are gone)
        miss = [s["fr"] for s in steps if not s["ok"]]
        q = _lj(REAL_QUEUE, [])
        if not isinstance(q, list):
            q = []
        q.append({"uid": TJ.OWNER_UID, "t": int(time.time()),
                  "title": "⚠️ Le labo : un contrôle ne répond plus",
                  "body": ("La répétition de cette nuit a trouvé une porte qui ne se ferme plus : " + " ; ".join(miss))[:220]})
        _sj(REAL_QUEUE, q)
    return 0 if ok_all else 1


if __name__ == "__main__":
    sys.exit(run())
