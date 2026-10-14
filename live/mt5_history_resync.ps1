# mt5_history_resync.ps1 - make MT5 terminals download their account's FULL
# deal history again from the broker.
#
# Why (2026-10-14): a terminal keeps recent history in memory and writes it to
# bases\<server>\trades\<login>\deals_*.dat only when it closes CLEANLY. The
# terminals ran from 09-10 to 10-14 and were then killed hard, so the files
# stopped at 09-08 and after the restart the terminals only fetched today's
# deals -> every nest stat showed 0 and the app greeted members as new.
# Renaming that folder makes the terminal rebuild it from the server.
#
#   powershell -File mt5_history_resync.ps1 -Terminal C:/NestTerminals/u476954287/terminal64.exe
#   powershell -File mt5_history_resync.ps1 -All      (every terminal in owl_nest_users.json)
#
# The bot/worker on that terminal loses MT5 for ~1 min; boot_all (every 5 min)
# restarts a bot that exits. Nothing is deleted: the old folder is renamed
# <login>.stale-<time>. Positions live at the broker and are not touched.
param([string]$Terminal = "", [switch]$All)

$here = "C:\Projects\KinoliveLines\live"
$roam = Join-Path $env:APPDATA "MetaQuotes\Terminal"
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"

function DataDir($exe) {
    $inst = Split-Path $exe -Parent
    foreach ($d in Get-ChildItem $roam -Directory) {
        $o = Join-Path $d.FullName "origin.txt"
        if ((Test-Path $o) -and ((Get-Content $o -Raw).Trim() -ieq $inst)) { return $d.FullName }
    }
    if (Test-Path (Join-Path $inst "bases")) { return $inst }   # portable install
    return $null
}

function Resync($exe) {
    $exe = [System.IO.Path]::GetFullPath($exe)
    Write-Output "== $exe"
    $dd = DataDir $exe
    if (-not $dd) { Write-Output "   no data folder found - skipped"; return }
    # 1) close every copy of THIS terminal, cleanly first (never the liveupdate
    #    one: it has another path)
    $procs = @(Get-Process terminal64 -ErrorAction SilentlyContinue | Where-Object { $_.Path -ieq $exe })
    foreach ($p in $procs) { [void]$p.CloseMainWindow() }
    for ($i = 0; $i -lt 30 -and @($procs | Where-Object { -not $_.HasExited }).Count; $i++) { Start-Sleep 1 }
    $hard = @($procs | Where-Object { -not $_.HasExited })
    $hard | ForEach-Object { Stop-Process -Id $_.Id -Force -Confirm:$false }
    Start-Sleep 2
    Write-Output ("   closed {0} copy(ies), {1} needed a hard stop" -f $procs.Count, $hard.Count)
    # 2) rename the stale history folder(s)
    foreach ($t in Get-ChildItem (Join-Path $dd "bases\*\trades\*") -Directory -ErrorAction SilentlyContinue) {
        if ($t.Name -match '\.stale-') { continue }
        Rename-Item $t.FullName ($t.Name + ".stale-" + $stamp)
        Write-Output ("   moved aside " + $t.FullName)
    }
    # 3) start it again; it rebuilds the history on connect
    Start-Process $exe
}

if ($All) {
    $list = (Get-Content (Join-Path $here "owl_nest_users.json") -Raw | ConvertFrom-Json) | ForEach-Object { $_.terminal } | Select-Object -Unique
} elseif ($Terminal) { $list = @($Terminal) } else { Write-Output "give -Terminal <path> or -All"; exit 1 }

foreach ($exe in $list) { Resync $exe }
Write-Output "waiting 60 s for the terminals to log in and download history..."
Start-Sleep 60
foreach ($exe in $list) { & python (Join-Path $here "mt5_history_check.py") $exe }
