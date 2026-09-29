# memwatch.ps1 - sample RAM of named processes every 5 s while a mesher/solver runs (called from Allrun).
# Writes <Dir>\mem_snappy.csv (time, sum WorkingSet MB, sum PrivateBytes MB, system available MB) and
# <Dir>\mem_snappy_peak.txt. RAM guard: if system available memory < MinAvailMB for 3 consecutive samples,
# kills the watched processes and writes mem_guard_tripped.txt (the Allrun then exits non-zero).
# Stops when <Dir>\.memstop exists.
param([string]$Dir, [string[]]$Names = @('snappyHexMesh'), [int]$MinAvailMB = 1500, [int]$Every = 5, [string]$Tag = 'snappy')
$csv = Join-Path $Dir "mem_$Tag.csv"; $peakF = Join-Path $Dir "mem_${Tag}_peak.txt"; $stop = Join-Path $Dir '.memstop'
"time,ws_mb,private_mb,avail_mb,nproc" | Set-Content $csv
$peakWS = 0; $peakPriv = 0; $minAvail = 1e9; $low = 0
while (-not (Test-Path $stop)) {
    $p = @(Get-Process -Name $Names -ErrorAction SilentlyContinue)
    $ws = [math]::Round((($p | Measure-Object WorkingSet64 -Sum).Sum) / 1MB, 0)
    $pv = [math]::Round((($p | Measure-Object PrivateMemorySize64 -Sum).Sum) / 1MB, 0)
    $av = [math]::Round((Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory / 1024, 0)
    "$(Get-Date -Format s),$ws,$pv,$av,$($p.Count)" | Add-Content $csv
    if ($ws -gt $peakWS) { $peakWS = $ws }; if ($pv -gt $peakPriv) { $peakPriv = $pv }
    if ($p.Count -gt 0 -and $av -lt $minAvail) { $minAvail = $av }
    "peak_ws_MB $peakWS peak_private_MB $peakPriv min_avail_MB $minAvail" | Set-Content $peakF
    if ($p.Count -gt 0 -and $av -lt $MinAvailMB) { $low++ } else { $low = 0 }
    if ($low -ge 3) {
        "RAM guard: available $av MB < $MinAvailMB MB at $(Get-Date -Format s); killed $($Names -join ',') (ws $ws MB)" | Set-Content (Join-Path $Dir 'mem_guard_tripped.txt')
        $p | ForEach-Object { try { Stop-Process -Id $_.Id -Force } catch {} }
        break
    }
    Start-Sleep -Seconds $Every
}
