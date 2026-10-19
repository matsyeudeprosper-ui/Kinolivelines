"""Warm model calls for the robot workshop (owner 2026-10-19: "it takes long to reply... conversation must flow").

A cold `claude -p` spends ~12 s starting before the model even reads the message; the answer itself takes ~4 s.
So the workshop keeps up to WARM ready processes per system prompt: started in advance (same safety as
robot_interview.call - no tools, no MCP, no session, empty folder), each one answers ONE message and is thrown
away, and a fresh one starts behind it. Nobody in the workshop for IDLE seconds = no process kept (each ~175 MB).
"""
import hashlib, io, json, os, queue, subprocess, threading, time

import robot_interview as IV

WARM, IDLE, MAX_AGE = 2, 600, 1500
_LOCK = threading.Lock()
_POOL = {}            # key -> [(proc, started_at)]
_KEYS = {}            # key -> (system file, model)
_SEEN = {"t": 0.0}    # last time someone used / opened the workshop


def _sysfile(system):
    os.makedirs(IV.JOBS, exist_ok=True)
    h = hashlib.sha1(system.encode("utf-8")).hexdigest()[:12]
    p = os.path.join(IV.JOBS, "_sys_%s.txt" % h)
    if not os.path.exists(p):
        io.open(p, "w", encoding="utf-8").write(system)
    return p, h


def _spawn(sp, model):
    cmd = [IV.CLAUDE, "-p", "--input-format", "stream-json", "--output-format", "stream-json", "--verbose",
           "--system-prompt-file", sp, "--tools", "", "--strict-mcp-config", "--no-session-persistence",
           "--max-turns", "1", "--model", model]
    return subprocess.Popen(cmd, cwd=IV.JOBS, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                            text=True, encoding="utf-8", errors="replace", creationflags=0x08000000)


def _fill(key):
    """top the pool up to WARM live processes (called outside the caller's wait)"""
    with _LOCK:
        sp, model = _KEYS[key]
        L = [(p, t) for p, t in _POOL.get(key, []) if p.poll() is None and time.time() - t < MAX_AGE]
        for p, t in _POOL.get(key, []):
            if (p, t) not in L:
                _kill(p)
        while len(L) < WARM:
            try:
                L.append((_spawn(sp, model), time.time()))
            except Exception:
                break
        _POOL[key] = L


def _kill(p):
    try:
        p.kill()
    except Exception:
        pass


def prewarm(system, model="sonnet"):
    """someone opened the workshop: have processes ready for their first message"""
    sp, h = _sysfile(system)
    key = h + model
    _KEYS[key] = (sp, model)
    _SEEN["t"] = time.time()
    threading.Thread(target=_fill, args=(key,), daemon=True).start()


def reap():
    """nobody used the workshop for IDLE seconds: let the processes go"""
    if time.time() - _SEEN["t"] < IDLE:
        return
    with _LOCK:
        for key, L in _POOL.items():
            for p, _ in L:
                _kill(p)
            _POOL[key] = []


def _reaper():
    while True:
        time.sleep(60)
        try:
            reap()
        except Exception:
            pass


threading.Thread(target=_reaper, daemon=True).start()


def ask_text(system, user, model="sonnet", timeout=150, log=None):
    """the model's whole answer as text (None on failure), from a warm process when one is ready"""
    sp, h = _sysfile(system)
    key = h + model
    _KEYS[key] = (sp, model)
    _SEEN["t"] = time.time()
    p = None
    with _LOCK:
        L = _POOL.get(key, [])
        while L:
            q, t = L.pop(0)
            if q.poll() is None and time.time() - t < MAX_AGE:
                p = q
                break
            _kill(q)
    if p is None:
        p = _spawn(sp, model)             # cold: ~12 s more
    threading.Thread(target=_fill, args=(key,), daemon=True).start()
    out = queue.Queue()

    def read():
        try:
            for line in p.stdout:
                try:
                    j = json.loads(line)
                except Exception:
                    continue
                if j.get("type") == "result":
                    out.put(j.get("result") if not j.get("is_error") else None)
                    return
        except Exception:
            pass
        out.put(None)
    threading.Thread(target=read, daemon=True).start()
    try:
        p.stdin.write(json.dumps({"type": "user", "message": {"role": "user", "content": user}}) + "\n")
        p.stdin.flush()
        txt = out.get(timeout=timeout)
    except Exception:
        txt = None
    _kill(p)
    if log:
        try:
            io.open(log, "a", encoding="utf-8").write("\n--- warm %s ---\n%s\n" % (model, (txt or "(none)")[-6000:]))
        except Exception:
            pass
    return txt


def ask_json(system, user, models=("sonnet", "haiku"), timeout=150, log=None):
    """the first JSON object of the answer; the next model if one fails"""
    for m in models:
        j = IV.first_json(ask_text(system, user, m, timeout, log) or "")
        if j is not None:
            return j
    return None
