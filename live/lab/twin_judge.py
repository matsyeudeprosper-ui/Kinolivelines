"""The lab's twin judge + the lab's messenger (2026-09-29, owner batch 34).

DUEL: every paper twin is measured against the REAL robot with brakes over
the same period - Valere's account (the frozen live config, lot 0.02, base
trades only, no boosts, because the twins do not boost). `duel(twin)` gives
both curves and where the twin stands; the app draws it.

RETIRE BY ITSELF (owner: "auto-delete what failed"): after 30 twin trades
and at least 15 real ones, a twin that is behind on money AND deeper in
its worst hole stops, its process is killed, and the decision is written
as "non, le jumeau a perdu le duel". A twin that is ahead with a hole no
deeper gets one push to Kino ("a decision is waiting").

MESSENGER: lab events go to the notifier's queue (owl_push_queue.json):
Kino gets everything; Strategie members get twin started / twin at 30
trades / a new dial request / an answered ask of theirs.

    python lab/twin_judge.py            # judge the running twins, push events
    python lab/twin_judge.py --post     # + after the chercheur session: new
                                        #   requests and answered asks
"""
import csv
import glob
import io
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone

LAB = os.path.dirname(os.path.abspath(__file__))
LIVE = os.path.dirname(LAB)
TWINS = os.path.join(LAB, "twins.json")
DEC = os.path.join(LAB, "decisions.json")
REQ = os.path.join(LAB, "requests.json")
ASKS = os.path.join(LAB, "asks.json")
SEEN = os.path.join(LAB, "events_seen.json")
QUEUE = os.path.join(LIVE, "owl_push_queue.json")
NEED = 30          # twin trades before the duel can be judged
NEED_REAL = 15
OWNER_UID = "std"


def _lj(p, d):
    try:
        return json.load(io.open(p, encoding="utf-8"))
    except Exception:
        return d


def _sj(p, obj):
    tmp = p + ".tmp"
    io.open(tmp, "w", encoding="utf-8").write(json.dumps(obj, ensure_ascii=False, indent=1))
    os.replace(tmp, p)


def _real_rows(since_ts):
    """Base trades of the real robot with brakes since `since_ts` (Valere's
    journal; every journal deduped if hers is missing)."""
    files = [os.path.join(LIVE, "bos_journal_valere.csv")]
    if not os.path.exists(files[0]):
        files = sorted(glob.glob(os.path.join(LIVE, "bos_journal*.csv")))
    seen = set()
    out = []
    for f in files:
        try:
            with open(f, encoding="utf-8", errors="replace") as fh:
                for r in csv.DictReader(fh):
                    if r.get("is_add") == "True" or not r.get("exit_time_utc"):
                        continue
                    key = (r["entry_time_utc"][:16], r["direction"])
                    if key in seen:
                        continue
                    seen.add(key)
                    tx = datetime.fromisoformat(r["exit_time_utc"].replace("Z", "+00:00")).timestamp()
                    if tx < since_ts:
                        continue
                    lot = float(r.get("lot") or 0.02) or 0.02
                    out.append({"t": tx, "pnl": float(r.get("profit_usd") or 0), "lot": lot})
        except Exception:
            continue
    return sorted(out, key=lambda x: x["t"])


def _curve(rows):
    cum, pk, worst = 0.0, 0.0, 0.0
    pts = []
    for r in rows:
        cum += r["pnl"]
        pk = max(pk, cum)
        worst = max(worst, pk - cum)
        pts.append([int(r["t"]), round(cum, 2)])
    return {"net": round(cum, 2), "worst": round(worst, 2), "trades": len(rows), "curve": pts}


def duel(tw):
    """tw = an entry of twins.json. Returns the duel record for the app."""
    try:
        since = datetime.fromisoformat(tw["started"]).timestamp()
    except Exception:
        since = 0
    st = _lj(os.path.join(LAB, f"twin_{tw.get('id')}_state.json"), {})
    tr = [{"t": float(t.get("t_close") or 0), "pnl": float(t.get("pnl") or 0)}
          for t in (st.get("trades") or []) if isinstance(t, dict) and t.get("t_close")]
    lot_tw = float((tw.get("cfg") or {}).get("lot") or 0.02) or 0.02
    real = _real_rows(since)
    for r in real:                       # same lot as the twin
        r["pnl"] = r["pnl"] * lot_tw / r["lot"]
    T, R = _curve(sorted(tr, key=lambda x: x["t"])), _curve(real)
    ready = T["trades"] >= NEED and R["trades"] >= NEED_REAL
    if T["trades"] == 0:
        status = "early"
    elif T["net"] > R["net"] and T["worst"] <= R["worst"] + 0.5:
        status = "ahead"
    elif T["net"] < R["net"] and T["worst"] > R["worst"] + 0.5:
        status = "behind"
    else:
        status = "even"
    return {"twin": T, "real": R, "need": NEED, "need_real": NEED_REAL, "ready": ready, "status": status,
            "since": tw.get("started")}


def _push(uid, title, body):
    q = _lj(QUEUE, [])
    if not isinstance(q, list):
        q = []
    q.append({"uid": uid, "t": int(time.time()), "title": title, "body": body})
    _sj(QUEUE, q)


def _strategy_uids():
    try:
        sys.path.insert(0, LIVE)
        import owl_app_server as S
        us = json.load(open(os.path.join(LIVE, "owl_nest_users.json"), encoding="utf-8"))
        return [u["id"] for u in us if S.has(u["id"], "strategy") and u["id"] != OWNER_UID]
    except Exception:
        return []


def _lang(uid):
    try:
        sys.path.insert(0, LIVE)
        import owl_app_server as S
        return S.member_lang(uid)
    except Exception:
        return "fr"


def emit(kind, fr, en, members=False):
    """One event -> Kino always; Strategie members when `members`."""
    _push(OWNER_UID, fr[0], fr[1])
    if members:
        for uid in _strategy_uids():
            t = en if _lang(uid) == "en" else fr
            _push(uid, t[0], t[1])
    try:
        with io.open(os.path.join(LAB, "events.jsonl"), "a", encoding="utf-8") as f:
            f.write(json.dumps({"t": int(time.time()), "kind": kind, "fr": fr[1], "en": en[1]}, ensure_ascii=False) + "\n")
    except Exception:
        pass


def _kill_twin(tid):
    try:
        subprocess.Popen(["powershell", "-NoProfile", "-Command",
                          "Get-CimInstance Win32_Process | Where-Object { $_.Name -like 'python*' -and $_.CommandLine -like '*bos_paper_variant.py " + tid + "*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"],
                         creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except Exception:
        pass


def judge():
    tw = _lj(TWINS, {"twins": []})
    dec = _lj(DEC, {"decisions": {}})
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    changed = False
    for t in tw.get("twins", []):
        if t.get("status") != "running":
            continue
        d = duel(t)
        tid, fr, en = t.get("id"), t.get("title_fr") or t.get("id"), t.get("title_en") or t.get("id")
        n = d["twin"]["trades"]
        if n >= NEED and not t.get("reached30"):
            t["reached30"] = today
            changed = True
            emit("twin_30", ("\U0001f52c Le labo : 30 trades pour un jumeau",
                             f"« {fr} » a joué 30 trades pour de faux. Jumeau {d['twin']['net']:+.0f} $, robot {d['real']['net']:+.0f} $ sur la même période."),
                 ("\U0001f52c The lab: a twin reached 30 trades",
                  f"“{en}” played 30 trades for pretend. Twin {d['twin']['net']:+.0f} $, robot {d['real']['net']:+.0f} $ over the same period."), members=True)
        if not d["ready"]:
            continue
        if d["status"] == "behind":
            t["status"] = "stopped"
            t["stopped"] = today
            t["reason"] = "duel_lost"
            dec.setdefault("decisions", {})[tid] = {"d": "no", "date": today, "by": "lab",
                                                    "note": f"le jumeau a perdu le duel ({d['twin']['net']:+.0f} $ contre {d['real']['net']:+.0f} $, trou {d['twin']['worst']:.0f} contre {d['real']['worst']:.0f})"}
            _kill_twin(tid)
            changed = True
            emit("twin_lost", ("\U0001f6d1 Le labo : un jumeau s’arrête",
                               f"« {fr} » a perdu le duel contre le robot ({d['twin']['net']:+.0f} $ contre {d['real']['net']:+.0f} $). Il est arrêté et gardé comme un non."),
                 ("\U0001f6d1 The lab: a twin stops",
                  f"“{en}” lost the duel against the robot ({d['twin']['net']:+.0f} $ vs {d['real']['net']:+.0f} $). Stopped and kept as a no."), members=True)
        elif d["status"] == "ahead" and not t.get("ahead_notified"):
            t["ahead_notified"] = today
            changed = True
            emit("twin_ahead", ("✅ Le labo : une décision vous attend",
                                f"« {fr} » est devant le robot après {n} trades ({d['twin']['net']:+.0f} $ contre {d['real']['net']:+.0f} $, trou pas plus profond). Approuver ou rejeter dans le labo."),
                 ("✅ The lab: a decision is waiting", ""), members=False)
    if changed:
        _sj(TWINS, tw)
        _sj(DEC, dec)
    return changed


def post_session():
    """After the chercheur wrote: new dial requests, answered asks."""
    seen = _lj(SEEN, {"requests": [], "asks_answered": []})
    rq = _lj(REQ, {"requests": []}).get("requests", [])
    for r in rq:
        if r.get("id") in seen["requests"]:
            continue
        seen["requests"].append(r.get("id"))
        emit("request", ("\U0001f527 Le labo : le chercheur demande un réglage",
                         f"« {r.get('title_fr') or r.get('id')} » — {(r.get('why_fr') or r.get('what_fr') or '')[:140]}"),
             ("\U0001f527 The lab: the chercheur asks for a dial",
              f"“{r.get('title_en') or r.get('id')}” — {(r.get('why_en') or r.get('what_en') or '')[:140]}"), members=True)
    asks = _lj(ASKS, {"asks": []}).get("asks", [])
    for a in asks:
        if a.get("status") != "answered" or a.get("id") in seen["asks_answered"]:
            continue
        seen["asks_answered"].append(a.get("id"))
        uid = a.get("by")
        if uid:
            en = _lang(uid) == "en"
            _push(uid, ("\U0001f4ac The chercheur answered you" if en else "\U0001f4ac Le chercheur vous a répondu"),
                  ((a.get("answer_en") or a.get("answer_fr") or "") if en else (a.get("answer_fr") or a.get("answer_en") or ""))[:180])
    _sj(SEEN, seen)


if __name__ == "__main__":
    ch = judge()
    print("judge: changed" if ch else "judge: nothing to change")
    if "--post" in sys.argv:
        post_session()
        print("post-session events sent")
    for t in _lj(TWINS, {"twins": []}).get("twins", []):
        d = duel(t)
        print(t.get("id"), t.get("status"), "twin", d["twin"]["net"], d["twin"]["trades"], "| real", d["real"]["net"], d["real"]["trades"], "|", d["status"], "ready" if d["ready"] else "")
