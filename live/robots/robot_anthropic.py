"""robot_anthropic.py (2026-11-01, owner: "connect the API key" - customers' conversations run on the commercial API, not on the
owner's personal plan).

ask_text(system, user, model, timeout, log, on_text) -> the whole answer as text, or None on failure (the caller then falls
back to the local brain). Same contract as robot_warm.ask_text / robot_openai.ask_text:
  - streaming (on_text gets the text so far, so the first words still show fast)
  - the long, stable system prompt is cached (cache_control on it): every turn after the first in 5 minutes pays ~10% for it
  - the cost of each call is written to brain_costs.jsonl like every other call, with "api": true
Key: C:\\ProgramData\\kino_secret\\anthropic_api.txt (admins only; Kino's own Windows user cannot read it).
"""
import io, json, os, time

HERE = os.path.dirname(os.path.abspath(__file__))
KEY = r"C:\ProgramData\kino_secret\anthropic_api.txt"
COSTS = os.path.join(HERE, "brain_costs.jsonl")
MODELS = {"haiku": "claude-haiku-5-5", "sonnet": "claude-sonnet-5-5", "opus": "claude-opus-5-5"}
# $ per million tokens: input, output (cache read = 0.1 x input, cache write = 1.25 x input)
PRICE = {"claude-haiku-5-5": (0.10, 0.50), "claude-sonnet-5-5": (2.00, 10.00), "claude-opus-5-5": (4.00, 20.00)}
# a chat reply wants a quick, natural answer: little deliberation on the small model, a normal amount on the others
EFFORT = {"claude-haiku-5-5": "low", "claude-sonnet-5-5": "medium", "claude-opus-5-5": "medium"}
_CLIENT = {}


def ready():
    return os.path.exists(KEY)


def _client():
    import anthropic
    if "c" not in _CLIENT:
        _CLIENT["c"] = anthropic.Anthropic(api_key=open(KEY, encoding="ascii").read().strip(), max_retries=1)
    return _CLIENT["c"]


def _cost(mid, u):
    pi, po = PRICE.get(mid, (2.0, 10.0))
    inp = getattr(u, "input_tokens", 0) or 0
    cr = getattr(u, "cache_read_input_tokens", 0) or 0
    cw = getattr(u, "cache_creation_input_tokens", 0) or 0
    out = getattr(u, "output_tokens", 0) or 0
    return (inp * pi + cr * pi * 0.1 + cw * pi * 1.25 + out * po) / 1e6


def _write(row):
    try:
        io.open(COSTS, "a", encoding="utf-8").write(json.dumps(row) + "\n")
    except Exception:
        pass


def ask_text(system, user, model="sonnet", timeout=150, log=None, on_text=None):
    mid = MODELS.get(model, model)
    t0, first = time.time(), None
    acc = []
    try:
        c = _client().with_options(timeout=timeout)
        with c.messages.stream(
            model=mid,
            max_tokens=16000,
            system=[{"type": "text", "text": str(system), "cache_control": {"type": "ephemeral"}}],
            output_config={"effort": EFFORT.get(mid, "medium")},
            messages=[{"role": "user", "content": str(user)}],
        ) as stream:
            for text in stream.text_stream:
                if first is None:
                    first = time.time()
                acc.append(text)
                if on_text is not None:
                    try:
                        on_text("".join(acc))
                    except Exception:
                        pass
            msg = stream.get_final_message()
    except Exception as e:
        _write({"t": int(time.time()), "m": model, "usd": 0, "tag": os.path.basename(log) if log else "", "err": str(e)[:200],
                "api": True})
        return None
    if msg.stop_reason == "refusal":
        _write({"t": int(time.time()), "m": model, "usd": round(_cost(mid, msg.usage), 6), "tag": os.path.basename(log) if log else "",
                "err": "refusal", "api": True})
        return None
    out = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
    _write({"t": int(time.time()), "m": model, "usd": round(_cost(mid, msg.usage), 6), "tag": os.path.basename(log) if log else "",
            "err": None, "ms": int((time.time() - t0) * 1000), "ttft_ms": int(((first or time.time()) - t0) * 1000),
            "out": getattr(msg.usage, "output_tokens", 0), "cache_read": getattr(msg.usage, "cache_read_input_tokens", 0) or 0,
            "api": True})
    if log:
        try:
            io.open(log, "a", encoding="utf-8").write("\n--- api %s ---\n%s\n" % (mid, out))
        except Exception:
            pass
    return out
