# Le chercheur - nightly run (2026-09-28). Scheduled task "OwlNestChercheur".
#   1. lab_researcher.py replays the battery + the pending proposals (verdicts)
#   2. a headless Claude Code session reads the night and writes its note +
#      new proposals (lab/CHERCHEUR.md is the mission)
#   3. the lab's outputs are committed and pushed
$live = "C:\Projects\KinoliveLines\live"
$lab = Join-Path $live "lab"
$log = Join-Path $lab "chercheur.log"
function Say($m) { Add-Content -Path $log -Value ("{0} {1}" -f (Get-Date -Format o), $m) }
Set-Location $live
Say "run start"
try {
    $quick = ($args -contains "--quick")
    if ($quick) { python lab_researcher.py --quick *> (Join-Path $lab "researcher_last.log") }
    else { python lab_researcher.py *> (Join-Path $lab "researcher_last.log") }
    Say ("researcher exit " + $LASTEXITCODE)
} catch { Say ("researcher failed: " + $_.Exception.Message) }
try {
    New-Item -ItemType Directory -Force (Join-Path $lab "notes") | Out-Null
    $claude = "$env:USERPROFILE\.local\bin\claude.exe"
    $mission = Get-Content (Join-Path $lab "CHERCHEUR.md") -Raw
    $mission += "`n`nToday is " + (Get-Date -Format "yyyy-MM-dd") + ". Begin."
    $out = & $claude -p $mission --output-format text --max-turns 90 `
        --allowedTools "Bash(python *)","Read","Write","Edit","Glob","Grep" 2>&1 | Out-String
    Set-Content -Path (Join-Path $lab "chercheur_last.log") -Value $out -Encoding utf8
    Say ("chercheur session done, " + $out.Length + " chars")
} catch { Say ("chercheur session failed: " + $_.Exception.Message) }
try {
    python lab/pretest_fill.py *> (Join-Path $lab "pretest_last.log")
    # 2026-09-29: judge the twins (retire the losers, flag the winners) and
    # send the night's events (new dial requests, answered asks)
    python lab/twin_judge.py --post *> (Join-Path $lab "judge_last.log")
    # 2026-09-29: the numbers behind "La preuve" (robot space)
    python lab/proof_build.py *> (Join-Path $lab "proof_last.log")
    git add lab/auto.json lab/auto_history.jsonl lab/proposals.json lab/requests.json lab/twins.json lab/decisions.json lab/asks.json lab/events_seen.json lab/chercheur_latest.json lab/notes 2>$null
    $msg = "chercheur: nightly run " + (Get-Date -Format "yyyy-MM-dd") + "`n`nCo-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
    git commit -q -m $msg 2>$null
    git push -q 2>$null
    Say "committed"
} catch { Say ("git failed: " + $_.Exception.Message) }
Say "run end"
