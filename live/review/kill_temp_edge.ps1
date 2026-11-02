# kill_temp_edge.ps1 (2026-11-02): closes every headless Edge started with a Temp profile (screenshots, ui checks).
# edge.kill() / taskkill on the launched pid missed them: Edge hands off to a new process tree, and 36 renderers stayed
# behind, pinned the CPU, and the owner's home sat on its skeleton. The owner's own Edge never runs from a Temp profile.
Get-CimInstance Win32_Process -Filter "name='msedge.exe'" |
    Where-Object { $_.CommandLine -like '*user-data-dir=*AppData*Local*Temp*' -or $_.CommandLine -like '*user-data-dir=*scratchpad*' } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
