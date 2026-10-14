# mt5_history_pull.ps1 - make MT5 terminals download their account's FULL deal
# history from the broker.
#
# Why (2026-10-14): these terminals only keep the deals they witnessed while
# running, and write them to disk only on a CLEAN close. After the hard kills
# of the 10-14 reboot they knew almost nothing, so every nest stat read 0 and
# the app greeted members as new. Python's history_deals_get() does NOT make
# the terminal fetch old history; an MQL5 HistorySelect() does (tested on
# u476954287: 0 deals -> 132 three seconds later). So: close the terminal
# cleanly, relaunch it AT ONCE (before a bot relaunches it without the config)
# with /config running Scripts\Owl\HistSync.ex5, wait for its log line.
#
#   powershell -File mt5_history_pull.ps1 C:\NestTerminals\demo\terminal64.exe [...more]
#
# The bot on that terminal loses MT5 for a few seconds. Positions live at the
# broker and are not touched. Nothing is deleted.
param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Terminals)

$here = "C:\Projects\KinoliveLines\live"
$roam = Join-Path $env:APPDATA "MetaQuotes\Terminal"
$ex5 = Join-Path $here "mql5\HistSync.ex5"

function DataDir($inst) {
    foreach ($d in Get-ChildItem $roam -Directory) {
        $o = Join-Path $d.FullName "origin.txt"
        if ((Test-Path $o) -and ((Get-Content $o -Raw).Trim() -ieq $inst)) { return $d.FullName }
    }
    return $inst   # portable install
}

foreach ($exe in $Terminals) {
    $exe = [System.IO.Path]::GetFullPath($exe)
    $inst = Split-Path $exe -Parent
    $dd = DataDir $inst
    Write-Output "== $exe"
    # the BTCUSD H1 chart this opens gets the default template, which on the
    # nest terminals carries the retired KinoliveTrader EA - it STARTED on
    # 5 accounts on 2026-10-14. Never run where that EA can still load.
    $tpl = Join-Path $dd "MQL5\Profiles\Templates\default.tpl"
    if (Test-Path $tpl) {
        $m = Select-String -Path $tpl -Pattern '^path=(Experts\\.+\.ex5)' -Encoding Unicode | Select-Object -First 1
        if ($m -and (Test-Path (Join-Path $dd ("MQL5\" + $m.Matches[0].Groups[1].Value)))) {
            Write-Output ("   default template would start " + $m.Matches[0].Groups[1].Value + " - skipped"); continue
        }
    }
    $sd = Join-Path $dd "MQL5\Scripts\Owl"
    New-Item -ItemType Directory -Force $sd | Out-Null
    Copy-Item $ex5 $sd -Force
    $ini = Join-Path $inst "histsync.ini"
    "[StartUp]`r`nScript=Owl\HistSync`r`nSymbol=BTCUSD`r`nPeriod=H1`r`nShutdownTerminal=0`r`n" | Set-Content -Encoding ascii $ini
    $log = Join-Path $dd ("MQL5\Logs\" + (Get-Date -Format yyyyMMdd) + ".log")
    $before = if (Test-Path $log) { @(Get-Content $log -Encoding Unicode | Select-String "HistSync (try|done)").Count } else { 0 }

    $procs = @(Get-Process terminal64 -ErrorAction SilentlyContinue | Where-Object { $_.Path -ieq $exe })
    foreach ($p in $procs) { [void]$p.CloseMainWindow() }
    for ($i = 0; $i -lt 900 -and @($procs | Where-Object { -not $_.HasExited }).Count; $i++) { Start-Sleep -Milliseconds 100 }
    $left = @($procs | Where-Object { -not $_.HasExited }).Count
    if ($left) { Write-Output "   $left copy(ies) did not close within 90 s - skipped (no hard kill)"; continue }
    Start-Process $exe -ArgumentList ("/config:" + $ini)

    $res = "no HistSync output after 240 s (a bot may have relaunched it first - run again)"
    for ($i = 0; $i -lt 120; $i++) {
        Start-Sleep 2
        if (-not (Test-Path $log)) { continue }
        $lines = @(Get-Content $log -Encoding Unicode | Select-String "HistSync (try|done)")
        $new = $lines | Select-Object -Skip $before
        $hit = $new | Where-Object { $_.Line -match 'HistSync done deals=[1-9]' } | Select-Object -Last 1
        if ($hit) { $res = ($hit.Line -replace '^.*HistSync done ', 'done '); break }
        if (@($new).Count -ge 21) { $res = "no deals after 20 tries"; break }
    }
    Write-Output "   $res"
}
