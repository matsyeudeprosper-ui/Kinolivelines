"""Warm model calls for the robot workshop (owner 2026-10-19: "it takes long to reply... conversation must flow").

A cold `claude -p` spends ~12 s starting before the model even reads the message; the answer itself takes ~4 s.
So the workshop keeps up to WARM ready processes per system prompt: started in advance (same safety as
robot_interview.call - no tools, no MCP, no session, empty folder), each one answers ONE message and is thrown
away, and a fresh one starts behind it. Nobody in the workshop for IDLE seconds = no process kept (each ~175 MB).
"""
import hashlib, io, json, os, queue, re, subprocess, threading, time

import robot_interview as IV

MAX_TOTAL, SUPERSEDE = 6, 900       # 2026-10-26 (owner, memory 29.3/31.8 GB committed): 6 ready processes, not 8
MAX_TOTAL_WAS = 8       # 2026-10-24 (speed): stable keys now, so more of them stay warm, longer         # 2026-10-23 (memory): the stable block carries the member's minute and live prices, so
                                      # EVERY message is a new key; 12 keys x 3 x ~330 MB (measured, not 175) = 11.5 GB of
                                      # claude.exe in 30 min, commit at 95 %, PowerShell could not even start. Never more than
                                      # MAX_TOTAL live processes over all keys (least recently used keys go first), and a key
                                      # nobody used for SUPERSEDE s is let go the moment a new key appears.
WARM, IDLE, MAX_AGE = 2, 1800, 5400   # IDLE 1800 (2026-10-23): a 10-min pause met a cold process (~12 s) - 3 x 175 MB is nothing on 18 GB     # 3 (2026-10-20 speed): two quick turns in a row no longer meet a cold process
_LOCK = threading.Lock()
_POOL = {}            # key -> [(proc, started_at)]
_KEYS = {}            # key -> (system file, model)
_SEEN = {"t": 0.0}    # last time someone used / opened the workshop
_LAST = {}            # key -> last use (2026-10-23: one key per member now - a key nobody used for IDLE s lets its processes go)


_TL = threading.local()          # member_turn: this thread answers the member right now (never budgeted)
_HIST = []                       # (t, ok) of every model call, last hour
BG_MAX_PER_HOUR = 150            # 2026-10-23: four night research processes made 360 calls ($19) in ONE hour, the usage
BG_FAIL_PAUSE = (5, 600)         # limit was hit and 1 266 calls failed for 6 h - the member's chat included. Background
                                 # work stops at 150 calls/hour, and for 10 min after 5 failures in 10 min (API down or capped).


def member_turn(flag):
    """the caller is answering the member themselves (chat message, live call): exempt from the background budget"""
    _TL.member = bool(flag)


_OA_DOWN = {"until": 0.0, "n": 0}


def set_brain(brain):
    """2026-10-24 (Kino-O prototype): the conversation's brain for this thread - "openai" routes every call of the turn
    (quick, build, judge, auditor, call brain) to robot_openai; None = Claude through claude.exe as usual"""
    _TL.brain = brain if brain in ("openai",) else None


def brain():
    return getattr(_TL, "brain", None)


def _budget_ok():
    now = time.time()
    with _LOCK:
        _HIST[:] = [(t, ok) for t, ok in _HIST if now - t <= 3600]
        n = len(_HIST)
        fails = sum(1 for t, ok in _HIST if not ok and now - t < BG_FAIL_PAUSE[1])
    return n < BG_MAX_PER_HOUR and fails < BG_FAIL_PAUSE[0]


def budget_state():
    ok = _budget_ok()                        # takes the lock itself - never inside it (a plain Lock is not re-entrant)
    now = time.time()
    with _LOCK:
        return {"calls_last_hour": len([1 for t, _ in _HIST if now - t <= 3600]),
                "fails_10min": sum(1 for t, ok_ in _HIST if not ok_ and now - t < 600), "ok": ok}


def _sysfile(system):
    os.makedirs(IV.JOBS, exist_ok=True)
    h = hashlib.sha1(system.encode("utf-8")).hexdigest()[:12]
    p = os.path.join(IV.JOBS, "_sys_%s.txt" % h)
    if not os.path.exists(p):
        io.open(p, "w", encoding="utf-8").write(system)
        try:                                  # 2026-10-23: one file per member and per change of their facts - the old ones go after 2 days
            for f in os.listdir(IV.JOBS):
                fp = os.path.join(IV.JOBS, f)
                if f.startswith("_sys_") and f.endswith(".txt") and time.time() - os.path.getmtime(fp) > 172800:
                    os.remove(fp)
        except Exception:
            pass
    return p, h


EFFORT = {"sonnet": "low"}   # 2026-10-23 (speed, measured on his real prompt): the model thinks 3-5 s before its first word;
                             # --effort low on Sonnet (the member's turns, chat) took ~2 s off (7.4-8.8 s vs 9.2-11.7 s a call)
                             # at the same cost and quality; Opus (his own messages, nightly engines) keeps its default.


def _spawn(sp, model):
    cmd = [IV.CLAUDE, "-p", "--input-format", "stream-json", "--output-format", "stream-json", "--verbose",
           "--system-prompt-file", sp, "--tools", "", "--strict-mcp-config", "--no-session-persistence",
           "--max-turns", "1", "--include-partial-messages", "--model", model] + (["--effort", EFFORT[model]] if model in EFFORT else [])
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
            _cap_locked(key)
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


def _live_total_locked():
    return sum(1 for L in _POOL.values() for p, _ in L if p.poll() is None)


PINNED = set()        # 2026-10-26 (green chat watch: first word 15-17 s right after a builder run): the one mind's key is never
                      # the one let go - the builder and the old pipeline's keys go first


def pin(system, model="sonnet"):
    """keep this prompt + model warm whatever else runs (the one mind - robots/kino_one.py)"""
    sp, h = _sysfile(system)
    key = h + model
    with _LOCK:
        _KEYS[key] = (sp, model)
        new = key not in PINNED
        PINNED.add(key)
        _LAST[key] = max(_LAST.get(key, 0), time.time())
    if new:
        threading.Thread(target=_fill, args=(key,), daemon=True).start()
    return key


def _cap_locked(keep):
    """with _LOCK held: let the least recently used OTHER keys go until fewer than MAX_TOTAL processes are alive"""
    while _live_total_locked() >= MAX_TOTAL:
        others = sorted((k for k, L in _POOL.items() if k != keep and k not in PINNED and any(p.poll() is None for p, _ in L)),
                        key=lambda k: _LAST.get(k, 0))
        if not others:
            break
        for p, _ in _POOL[others[0]]:
            _kill(p)
        _POOL[others[0]] = []


def live_count():
    with _LOCK:
        return _live_total_locked()


def ready(system, model, min_age=12):
    """2026-10-23: is a WARM process (booted at least min_age s ago) waiting for this prompt + model? A cold boot (~10 s) is
    slower than a warm answer from the other model, so the caller only switches models when one is really ready."""
    sp, h = _sysfile(system)
    key = h + model
    with _LOCK:
        return any(p.poll() is None and min_age <= time.time() - t < MAX_AGE for p, t in _POOL.get(key, []))


def prewarm(system, model="sonnet"):
    """someone opened the workshop: have processes ready for their first message"""
    sp, h = _sysfile(system)
    key = h + model
    new = key not in _POOL
    _KEYS[key] = (sp, model)
    _SEEN["t"] = _LAST[key] = time.time()
    if new:
        reap(SUPERSEDE)
    threading.Thread(target=_fill, args=(key,), daemon=True).start()


def reap(idle=None):
    """nobody used the workshop for IDLE seconds: let the processes go - and (2026-10-23) so does any key nobody used for
    IDLE seconds while others are busy: a member's facts changed = a new key, the old one must not keep 3 processes.
    idle=SUPERSEDE (a new key just appeared): any key nobody used for that long goes now, whoever is in the workshop."""
    now = time.time()
    with _LOCK:
        for key, L in _POOL.items():
            if key in PINNED and now - _LAST.get(key, 0) < 3 * 3600:
                continue                      # the one mind stays warm through a quiet evening
            if idle is None:
                if now - _SEEN["t"] < IDLE and now - _LAST.get(key, 0) < IDLE:
                    continue
            elif now - _LAST.get(key, 0) < idle:
                continue
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
        try:                                  # 2026-10-24 (speed): keep the keys in use warm - a ready process older than MAX_AGE was
            now = time.time()                 # dropped at the next call and nothing replaced it, so the judge met a cold boot after
            with _LOCK:                       # every quiet spell. A refill for each key used in the last 30 min, two boots a minute at most.
                keys = [k for k in _KEYS if (now - _LAST.get(k, 0) < 1800 or (k in PINNED and now - _LAST.get(k, 0) < 3 * 3600))
                        and sum(1 for p, t in _POOL.get(k, []) if p.poll() is None and now - t < MAX_AGE) < WARM]
            for k in keys[:2]:
                _fill(k)
        except Exception:
            pass


threading.Thread(target=_reaper, daemon=True).start()


_PARAM = re.compile(r'<parameter name="([A-Za-z_]+)">(.*?)(?:</parameter>|$)', re.S)


def param_fields(txt):
    """2026-10-22: the model sometimes answers in tool-call form - <parameter name="notes">...</parameter><parameter
    name="say">...</parameter> - instead of JSON; the chat then showed those tags. Read it as the same fields."""
    if '<parameter name="' not in (txt or ""):
        return None
    out = {}
    for k, v in _PARAM.findall(txt):
        v = v.strip()
        try:
            out[k] = json.loads(v) if v[:1] in "{[" or v in ("null", "true", "false") or re.fullmatch(r"-?\d+(\.\d+)?", v) else v
        except Exception:
            out[k] = v
    return out if str(out.get("say") or "").strip() else None


def partial_say(buf, key="say"):
    """the "say" text (or another string field) of a JSON answer still being written (for the typing bubble), or "" """
    tag = '<parameter name="%s">' % key
    if tag in buf:                                   # tool-call form (see param_fields)
        return buf.split(tag, 1)[1].split("</parameter>", 1)[0]
    if '<parameter name="' in buf:
        return ""
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
    if getattr(_TL, "brain", None) == "openai" and time.time() > _OA_DOWN["until"]:   # 2026-10-24 (Kino-O): through OpenAI
        try:
            import robot_openai as _RO
            _r = _RO.ask_text(system, user, model, timeout, log, on_text)
        except Exception:
            _r = None
        if _r is not None:
            _OA_DOWN["n"] = 0
            return _r
        # 2026-10-25 18:53 UTC (watch): the OpenAI account ran out of credit ("credit_balance_exhausted") and every Kino-O
        # reply became "je n'ai pas reussi a l'assembler". A failed OpenAI call now falls through to the Claude brain;
        # after two failures in a row OpenAI is skipped for 10 minutes, then tried again.
        _OA_DOWN["n"] += 1
        if _OA_DOWN["n"] >= 2:
            _OA_DOWN["until"], _OA_DOWN["n"] = time.time() + 600, 0
    if not getattr(_TL, "member", False) and not _budget_ok():
        try:                                      # refused, and said so in the cost log
            io.open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "brain_costs.jsonl"), "a", encoding="utf-8").write(json.dumps(
                {"t": int(time.time()), "m": model, "usd": 0, "tag": os.path.basename(log) if log else "", "skip": "budget"}) + "\n")
        except Exception:
            pass
        return None
    sp, h = _sysfile(system)
    key = h + model
    new = key not in _POOL
    _KEYS[key] = (sp, model)
    _SEEN["t"] = _LAST[key] = time.time()
    if new:
        reap(SUPERSEDE)
    p = None
    with _LOCK:
        L = _POOL.get(key, [])
        while L:
            q, t = L.pop(0)
            if q.poll() is None and time.time() - t < MAX_AGE:
                p = q
                break
            _kill(q)
    cold = p is None
    if p is None:
        p = _spawn(sp, model)             # cold: ~12 s more
    tm = {"t0": time.time(), "first": None}   # 2026-10-23 (owner: "check response time"): where the seconds go, per call
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
                if j.get("type") == "stream_event" and tm["first"] is None:
                    tm["first"] = time.time()
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
                            {"t": int(time.time()), "m": model, "usd": j.get("total_cost_usd"), "tag": os.path.basename(log) if log else "",
                             "err": (str(j.get("result") or "")[:200] if j.get("is_error") else None),
                             "cold": cold, "ttft_ms": int(((tm["first"] or time.time()) - tm["t0"]) * 1000), "ms": int((time.time() - tm["t0"]) * 1000),
                             "out": len(str(j.get("result") or ""))}) + "\n")   # err (2026-10-23): 1 266 failures were logged as "(none)" - now we know why
                    except Exception:
                        pass
                    if j.get("is_error") and "safeguards flagged" in str(j.get("result") or ""):
                        tm["flagged"] = True
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
    with _LOCK:
        _HIST.append((time.time(), txt is not None))
    if warm:                              # warm=False (2026-10-20): a background call keeps no processes for its prompt
        threading.Thread(target=_fill, args=(key,), daemon=True).start()
    if log:
        try:
            io.open(log, "a", encoding="utf-8").write("\n--- warm %s ---\n%s\n" % (model, (txt or "(none)")[-6000:]))
        except Exception:
            pass
    # 2026-10-26 21:38-22:36 UTC: "Sonnet 5.5's safeguards flagged this message ... sometimes happens with safe, normal
    # conversations" - 24 of the owner's chart-chat turns in a row came back empty (a member message unanswered 95 s). The
    # same call once more on the other model instead of silence.
    if txt is None and tm.get("flagged") and model != "opus" and getattr(_TL, "member", False):   # their message, not a wake-up
        if log:
            try:
                io.open(log, "a", encoding="utf-8").write("\n--- safeguards flagged on %s: retry on opus ---\n" % model)
            except Exception:
                pass
        return ask_text(system, user, "opus", timeout, log, on_text, warm=False)
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
        j = param_fields(txt)
        if j is not None:
            return j
        t = txt.strip()
        # 2026-10-22: '<invoke name="noop"/></invoke>' was salvaged as the answer - shown 3 times, their question unanswered.
        # Tool-call markup is never a chat message: try the next model instead.
        if re.search(r"</?(invoke|function_calls|parameter|antml)\b", t):
            continue
        if salvage and t and "{" not in t and len(t) < 1500 and t.lower() not in ("(none)", "none"):
            return {"say": t, "salvaged": True}
    return None
