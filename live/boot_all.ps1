# boot_all.ps1 - revive the whole Kinolive stack after a reboot/logon.
# Idempotent: only starts what is not already running. Registered by the
# USER as a scheduled task (auto-trading launch authority = user).
$log = "C:\Projects\KinoliveLines\live\boot_all.log"
function Say($m) {
    Add-Content -Path $log -Value ("{0} {1}" -f (Get-Date -Format o), $m)
}
Say "boot_all run"

function ProcRunning($match) {
    $p = Get-CimInstance Win32_Process |
        Where-Object { $_.CommandLine -like ("*" + $match + "*") }
    return ($null -ne $p)
}

# 1) live MT5 terminal
if (-not (ProcRunning "MT5-KinoliveTrader\terminal64.exe")) {
    Say "starting live terminal"
    Start-Process "C:\Projects\MT5-KinoliveTrader\terminal64.exe"
    Start-Sleep -Seconds 30
}

# 2) live Owl (KINO machine)
if (-not (ProcRunning "owl_manual_bot.py")) {
    Say "starting live Owl"
    Start-Process python -ArgumentList "owl_manual_bot.py" `
        -WorkingDirectory "C:\Projects\KinoliveLines\live" -WindowStyle Hidden
}

# 3) OwlNest app server
if (-not (ProcRunning "owl_app_server.py")) {
    Say "starting OwlNest"
    Start-Process python -ArgumentList "owl_app_server.py" `
        -WorkingDirectory "C:\Projects\KinoliveLines\live" -WindowStyle Hidden
}

# 3b) OwlNest worker manager (one stats worker per registered user)
if (-not (ProcRunning "owl_nest_manager.py")) {
    Say "starting OwlNest manager"
    Start-Process python -ArgumentList "owl_nest_manager.py" `
        -WorkingDirectory "C:\Projects\KinoliveLines\live" -WindowStyle Hidden
}

# 3b2) OwlNest provisioner (auto-builds terminals for new members)
if (-not (ProcRunning "owl_nest_provision.py")) {
    Say "starting OwlNest provisioner"
    Start-Process python -ArgumentList "owl_nest_provision.py" `
        -WorkingDirectory "C:\Projects\KinoliveLines\live" -WindowStyle Hidden
}

# 3b3) phone push notifier (web-push from owl_manual.log events)
if (-not (ProcRunning "owl_push_notifier.py")) {
    Say "starting push notifier"
    Start-Process python -ArgumentList "owl_push_notifier.py" `
        -WorkingDirectory "C:\Projects\KinoliveLines\live" -WindowStyle Hidden
}

# 3c) Telegram alert daemon
if (-not (ProcRunning "owl_telegram.py")) {
    Say "starting Telegram daemon"
    Start-Process python -ArgumentList "owl_telegram.py" `
        -WorkingDirectory "C:\Projects\KinoliveLines\live" -WindowStyle Hidden
}

# 4) demo fleet (each restart script brings its own terminal + bot)
$demos = @(
    @{ script = "C:\Projects\KinoliveLines\live\restart_pro.ps1";
       match = "owl_pro_bot.py" },
    @{ script = "C:\Projects\KinoliveLines\live\restart_raw.ps1";
       match = "owl_raw_bot.py" },
    @{ script = "C:\Projects\KinoliveLines\live\restart_demo2.ps1";
       match = "owl_demo2_bot.py" }
)
foreach ($d in $demos) {
    if (-not (ProcRunning $d.match)) {
        Say ("starting " + $d.match)
        powershell -NoProfile -ExecutionPolicy Bypass -File $d.script
    }
}
Say "boot_all done"
