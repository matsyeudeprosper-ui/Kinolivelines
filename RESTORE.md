# KinoliveLines — restore after a restart or a closed Claude session

**Read this first in a new session.** It is the handoff document.

## The split: who does what

| Role | Who | Survives a closed Claude session? |
|---|---|---|
| **Decides & trades** | GPT-5, via `live/daemon.py` | ✅ **YES — keeps trading unattended** |
| Captures price/ticks | `recorder/recorder.py` | ✅ yes |
| **Captures derivatives** | `recorder/derivs_recorder.py` | ✅ yes — **do not stop this** |
| **Captures microstructure** | `recorder/microstructure_recorder.py` | ✅ yes — **do not stop this** |
| Executes orders safely | `live/act.py` | ✅ yes (called by the daemon) |
| **Watches, reports, fixes bugs** | Claude, in a session | ❌ **NO — dies with the terminal** |

### ⚠ `derivs_recorder.py` is a 30-day asset — leave it running
Started 2026-07-31 20:10 UTC. It polls OKX every 5 minutes for open interest, contract volume, long/short account ratio, taker buy/sell volume, and funding (OKX + Deribit), appending to `recorder/data/derivs_BTC.csv`.

**Why it exists:** twelve entry ideas built on BTC's own OHLC were tested and all came back empty (see the `mt5-entry-research-map` memory). The one direction not exhausted is information the price chart does not contain — leverage, positioning, funding stress. That data is free but OKX only serves **2 days** of 5-minute history, so it was untestable on 2026-07-31 at ~700 observations. Recording forward turns that into ~8,600 observations in a month.

**Nothing is testable from it before roughly 2026-08-30.** Killing this process resets that clock to zero, and the history cannot be bought back — it is the only irreplaceable thing in the stack.

Binance and Bybit are geo-blocked from this server (HTTP 451 / 403). OKX and Deribit work.

### ⚠ `microstructure_recorder.py` — also irreplaceable, also leave running
Started 2026-07-31 20:29 UTC. Every 2 seconds it records the Exness BTCUSDm quote and the OKX BTC-USDT order book **side by side**, into `recorder/data/micro_BTCUSDm_YYYYMMDD.csv` (rotates daily).

**Two questions it will answer, neither of which any OHLC feed can:**
1. **Broker lag.** Exness quote BTCUSDm themselves; the price is derived from real exchange prices. If their feed trails the real market, that is exploitable *without predicting anything*. First observation on the day it started: OKX sat flat at 63,006.2 for sixteen seconds while Exness moved +9.5 points toward it — the shape of a feed catching up. One observation proves nothing; that is what the recording is for.
2. **Order book imbalance.** Size resting on bid vs ask at the real exchange, a short-horizon predictor in most markets. OKX serves the live book but NO history.

**Verified before running:** the OKX book endpoint is genuinely live, not cached — its own timestamp advances on every poll and data is ~1.1s stale. A flat price is a quiet market, not a stale feed. Check this again if the data ever looks frozen for long stretches.

**Reading the data later:** the raw gap between the two feeds is roughly −63 points, which is mostly the **USDT basis** (BTC-USDT vs BTC-USD), not a lag. Analyse CHANGES, never levels.

That asymmetry is the important part. **Closing the session does not stop trading.** It removes oversight from a system in which four separate rule-specification bugs were found on day one, all by reading live output. If you are away for a long stretch and want it stopped, kill the daemon (below).

## ⚠️ ONE Claude session at a time

**Check for an existing session before starting one.** Two sessions each follow the resume
instructions below — including "kill orphaned watcher.py and start your own" — so each sees the
other's process as an orphan and they fight over it indefinitely. This happened on 2026-07-30: the
second session killed the first's watcher within two minutes.

That instance was harmless (the watcher is read-only). The dangerous versions are the same collision
on the **daemon** — killing a live trading process — and **two health-check crons** that both decide
the daemon is dead and start two, which then race on the same account and can breach
one-position-at-a-time.

`KinoliveLines.cmd` now detects a running `claude.exe` and asks before opening a second.
If you find two open, close one, kill any orphaned `python.exe ... watcher.py`, and re-arm the
Monitor from the surviving session.

## ⚠ WHO DECIDES TRADES — check this FIRST, it changes your job

**`live/decider_state.json` is the single source of truth.** Read it before doing anything else.

```powershell
powershell -File C:\Projects\KinoliveLines\set_decider.ps1            # show current
powershell -File C:\Projects\KinoliveLines\set_decider.ps1 openai     # GPT-5 decides
powershell -File C:\Projects\KinoliveLines\set_decider.ps1 session    # Claude decides
```

| decider | who acts | latency | cost | unattended? |
|---|---|---|---|---|
| `openai` | GPT-5 autonomously | ~20s | **~$85/month real money** | ✅ yes |
| `session` | the attached Claude session | minutes | **$0** | ❌ **nothing decides** |

**Set to `session` on 2026-07-31** at the user's request, while the edge research is unresolved — GPT-5 was costing real money to trade a strategy measured as having no edge.

**If the decider is `session` you MUST arm a persistent Monitor** on `daemon.log` matching `DECISION NEEDED|AWAIT_SESSION|ALL PROVIDERS FAILED`. Without it the daemon writes handoffs to `NEEDS_HUMAN.json` that nobody ever reads, and it looks healthy the whole time. That file holds the full briefing — decide from it, then act through `act.py` with `KL_DECIDER_PROVIDER=claude-session` set so `decisions.csv` attributes correctly.

### The re-attach deadlock — fixed 2026-08-02, know how it works

Arming the Monitor was **not enough** on its own. The 20-minute fallback used to short-circuit
*before* writing a handoff, so once a session died past the timeout, a newly attached session was
never asked anything, could never answer, and the unanswered `AWAIT_SESSION` stayed unanswered
forever. Result: **25 hours of decisions silently routed to GPT-5** (63 paid calls) while
`KL_PROVIDER=session`, `decider_state.json` said `session`, and every heartbeat read green.

`brain._session_attached()` now reads `live/watcher_alive.json`. The watcher is a child of the
session's Monitor and dies with the terminal, so a fresh heartbeat is the one thing on disk that
cannot outlive the session that wrote it. Fresh ⇒ never fall back, just write the handoff and wait.
Threshold 360s, set from measured cadence (79–104s, see trap 10) — **not** from `POLL=30`.

**If you find GPT-5 deciding while the policy says session,** the lock is a stale unanswered
handoff. Clear it with one log-only action, no order:

```powershell
$env:KL_DECIDER_PROVIDER="claude-session"; $env:KL_DECIDER_MODEL="claude-in-session"
python C:\Projects\KinoliveLines\live\act.py note NO_ACTION "session re-attached" "reclaiming primary"
```

**Nothing deciding is SAFE, not broken.** No decider means no NEW trades; it does not mean unmanaged ones. Every open position keeps its stop and target on Exness's server regardless of what happens in this stack — that is the real safety net and it never depended on any model.

Switching back is one command and needs no code change. `set_decider.ps1` restarts the daemon with the right environment and rewrites `decider_state.json`; the launcher and the hourly health check both read that file rather than assuming.

## Resume the watch-and-fix loop

Open Claude Code anywhere and paste:

```
Read C:\Projects\KinoliveLines\RESTORE.md and resume the KinoliveLines watch-and-fix loop:
restart the event watcher as a persistent Monitor, arm the decider-escalation Monitor,
re-create the hourly health-check cron, then report current state. GPT-5 owns trading
decisions — you observe, report and fix code. Do not trade.
```

That single paste rebuilds everything Claude-side. The three pieces it restores:

1. **Event watcher** (notifies Claude): `cd C:/Projects/KinoliveLines/live && python -u watcher.py`
   Arm it with the Monitor tool, `persistent: true`. It only notifies — it never trades.
2. **Decider-escalation Monitor** — the tier-3 fallback (below). Arm with `persistent: true`:
   ```
   tail -n 0 -F "C:/Projects/KinoliveLines/live/daemon.log" 2>/dev/null | grep -E --line-buffered "ALL PROVIDERS FAILED|ESCALAT|provider .* failed|FAILOVER"
   ```
3. **Hourly health-check cron** at `:37` — verifies the three components, restarts dead ones,
   kills duplicate processes, reports state. **It must not trade** — two decision makers on one
   account race each other and can breach the one-position rule.

## Decider failover — three tiers

`brain.decide()` tries each in order and stops at the first that answers:

| Tier | Decider | Needs | Survives a closed session? |
|---|---|---|---|
| 1 | GPT-5 | `OPENAI_API_KEY` (User env var) | ✅ yes |
| 2 | Claude API | `ANTHROPIC_API_KEY` — **not set**, so skipped | ✅ yes, if set |
| 3 | **Claude in this session** | nothing | ❌ **no — must be re-armed** |

Tier 3 is file-based on the daemon side and therefore automatic: on total failure `brain.py` writes
`live/NEEDS_HUMAN.json` (full briefing, trigger, both errors) and logs a line containing
`ALL PROVIDERS FAILED / ESCALATING TO HUMAN`. **What is not automatic is the Monitor that reads that
line and wakes Claude** — it is a session object and dies with the terminal. Re-arm it every session
(piece 2 above), or an OpenAI outage is logged and nothing else.

**With no session attached this is not a disaster.** The real safety net is the server-side SL/TP on
any open position, which needs no decider at all. What an unattended outage costs is new entries and
early exits, not protection.

If woken by an escalation: read `NEEDS_HUMAN.json`, then act through `act.py` as the decider — this
is the one situation where Claude trades rather than observes.

## Architecture

```
EXNESS  ← SL/TP live here, execute even with this PC off
   │
MT5 terminal (C:\Program Files\MetaTrader 5)  account 436771046 DEMO
   │  MetaTrader5 python API — always pinned by path AND verified by login
   ├── recorder.py     5s poll  → ticks / bars / fills CSVs (read-only)
   └── daemon.py      30s poll  → detect → briefing.py → brain.py (GPT-5) → act.py
```

**Decision flow:** an event fires → `briefing.py` builds state → `brain.decide()` calls GPT-5 with
the rules as a system prompt and six tools → the model returns a tool call → `brain.execute()`
routes it to `act.py` → `act.py` independently re-verifies → order sent → logged.

## Files

| File | Role |
|---|---|
| `live/daemon.py` | the 24/7 loop; event detection, wakes the model |
| `live/brain.py` | **the rules** (system prompt), tool definitions, provider dispatch |
| `live/act.py` | guarded order execution — the safety layer |
| `live/briefing.py` | one-shot state snapshot fed to the model |
| `live/watch_config.json` | levels that wake the loop; the model maintains these itself |
| `live/decisions.csv` | every action + reason. **The trade record.** |
| `live/llm_calls.jsonl` | full model I/O + token usage per call |
| `live/daemon.log` | event and execution log |
| `recorder/data/` | ticks, M1 bars, fills — the un-overfittable forward sample |

## Restart commands

**Daemon (must preserve the API key — a plain `Start-Process` loses it):**
```powershell
$psi = New-Object System.Diagnostics.ProcessStartInfo
$psi.FileName = "C:\Users\Administrator\AppData\Local\Programs\Python\Python311\pythonw.exe"
$psi.Arguments = '"C:\Projects\KinoliveLines\live\daemon.py" --live'
$psi.WorkingDirectory = "C:\Projects\KinoliveLines\live"
$psi.UseShellExecute = $false
$psi.EnvironmentVariables["OPENAI_API_KEY"] = [Environment]::GetEnvironmentVariable("OPENAI_API_KEY","User")
$psi.EnvironmentVariables["KL_REASONING_EFFORT"] = "low"
[System.Diagnostics.Process]::Start($psi)
```

**Recorder:** `Start-Process pythonw "C:\Projects\KinoliveLines\recorder\recorder.py" -WindowStyle Hidden`

**Derivatives recorder** (check this is alive at every health check):
`Start-Process pythonw "C:\Projects\KinoliveLines\recorder\derivs_recorder.py" -WindowStyle Hidden`
Safe to restart — it deduplicates on the exchange's own timestamp, so a restart or an overlapping poll cannot double-write rows.

**Microstructure recorder** (check this is alive at every health check):
`Start-Process pythonw "C:\Projects\KinoliveLines\recorder\microstructure_recorder.py" -WindowStyle Hidden`
Appends only and rotates daily, so a restart just continues the current day's file.

**Stop the daemon (stops all trading):**
`Get-CimInstance Win32_Process -Filter "Name='pythonw.exe'" | Where-Object { $_.CommandLine -like "*daemon.py*" } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }`

**Modes:** `--live` sends orders · no flag = dry run (decides, sends nothing) · `--no-llm` = plumbing only.
The ONLOGON scheduled task **includes `--live`** — a reboot resumes live trading.

## Health checks

| Check | Where | Fresh means |
|---|---|---|
| daemon alive | `live/daemon_alive.json` → `alive_utc` | < 90s |
| recorder alive | `recorder/data/status.json` → `updated_utc` | < 60s |
| watcher alive | `live/watcher_alive.json` → `alive_utc` | < 90s |
| **derivs alive** | `recorder/data/derivs_alive.json` → `alive_utc` | **< 400s** (5-min poll) |
| **micro alive** | `recorder/data/micro_alive.json` → `alive_utc` | **< 30s** (2-sec poll) |
| duplicates | `Get-CimInstance Win32_Process -Filter "Name='pythonw.exe'"` | **exactly one of each** |

Two recorders double-write the CSVs; two daemons race on orders. Both have happened — check.

## Traps that have actually bitten (do not re-learn these)

1. **Two MT5 terminals run on this box.** A bare `mt5.initialize()` attaches to whichever it likes —
   it once returned account 134499778 ($42.70) while the position being looked for sat on 436771046.
   Every script pins the path **and** verifies the login. Do not remove those guards.
2. **`TradeDeal` has no `sl`/`tp`** — those belong to orders, not deals.
3. **Server time ≠ local time.** Use `pd.to_datetime(unit='s')`, never `datetime.fromtimestamp`.
4. **Oversized bar requests return nothing** rather than truncating. Step down through sizes.
5. **A restart re-baselines watch levels** — a level already broken at restart won't fire until price
   recovers past it and breaks again. Silent blind spot; every restart creates one.
6. **Success detection must match on the MT5 retcode (10009/10008), not formatted text.** A version
   matching `"-> OK"` against output printing `"->  OK"` reported every success as FAILED — and a
   model told its order failed will retry, placing a second live order.
7. **Claude's prose about file state is unreliable.** Twice on 2026-07-30 Claude reported updating
   `watch_config.json` without writing it, and once flattened a conditional plan into a certainty.
   Verify by reading the file, not the summary.
8. **`import daemon` starts a SECOND live daemon.** The loop runs at module level with no `main()`
   guard, so importing the file to test one helper launches a full second daemon on the same account.
   Happened 2026-08-02 — it was dry-run by luck, not design. The file now refuses to be imported.
   To test a helper, run the file as a script or copy the function out.
9. **A trade can fill AND close inside one 30s poll.** The daemon used to check only *currently open*
   positions, so a pending that filled and stopped out between polls was reported to the decider as
   `PENDING GONE — left the book without filling`. The decider was told "nothing happened, you're
   flat" immediately after a loss, and re-placed the same setup. Four times on 2026-08-02. Fixed via
   `order_filled_and_closed()`, which reads deal history — positions lie here, deals do not.
10. **The heartbeat cadence is not the poll interval.** `watcher.py` has `POLL=30` but writes its
   heartbeat *after* its MT5 work, so the real gap is 79–104s (measured 2026-08-02). Any freshness
   threshold built from the 30s constant will fire falsely. Measure, do not read the constant.

## ⚠ The trading rules are NOT listed here — read `brain.py` SYSTEM

**Do not summarise the rules in this file.** This section used to hold a copy, and the copy went
stale. On 2026-08-02 a session read it, saw *"stops outside the noise — ATR(M15) runs $120–160"*,
compared that to the live 20-point stops, and reported the loop as violating its own rule 4. It was
not: rule 4 had been deliberately changed to **a fixed 20 points** and the stale copy here never
caught up. That session then proposed re-opening the stop/target search — which **rule 6b explicitly
closes**, on 30 shapes tested across 68 days — and shipped an `act.py` gate that would have rejected
every rule-compliant order. Caught before it traded, but only just.

```powershell
# The only source of truth. Read it before judging any decision the loop made.
python -c "import sys; sys.path.insert(0,r'C:\Projects\KinoliveLines\live'); import brain; print(brain.SYSTEM)"
```

Two things about those rules that are easy to get wrong from the outside:

- **The tight stop is intentional.** Rule 4 fixes it at 20 points and says being hit often "is not a
  reason to widen it." At 0.01 lots that is $0.20 of risk. The live mirror is an **execution record,
  not a P&L experiment** — losses at this size are the cost of the recording, not evidence.
- **Geometry is a closed question.** Rule 6b: thirty stop/target shapes tested over the full 68 days,
  every one losing 0.021–0.037 ATR per trade, all thirty statistically tied — the loss simply equals
  the spread. Two earlier "findings" here evaporated once timed-out trades were settled at their real
  closing price. **The entry is the only lever.** Do not propose a 31st shape.

## The honest state of the edge

**There isn't one yet.** Four statistical tests on 2026-07-30 — level touches, sweep-and-reclaim,
liquidity-pool sweeps across four symbols, and an out-of-sample check — all showed these lines do
**not** predict direction. Live record day one: **4 trades, 4 losses, −$3.56**, with ~$40 of that
paid in spread. Both Claude's discretionary reads and GPT-5's lost.

The infrastructure is verified working. The strategy is not. Do not let a run of wins imply otherwise
without a fresh out-of-sample test.

## Costs

~$0.019 per decision at `reasoning_effort=low` (was $0.061 at default). Output tokens dominate.
Check spend with `llm_calls.jsonl`; the OpenAI balance is the ground truth.

## Account

`436771046` / `Exness-MT5Trial9` / **DEMO** (`trade_mode 0`). `act.py` refuses to trade if it is not.
