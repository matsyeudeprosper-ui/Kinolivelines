"""One way to run a headless Claude session for the lab (owner 2026-10-04:
"switch automatically to a lower model if the tokens are done, or while
waiting for Claude"). Tries the models in order; a run that fails for a
reason that smells like a limit or an outage (rate limit, usage limit,
overloaded, timeout, no output) is retried with the next, smaller model.
Every runner (night chercheur, day watch, critic, builder) goes through
here, so the rule lives in one place.

    from claude_run import run
    rc, out, model = run(mission, turns=30, tools=[...], cwd=LIVE, timeout=1500, log=path)

    python lab/claude_run.py --mission-file lab/CHERCHEUR.md --turns 140 --out lab/chercheur_last.log --suffix "Today is ... Begin."
"""
import io
import json
import os
import re
import subprocess
import sys
import time

LAB = os.path.dirname(os.path.abspath(__file__))
LIVE = os.path.dirname(LAB)
CLAUDE = os.path.join(os.environ.get("USERPROFILE", ""), ".local", "bin", "claude.exe")
# the default model first (whatever Claude Code is set to), then smaller ones
MODELS = [None, "sonnet", "haiku"]
TOOLS = ["Bash(python *)", "Read", "Write", "Edit", "Glob", "Grep"]
LIMIT_RE = re.compile(r"rate.?limit|usage limit|limit reached|out of (?:tokens|credits)|quota|overloaded|529|too many requests|"
                      r"capacity|try again later|temporarily unavailable|service unavailable|not available|"
                      r"api error|connection error|ECONNRESET|fetch failed|timed out", re.I)
MARK = os.path.join(LAB, "model_fallback.json")


def _looks_limited(rc, out, err):
    text = (out or "")[-4000:] + (err or "")[-4000:]
    if rc != 0 and LIMIT_RE.search(text):
        return True
    if rc != 0 and not (out or "").strip():
        return True                      # died before saying anything
    if LIMIT_RE.search(text) and len((out or "").strip()) < 400:
        return True                      # said only that it could not
    return False


def _note(model, why, who):
    """Remember the fall-back and tell Kino once a day."""
    try:
        m = json.load(io.open(MARK, encoding="utf-8"))
    except Exception:
        m = {}
    day = time.strftime("%Y-%m-%d")
    m.setdefault("events", []).append({"t": int(time.time()), "who": who, "model": model, "why": (why or "")[:160]})
    m["events"] = m["events"][-100:]
    io.open(MARK, "w", encoding="utf-8").write(json.dumps(m, ensure_ascii=False, indent=1))
    if m.get("told") != day and model:
        m["told"] = day
        io.open(MARK, "w", encoding="utf-8").write(json.dumps(m, ensure_ascii=False, indent=1))
        try:
            qf = os.path.join(LIVE, "owl_push_queue.json")
            try:
                q = json.load(io.open(qf, encoding="utf-8"))
            except Exception:
                q = []
            q.append({"uid": "kino", "t": int(time.time()), "title": "\U0001f9e0 Le labo a changé de modèle",
                      "body": f"{who} : le modèle habituel n’a pas répondu ({(why or '')[:80]}). Suite avec « {model} ». Rien d’autre à faire."})
            io.open(qf, "w", encoding="utf-8").write(json.dumps(q, ensure_ascii=False))
        except Exception:
            pass


def run(mission, turns=30, tools=None, cwd=LIVE, timeout=1500, log=None, who="le labo", models=None):
    """Returns (rc, output, model_used). model_used is None for the default."""
    last = (-1, "", "")
    for model in (models or MODELS):
        cmd = [CLAUDE, "-p", mission, "--output-format", "text", "--max-turns", str(turns), "--allowedTools"] + list(tools or TOOLS)
        if model:
            cmd += ["--model", model]
        try:
            r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
            rc, out, err = r.returncode, r.stdout or "", r.stderr or ""
        except subprocess.TimeoutExpired as e:
            rc, out, err = -2, (e.stdout.decode("utf-8", "replace") if isinstance(e.stdout, bytes) else (e.stdout or "")), "timed out"
        except Exception as e:
            rc, out, err = -1, "", str(e)
        if log:
            try:
                io.open(log, "w", encoding="utf-8").write(out + ("\n[stderr]\n" + err if err else "") + f"\n[model {model or 'default'} rc {rc}]\n")
            except Exception:
                pass
        if not _looks_limited(rc, out, err):
            if model:
                _note(model, "ok après repli", who)
            return rc, out, model
        why = (LIMIT_RE.search((out + err)[-4000:]) or [None])[0] if LIMIT_RE.search((out + err)[-4000:]) else ("rc %s, sans réponse" % rc)
        last = (rc, out, err)
        nxt = (models or MODELS)[(models or MODELS).index(model) + 1] if (models or MODELS).index(model) + 1 < len(models or MODELS) else None
        if nxt:
            _note(nxt, why, who)
        time.sleep(5)
    return last[0], last[1], (models or MODELS)[-1]


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--mission-file", required=True)
    ap.add_argument("--turns", type=int, default=30)
    ap.add_argument("--out", required=True)
    ap.add_argument("--suffix", default="")
    ap.add_argument("--who", default="le chercheur")
    ap.add_argument("--timeout", type=int, default=3000)
    a = ap.parse_args()
    mission = io.open(a.mission_file, encoding="utf-8").read() + ("\n\n" + a.suffix if a.suffix else "")
    rc, out, model = run(mission, turns=a.turns, cwd=LIVE, timeout=a.timeout, log=a.out, who=a.who)
    print(f"model {model or 'default'} rc {rc} chars {len(out)}")
    sys.exit(0 if rc == 0 else 1)
