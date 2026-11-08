# 2026-11-07: the pullback-chart history for the owner's rule test, one month after another (after September), low priority
Set-Location "C:\Projects\KinoliveLines\study"
while (-not (Test-Path "pb_series\2026-09.npz")) { Start-Sleep -Seconds 30 }
& python -X utf8 pb_series_months.py 2026-08 2026-07 2026-06 2026-05 2026-04 2026-03 2026-02 *>> pb_series_months.log
