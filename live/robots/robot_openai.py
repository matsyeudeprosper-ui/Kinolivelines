"""robot_openai.py (2026-10-24, owner: "a prototype, a copy of Kino with OpenAI as the brain and voice, on our local data").

The same text in, the same text out as robot_warm.ask_text, through OpenAI's Responses API instead of a claude.exe process:
no process to boot, streaming, the system prompt cached on their side. Used only when a conversation carries
brain = "openai" (admin-only prototype "Kino-O"); robot_warm routes there through a thread-local flag set by the chat
module, so the quick turn, the build turn, the judge, the auditor and the call brain all follow the conversation's brain.

  ask_text(system, user, model, timeout, log, on_text) -> str | None      model = the Claude alias ("sonnet"...) -> MAP
  cost -> robots/brain_costs.jsonl with m = "openai:<model>" (the scorecard and the owner's cost views count it like the rest)
"""
import io, json, os, time, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
MAP = {"sonnet": "gpt-5.1", "opus": "gpt-5.1", "haiku": "gpt-5.1"}     # measured 2026-10-24: gpt-5.1 0.9 s, gpt-5-mini 2-3.5 s (reasoning) - 5.1 everywhere
EFFORT = {"gpt-5.1": "low", "gpt-5-mini": "low"}
PRICE = {"gpt-5.1": (1.25, 10.0), "gpt-5-mini": (0.25, 2.0)}    # $/MTok in, out (OpenAI list 2026-10; cached input is cheaper)


def _key():
    return os.environ.get("OPENAI_API_KEY")


def ask_text(system, user, model="sonnet", timeout=150, log=None, on_text=None):
    """the model's whole answer as text (None on failure); on_text(partial) while it streams"""
    k = _key()
    if not k:
        return None
    mid = MAP.get(model, model)
    body = {"model": mid, "instructions": system, "input": user, "stream": True, "max_output_tokens": 4000, "store": False}
    if mid in EFFORT:
        body["reasoning"] = {"effort": EFFORT[mid]}
    t0 = time.time()
    first = None
    acc = []
    usage = {}
    try:
        rq = urllib.request.Request("https://api.openai.com/v1/responses", data=json.dumps(body).encode("utf-8"),
                                    headers={"Authorization": "Bearer " + k, "Content-Type": "application/json", "User-Agent": "OwlNest/1.0"})
        with urllib.request.urlopen(rq, timeout=timeout) as r:
            buf = b""
            while True:
                chunk = r.read(4096)
                if not chunk:
                    break
                buf += chunk
                while b"\n\n" in buf:
                    ev, buf = buf.split(b"\n\n", 1)
                    for line in ev.decode("utf-8", "replace").splitlines():
                        if not line.startswith("data:"):
                            continue
                        d = line[5:].strip()
                        if not d or d == "[DONE]":
                            continue
                        try:
                            j = json.loads(d)
                        except Exception:
                            continue
                        t = j.get("type")
                        if t == "response.output_text.delta":
                            if first is None:
                                first = time.time()
                            acc.append(str(j.get("delta") or ""))
                            if on_text:
                                try:
                                    on_text("".join(acc))
                                except Exception:
                                    pass
                        elif t == "response.completed":
                            usage = ((j.get("response") or {}).get("usage") or {})
                        elif t in ("response.failed", "error"):
                            _log_cost(mid, 0, 0, 0, t0, first, log, err=str(j)[:160])
                            return None
    except Exception as e:
        _log_cost(mid, 0, 0, 0, t0, first, log, err=type(e).__name__ + ": " + str(e)[:120])
        return None
    txt = "".join(acc)
    _log_cost(mid, int(usage.get("input_tokens") or 0), int(usage.get("output_tokens") or 0), int(((usage.get("input_tokens_details") or {}).get("cached_tokens")) or 0), t0, first, log)
    if log:
        try:
            io.open(log, "a", encoding="utf-8").write("\n--- openai %s ---\n%s\n" % (mid, txt[-6000:]))
        except Exception:
            pass
    return txt or None


def _log_cost(mid, tin, tout, cached, t0, first, log, err=None):
    pin, pout = PRICE.get(mid, (1.25, 10.0))
    usd = ((tin - cached) * pin + cached * pin * 0.1 + tout * pout) / 1e6
    try:
        io.open(os.path.join(HERE, "brain_costs.jsonl"), "a", encoding="utf-8").write(json.dumps(
            {"t": int(time.time()), "m": "openai:" + mid, "usd": round(usd, 6), "tag": os.path.basename(log) if log else "", "err": err, "cold": False,
             "ttft_ms": int(((first or time.time()) - t0) * 1000), "ms": int((time.time() - t0) * 1000), "out": tout, "in": tin, "cached": cached}) + "\n")
    except Exception:
        pass
