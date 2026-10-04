"""Kino numérique's alarm clock (owner 2026-10-02: "busy throughout the day,
working for me constantly, because that's literally what I do all day").

Runs every 30 minutes from the OwlNestVeille task. Decides whether the
chercheur should wake for a short watch, and if so prepares what it will
find, runs the session, and puts the lab's files in git afterwards.

Wake when something happened - a real trade closed, a twin's score moved,
the lab's robot took or dropped an idea, an ask is waiting - or when four
hours passed with nothing. Never during the night run, never twice within
ninety minutes, never more than six times a day.

    python lab/wake.py            # decide, and wake if due
    python lab/wake.py --dry      # say what it would do
    python lab/wake.py --force    # wake now (still respects the night lock)
"""
import io
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone

LAB = os.path.dirname(os.path.abspath(__file__))
LIVE = os.path.dirname(LAB)
STATE = os.path.join(LAB, "veille_state.json")
CONTEXT = os.path.join(LAB, "wake_context.json")
VEILLE = os.path.join(LAB, "veille.jsonl")
NIGHT_LOCK = os.path.join(LAB, "night.lock")
LOG = os.path.join(LAB, "veille.log")
MISSION = os.path.join(LAB, "VEILLE.md")
MAX_PER_DAY = 6         # 2026-10-04 (owner): woken by the trades, at most six looks a day
MIN_GAP = 60 * 60       # one look per hour at most - a burst of trades is one look
MAX_GAP = 12 * 3600     # a dead day still gets one look
QUIET_LOCAL = (3, 7)        # the night run owns 03:30-06:30 local
TURNS = 20              # a look, not a study: the night run is the deep one
A = sys.argv[1:]
DRY, FORCE = "--dry" in A, "--force" in A


def say(m):
    line = f"{datetime.now(timezone.utc).isoformat(timespec='seconds')} {m}"
    print(line, flush=True)
    try:
        io.open(LOG, "a", encoding="utf-8").write(line + "\n")
    except Exception:
        pass


def _lj(p, d):
    try:
        return json.load(io.open(p, encoding="utf-8"))
    except Exception:
        return d


def _sj(p, obj):
    tmp = p + ".tmp"
    io.open(tmp, "w", encoding="utf-8").write(json.dumps(obj, ensure_ascii=False, indent=1))
    os.replace(tmp, p)


def signals(state):
    """What is new since the last watch, in the chercheur's words."""
    sys.argv = ["wake"]
    sys.path.insert(0, LIVE)
    import owl_app_server as S
    J = S._journal_unique()
    last_x = float(state.get("last_trade_x") or 0)
    new_trades = [r for r in J if r["x"] > last_x]
    twins = []
    for t in _lj(os.path.join(LAB, "twins.json"), {"twins": []}).get("twins", []):
        if t.get("status") not in ("running", "deployed"):
            continue
        st = _lj(os.path.join(LAB, f"twin_{t.get('id')}_state.json"), {})
        tr = [x for x in (st.get("trades") or []) if isinstance(x, dict) and x.get("t_close")]
        twins.append({"id": t.get("id"), "title_fr": t.get("title_fr"), "status": t.get("status"),
                      "trades": len(tr), "net": round(sum(float(x.get("pnl") or 0) for x in tr), 2)})
    twins_sig = ";".join(f"{t['id']}:{t['status']}:{t['trades']}" for t in twins)
    pk = (_lj(os.path.join(LIVE, "owl_packages.json"), {}).get("packages") or {}).get("labo") or {}
    labo = {k: pk.get(k) for k in ("_deployed", "_confirmed", "_reverted", "_watch") if pk.get(k)}
    labo_sig = json.dumps({k: v for k, v in labo.items() if k != "_watch"}, sort_keys=True)
    asks_open = [a for a in _lj(os.path.join(LAB, "asks.json"), {"asks": []}).get("asks", []) if a.get("status") == "open"]
    reasons = []
    if new_trades:
        reasons.append(f"{len(new_trades)} vrai(s) trade(s) fermé(s)")
    if twins_sig != state.get("twins_sig", "") and twins:
        reasons.append("le score d’un jumeau a bougé")
    if labo_sig != state.get("labo_sig", "{}"):
        reasons.append("le robot du labo a pris ou lâché une idée")
    if len(asks_open) > int(state.get("asks_open") or 0):
        reasons.append(f"{len(asks_open)} demande(s) en attente")
    last_obs = []
    if os.path.exists(VEILLE):
        for ln in io.open(VEILLE, encoding="utf-8").read().splitlines()[-5:]:
            try:
                last_obs.append(json.loads(ln))
            except Exception:
                pass
    ctx = {"now": datetime.now(timezone.utc).isoformat(timespec="seconds"), "reasons": reasons,
           "new_trades": [{"closed": datetime.fromtimestamp(r["x"], timezone.utc).strftime("%Y-%m-%d %H:%M"),
                           "dir": r["dir"], "kind": r["kind"], "won": r["win"], "money": r["p"],
                           "pace": r["nerv"]} for r in new_trades[-12:]],
           "twins": twins, "labo": labo, "asks_open": asks_open[-6:],
           "last_observations": last_obs, "trades_total": len(J)}
    nxt = dict(state, last_trade_x=(J[-1]["x"] if J else last_x), twins_sig=twins_sig, labo_sig=labo_sig, asks_open=len(asks_open))
    return reasons, ctx, nxt


def decide(state, reasons, now):
    today = datetime.now().strftime("%Y-%m-%d")
    count = int(state.get("count") or 0) if state.get("day") == today else 0
    last = float(state.get("last_wake") or 0)
    h = datetime.now().hour
    if os.path.exists(NIGHT_LOCK) or QUIET_LOCAL[0] <= h < QUIET_LOCAL[1]:
        return False, "la nuit travaille"
    lock = state.get("lock") or {}
    if lock and now - float(lock.get("t") or 0) < 3600:
        return False, "une veille est en cours"
    if count >= MAX_PER_DAY:
        return False, f"{MAX_PER_DAY} veilles aujourd’hui, assez"
    if FORCE:
        return True, "forcé"
    if now - last >= MAX_GAP:
        return True, "douze heures sans regarder"
    if reasons and now - last >= MIN_GAP:
        return True, " ; ".join(reasons)
    if reasons:
        return False, "trop tôt depuis la dernière veille (" + " ; ".join(reasons) + ")"
    return False, "rien de neuf"


def run_session(ctx):
    claude = os.path.join(os.environ.get("USERPROFILE", ""), ".local", "bin", "claude.exe")
    mission = io.open(MISSION, encoding="utf-8").read()
    mission += ("\n\nNow is " + ctx["now"] + ". You were woken because: " + ("; ".join(ctx["reasons"]) or "four hours passed") +
                ". Read lab/wake_context.json first. Begin.")
    try:
        # 2026-10-04 (owner): the model falls back by itself when the usual one is out (claude_run)
        sys.path.insert(0, LAB)
        from claude_run import run as _crun
        rc, out, model = _crun(mission, turns=TURNS, cwd=LIVE, timeout=1500, log=os.path.join(LAB, "veille_last.log"), who="la veille")
        if model:
            say(f"model fallback: {model}")
        return rc, len(out or "")
    except Exception as e:
        return -1, str(e)


def after():
    try:
        r = subprocess.run(["python", "lab/twin_judge.py", "--post"], cwd=LIVE, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=600)
        io.open(os.path.join(LAB, "judge_day_last.log"), "w", encoding="utf-8").write((r.stdout or "") + (r.stderr or ""))
    except Exception as e:
        say(f"judge failed: {e}")
    try:
        files = ["lab/veille.jsonl", "lab/memoire.json", "lab/cuts.json", "lab/proposals.json", "lab/asks.json",
                 "lab/requests.json", "lab/metrics.json", "lab/veille_state.json"]
        subprocess.run(["git", "add"] + files, cwd=LIVE, capture_output=True, timeout=60)
        msg = "veille: " + datetime.now().strftime("%Y-%m-%d %H:%M") + "\n\nCo-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
        subprocess.run(["git", "commit", "-q", "-m", msg], cwd=LIVE, capture_output=True, timeout=60)
        subprocess.run(["git", "push", "-q"], cwd=LIVE, capture_output=True, timeout=120)
    except Exception as e:
        say(f"git failed: {e}")


def main():
    now = time.time()
    state = _lj(STATE, {})
    reasons, ctx, nxt = signals(state)
    go, why = decide(state, reasons, now)
    say(("WAKE " if go else "sleep ") + why + (" [dry]" if DRY else ""))
    if DRY or not go:
        return 0
    today = datetime.now().strftime("%Y-%m-%d")
    nxt.update(lock={"pid": os.getpid(), "t": now}, day=today,
               count=(int(state.get("count") or 0) + 1) if state.get("day") == today else 1)
    _sj(STATE, nxt)
    _sj(CONTEXT, ctx)
    for cmd in (["python", "lab/scrutiny.py", "--write"], ["python", "lab/auto_ask.py"]):
        try:
            subprocess.run(cmd, cwd=LIVE, capture_output=True, timeout=600)
        except Exception as e:
            say(f"{cmd[1]} failed: {e}")
    rc, n = run_session(ctx)
    say(f"session done rc={rc} out={n}")
    after()
    nxt = _lj(STATE, nxt)
    nxt["last_wake"] = time.time()
    nxt.pop("lock", None)
    _sj(STATE, nxt)
    say("watch over")
    return 0


if __name__ == "__main__":
    sys.exit(main())
