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

# 2) KINO account 223985697 - owner 2026-09-18: owl_manual_bot is
# RETIRED here. The structure bot runs this account with the
# nervosity brake OFF (package kino_sans_frein): a live A/B against
# Valere, which keeps the brake. 41.7 days of replay could not say
# whether that brake helps, so the two accounts answer it forward.
if (-not (ProcRunning "structure_bos_bot.py kino")) {
    Say "starting STRUCTURE kino (real 223985697, no nervosity)"
    Start-Process pythonw -ArgumentList "structure_bos_bot.py", "kino" `
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

# 2c) STRUCTURE bots: live (223995441) + demo variants
$sb = Get-CimInstance Win32_Process |
    Where-Object { $_.CommandLine -like "*structure_bos_bot.py*" }
# 2026-09-15 (owner): the LIVE account is half manual now. The auto BOS
# bot is RETIRED on 223995441 - owl_manual_trader.py keeps the structure,
# the CHoCH alerts and the debt ledger, and places only what the chart
# explicitly confirms. Valere's dedicated instance is unaffected.
# one instance per account in manual / semi mode; full-automation
# accounts never get one (owner 2026-09-15)
try {
    $nu = Get-Content "C:\Projects\KinoliveLines\live\owl_nest_users.json" -Raw |
        ConvertFrom-Json
    foreach ($m in $nu) {
        if ($m.mode -eq "manual" -or $m.mode -eq "semi") {
            if (-not (ProcRunning ("owl_manual_trader.py " + $m.id))) {
                Say ("starting manual trader " + $m.id)
                Start-Process pythonw -ArgumentList "owl_manual_trader.py", $m.id `
                    -WorkingDirectory "C:\Projects\KinoliveLines\live" -WindowStyle Hidden
            }
        }
    }
} catch {
    Say ("manual trader boot failed: " + $_)
}
# sniper and halfdebt both hit their kill lines on 2026-09-18, on
# the SAME trade, and the owner retired them. Their accounts are
# out of the nest. Do NOT revive: a killed variant that restarts
# just re-reads its killed flag and sits there looking alive.

# 2h) the PUBLIC showcase account 296378359 (owner 2026-09-19): same bot,
# base package, auto. Anyone can watch it from the front door; the server
# refuses every action on its token.
if (-not (ProcRunning "structure_bos_bot.py demo")) {
    Say "starting STRUCTURE demo (public showcase 296378359)"
    Start-Process pythonw -ArgumentList "structure_bos_bot.py", "demo" `
        -WorkingDirectory "C:\Projects\KinoliveLines\live" -WindowStyle Hidden
}
# 2g) Valere's real account: its own instance of the frozen live config
# (own debt ledger, own war-chest, own -$60 kill line). Owner 2026-09-14.
if (-not (ProcRunning "structure_bos_bot.py valere")) {
    Say "starting BOS bot (valere)"
    Start-Process pythonw -ArgumentList "structure_bos_bot.py", "valere" `
        -WorkingDirectory "C:\Projects\KinoliveLines\live" -WindowStyle Hidden
}
# 2i) Infinity's real account. Owner 2026-09-19/24 addition - found
# 2026-09-25 that this block never existed (only kino/demo/valere were
# ever wired in here), so a real reboot would NOT have revived it.
if (-not (ProcRunning "structure_bos_bot.py infinity")) {
    Say "starting BOS bot (infinity)"
    Start-Process pythonw -ArgumentList "structure_bos_bot.py", "infinity" `
        -WorkingDirectory "C:\Projects\KinoliveLines\live" -WindowStyle Hidden
}
if (-not (ProcRunning "structure_bos_bot.py expenses")) {
    Say "starting BOS bot (expenses)"
    Start-Process pythonw -ArgumentList "structure_bos_bot.py", "expenses" `
        -WorkingDirectory "C:\Projects\KinoliveLines\live" -WindowStyle Hidden
}
# 2j) Dad's real account: the DEFAULT instance, no argv (own debt ledger,
# package special_10). Same gap as Infinity above - never had a launch
# block, found and fixed the same day, before it was ever tested by a
# real restart. Must match the bare ".py" ending exactly, or this would
# also match kino/demo/valere/infinity's command lines.
if (-not (Get-CimInstance Win32_Process |
        Where-Object { $_.CommandLine -match "structure_bos_bot\.py\s*$" })) {
    Say "starting BOS bot (bos / Dad, default account)"
    Start-Process pythonw -ArgumentList "structure_bos_bot.py" `
        -WorkingDirectory "C:\Projects\KinoliveLines\live" -WindowStyle Hidden
}
# 2e) forward-observation ledger (narrow-stop flag + rolling-20 shadow state, informational)
if (-not (Get-CimInstance Win32_Process |
        Where-Object { $_.CommandLine -like "*bos_forward_observer.py*" })) {
    Say "starting BOS forward observer"
    Start-Process pythonw -ArgumentList "bos_forward_observer.py" `
        -WorkingDirectory "C:\Projects\KinoliveLines\live" -WindowStyle Hidden
}
# 2f) E016 liquidation shadow observer (OKX websocket latency logger, NO ORDERS, informational)
if (-not (Get-CimInstance Win32_Process |
        Where-Object { $_.CommandLine -like "*liq_shadow.py*" })) {
    Say "starting liquidation shadow observer"
    Start-Process pythonw -ArgumentList "liq_shadow.py" `
        -WorkingDirectory "C:\Projects\KinoliveLines\live" -WindowStyle Hidden
}
# 2c) the lab's variant twins (2026-09-28): every running entry in lab/twins.json
try {
    # (2026-09-29: the path used to hold a TAB instead of a backslash, so this
    #  block silently never ran - fixed, verified with a parse + Test-Path)
    $tw = Get-Content (Join-Path $PSScriptRoot "lab/twins.json") -Raw -ErrorAction Stop | ConvertFrom-Json
    foreach ($t in $tw.twins) {
        if ($t.status -ne "running") { continue }
        $pat = "*bos_paper_variant.py*" + $t.id + "*"
        if (-not (Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like $pat })) {
            Say ("starting lab twin " + $t.id)
            Start-Process pythonw -ArgumentList "bos_paper_variant.py", $t.id -WorkingDirectory $PSScriptRoot -WindowStyle Hidden
        }
    }
} catch {}
# 2k) daemons found missing from this file on 2026-09-29 (owner: "make sure
#     the setup can survive a VPS restart"): the auto/manual mode switch
#     watcher, the harvest journal, the brick-size watch.
# 2026-09-29: the hourly proof refresh is a scheduled task (OwlProofRefresh);
# make sure it exists after a rebuild of the box
if (-not (Get-ScheduledTask -TaskName "OwlProofRefresh" -ErrorAction SilentlyContinue)) {
    Say "OwlProofRefresh task missing - see lab/proof_refresh.py"
}
foreach ($extra in @("owl_mode_switch.py", "harvest_journal.py", "brick_watch.py")) {
    if (-not (ProcRunning $extra)) {
        Say ("starting " + $extra)
        Start-Process pythonw -ArgumentList $extra -WorkingDirectory $PSScriptRoot -WindowStyle Hidden
    }
}
# 2026-09-30 (owner): RETIRED - "just kill it". The flip+TOUCH twin
# reached -$90.41 over 118 trades, 61W/57L: it wins slightly more
# often than it loses and still bleeds, because its losers are wider.
# That confirms the 2026-09-11 tick audit (touch alone ~$0 net) with a
# real forward sample, which is all it was ever there to do.
# Do NOT revive: re-enabling it re-opens a question already answered
# twice. See review/ and the memory note mt5-bos-execution-audit.
# # 2d) paper twin of the flip+TOUCH rule (2026-09-11 audit comparison)
# if (-not (Get-CimInstance Win32_Process |
#         Where-Object { $_.CommandLine -like "*bos_paper_touch.py*" })) {
#     Say "starting BOS paper twin (flip+touch, virtual)"
#     Start-Process pythonw -ArgumentList "bos_paper_touch.py" `
#         -WorkingDirectory "C:\Projects\KinoliveLines\live" -WindowStyle Hidden
# }

# 2d) chart feed (aura chart data)
if (-not (ProcRunning "owl_chart_feed.py")) {
    Say "starting chart feed"
    Start-Process pythonw -ArgumentList "owl_chart_feed.py" `
        -WorkingDirectory "C:\Projects\KinoliveLines\live" -WindowStyle Hidden
}

# 2b) STANDARD account 134499778 (nest id "std"): the old Owl instance
#     (owl_run_std.py) died on 2026-09-12 (disk full) and was never wanted
#     back - the account is hand-traded now. 2026-09-27: it runs the manual
#     desk instead, started by the mode/manual block above. Do not revive.

# 3) OwlNest app server
# 2026-09-27: checked on its PORT, not only its process - a hung server
#     still has a process. No answer within 15 s -> stop it and start again.
$appStarted = $false
$appOk = $false
if (ProcRunning "owl_app_server.py") {
    try { $r = Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:8787/join" -TimeoutSec 15; $appOk = ($r.StatusCode -eq 200) } catch { $appOk = $false }
    if (-not $appOk) {
        Say "OwlNest not answering on 8787 - restarting it"
        Get-CimInstance Win32_Process | Where-Object { $_.Name -like "python*" -and $_.CommandLine -like "*owl_app_server.py*" } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -Confirm:$false }
        Start-Sleep -Seconds 2
    }
}
if (-not (ProcRunning "owl_app_server.py")) {
    Say "starting OwlNest"
    Start-Process python -ArgumentList "owl_app_server.py" `
        -WorkingDirectory "C:\Projects\KinoliveLines\live" -WindowStyle Hidden
    $appStarted = $true
}
# ui_check after a (re)start, and at most every 6 h; a failure lands in this
# log where the notifier pushes it to the owner
$uiMark = "C:\Projects\KinoliveLines\live\owl_ui_check.log"
$uiDue = $appStarted -or (-not (Test-Path $uiMark)) -or (((Get-Date) - (Get-Item $uiMark).LastWriteTime).TotalHours -gt 6)
if ($uiDue) {
    if ($appStarted) { Start-Sleep -Seconds 12 }
    try {
        $p = Start-Process node -ArgumentList "review\ui_check.mjs" -WorkingDirectory "C:\Projects\KinoliveLines\live" -WindowStyle Hidden -RedirectStandardOutput $uiMark -PassThru -Wait
        if ($p.ExitCode -ne 0) { Say ("UI CHECK FAILED (exit " + $p.ExitCode + ") - see owl_ui_check.log") } else { Say "ui_check OK" }
    } catch { Say ("ui_check could not run: " + $_) }
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
        # 2026-09-14: a member running his OWN bot instance must NOT
        # also get a copier, or he would trade the same signal twice.
        if ($u.trade -eq $true -and $u.id -ne "kino" -and -not $u.dedicated) {
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
# owner 2026-09-18: CROC kept, the rest retired. demo2 sat below its
# own $50 floor and could not enter at all.
# owner 2026-09-24: CROC retired too - -$163 (-33%) over ~30 days on a
# 64% win rate, because it has no stop-loss by design and its avg loss
# ($2.51) runs about 2x its avg win ($1.25), a ratio that 64% cannot
# clear. Positions closed flat, bot stopped. Empty on purpose - do NOT
# revive: same reasoning as sniper/halfdebt below.
$demos = @()
foreach ($d in $demos) {
    if (-not (ProcRunning $d.match)) {
        Say ("starting " + $d.match)
        powershell -NoProfile -ExecutionPolicy Bypass -File $d.script
    }
}
# 2026-09-27: the landing carousel shows REAL renders of the demo - refresh
#     them once a day (needs the app server up; ~20 s of headless Edge)
$shot = "C:\Projects\KinoliveLines\live\static\shot_home.png"
if (-not (Test-Path $shot) -or ((Get-Date) - (Get-Item $shot).LastWriteTime).TotalHours -gt 24) {
    Say "refreshing landing screenshots"
    try { Start-Process node -ArgumentList "review\landing_shots.mjs" -WorkingDirectory "C:\Projects\KinoliveLines\live" -WindowStyle Hidden } catch { Say ("landing shots failed: " + $_) }
}
Say "boot_all done"
