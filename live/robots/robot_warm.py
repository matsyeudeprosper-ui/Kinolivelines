"""Warm model calls for the robot workshop (owner 2026-10-19: "it takes long to reply... conversation must flow").

A cold `claude -p` spends ~12 s starting before the model even reads the message; the answer itself takes ~4 s.
So the workshop keeps up to WARM ready processes per system prompt: started in advance (same safety as
robot_interview.call - no tools, no MCP, no session, empty folder), each one answers ONE message and is thrown
away, and a fresh one starts behind it. Nobody in the workshop for IDLE seconds = no process kept (each ~175 MB).
"""
import hashlib, io, json, os, queue, subprocess, threading, time

import robot_interview as IV

WARM, IDLE, MAX_AGE = 3, 600, 1500     # 3 (2026-10-20 speed): two quick turns in a row no longer meet a cold process
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
           "--max-turns", "1", "--include-partial-messages", "--model", model]
    return subprocess.Popen(cmd, cwd=IV.JOBS, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                            text=True, encoding="utf-8", errors="replace", creationflags=0x08000000)   # normal priority: at below-normal a busy CPU starved it (api 2 s, total 60-140 s)


def _fill(key):
    """top the pool up to WARM live processes (called outside the caller's wait)"""
    with _LOCK:
        sp, model = _KEYS[key]
        L = [(p, t) for p, t in _POOL.get(key, []) if p.poll() is None and time.time() - t < MAX_AGE]
        for p, t in _POOL.get(key, []):
            if (p, t) not in L:
                _kill(p)
        if len(L) < WARM:                    # one at a time: a starting process is CPU-hungry for ~10 s
            try:
                L.append((_spawn(sp, model), time.time()))
            except Exception:
                pass
        _POOL[key] = L
        short = len(L) < WARM
    if short:
        threading.Timer(12, _fill, args=(key,)).start()


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


def partial_say(buf, key="say"):
    """the "say" text (or another string field) of a JSON answer still being written (for the typing bubble), or "" """
    i = buf.find('"%s"' % key)
    if i < 0:
        return ""
    i = buf.find('"', buf.find(":", i) + 1)
    if i < 0:
        return ""
    out, esc = [], False
    for ch in buf[i + 1:]:
        if esc:
            out.append({"n": "\n", "t": " ", '"': '"', "\\": "\\"}.get(ch, ch)); esc = False
        elif ch == "\\":
            esc = True
        elif ch == '"':
            break
        else:
            out.append(ch)
    return "".join(out)


def ask_text(system, user, model="sonnet", timeout=150, log=None, on_text=None, warm=True):
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
    try:                                  # the one answering now goes back to normal priority
        import ctypes
        ctypes.windll.kernel32.SetPriorityClass(int(p._handle), 0x00000020)
    except Exception:
        pass
    # the pool is topped up AFTER the answer: a process starting meanwhile takes the CPU from the reply (5 s vs 2.5 s)
    out = queue.Queue()
    acc = []

    def read():
        try:
            for line in p.stdout:
                try:
                    j = json.loads(line)
                except Exception:
                    continue
                if on_text is not None and j.get("type") == "stream_event":
                    dl = (j.get("event") or {}).get("delta") or {}
                    if dl.get("type") == "text_delta":
                        acc.append(dl.get("text") or "")
                        try:
                            on_text("".join(acc))
                        except Exception:
                            pass
                if j.get("type") == "result":
                    try:                          # 2026-10-21 (owner item 12): what each answer costs
                        io.open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "brain_costs.jsonl"), "a", encoding="utf-8").write(json.dumps(
                            {"t": int(time.time()), "m": model, "usd": j.get("total_cost_usd"), "tag": os.path.basename(log) if log else ""}) + "\n")
                    except Exception:
                        pass
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
    if warm:                              # warm=False (2026-10-20): a background call keeps no processes for its prompt
        threading.Thread(target=_fill, args=(key,), daemon=True).start()
    if log:
        try:
            io.open(log, "a", encoding="utf-8").write("\n--- warm %s ---\n%s\n" % (model, (txt or "(none)")[-6000:]))
        except Exception:
            pass
    return txt


def ask_json(system, user, models=("sonnet", "haiku"), timeout=150, log=None, on_text=None, salvage=False, warm=True):
    """the first JSON object of the answer; the next model if one fails; on_text(partial text) while it is written.
    salvage=True (2026-10-20, a 2 min 20 s reply: the quick answer came as plain text, was thrown away, and the slow turn
    had to answer): a plain chat message without JSON is kept as {"say": text} instead of trying another model"""
    for m in models:
        txt = ask_text(system, user, m, timeout, log, on_text, warm=warm) or ""
        j = IV.first_json(txt)
        if j is not None:
            return j
        t = txt.strip()
        if salvage and t and "{" not in t and len(t) < 1500 and t.lower() not in ("(none)", "none"):
            return {"say": t, "salvaged": True}
    return None
