@echo off
REM ============================================================================
REM  Start the KinoliveLines mirror publisher.
REM
REM  This turns ON real-money trading on account 134499778. The publisher itself
REM  only reads the demo account and writes a signal file - but KLMirror.mq5 is
REM  attached to the live terminal and will act on those signals immediately.
REM
REM  WHAT IT COSTS, measured rather than assumed:
REM    the two accounts are exact mirrors, so exactly one wins on every trade.
REM      demo target hit -> demo +$1.00, live -$2.00  = -$1.00 for the pair
REM      demo stop hit   -> demo -$2.00, live +$1.00  = -$1.00 for the pair
REM    There is no third outcome. Losses can also overshoot in fast markets -
REM    one stop on 2026-08-01 slipped 11 points, turning -$2.00 into -$2.54 -
REM    while wins stay pinned at +$1.00 because targets are limit fills.
REM    Live balance was $42.70, which funds roughly eleven days.
REM
REM  TO STOP: close the window this opens. The EA then receives nothing.
REM ============================================================================
setlocal
set PY=C:\Users\Administrator\AppData\Local\Programs\Python\Python311\python.exe
set SCRIPT=C:\Projects\KinoliveLines\live\mirror_publisher.py

echo.
echo   MIRROR PUBLISHER
echo   ----------------
echo   Demo account 436771046  ---- signals ---^>  LIVE account 134499778
echo   Direction is REVERSED. This trades REAL money.
echo.
echo   Every mirrored pair loses about $1.00 regardless of market direction.
echo.
set /p OK="  Type Y then Enter to start, anything else to cancel: "
if /I not "%OK%"=="Y" (
  echo.
  echo   Cancelled. Nothing started.
  timeout /t 3 >nul
  exit /b 0
)

echo.
echo   Starting. Close this window to stop mirroring.
echo.
"%PY%" "%SCRIPT%"
echo.
echo   Publisher has stopped. Mirroring is OFF.
pause
