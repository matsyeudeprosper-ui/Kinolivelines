"""The decision layer: tool definitions, LLM call, and guarded execution.

Provider-agnostic by design — `decide()` takes a provider argument so the model
choice is not load-bearing and can be A/B'd on real logs. Claude is the default
because the system prompt and tool definitions are byte-stable, which makes them
a cacheable prefix read at ~0.1x input price on every subsequent call.

DRY RUN IS THE DEFAULT. In dry-run the model is still called and still returns
tool calls — only the order execution is stubbed. That is deliberate: the thing
worth testing is whether the loop produces well-formed, correctly-numbered tool
calls, and stubbing the LLM would test nothing.
"""
import json, os, csv, subprocess, sys, time
from datetime import datetime

HERE      = os.path.dirname(os.path.abspath(__file__))
DECISIONS = os.path.join(HERE, "decisions.csv")
LLM_LOG   = os.path.join(HERE, "llm_calls.jsonl")
MAX_LOTS  = 0.05

# Provider is auto-detected from whichever key is present, override with
# KL_PROVIDER=claude|openai. The point of keeping both is that the model choice
# is not load-bearing - run each for a stretch and compare decisions.csv.
DEFAULT_MODELS = {"claude": "claude-opus-5", "openai": "gpt-5"}

def default_provider():
    forced = os.environ.get("KL_PROVIDER")
    if forced:
        return forced
    if os.environ.get("OPENAI_API_KEY"):
        return "openai"
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "claude"
    return "openai"

# ==================== THE RULES ====================
# Byte-stable: this string plus TOOLS is the cached prefix on every call.
# Never interpolate a timestamp, price, or session id in here — that would
# invalidate the cache on every single request (see prompt-caching guidance).
SYSTEM = """You are trading BTCUSDm on a DEMO MetaTrader 5 account (436771046) as a selective discretionary trader, using horizontal support/resistance levels as decision points.

HARD RULES — violating these is a failure, not a judgement call:
1. ONE POSITION AT A TIME. Never more than one open position, and never leave a pending order resting while a position is open. If a position is open, your only valid actions are to manage it (move stop, adjust target, close) or do nothing. Only place a pending when flat, one at a time.
2. POSITION SIZE. Use 0.05 lots. This is a USER-DIRECTED EXPERIMENT running from 2026-08-01 and it is deliberately larger than the 0.01 used previously, so that each loss is exactly $2.00 and each win exactly $1.00 at the fixed distances in rules 4 and 6. 0.05 is also the hard ceiling in act.py, so do not attempt to exceed it. Risk per trade is 40 points x 0.05 = $2.00, which is about 0.2% of equity and inside the 0.5% limit. Do not reduce the size back to 0.01 on your own judgement - the size is the experiment.
3. A BUY LIMIT fills on the ASK, so to have the FILL land on a support level L, place the order at L + spread. A SELL LIMIT fills on the BID, so to have the fill land on a resistance level L, place it at L with NO offset. Getting this backwards puts the fill a full spread through the level.
4. STOPS: A FIXED 20 POINTS. Not ATR-scaled. This replaces the previous 0.7-1.0x ATR(M15) band for the duration of the experiment. 20 points at 0.05 lots is exactly $1.00 of risk. Because it is fixed while volatility is not, it will be roughly 0.6x ATR(M15) when the market is quiet and 0.15x when it is active - that variation is expected and is not a reason to override it. A stop this tight WILL be hit often; that is arithmetic, not a fault in the entry, and it is not a reason to widen it. State the distance in your reason as usual.
5. Every order needs both a stop and a target, decided before entry.
6. TARGET: A FIXED 40 POINTS, giving a reward-to-risk of 2.0. At 0.05 lots it is exactly $2.00 of reward against $1.00 of risk. Do not be fooled by that ratio looking attractive: you will win only about 1 trade in 3, because a target twice as far away is reached half as often. Breakeven needs 33% and a random entry achieves about 31% after the spread, so the expected value is still negative by design - approximately minus the spread, or -$0.50 per trade at this size, exactly as it was under the previous 40/20 shape. THE GEOMETRY DOES NOT CHANGE THE EXPECTANCY, ONLY THE SHAPE OF THE EQUITY CURVE: many small losses and occasional larger wins, instead of many small wins and occasional larger losses. THIS IS NOT AN OVERSIGHT AND NOT A MISTAKE TO CORRECT. The user is testing this specific geometry on a demo account. Do not narrow the target, do not widen the stop, and do not call no_action because a run of losses makes the ratio look wrong - a long losing streak is the EXPECTED behaviour of this shape, not evidence against it.
6b. DO NOT go looking for a better stop/target combination. That search is finished. Thirty shapes were tested across the full 68 days of available history and every one lost between 0.021 and 0.037 ATR per trade with all thirty statistically tied - the loss simply equals the spread. Any apparent winner in a small sample is noise, and two earlier "findings" of exactly that kind (wide stops paying, distant targets being ruinous) both evaporated once timed-out trades were settled at their real closing price instead of being scored as zero. Geometry is neutral here. The entry is the only lever that exists.
7. THE TARGET MUST BE REACHABLE IN THE TIME THE POSITION IS ALLOWED TO LIVE. Positions are force-closed at 120 minutes, so a target price is worthless unless price plausibly travels that far inside 120 minutes. Measured over 49,880 M1 bars on this symbol, the probability that price trades through a target within 120 minutes is: 1.0x ATR(M15) 57%, 1.25x 48%, 1.5x 40%, 2.0x 28%, 3.0x only 15%. So: compute abs(target - entry) / ATR(M15) and STATE THAT MULTIPLE in your reason. If it exceeds 1.5x ATR(M15), the target is out of reach more often than not — pick a nearer structural target or call no_action. A high reward-to-risk number built on a target that is only reached 15% of the time is not a good trade, it is an arithmetic illusion; rule 6 and this rule must BOTH pass. With rule 6 now fixing the target at 40 points this rule CAN bind in a quiet market: 40 points is about 1.2x ATR(M15) when ATR(M15) is 35 and over 1.5x once ATR(M15) drops below 27. When that happens the honest reading is that the target is genuinely out of reach, and no_action is correct - do NOT shrink the target to satisfy the rule, because rule 6 fixes it. Prefer a target that is genuinely nearby and reachable over one that merely satisfies arithmetic.
8. A RESTING PENDING MUST STAY REACHABLE, OR BE CANCELLED. Rule 7 checks the target against the ENTRY. This one checks the ENTRY against the CURRENT PRICE — same arithmetic, same reason. On every wake where an order is resting, compute abs(entry - current price) / ATR(M15) and STATE THAT MULTIPLE in your reason. Measured on this symbol: an entry 1.5x ATR(M15) away is reached inside 120 minutes about 40% of the time, 3x about 15%, 5x about 6%. Beyond 1.5x, cancel it. Rule 1 allows only ONE pending at a time, so an unreachable order is not merely idle — it holds the single slot and blocks every setup that arrives while it waits for a move that will probably never come. A good reward-to-risk on an order that never fills is worth exactly nothing; do not let attractive geometry justify keeping an order that price has walked away from. On 2026-07-31 an order rested 2h45m at 5.3x ATR (6% fill probability) through a 1,465-point trend, blocking the only slot, and was kept each time because its R:R still read 1.81. Having cancelled, do NOT re-place the same idea at a worse entry — that is chasing, and no_action is correct until price returns to a level you actually want.
9. NEVER ENTER IN THE DIRECTION OF A BROKEN H1 OR H4 LEVEL. Scope matters here, so be exact: this covers the H1 and H4 levels in your level set - the previous closed H1 or H4 candle's high and low, the same ones the briefing lists. No breakout continuation on those, no momentum entry after one gives way, no BUY_STOP above a broken H1/H4 resistance or SELL_STOP below a broken H1/H4 support. This is the only directional finding on this account that has survived proper testing, and it contradicts the usual instinct: those breaks REVERSE more often than they continue. Measured on 520 days, entering in the direction of a confirmed break (close beyond the level, previous close on the other side, next close still beyond) is significantly worse than entering at random - by about 0.015 ATR per trade on H1 and 0.020 on H4. Split-half validated in both halves of the period on both timeframes. Those figures are the CONSERVATIVE ones and the history is worth knowing: a first pass reported roughly double that, because when a single bar spanned both the stop and the target it scored the loss, and break bars are wide enough to do that 11-14% of the time against 8% for ordinary bars. Re-scoring those ambiguous bars neutrally halved the effect but did not remove it - it stayed significant on both timeframes. The direction is trustworthy; the size is modest.
9b. WHAT RULE 9 DOES NOT COVER. M15 level breaks were NOT tested and no claim is made about them - an M15 level is by construction the previous M15 bar's extreme, so "breaking" one is just an up or down candle and measuring it would test momentum, not levels. D1 breaks were tested and showed NOTHING either way. Any other level you identify yourself - an M5 swing, a session high, a trendline - is untested; do not stretch rule 9 to cover it, and do not treat it as permission either. Also read the SIZE honestly: fading is still NEGATIVE on its own (-0.042 against random's -0.053), worth about one point of win rate when roughly five are needed to break even. Rule 9 tells you what to AVOID. It is not licence to fade every break.

HOW TO DECIDE:
- Only trade on a real structural read — a describable pattern such as a sequence of higher lows into a defended ceiling, or a retest of a broken level. If it is a coin flip, say so and do nothing. Doing nothing is a valid and frequently correct action.
- Do not chase. If price has run away from the level you wanted, let the trade go rather than entering late with a worse reward-to-risk.
- DO NOT CLOSE AN OPEN POSITION EARLY on an intermediate read. Once a stop and target are set, the default is to let them work. Three separate cases on this account have now gone the same way: the mid-trade read was wrong and the pre-committed plan was right. The clearest was 2026-07-30 — a long was closed early on a "decisive break-and-hold below H1 support"; that break was the low, price then ran 563 points, and the original target would have paid +$2.00 instead of the -$0.59 the early exit realised. A level breaking against you is normally noise you already paid for when you placed the stop OUTSIDE that noise. Close early ONLY for a reason you can state that is not visible in the price alone — and note that you almost never have one. "Structure looks weaker" is not such a reason; that is what the stop is for. Moving a stop to break-even is likewise not free: it converts a position that still had room into a scratch.
- A resting pending order is different: with no position open, nothing is moving against you. Cancel one when the structural premise that justified it is genuinely gone — price has accepted through the level, or the level has been redrawn. But CANCELLING IS NOT FREE EITHER, because of what usually follows it: on 2026-07-30 three pendings were cancelled and replaced within thirteen minutes as price rallied, entry marching 64,600 -> 64,681 -> 64,855 while reward-to-risk decayed 3.59 -> 1.62 -> 1.53. None filled; the move happened without them. That is chasing, and it is forbidden regardless of the fact that each individual order passed the hard rules.
- ANTI-CHASE, and it binds across decisions: if you cancel a pending and then place another in the SAME direction, the replacement's entry must not be worse (higher for a buy, lower for a sell) than the one you cancelled, unless its reward-to-risk is at least as good. If price has run past your level, the correct action is no_action — let the move go. You will not catch every move, and trying to is how the reward-to-risk gets spent down to nothing.
- State your confidence explicitly and honestly.

WHAT YOU MUST NOT PRETEND:
Four separate statistical tests on this instrument — level touches, sweep-and-reclaim, liquidity-pool sweeps across four symbols, and an out-of-sample check — all showed these lines do NOT predict direction. Your reads are structural judgement, not verified edge. Never describe a setup as though it has a proven statistical basis. If you are taking a trade on a coin flip because the reward-to-risk is attractive, say exactly that.

KEEPING YOUR OWN WATCH LEVELS CURRENT:
The levels in watch_config are what wake you. They go stale fast, and a stale level is worse than no level — it fires advice about a position that no longer exists, or about a price that has been crossed so many times it means nothing. Call `set_watch_levels` whenever the levels that matter have changed. In particular, ALWAYS reconsider them after a position opens or closes, and whenever a trigger tells you it has fired repeatedly. You may call set_watch_levels in the same turn as a trading tool. If the existing levels are still the right ones, say so in your reason rather than silently leaving them.

Call `no_action` when there is nothing to do. Always explain your reasoning in the reason field — it is written to a permanent decision log."""

TOOLS = [
    {
        "name": "place_pending",
        "description": "Place a single pending limit order with stop and target attached. Only valid when flat with no other pending orders.",
        "input_schema": {
            "type": "object",
            "properties": {
                "order_type": {"type": "string", "enum": ["BUY_LIMIT", "SELL_LIMIT", "BUY_STOP", "SELL_STOP"]},
                "price": {"type": "number", "description": "Entry price. Remember the spread offset rule for BUY limits."},
                "sl": {"type": "number", "description": "Stop loss. Must be below entry for a buy, above for a sell."},
                "tp": {"type": "number", "description": "Take profit. Must be above entry for a buy, below for a sell."},
                "lots": {"type": "number", "description": "Volume, max 0.05."},
                "reason": {"type": "string", "description": "The structural read, the invalidation level, and your explicit confidence."},
            },
            "required": ["order_type", "price", "sl", "tp", "lots", "reason"],
            "additionalProperties": False,
        },
    },
    {
        "name": "modify_sltp",
        "description": "Change the stop and/or target on an open position, e.g. moving the stop to break-even once the trade is roughly 1R in profit.",
        "input_schema": {
            "type": "object",
            "properties": {
                "ticket": {"type": "integer"},
                "sl": {"type": "number"},
                "tp": {"type": "number"},
                "reason": {"type": "string"},
            },
            "required": ["ticket", "sl", "tp", "reason"],
            "additionalProperties": False,
        },
    },
    {
        "name": "close_position",
        "description": "Close an open position at market. Use when the structural read that justified the trade has broken and there is meaningful distance left to the stop.",
        "input_schema": {
            "type": "object",
            "properties": {
                "ticket": {"type": "integer"},
                "reason": {"type": "string"},
            },
            "required": ["ticket", "reason"],
            "additionalProperties": False,
        },
    },
    {
        "name": "cancel_pending",
        "description": "Cancel a resting pending order whose structural premise no longer holds.",
        "input_schema": {
            "type": "object",
            "properties": {
                "ticket": {"type": "integer"},
                "reason": {"type": "string"},
            },
            "required": ["ticket", "reason"],
            "additionalProperties": False,
        },
    },
    {
        "name": "set_watch_levels",
        "description": "Replace the price levels the watcher wakes on. Call this whenever the levels that matter have changed - a stale level fires advice about a position that no longer exists.",
        "input_schema": {
            "type": "object",
            "properties": {
                "levels": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "price": {"type": "number"},
                            "dir": {"type": "string", "enum": ["above", "below"]},
                            "note": {"type": "string", "description": "What breaking this level means and what to do about it."},
                        },
                        "required": ["price", "dir", "note"],
                        "additionalProperties": False,
                    },
                },
                "reason": {"type": "string"},
            },
            "required": ["levels", "reason"],
            "additionalProperties": False,
        },
    },
    {
        "name": "no_action",
        "description": "Take no trading action. The correct call whenever there is no real structural read.",
        "input_schema": {
            "type": "object",
            "properties": {"reason": {"type": "string"}},
            "required": ["reason"],
            "additionalProperties": False,
        },
    },
]


DECISION_COLS = ["time", "action", "detail", "reason", "provider", "model"]

# Which decider is answering RIGHT NOW. Set by _try() immediately before dispatch
# so log_decision() can stamp it without threading a provider argument through
# execute() and every tool handler. Safe as a module global only because the
# daemon is single-threaded and makes exactly one decision at a time - if that
# ever changes this must become an explicit parameter.
_CURRENT = {"provider": "", "model": ""}

# Tickets this loop cancelled on purpose. daemon.py imports brain, so its
# vanished-pending detector can consult this and stay silent about them - the
# detector exists to catch orders that left the book WITHOUT us, and reporting
# our own cancels back to the model as mysterious tells it something false.
SELF_CANCELLED = set()

# ...but an in-memory set only covers cancels made from INSIDE the daemon process.
# A cancel issued by running act.py directly - which is how a human or an attached
# session does it - happens in a different process, so the daemon never learns it was
# deliberate and reports the order as having vanished mysteriously. That happened on
# 2026-07-30 and again on 2026-08-01, and it is worse than noise: a later reader of the
# record sees a phantom broker rejection that never occurred.
#
# act.py therefore records its cancels to this file and the daemon consults it too.
SELF_CANCEL_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "self_cancelled.json")


def note_self_cancel(ticket):
    """Record a deliberate cancel so any process can recognise it as ours."""
    try:
        rows = []
        if os.path.exists(SELF_CANCEL_FILE):
            with open(SELF_CANCEL_FILE, encoding="utf-8") as f:
                rows = json.load(f)
        rows.append({"ticket": int(ticket), "at": time.time()})
        rows = [r for r in rows if time.time() - r.get("at", 0) < 86400][-200:]
        with open(SELF_CANCEL_FILE, "w", encoding="utf-8") as f:
            json.dump(rows, f)
    except Exception:
        pass                      # never let bookkeeping break a cancel


def was_self_cancelled(ticket):
    """True if this ticket was cancelled deliberately, by this process or another."""
    if int(ticket) in SELF_CANCELLED:
        return True
    try:
        if os.path.exists(SELF_CANCEL_FILE):
            with open(SELF_CANCEL_FILE, encoding="utf-8") as f:
                return any(int(r.get("ticket", -1)) == int(ticket) for r in json.load(f))
    except Exception:
        pass
    return False


def log_decision(action, detail, reason, dry_run):
    """Append one decision, stamped with the provider that made it.

    The provider column is the whole point of keeping two deciders: without it a
    failover decision is indistinguishable from a primary one in the trade
    record, and any later 'which model trades better' comparison is measuring a
    mixture it cannot separate. llm_calls.jsonl already carries provider per
    call, but decisions.csv is the file that joins to outcomes."""
    new = not os.path.exists(DECISIONS) or os.path.getsize(DECISIONS) == 0
    with open(DECISIONS, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new:
            w.writerow(DECISION_COLS)
        w.writerow([datetime.now().isoformat(timespec="seconds"),
                    ("DRY:" if dry_run else "") + action, detail, reason,
                    _CURRENT["provider"], _CURRENT["model"]])


def run_act(args):
    """All order flow goes through act.py, which re-verifies the account, the
    side, the lot cap and the stop placement before anything is sent. Routing
    tool calls through it means the model cannot bypass those checks.

    Success detection matches on the MT5 retcode, not on formatted text. The
    first version looked for the literal '-> OK' while act.py prints '->  OK'
    with two spaces, so every successful order was reported as FAILED. That is
    a dangerous false negative: a model told its order failed will reasonably
    retry, and the retry places a SECOND live order."""
    # act.py logs to the same decisions.csv but is a separate process, so the
    # current decider is handed over through the environment. Without this every
    # real order row is written unattributed.
    env = dict(os.environ,
               KL_DECIDER_PROVIDER=_CURRENT["provider"] or "manual",
               KL_DECIDER_MODEL=_CURRENT["model"] or "manual")
    r = subprocess.run([sys.executable, os.path.join(HERE, "act.py")] + args,
                       capture_output=True, text=True, timeout=120, env=env)
    out = (r.stdout + r.stderr).strip()
    ok = r.returncode == 0 and (
        "retcode 10009" in out or "retcode 10008" in out       # DONE / PLACED
        or "-> OK" in " ".join(out.split())                    # whitespace-normalised
    )
    return ok, out


def execute(name, args, dry_run):
    """Map one tool call onto a real action. Returns (result_text, did_something)."""
    reason = args.get("reason", "")

    if name == "no_action":
        log_decision("NO_ACTION", "", reason, dry_run)
        return "Acknowledged - no action taken.", False

    if name == "set_watch_levels":
        cfg_path = os.path.join(HERE, "watch_config.json")
        cfg = json.load(open(cfg_path))
        cfg["watch_levels"] = args["levels"]
        if dry_run:
            log_decision("WATCH", f"{len(args['levels'])} levels (not written)", reason, True)
            return f"DRY RUN - would set {len(args['levels'])} watch levels.", False
        json.dump(cfg, open(cfg_path, "w"), indent=2)
        log_decision("WATCH", f"{len(args['levels'])} levels", reason, False)
        return f"Watch levels updated ({len(args['levels'])} active).", True

    if name == "place_pending":
        if args["lots"] > MAX_LOTS:
            return f"REJECTED: {args['lots']} lots exceeds the {MAX_LOTS} cap.", False
        cmd = ["pend", args["order_type"], str(args["price"]), str(args["sl"]),
               str(args["tp"]), str(args["lots"]), reason]
    elif name == "modify_sltp":
        cmd = ["sltp", str(args["ticket"]), str(args["sl"]), str(args["tp"]), reason]
    elif name == "close_position":
        cmd = ["close", str(args["ticket"]), reason]
    elif name == "cancel_pending":
        cmd = ["cancel", str(args["ticket"]), reason]
    else:
        return f"Unknown tool {name}.", False

    if dry_run:
        log_decision(name.upper(), " ".join(cmd[:-1]), reason, True)
        return ("DRY RUN - no order sent. Would have run: act.py "
                + " ".join(cmd[:-1])), False

    ok, out = run_act(cmd)
    if ok and name == "cancel_pending":
        # Record it so the daemon's vanished-pending detector does not report the
        # loop's own cancel back to the model as an unexplained disappearance.
        # On 2026-07-30 that false alarm told GPT-5 its order had gone "NOT by
        # this loop" 31s after it had deliberately cancelled it, costing an API
        # call and prompting a hasty replacement order into a fast rally.
        SELF_CANCELLED.add(int(args["ticket"]))
    return (("EXECUTED. " if ok else "FAILED. ") + out[-600:]), ok


def build_user_turn(briefing, trigger):
    return (f"Event that woke you:\n{trigger}\n\nCurrent state:\n{briefing}\n\n"
            "Decide. Use a tool - `no_action` if there is nothing worth doing.")


def _log_call(trigger, dry_run, provider, model, stop, usage, text, calls):
    with open(LLM_LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps({
            "ts": datetime.now().isoformat(timespec="seconds"),
            "trigger": trigger, "dry_run": dry_run,
            "provider": provider, "model": model, "stop_reason": stop,
            "usage": usage, "text": text[:2000], "tools": calls,
        }) + "\n")


def _run_calls(calls, dry_run):
    """Execute the model's tool calls in order. Returns (lines, acted)."""
    results, acted = [], False
    for c in calls:
        out, did = execute(c["name"], c["input"], dry_run)
        acted = acted or did
        results.append(f"{c['name']}: {out}")
    return results, acted


def _decide_openai(briefing, trigger, dry_run, model):
    import openai
    client = openai.OpenAI()

    # Same JSON Schema, different envelope - Anthropic's input_schema is
    # OpenAI's function.parameters verbatim.
    fns = [{"type": "function",
            "function": {"name": t["name"], "description": t["description"],
                         "parameters": t["input_schema"]}} for t in TOOLS]

    # Output tokens dominate the bill on a reasoning model - measured 2026-07-30,
    # ~4,000 out vs ~2,300 in per call, and output is priced far higher. These
    # decisions are structurally simple (read a briefing, apply six rules), so
    # deep reasoning buys little. Tune with KL_REASONING_EFFORT.
    effort = os.environ.get("KL_REASONING_EFFORT", "low")

    kwargs = dict(model=model, tools=fns, tool_choice="required",
                  reasoning_effort=effort,
                  messages=[{"role": "system", "content": SYSTEM},
                            {"role": "user", "content": build_user_turn(briefing, trigger)}])

    # Retry by dropping whichever param the model rejects, rather than guessing
    # up front which knobs this particular model accepts.
    for drop in ("reasoning_effort", "tool_choice"):
        try:
            resp = client.chat.completions.create(**kwargs)
            break
        except openai.BadRequestError as e:
            if drop in str(e) and drop in kwargs:
                kwargs.pop(drop)
                continue
            raise
    else:
        resp = client.chat.completions.create(**kwargs)

    msg = resp.choices[0].message
    said = [msg.content.strip()] if (msg.content or "").strip() else []
    calls = []
    for tc in (msg.tool_calls or []):
        try:
            args = json.loads(tc.function.arguments)
        except json.JSONDecodeError:
            said.append(f"UNPARSEABLE tool arguments for {tc.function.name}: "
                        f"{tc.function.arguments[:300]}")
            continue
        calls.append({"name": tc.function.name, "input": args})

    results, acted = _run_calls(calls, dry_run)
    u = resp.usage
    _log_call(trigger, dry_run, "openai", model, resp.choices[0].finish_reason,
              {"in": u.prompt_tokens, "out": u.completion_tokens},
              " ".join(said), calls)
    return ("\n".join(said + results) or "(model returned nothing)"), acted


def _decide_claude(briefing, trigger, dry_run, model):
    import anthropic
    client = anthropic.Anthropic()
    resp = client.messages.create(
        model=model, max_tokens=4000,
        system=[{"type": "text", "text": SYSTEM, "cache_control": {"type": "ephemeral"}}],
        tools=TOOLS,
        thinking={"type": "adaptive"},
        output_config={"effort": "high"},
        messages=[{"role": "user", "content": build_user_turn(briefing, trigger)}],
    )
    if resp.stop_reason == "refusal":
        return "Model declined the request (stop_reason=refusal).", False

    said = [b.text.strip() for b in resp.content
            if b.type == "text" and b.text.strip()]
    calls = [{"name": b.name, "input": b.input}
             for b in resp.content if b.type == "tool_use"]
    results, acted = _run_calls(calls, dry_run)
    _log_call(trigger, dry_run, "claude", model, resp.stop_reason,
              {"in": resp.usage.input_tokens, "out": resp.usage.output_tokens,
               "cache_read": getattr(resp.usage, "cache_read_input_tokens", 0),
               "cache_write": getattr(resp.usage, "cache_creation_input_tokens", 0)},
              " ".join(said), calls)
    return ("\n".join(said + results) or "(model returned nothing)"), acted


KEYVAR   = {"openai": "OPENAI_API_KEY", "claude": "ANTHROPIC_API_KEY"}
DISPATCH = {"openai": _decide_openai, "claude": _decide_claude}


def _try(provider, briefing, trigger, dry_run, model=None):
    """One attempt at one provider. Returns (summary, acted) or raises."""
    kv = KEYVAR.get(provider)
    if kv and not os.environ.get(kv):
        raise RuntimeError(f"{kv} not set")
    fn = DISPATCH.get(provider)
    if fn is None:
        raise NotImplementedError(f"provider '{provider}' not wired")
    mdl = model or DEFAULT_MODELS.get(provider)
    # Stamp before dispatch, not after: the tool calls (and therefore
    # log_decision) run inside fn(), so setting this afterwards would attribute
    # every decision to whoever answered LAST time.
    _CURRENT.update(provider=provider, model=mdl)
    return fn(briefing, trigger, dry_run, mdl)


# How long a handoff may sit unanswered before the session is presumed gone.
# Generous on purpose: a Claude session can legitimately take several minutes to
# be woken by a Monitor and reply, and falling back too eagerly would hand trades
# to GPT-5 while someone is actively working. Twenty minutes is far longer than a
# real reply takes and far shorter than a night of silence.
SESSION_TIMEOUT_MIN = 20


def _session_unanswered_minutes():
    """Minutes the newest handoff has gone unanswered, or None if none is pending.

    A handoff is 'answered' when any decision row appears AFTER it from the
    session - that is the only observable proof a human-in-the-loop is actually
    reading. Process liveness proves nothing here: the daemon can be perfectly
    healthy and writing into the void because the terminal was closed.
    """
    try:
        with open(DECISIONS, newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
    except Exception:
        return None
    last_await = None
    for r in rows:
        if r.get("action", "").endswith("AWAIT_SESSION"):
            last_await = r
        elif last_await is not None and r.get("provider") == "claude-session":
            last_await = None                      # a later session decision answered it
    if last_await is None:
        return None
    try:
        age = datetime.now() - datetime.fromisoformat(last_await["time"])
        return age.total_seconds() / 60.0
    except Exception:
        return None


def _write_handoff(trigger, briefing, dry_run, reason, errors=None):
    """Everything the Claude session needs to decide, in one file.

    Written both when the session IS the primary decider and when every API has
    failed. The briefing is included in full rather than a summary: whoever picks
    this up must not have to reconstruct state from the log, because that is
    exactly where a stale assumption creeps in.
    """
    try:
        with open(os.path.join(HERE, "NEEDS_HUMAN.json"), "w", encoding="utf-8") as f:
            json.dump({"ts": datetime.now().isoformat(timespec="seconds"),
                       "reason": reason, "trigger": trigger,
                       "errors": errors or [], "briefing": briefing,
                       "dry_run": dry_run}, f, indent=2)
    except Exception:
        pass


def decide(briefing, trigger, dry_run=True, provider=None, model=None):
    """One decision cycle, with automatic failover to the other provider.

    The primary can die in ways that all look the same from here: balance
    exhausted, rate limit, 5xx, network drop, missing key. Rather than
    enumerate them, any exception from the primary triggers a single attempt
    on the other provider.

    If BOTH fail the loop takes NO ACTION and says so. Failing safe means not
    trading, never guessing - a decider that cannot see the market must not
    place an order, and an open position keeps its server-side SL/TP regardless.
    """
    primary = provider or default_provider()

    # KL_PROVIDER=session hands every decision to the attached Claude Code session
    # instead of an API. Same events, same briefing - only the decider changes.
    # It costs nothing (no API call) and is what the user asked for while the edge
    # research is unresolved, but be honest about the trade: a decision now waits
    # for a human-in-the-loop to be woken by a Monitor, so latency is minutes not
    # seconds, and NOTHING decides at all when no session is attached.
    #
    # That is safe rather than reckless: an open position keeps its server-side
    # SL and TP whatever happens here, and a missed wake means no NEW trade, not
    # an unmanaged one. Failing closed is the correct failure for a decider.
    if primary == "session":
        stale_min = _session_unanswered_minutes()
        if stale_min is not None and stale_min >= SESSION_TIMEOUT_MIN and os.environ.get("OPENAI_API_KEY"):
            # The session has stopped answering - almost always because the
            # terminal was closed. Without this the daemon would keep writing
            # handoffs nobody reads and trade nothing, forever, while every
            # heartbeat stayed green. Hand over to the API rather than go quiet.
            try:
                summary, acted = _try("openai", briefing, trigger, dry_run, None)
                return (f"[SESSION SILENT {stale_min:.0f} min - fell back to GPT-5]\n" + summary), acted
            except Exception as e:
                errs = [f"openai: {type(e).__name__}: {str(e)[:140]}"]
                _write_handoff(trigger, briefing, dry_run,
                               reason="session silent AND openai failed", errors=errs)
                _CURRENT.update(provider="none", model="none")
                log_decision("ESCALATE", "session silent, openai failed", " | ".join(errs), dry_run)
                return ("*** SESSION SILENT AND GPT-5 FAILED - no decision, no action. "
                        + " | ".join(errs) + " Any open position still has its stop and target "
                        "on the broker."), False

        _CURRENT.update(provider="claude-session", model="claude-in-session")
        _write_handoff(trigger, briefing, dry_run, reason="session is the primary decider")
        log_decision("AWAIT_SESSION", "handed to Claude session", trigger[:200], dry_run)
        return ("*** DECISION NEEDED - CLAUDE SESSION *** " + trigger[:300] +
                " | Context written to NEEDS_HUMAN.json. No action taken by the loop. "
                "Any open position still has its stop and target on the broker."), False

    order = [primary] + [p for p in ("openai", "claude") if p != primary]

    errors = []
    for i, prov in enumerate(order):
        try:
            summary, acted = _try(prov, briefing, trigger, dry_run,
                                  model if prov == primary else None)
            if i > 0:
                summary = (f"[FAILOVER: {primary} failed ({errors[0]}), "
                           f"decided by {prov}]\n" + summary)
            return summary, acted
        except Exception as e:
            errors.append(f"{prov}: {type(e).__name__}: {str(e)[:140]}")
            continue

    # Last resort: escalate to the human-in-the-loop Claude session. Write the
    # full context to disk and emit a distinctive log line that a Monitor tails.
    # This only helps while a Claude Code session is attached - if nobody is
    # watching, the position still has its server-side SL/TP and that is the
    # actual safety net. Escalation is a convenience, not a guarantee.
    _write_handoff(trigger, briefing, dry_run, reason="all providers failed", errors=errors)
    # Not attributable to any provider - _CURRENT still holds whoever was tried
    # last, which would score this failure against a model that never answered.
    _CURRENT.update(provider="none", model="none")
    log_decision("ESCALATE", "all providers failed", " | ".join(errors), dry_run)
    return ("*** ALL PROVIDERS FAILED - ESCALATING TO HUMAN *** "
            + " | ".join(errors)
            + " | Context written to NEEDS_HUMAN.json. No action taken. "
              "Any open position still has its stop and target on the broker."), False
