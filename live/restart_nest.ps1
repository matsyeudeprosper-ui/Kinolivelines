# restart_nest.ps1 - USER-RUN: restarts the OwlNest service layer
# (web server + manager + workers + trading Owls) with current code.
$ErrorActionPreference = 'SilentlyContinue'
$targets = @('owl_app_server.py', 'owl_nest_manager.py',
             'owl_nest_worker.py', 'owl_user_bot.py')
$procs = Get-CimInstance Win32_Process | Where-Object {
    $c = $_.CommandLine
    if (-not $c) { return $false }
    foreach ($t in $targets) { if ($c -like ('*' + $t + '*')) { return $true } }
    return $false
}
foreach ($x in $procs) { Stop-Process -Id $x.ProcessId -Force }
Write-Output ("stopped " + @($procs).Count + " nest process(es)")
Start-Sleep -Seconds 2
Start-Process python -ArgumentList 'owl_app_server.py' `
    -WorkingDirectory 'C:\Projects\KinoliveLines\live' -WindowStyle Hidden
Start-Process python -ArgumentList 'owl_nest_manager.py' `
    -WorkingDirectory 'C:\Projects\KinoliveLines\live' -WindowStyle Hidden
Write-Output "nest relaunched (server + manager; workers/Owls follow in ~30s)"
