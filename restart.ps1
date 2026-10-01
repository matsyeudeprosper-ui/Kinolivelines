# restart.ps1 - the only way a bot should be restarted by hand.
#
# 2026-09-30: a patch added two USES of a name whose DEFINITION was never
# written. The file compiled, the bots restarted clean, and then threw
# NameError on two REAL accounts for two minutes. The check that catches
# that existed by the evening - but it only runs if somebody remembers, and
# remembering is the part that failed.
#
# So: check first, refuse on failure, restart, count what came back.
#
#   .\restart.ps1                     every bot + app + feed
#   .\restart.ps1 expenses            one bot variant
#   .\restart.ps1 -What app           app only   (app | feed | bots | all)
#   .\restart.ps1 -SkipCheck          only with a reason you can say out loud
param(
    [string]$Variant = "",
    [ValidateSet("all", "app", "feed", "bots")][string]$What = "all",
    [switch]$SkipCheck
)
$ErrorActionPreference = "Stop"
$LIVE = "C:\Projects\KinoliveLines\live"
$ROOT = "C:\Projects\KinoliveLines"
$PY = "C:\Users\Administrator\AppData\Local\Programs\Python\Python311\python.exe"
$PYW = "C:\Users\Administrator\AppData\Local\Programs\Python\Python311\pythonw.exe"

function Say($m) { Write-Host $m }

# ---- 1. the check -----------------------------------------------------
if (-not $SkipCheck) {
    Say "pre-flight..."
    $out = & $PY (Join-Path $ROOT "review\preflight.py") 2>&1
    $rc = $LASTEXITCODE
    $out | ForEach-Object { Say ("  " + $_) }
    if ($rc -ne 0) {
        Say ""
        Say "REFUSING TO RESTART. Fix the names above first."
        Say "If you are certain, re-run with -SkipCheck."
        exit 1
    }
} else {
    Say "pre-flight SKIPPED by request"
}

# ---- 2. what is running now -------------------------------------------
function Running($pattern) {
    Get-CimInstance Win32_Process -Filter "Name like 'python%'" |
        Where-Object { $_.CommandLine -like $pattern }
}
$before = @{
    app  = @(Running "*owl_app_server.py*").Count
    feed = @(Running "*owl_chart_feed.py*").Count
    bots = @(Running "*structure_bos_bot.py*").Count
}
Say ""
Say ("before: app " + $before.app + ", feed " + $before.feed + ", bots " + $before.bots)

# ---- 3. stop, remembering each bot's own argument ---------------------
$botArgs = @()
if ($What -eq "all" -or $What -eq "bots") {
    $procs = Running "*structure_bos_bot.py*"
    foreach ($p in $procs) {
        $a = ($p.CommandLine -split 'structure_bos_bot\.py')[-1].Trim(' "')
        if ($Variant -ne "" -and $a -ne $Variant) { continue }
        $botArgs += $a
        Stop-Process -Id $p.ProcessId -Force
    }
}
if ($What -eq "all" -or $What -eq "app") {
    Running "*owl_app_server.py*" | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
}
if ($What -eq "all" -or $What -eq "feed") {
    Running "*owl_chart_feed.py*" | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
}
Start-Sleep -Seconds 4

# ---- 4. start -----------------------------------------------------------
foreach ($a in $botArgs) {
    if ($a -eq "") {
        Start-Process $PYW -ArgumentList "structure_bos_bot.py" -WorkingDirectory $LIVE -WindowStyle Hidden
    } else {
        Start-Process $PYW -ArgumentList "structure_bos_bot.py", $a -WorkingDirectory $LIVE -WindowStyle Hidden
    }
    Start-Sleep -Seconds 2
}
if ($What -eq "all" -or $What -eq "feed") {
    Start-Process $PYW -ArgumentList "owl_chart_feed.py" -WorkingDirectory $LIVE -WindowStyle Hidden
}
if ($What -eq "all" -or $What -eq "app") {
    Start-Process $PYW -ArgumentList "owl_app_server.py" -WorkingDirectory $LIVE -WindowStyle Hidden
}
Start-Sleep -Seconds 12

# ---- 5. count what came back, and say if it does not match -------------
$after = @{
    app  = @(Running "*owl_app_server.py*").Count
    feed = @(Running "*owl_chart_feed.py*").Count
    bots = @(Running "*structure_bos_bot.py*").Count
}
Say ("after : app " + $after.app + ", feed " + $after.feed + ", bots " + $after.bots)
$bad = $false
foreach ($k in @("app", "feed", "bots")) {
    if ($after[$k] -lt $before[$k]) {
        Say ("MISSING: " + $k + " went from " + $before[$k] + " to " + $after[$k])
        $bad = $true
    }
}
$port = (Get-NetTCPConnection -LocalPort 8787 -State Listen -ErrorAction SilentlyContinue |
         Select-Object -First 1).OwningProcess
if ($What -eq "all" -or $What -eq "app") {
    if ($port) { Say ("app is listening on 8787, pid " + $port) }
    else { Say "app is NOT listening on 8787"; $bad = $true }
}
Say ""
if ($bad) { Say "RESTART INCOMPLETE - look above."; exit 1 }
Say "restart ok"
exit 0
