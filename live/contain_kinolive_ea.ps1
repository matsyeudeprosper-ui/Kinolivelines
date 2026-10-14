# contain_kinolive_ea.ps1 - 2026-10-14: stop the retired KinoliveTrader EA from
# running on the nest terminals.
# Every nest terminal's default chart template carries KinoliveTrader. On its
# old BTCUSDm M1 chart it fails (symbol missing on these accounts); a new
# BTCUSD H1 chart opened by mt5_history_pull.ps1 got the template and the EA
# started for real. This disables the EA file (renamed, not deleted) and closes
# the affected terminals CLEANLY so they come back without it (the bots relaunch
# them within seconds).
$roam = Join-Path $env:APPDATA "MetaQuotes\Terminal"
foreach ($d in Get-ChildItem $roam -Directory) {
    $o = Join-Path $d.FullName "origin.txt"
    if (-not (Test-Path $o)) { continue }
    $inst = (Get-Content $o -Raw).Trim()
    if ($inst -notlike "C:\NestTerminals\*") { continue }
    $f = Join-Path $d.FullName "MQL5\Experts\KinoliveTrader\KinoliveTrader.ex5"
    if (Test-Path $f) { Rename-Item $f "KinoliveTrader.ex5.disabled"; "disabled EA in $inst" }
}
foreach ($u in "u224016179", "infinity", "demo", "u477508138", "u476954287") {
    $exe = "C:\NestTerminals\$u\terminal64.exe"
    $ps = @(Get-Process terminal64 -ErrorAction SilentlyContinue | Where-Object { $_.Path -ieq $exe })
    foreach ($p in $ps) { [void]$p.CloseMainWindow() }
    "closing $u ($($ps.Count) copy)"
}
