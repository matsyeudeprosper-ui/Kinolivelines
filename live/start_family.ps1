# start_family.ps1 - (re)start the master publisher + one copier per
# trade-enabled user. ONE codebase (owl_copier.py) for all accounts.
$ErrorActionPreference = 'Continue'
$py = "C:\Users\Administrator\AppData\Local\Programs\Python\Python311\python.exe"
$pyw = "C:\Users\Administrator\AppData\Local\Programs\Python\Python311\pythonw.exe"
$live = "C:\Projects\KinoliveLines\live"

# syntax check both files first - refuse to launch broken code
foreach ($f in @("owl_master_publisher.py", "owl_copier.py")) {
    $chk = & $py -c "import ast; ast.parse(open(r'$live\$f',encoding='utf-8').read()); print('ok')"
    if ($chk -ne 'ok') { Write-Output "SYNTAX FAIL $f - aborting"; exit 1 }
}

# stop old instances
Get-CimInstance Win32_Process -Filter "Name='pythonw.exe'" |
    Where-Object { $_.CommandLine -match 'owl_master_publisher\.py|owl_copier\.py' } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force; Write-Output "stopped $($_.ProcessId)" }
Start-Sleep -Seconds 2

# publisher
Start-Process -FilePath $pyw -ArgumentList "$live\owl_master_publisher.py" -WorkingDirectory $live
Write-Output "publisher launched"

# one copier per trade-enabled user
$users = Get-Content "$live\owl_nest_users.json" -Raw | ConvertFrom-Json
foreach ($u in $users) {
    if ($u.trade -eq $true) {
        Start-Process -FilePath $pyw -ArgumentList "$live\owl_copier.py", $u.id -WorkingDirectory $live
        Write-Output "copier launched for $($u.id)"
    }
}
