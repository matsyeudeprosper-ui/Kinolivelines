# 2026-11-02 (owner: "Kino was supposed to pick up that cpu and those things automatically and clean up"): Kino's body
# reflex, run by kino_care.py from the app (administrator) at each check-up. It closes hidden test browsers left behind by a
# finished screenshot / check script: a headless Edge or Chrome whose throw-away profile sits in a Temp folder, open for
# -MinAge minutes or more, with every helper process sharing that profile. Never Kino's own browser (Playwright or
# KinoWorld profiles). Prints how many processes it closed.
param([int]$MinAge = 30)
$cut = (Get-Date).AddMinutes(-$MinAge)
$all = @(Get-CimInstance Win32_Process -Filter "Name='msedge.exe' or Name='chrome.exe'")
$dirs = @()
foreach ($p in $all) {
    $cl = $p.CommandLine
    if (-not $cl -or $cl -notmatch '--headless' -or $cl -match 'playwright|KinoWorld' -or $p.CreationDate -ge $cut) { continue }
    if ($cl -match 'user-data-dir=("[^"]+"|\S+)') {
        $d = $Matches[1].Trim('"')
        if ($d -match '\\Temp\\') { $dirs += $d }
    }
}
$dirs = @($dirs | Sort-Object -Unique)
$n = 0
foreach ($p in $all) {
    $cl = $p.CommandLine
    if (-not $cl) { continue }
    foreach ($d in $dirs) {
        if ($cl.Contains($d)) {
            try { Stop-Process -Id $p.ProcessId -Force -ErrorAction Stop; $n++ } catch {}
            break
        }
    }
}
$n
