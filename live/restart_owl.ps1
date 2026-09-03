# Restart the Owl bot (kill old instance, launch new) - run by the USER to
# approve activating a new Owl version. 2026-08-22: AUTO_ENTRY version
# (the Owl trades the user's 3-step recipe itself on green light).
$ErrorActionPreference = 'Continue'

# 1. syntax check first - refuse to launch broken code
$check = & "C:\Users\Administrator\AppData\Local\Programs\Python\Python311\python.exe" -c "import ast; ast.parse(open(r'C:\Projects\KinoliveLines\live\owl_manual_bot.py').read()); print('syntax OK')"
if ($check -ne 'syntax OK') {
    Write-Output "SYNTAX CHECK FAILED - not restarting. Tell the assistant."
    exit 1
}
Write-Output $check

# 2. stop existing Owl instance(s)
Get-CimInstance Win32_Process -Filter "Name='pythonw.exe'" |
    Where-Object { $_.CommandLine -match 'owl_manual_bot' } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force; Write-Output ("stopped " + $_.ProcessId) }

Start-Sleep -Seconds 2

# 3. launch the new one
Start-Process -FilePath "C:\Users\Administrator\AppData\Local\Programs\Python\Python311\pythonw.exe" `
    -ArgumentList "C:\Projects\KinoliveLines\live\owl_manual_bot.py" `
    -WorkingDirectory "C:\Projects\KinoliveLines\live"
Write-Output "new Owl launched"
