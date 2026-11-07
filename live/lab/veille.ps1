# Kino numerique's day watch (2026-10-02). Scheduled task "OwlNestVeille",
# every 30 minutes. The decision to actually wake lives in lab/wake.py.
# 2026-11-07 (owner): the old lab is PAUSED - Kino's trading lab (robots/kino_lab.py) replaced it. Delete lab\PAUSED to bring it back.
if (Test-Path "C:\Projects\KinoliveLines\live\lab\PAUSED") { exit 0 }
Set-Location "C:\Projects\KinoliveLines\live"
python lab/wake.py *> (Join-Path "C:\Projects\KinoliveLines\live\lab" "wake_last.log")
