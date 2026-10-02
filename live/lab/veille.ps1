# Kino numerique's day watch (2026-10-02). Scheduled task "OwlNestVeille",
# every 30 minutes. The decision to actually wake lives in lab/wake.py.
Set-Location "C:\Projects\KinoliveLines\live"
python lab/wake.py *> (Join-Path "C:\Projects\KinoliveLines\live\lab" "wake_last.log")
