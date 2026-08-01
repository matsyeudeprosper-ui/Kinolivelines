<#
  KinoliveLines launcher — brings the whole stack up and opens Claude ready to watch.

  Safe to run repeatedly. Every step checks before it starts anything, because
  duplicates are a real fault here, not just untidiness: two recorders double-write
  the CSVs, and two daemons race each other on orders. On 2026-07-30 a careless
  restart left two recorders running and corrupted 179 tick rows.

  Order matters: MT5 must be up before the daemon, and both background services
  must be running before Claude is asked to report on them.
#>

$ErrorActionPreference = "Continue"
$PY       = "C:\Users\Administrator\AppData\Local\Programs\Python\Python311\pythonw.exe"
$CLAUDE   = "C:\Users\Administrator\.local\bin\claude.exe"
$MT5      = "C:\Program Files\MetaTrader 5\terminal64.exe"
$ROOT     = "C:\Projects\KinoliveLines"
$DAEMON   = "$ROOT\live\daemon.py"
$RECORDER = "$ROOT\recorder\recorder.py"

function Say($m, $c = "Gray") { Write-Host $m -ForegroundColor $c }

function Running($pattern) {
    Get-CimInstance Win32_Process -Filter "Name='pythonw.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -like "*$pattern*" }
}

function KillExtras($pattern, $label) {
    # Keep the OLDEST instance; a duplicate is always the accidental one.
    $procs = @(Running $pattern | Sort-Object CreationDate)
    if ($procs.Count -gt 1) {
        Say "  ! $($procs.Count) copies of $label running - killing $($procs.Count - 1) duplicate(s)" Yellow
        $procs | Select-Object -Skip 1 | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
        Start-Sleep -Seconds 2
    }
}

Write-Host ""
Say "==== KinoliveLines ====" Cyan
Write-Host ""

# ---- 1. MT5 --------------------------------------------------------------
# Everything else talks to the terminal; without it the daemon just retries.
if (Get-Process terminal64 -ErrorAction SilentlyContinue) {
    Say "[1/4] MT5 already running" Green
} else {
    Say "[1/4] starting MT5..." Yellow
    Start-Process $MT5
    Start-Sleep -Seconds 20
    if (Get-Process terminal64 -ErrorAction SilentlyContinue) { Say "      up" Green }
    else { Say "      FAILED - open MT5 manually and log in to 436771046" Red }
}

# ---- 2. recorder ---------------------------------------------------------
KillExtras "recorder.py" "recorder"
if (Running "recorder.py") {
    Say "[2/4] recorder already running" Green
} else {
    Say "[2/4] starting recorder..." Yellow
    Start-Process -FilePath $PY -ArgumentList $RECORDER -WindowStyle Hidden
    Start-Sleep -Seconds 5
    if (Running "recorder.py") { Say "      up" Green } else { Say "      FAILED" Red }
}

# ---- 3. the two research recorders ---------------------------------------
# These accumulate history that CANNOT be backfilled - derivatives positioning and
# broker-vs-exchange microstructure. Twelve entry ideas built on OHLC came back
# empty; these two datasets are the only live research thread, and every hour they
# are down is an hour permanently missing.
foreach ($r in @(@{f="derivs_recorder.py";  n="derivs"},
                 @{f="microstructure_recorder.py"; n="microstructure"})) {
    KillExtras $r.f $r.n
    if (Running $r.f) {
        Say "[3/5] $($r.n) recorder already running" Green
    } else {
        Say "[3/5] starting $($r.n) recorder..." Yellow
        Start-Process -FilePath $PY -ArgumentList "`"$ROOT\recorder\$($r.f)`"" -WindowStyle Hidden
        Start-Sleep -Seconds 3
        if (Running $r.f) { Say "      up" Green } else { Say "      FAILED" Red }
    }
}

# ---- 4. daemon, using whichever decider is currently configured -----------
# decider_state.json is the single source of truth for who decides. set_decider.ps1
# writes it and restarts the daemon with the matching environment, so the launcher
# never has to guess - and neither does anyone reading this later.
KillExtras "daemon.py" "daemon"
$state = Join-Path $ROOT "live\decider_state.json"
$decider = if (Test-Path $state) { (Get-Content $state -Raw | ConvertFrom-Json).decider } else { "openai" }
if (Running "daemon.py") {
    Say "[4/5] daemon already running (LIVE, decider=$decider)" Green
} else {
    Say "[4/5] starting daemon LIVE with decider '$decider'..." Yellow
    & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $ROOT "set_decider.ps1") $decider | Out-Null
    Start-Sleep -Seconds 5
    if (Running "daemon.py") { Say "      up - decider is '$decider'" Green }
    else { Say "      FAILED - check $ROOT\live\daemon.log" Red }
}
if ($decider -eq "session") {
    Say "      NOTE: decider is the Claude session - it must arm a Monitor on daemon.log" Yellow
    Say "      or handoffs are written and never read. The resume prompt covers this." Yellow
}

# ---- 4. state ------------------------------------------------------------
Write-Host ""
Say "---- account ----" Cyan
$env:OPENAI_API_KEY = [Environment]::GetEnvironmentVariable("OPENAI_API_KEY", "User")
& "C:\Users\Administrator\AppData\Local\Programs\Python\Python311\python.exe" -c @"
import MetaTrader5 as mt5
if mt5.initialize(path=r'C:\Program Files\MetaTrader 5\terminal64.exe'):
    a = mt5.account_info(); t = mt5.symbol_info_tick('BTCUSDm')
    mode = 'DEMO' if a.trade_mode == 0 else '*** NOT DEMO ***'
    print(f'  {a.login} {mode}  equity {a.equity}  bid {t.bid}')
    print(f'  positions {mt5.positions_total()}   orders {mt5.orders_total()}')
    for p in (mt5.positions_get() or []):
        print(f'    POSITION #{p.ticket} {"BUY" if p.type==0 else "SELL"} {p.volume} @ {p.price_open} P&L {p.profit:+.2f}')
    for o in (mt5.orders_get() or []):
        print(f'    PENDING  #{o.ticket} @ {o.price_open} SL {o.sl} TP {o.tp}')
    mt5.shutdown()
else:
    print('  could not reach MT5')
"@ 2>&1

Write-Host ""

# ---- 4. Claude ------------------------------------------------------------
# Only ONE session may run. Two sessions each follow RESTORE.md's instruction to
# kill "orphaned" watcher.py processes and start their own - so they fight over
# it indefinitely, each seeing the other's process as the orphan. It happened on
# 2026-07-30: the second session killed the first's watcher within two minutes.
# Harmless there because the watcher is read-only. The same collision on the
# daemon would kill a live trading process, and two health-check crons that both
# decide the daemon is dead will start two daemons that race on the same account.
$existing = @(Get-CimInstance Win32_Process -Filter "Name='claude.exe'" -ErrorAction SilentlyContinue)
if ($existing.Count -gt 0) {
    Say "[4/4] A Claude session is ALREADY RUNNING (pid $($existing.ProcessId -join ', '))." Yellow
    Write-Host ""
    Say "      Two sessions fight over the watcher and can start duplicate daemons." Yellow
    Say "      Background services are up to date - switch to the existing window." Yellow
    Write-Host ""
    $ans = Read-Host "      Open a second session anyway? (y/N)"
    if ($ans -notmatch '^[Yy]') {
        Say "      Not opening. Services are running; use your existing Claude window." Green
        Write-Host ""
        return
    }
    Say "      Opening anyway - close one window as soon as you can." Red
}

Say "[4/4] opening Claude to watch and fix..." Yellow
Write-Host ""

# The escalation Monitor is named explicitly because it is the tier-3 fallback and is
# the ONLY part of failover that does not survive a closed session. The daemon-side
# code is file-based and loads itself on start; the wake-up is a session object.
$prompt = "Read C:\Projects\KinoliveLines\RESTORE.md, then read live\decider_state.json to find out WHO DECIDES TRADES - " +
          "that file is the single source of truth and the answer changes what your job is. " +
          "If decider is 'session' YOU decide, woken by daemon events via NEEDS_HUMAN.json, and you MUST arm a persistent " +
          "Monitor on daemon.log matching 'DECISION NEEDED|AWAIT_SESSION|ALL PROVIDERS FAILED' or handoffs are written and never read. " +
          "If decider is 'openai' GPT-5 decides and you observe, report and fix code only - do not trade. " +
          "Either way: arm the event watcher Monitor, re-create the hourly health-check cron, confirm BOTH research recorders " +
          "(derivs_recorder, microstructure_recorder) are alive since their history cannot be backfilled, then report state. " +
          "Verify rather than assume: read the file or the log before stating what a component did, " +
          "measure before writing any threshold, and after adding a gate confirm it actually fired. " +
          "Report findings short and structured."

# Claude's memory is scoped per PROJECT DIRECTORY - the directory it starts in
# decides which .claude\projects\<slug>\memory\ it loads. Starting it in
# $ROOT\live gave it the slug C--Projects-KinoliveLines-live, which has zero
# memory files, so every launched session ran without the 32 accumulated
# memories: the project history, the edge-research verdict, and the feedback
# entries that encode how to verify things rather than assume them. RESTORE.md
# was the only channel that survived. Start where the memory actually lives;
# every path in $prompt and RESTORE.md is absolute, so nothing else depends on
# the working directory.
Set-Location "C:\Users\Administrator\.local\bin"
& $CLAUDE $prompt
