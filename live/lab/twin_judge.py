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
# 2026-10-02 (owner): a winner deploys itself to the lab's own demo account.
# PKG_FILE is the same file every bot reads its dials from; LABO_PKG is the
# package only this account uses, so nothing else can be reached from here.
PKG_FILE = os.path.join(LIVE, "owl_packages.json")
LABO_PKG = "labo"
LABO_VARIANT = "labo"
# The dials a bot can actually express. A winning cfg that needs anything
# else is not deployable, and saying so is the honest outcome - the harness
# knows ~37 dials and the bot has these.
BOT_DIALS = {"rr", "k_streak", "lot", "bullets", "day_cap", "kill_net",
             "risk_pct", "jar", "nerv_gate", "debt_mode", "max_trades_day",
             "movement", "internal"}
# harness dial -> the package field that carries it
TO_PKG = {"rr": "rr", "k_streak": "k_streak", "lot": "base_lot",
          "bullets": "max_extra", "day_cap": "day_cap", "kill_net": "kill_net",
          "risk_pct": "max_risk_pct", "jar": "jar", "nerv_gate": "nervosity",
          "debt_mode": "debt_mode", "max_trades_day": "max_trades_day",
          "movement": "movement", "internal": "internal_entries"}


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


def _base_cfg():
    try:
        sys.path.insert(0, os.path.join(LIVE, "lab"))
        import harness as H
        return dict(H.CFG_BASE)
    except Exception:
        return {}


def deploy(tid, cfg, fr, en):
    """Write a winning idea's dials into the labo package and restart that
    bot. Returns (ok, message). Never touches another account."""
    base = _base_cfg()
    diff = {k: v for k, v in (cfg or {}).items()
            if k in base and v != base[k]}
    if not diff:
        return False, "rien a changer"
    missing = sorted(set(diff) - BOT_DIALS)
    if missing:
        return False, "le robot n'a pas de reglage pour " + ", ".join(missing)
    raw = _lj(PKG_FILE, None)
    if not raw or LABO_PKG not in (raw.get("packages") or {}):
        return False, "paquet labo introuvable"
    pk = raw["packages"][LABO_PKG]
    # Keep what we are replacing, so an undo is one edit and not a memory.
    # The RESOLVED value, not pk.get(): a package that inherits a dial has
    # no key of its own, and writing that None back on an undo would stop
    # the bot at import (float(None)).
    try:
        sys.path.insert(0, LIVE)
        import owl_package as _PK
        _PK._cache = {"t": 0.0, "raw": None, "err": None}
        _eff = _PK.for_account(LABO_PKG)
    except Exception:
        _eff = {}
    pk["_previous"] = {TO_PKG[k]: _eff.get(TO_PKG[k], pk.get(TO_PKG[k])) for k in diff}
    pk["_deployed"] = {"id": tid, "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                       "title_fr": fr, "title_en": en}
    for k, v in diff.items():
        pk[TO_PKG[k]] = v
    _sj(PKG_FILE, raw)
    # a bot resolves its package ONCE at import, so a restart is the deploy
    try:
        subprocess.Popen(["powershell", "-NoProfile", "-Command",
                          "Get-CimInstance Win32_Process | Where-Object { $_.Name -like 'python*' -and $_.CommandLine -like '*structure_bos_bot.py " + LABO_VARIANT + "*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"],
                         creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).wait(30)
    except Exception:
        pass
    try:
        exe = sys.executable.replace("python.exe", "pythonw.exe")
        subprocess.Popen([exe, os.path.join(LIVE, "structure_bos_bot.py"), LABO_VARIANT],
                         cwd=LIVE, creationflags=getattr(subprocess, "DETACHED_PROCESS", 0))
    except Exception as e:
        return False, f"redemarrage: {e}"
    return True, ", ".join(f"{TO_PKG[k]} {v}" for k, v in sorted(diff.items()))


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
        elif d["status"] == "ahead" and not t.get("deployed") and not t.get("deploy_failed"):
            # 2026-10-02 (owner): no decision waits here any more. It won its
            # duel, so it goes in - on the lab's demo account.
            ok, how = deploy(tid, (t.get("cfg") or {}), fr, en)
            changed = True
            if ok:
                t["deployed"] = today
                t["status"] = "deployed"
                dec.setdefault("decisions", {})[tid] = {
                    "d": "yes", "date": today, "by": "lab",
                    "note": f"le jumeau a gagne le duel ({d['twin']['net']:+.0f} $ contre {d['real']['net']:+.0f} $) et est entre dans le robot du labo"}
                _kill_twin(tid)
                emit("twin_deployed",
                     ("\U0001f680 Le labo : une idée est entrée dans le robot",
                      f"« {fr} » a battu le robot sur {n} trades ({d['twin']['net']:+.0f} $ contre {d['real']['net']:+.0f} $) et vient d’entrer dans le robot du labo, toute seule. Réglage : {how}. Argent de démonstration. Vos vrais comptes n’ont pas bougé."),
                     ("\U0001f680 The lab: an idea went into the robot",
                      f"“{en}” beat the robot over {n} trades ({d['twin']['net']:+.0f} $ vs {d['real']['net']:+.0f} $) and just went into the lab's robot by itself. Dial: {how}. Demo money. Your real accounts did not move."),
                     members=True)
            else:
                t["deploy_failed"] = how
                emit("twin_blocked",
                     ("\U0001f6e0 Le labo : une idée a gagné mais ne peut pas entrer",
                      f"« {fr} » a battu le robot ({d['twin']['net']:+.0f} $ contre {d['real']['net']:+.0f} $) mais ne peut pas être posée : {how}. Elle attend que le réglage existe."),
                     ("\U0001f6e0 The lab: an idea won but cannot go in",
                      f"“{en}” beat the robot ({d['twin']['net']:+.0f} $ vs {d['real']['net']:+.0f} $) but cannot be applied: {how}."),
                     members=False)
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
