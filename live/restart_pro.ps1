# restart_demo2.ps1 - restart the PRO CROC Owl (account 476604490)
# Order matters: the Session3 terminal MUST be launched with the start-config
# (AllowLiveTrading=1) or order_send fails with retcode 10027.
$ErrorActionPreference = "Stop"
& "C:\Users\Administrator\AppData\Local\Programs\Python\Python311\python.exe" -c "import ast; ast.parse(open(r'C:\Projects\KinoliveLines\live\owl_pro_bot.py', encoding='utf-8').read()); print('syntax OK')"
if ($LASTEXITCODE -ne 0) { Write-Output "SYNTAX CHECK FAILED - not restarting."; exit 1 }
Get-CimInstance Win32_Process -Filter "Name='pythonw.exe'" | Where-Object { $_.CommandLine -match 'owl_pro' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force; Write-Output "stopped bot $($_.ProcessId)" }
Get-CimInstance Win32_Process -Filter "Name='terminal64.exe'" | Where-Object { $_.ExecutablePath -match 'Session3' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force; Write-Output "stopped terminal $($_.ProcessId)" }
Start-Sleep -Seconds 3
Start-Process -FilePath "C:\Projects\MT5-KinoliveTrader-Session3\terminal64.exe" -ArgumentList '/config:C:\Projects\KinoliveLines\live\pro_start.ini'
Start-Sleep -Seconds 20
Start-Process -FilePath "C:\Users\Administrator\AppData\Local\Programs\Python\Python311\pythonw.exe" -ArgumentList "C:\Projects\KinoliveLines\live\owl_pro_bot.py" -WorkingDirectory "C:\Projects\KinoliveLines\live"
Write-Output "demo2 terminal + bot relaunched"
