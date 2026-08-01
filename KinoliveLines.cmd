@echo off
REM ============================================================
REM  KinoliveLines - double-click to bring up the whole stack
REM    MT5 -> recorder -> daemon (GPT-5, LIVE) -> Claude watching
REM  Safe to run twice; it checks before starting anything.
REM ============================================================
title KinoliveLines
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0start_kinolive.ps1"
echo.
echo ==== Claude session ended. Background services keep running. ====
echo   GPT-5 is STILL TRADING unless you stop the daemon.
echo   Stop everything:  StopKinoliveLines.cmd
echo.
pause
