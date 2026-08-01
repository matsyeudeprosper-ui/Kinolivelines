<#
  Switch who decides trades, and record it where everything else can read it.

    powershell -File C:\Projects\KinoliveLines\set_decider.ps1 openai
    powershell -File C:\Projects\KinoliveLines\set_decider.ps1 session
    powershell -File C:\Projects\KinoliveLines\set_decider.ps1          (shows current)

  WHY A SCRIPT RATHER THAN AN ENV VAR: the daemon reads KL_PROVIDER from its own
  process environment, which is invisible once it is running. Anyone - a future
  Claude session, the hourly health check, or the user next week - needs to know
  who is deciding WITHOUT guessing from log archaeology. So the choice is written
  to decider_state.json, and that file is the single source of truth.

  Restarting is unavoidable: the environment is fixed at process start. This does
  it safely - the daemon is stateless between polls, and any open position keeps
  its stop and target on the broker throughout.

  session : the attached Claude Code session decides, woken by NEEDS_HUMAN.json
            and a Monitor on daemon.log. Costs nothing. Latency is minutes, and
            NOTHING decides while no session is attached - which is safe, because
            it means no NEW trades rather than unmanaged ones.
  openai  : GPT-5 decides autonomously, ~20s latency, keeps running unattended.
            Costs roughly $85/month at the observed rate.
#>

param([string]$Decider = "")

$ErrorActionPreference = "Stop"
$ROOT   = "C:\Projects\KinoliveLines"
$STATE  = Join-Path $ROOT "live\decider_state.json"
$PY     = "C:\Users\Administrator\AppData\Local\Programs\Python\Python311\pythonw.exe"
$DAEMON = Join-Path $ROOT "live\daemon.py"

function Show-Current {
    if (Test-Path $STATE) {
        $s = Get-Content $STATE -Raw | ConvertFrom-Json
        Write-Host ""
        Write-Host "current decider : $($s.decider)" -ForegroundColor Cyan
        Write-Host "set at          : $($s.set_at)"
        Write-Host "note            : $($s.note)"
    } else {
        Write-Host "no decider_state.json - decider unknown" -ForegroundColor Yellow
    }
    $p = Get-CimInstance Win32_Process -Filter "Name='pythonw.exe'" -ErrorAction SilentlyContinue |
         Where-Object { $_.CommandLine -like "*daemon.py*" }
    if ($p) { Write-Host "daemon          : running, pid $($p.ProcessId)" }
    else    { Write-Host "daemon          : NOT RUNNING" -ForegroundColor Yellow }
    Write-Host ""
}

if ([string]::IsNullOrWhiteSpace($Decider)) { Show-Current; exit 0 }

$Decider = $Decider.ToLower()
if ($Decider -notin @("openai", "session")) {
    Write-Host "usage: set_decider.ps1 [openai|session]" -ForegroundColor Red
    exit 1
}

# An API decider without its key would detect events and silently decide nothing.
$key = [Environment]::GetEnvironmentVariable("OPENAI_API_KEY", "User")
if ($Decider -eq "openai" -and -not $key) {
    Write-Host "OPENAI_API_KEY is not set for this user - GPT-5 cannot decide." -ForegroundColor Red
    Write-Host "set it, or use: set_decider.ps1 session" -ForegroundColor Red
    exit 1
}

Get-CimInstance Win32_Process -Filter "Name='pythonw.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -like "*daemon.py*" } |
    ForEach-Object { Write-Host "stopping daemon pid $($_.ProcessId)"; Stop-Process -Id $_.ProcessId -Force }
Start-Sleep -Milliseconds 1500

$psi = New-Object System.Diagnostics.ProcessStartInfo
$psi.FileName         = $PY
$psi.Arguments        = "`"$DAEMON`" --live"
$psi.WorkingDirectory = Join-Path $ROOT "live"
$psi.UseShellExecute  = $false
$psi.EnvironmentVariables["KL_PROVIDER"]      = $Decider
$psi.EnvironmentVariables["PYTHONIOENCODING"] = "utf-8"
# The key is passed even for 'session' so a switch back needs no re-entry, and so
# the API failover tier still exists if it is ever wanted.
if ($key) { $psi.EnvironmentVariables["OPENAI_API_KEY"] = $key }
if ($Decider -eq "openai") { $psi.EnvironmentVariables["KL_REASONING_EFFORT"] = "low" }

$proc = [System.Diagnostics.Process]::Start($psi)

$note = if ($Decider -eq "session") {
    "Claude Code session decides. Zero API cost. Needs a Monitor armed on daemon.log for DECISION NEEDED|AWAIT_SESSION, or handoffs are written and never read. Nothing decides while no session is attached - open positions still hold their broker-side SL/TP."
} else {
    "GPT-5 decides autonomously, ~20s latency, runs unattended. Costs roughly `$85/month at the observed rate."
}

@{ decider = $Decider
   set_at  = (Get-Date).ToString("s")
   pid     = $proc.Id
   note    = $note } | ConvertTo-Json | Set-Content $STATE -Encoding utf8

Write-Host ""
Write-Host "decider set to '$Decider' - daemon restarted, pid $($proc.Id)" -ForegroundColor Green
if ($Decider -eq "session") {
    Write-Host "REMINDER: arm a persistent Monitor on daemon.log matching" -ForegroundColor Yellow
    Write-Host "  DECISION NEEDED|AWAIT_SESSION|ALL PROVIDERS FAILED" -ForegroundColor Yellow
    Write-Host "or the daemon will write handoffs that nobody reads." -ForegroundColor Yellow
}
Write-Host ""
