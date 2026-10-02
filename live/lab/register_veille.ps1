# Registers the day watch: scheduled task "OwlNestVeille", every 30 minutes,
# running lab/veille.ps1 (which asks lab/wake.py whether Kino numerique
# should wake). Same principal and shape as OwlNestChercheur. Re-run after a
# VPS rebuild; -Force replaces an existing task.
$a = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File C:\Projects\KinoliveLines\live\lab\veille.ps1"
$t = New-ScheduledTaskTrigger -Once -At (Get-Date).Date `
    -RepetitionInterval (New-TimeSpan -Minutes 30) -RepetitionDuration (New-TimeSpan -Days 3650)
$p = New-ScheduledTaskPrincipal -UserId "Administrator" -LogonType Interactive -RunLevel Highest
$s = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Hours 1) `
    -MultipleInstances IgnoreNew -StartWhenAvailable
Register-ScheduledTask -TaskName "OwlNestVeille" -Action $a -Trigger $t -Principal $p -Settings $s -Force | Out-Null
$x = Get-ScheduledTask -TaskName "OwlNestVeille"
"registered: $($x.TaskName) state=$($x.State) every=$($x.Triggers[0].Repetition.Interval)"
