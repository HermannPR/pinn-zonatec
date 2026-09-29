<#
  AIJ Case A - run a queue of generated OpenFOAM cases one after another (detached-friendly).

  Launch detached (returns immediately, low priority):
    powershell -NoProfile -File E:\PINN\v2\cfd\aij\scripts\run_queue.ps1 -Detach -Cases bld_rke_M,bld_sst_M,bld_ske_M

  Each case <name> in E:\PINN\runs\aij\<name> must have been produced by gen_case.py.
  Log:    E:\PINN\logs\aij_<name>.log   (plus the OpenFOAM log.* files inside the case)
  Marker: <case>\DONE or <case>\FAILED (written by Allrun or here if Allrun could not start),
          and E:\PINN\logs\aij_queue_<tag>.DONE when the whole queue finished.
#>
param(
    [Parameter(Mandatory = $true)][string[]]$Cases,
    [string]$Root = 'E:\PINN\runs\aij',
    [string]$Tag = (Get-Date -Format 'yyyyMMdd_HHmmss'),
    [switch]$Detach
)
$ErrorActionPreference = 'Continue'
$logs = 'E:\PINN\logs'
New-Item -ItemType Directory -Force $logs | Out-Null
if ($Cases.Count -eq 1 -and $Cases[0].Contains(',')) { $Cases = $Cases[0].Split(',') }

if ($Detach) {
    $argList = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $PSCommandPath,
                 '-Cases', ($Cases -join ','), '-Root', $Root, '-Tag', $Tag)
    $p = Start-Process -FilePath 'powershell.exe' -ArgumentList $argList -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput "$logs\aij_queue_$Tag.out" -RedirectStandardError "$logs\aij_queue_$Tag.err"
    try { $p.PriorityClass = 'BelowNormal' } catch {}
    "queue $Tag started, PID $($p.Id): $($Cases -join ', ')"
    exit 0
}

try { (Get-Process -Id $PID).PriorityClass = 'BelowNormal' } catch {}
$ofRun = 'E:\PINN\tools\of_run.ps1'   # OpenFOAM v2306 MinGW launcher (see E:\PINN\tools\OPENFOAM_SETUP.md)

foreach ($c in $Cases) {
    $dir = Join-Path $Root $c
    $log = Join-Path $logs "aij_$c.log"
    if (-not (Test-Path "$dir\Allrun")) { "missing $dir\Allrun" | Out-File -Append $log; continue }
    if (Test-Path "$dir\DONE") { "skip $c (DONE exists)" | Out-File -Append $log; continue }
    Remove-Item -ErrorAction SilentlyContinue "$dir\FAILED"
    "=== $c start $(Get-Date -Format s)" | Out-File -Append -Encoding utf8 $log
    $t0 = Get-Date
    try {
        & $ofRun -Case $dir -Cmd 'bash ./Allrun' -LogFile "$log.of" | Out-Null
    } catch {
        "launcher error: $_" | Out-File -Append -Encoding utf8 $log
    }
    $dt = [int]((Get-Date) - $t0).TotalSeconds
    if (-not (Test-Path "$dir\DONE") -and -not (Test-Path "$dir\FAILED")) {
        "FAILED: Allrun ended without marker" | Out-File -Encoding utf8 "$dir\FAILED"
    }
    $st = if (Test-Path "$dir\DONE") { 'DONE' } else { 'FAILED' }
    "=== $c $st after $dt s $(Get-Date -Format s)" | Out-File -Append -Encoding utf8 $log
}
"finished $(Get-Date -Format s)" | Out-File -Encoding utf8 "$logs\aij_queue_$Tag.DONE"
