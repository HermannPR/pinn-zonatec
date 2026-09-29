# watchdog.ps1 - run by the user-level scheduled task 'PinnColaWatchdog' (every 10 min and at logon).
# If jobs are pending and no runner is alive, start runner.ps1 detached. Idempotent and cheap.
$COLA = 'E:\PINN\cola'; $LOCK = Join-Path $COLA 'runner.lock'
if (Test-Path (Join-Path $COLA 'PAUSA')) { exit 0 }      # manual pause switch: create E:\PINN\cola\PAUSA
$alive = $false
if (Test-Path $LOCK) {
    $old = (Get-Content $LOCK -ErrorAction SilentlyContinue | Select-Object -First 1) -as [int]
    if ($old -and (Get-Process -Id $old -ErrorAction SilentlyContinue | Where-Object { $_.ProcessName -match 'powershell' })) { $alive = $true }
}
if ($alive) { exit 0 }
$pending = Get-ChildItem (Join-Path $COLA 'jobs') -Filter *.json -ErrorAction SilentlyContinue | Where-Object {
    $id = (Get-Content $_.FullName -Raw | ConvertFrom-Json).id
    -not (Test-Path (Join-Path $COLA "state\$id.DONE")) -and -not (Test-Path (Join-Path $COLA "state\$id.FAILED"))
}
if (-not $pending) { exit 0 }
Add-Content E:\PINN\logs\cola_runner.log "$(Get-Date -Format s) [watchdog] starting runner ($(@($pending).Count) pending)"
Start-Process powershell -ArgumentList '-NoProfile','-ExecutionPolicy','Bypass','-File','E:\PINN\tools\cola\runner.ps1' -WindowStyle Hidden
