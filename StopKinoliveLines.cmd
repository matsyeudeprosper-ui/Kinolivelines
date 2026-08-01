@echo off
REM ============================================================
REM  Stops the KinoliveLines daemon and recorder.
REM  Stopping the daemon STOPS ALL TRADING.
REM  Open positions keep their SL/TP - those live on Exness and
REM  execute whether or not anything here is running.
REM ============================================================
title Stop KinoliveLines
echo.
echo Stopping KinoliveLines background services...
echo.
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command ^
  "$p = Get-CimInstance Win32_Process -Filter \"Name='pythonw.exe'\" | Where-Object { $_.CommandLine -like '*daemon.py*' -or $_.CommandLine -like '*recorder.py*' };" ^
  "if (-not $p) { Write-Host '  nothing was running' -ForegroundColor Yellow } else { $p | ForEach-Object { $n = if ($_.CommandLine -like '*daemon*') {'daemon (trading)'} else {'recorder'}; Write-Host \"  stopped $n  pid $($_.ProcessId)\" -ForegroundColor Green; Stop-Process -Id $_.ProcessId -Force } };" ^
  "Write-Host ''; Write-Host '  Trading is stopped. Any OPEN position still has its SL/TP on the broker.' -ForegroundColor Cyan;" ^
  "$env:OPENAI_API_KEY=[Environment]::GetEnvironmentVariable('OPENAI_API_KEY','User');" ^
  "& 'C:\Users\Administrator\AppData\Local\Programs\Python\Python311\python.exe' -c \"import MetaTrader5 as mt5; mt5.initialize(path=r'C:\Program Files\MetaTrader 5\terminal64.exe') and [print(f'  open positions: {mt5.positions_total()}   pending orders: {mt5.orders_total()}'), mt5.shutdown()]\""
echo.
pause
