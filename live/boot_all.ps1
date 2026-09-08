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

# 2a) FRESH-H1 harvest forward test on DEMO Pro 476954287 (BTC + ETH
#     streams, 2026-09-08). BTC instance has no symbol arg.
$fh = Get-CimInstance Win32_Process |
    Where-Object { $_.CommandLine -like "*harvest_fresh_h1_bot.py*" }
if (-not ($fh | Where-Object { $_.CommandLine -notlike "*ETHUSD*" })) {
    Say "starting FRESH-H1 BTC (demo)"
    Start-Process pythonw -ArgumentList "harvest_fresh_h1_bot.py" `
        -WorkingDirectory "C:\Projects\KinoliveLines\live" -WindowStyle Hidden
}
if (-not ($fh | Where-Object { $_.CommandLine -like "*ETHUSD*" })) {
    Say "starting FRESH-H1 ETH (demo)"
    Start-Process pythonw -ArgumentList "harvest_fresh_h1_bot.py", "ETHUSD" `
        -WorkingDirectory "C:\Projects\KinoliveLines\live" -WindowStyle Hidden
}

# 2c) STRUCTURE bot (user's BOS rules, real acct 223995441)
if (-not (ProcRunning "structure_bos_bot.py")) {
    Say "starting STRUCTURE bot (223995441)"
    Start-Process pythonw -ArgumentList "structure_bos_bot.py" `
        -WorkingDirectory "C:\Projects\KinoliveLines\live" -WindowStyle Hidden
}

# 2d) chart feed (aura chart data)
if (-not (ProcRunning "owl_chart_feed.py")) {
    Say "starting chart feed"
    Start-Process pythonw -ArgumentList "owl_chart_feed.py" `
        -WorkingDirectory "C:\Projects\KinoliveLines\live" -WindowStyle Hidden
}

# 2b) STANDARD-account Owl instance (one codebase, regenerated at
#     launch from owl_manual_bot.py by owl_run_std.py)
if (-not (ProcRunning "owl_run_std.py")) {
    Say "starting STD Owl (134499778)"
    Start-Process pythonw -ArgumentList "owl_run_std.py" `
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

# 3b4) master publisher + family copiers (2026-09-07 go-live: these
#      were missing here - a reboot silently stopped the mirroring)
if (-not (ProcRunning "owl_master_publisher.py")) {
    Say "starting master publisher"
    Start-Process pythonw -ArgumentList "owl_master_publisher.py" `
        -WorkingDirectory "C:\Projects\KinoliveLines\live" -WindowStyle Hidden
}
try {
    $users = Get-Content "C:\Projects\KinoliveLines\live\owl_nest_users.json" -Raw |
        ConvertFrom-Json
    foreach ($u in $users) {
        if ($u.trade -eq $true -and $u.id -ne "kino") {
            if (-not (ProcRunning ("owl_copier.py " + $u.id))) {
                Say ("starting copier " + $u.id)
                Start-Process pythonw -ArgumentList ("owl_copier.py " + $u.id) `
                    -WorkingDirectory "C:\Projects\KinoliveLines\live" -WindowStyle Hidden
            }
        }
    }
} catch {
    Say ("copier revive failed: " + $_)
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
