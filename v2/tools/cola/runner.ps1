# Canal: servidor y topic vienen de variables de entorno o de un archivo local fuera del repo (nunca en git).
if (-not $env:HIVEMIND_TOPIC -and (Test-Path 'C:\hivemind\canal.local.json')) { $cfg = Get-Content 'C:\hivemind\canal.local.json' -Raw | ConvertFrom-Json; $env:HIVEMIND_SERVER = $cfg.server; $env:HIVEMIND_TOPIC = $cfg.topic }
# runner.ps1 - fail-safe sequential job queue for PINN Zona Tec (CFD + ML).
# Started (detached) by watchdog.ps1; safe to start by hand too. Only one instance runs (lock + PID check).
# Job specs: E:\PINN\cola\jobs\*.json, processed in file-name order. Contract: E:\PINN\cola\README.md
# State markers: E:\PINN\cola\state\<id>.DONE | .FAILED | .attempts | .verify.log ; logs: E:\PINN\logs\jobs\<id>.log
param([switch]$Once)   # -Once: process at most one job then exit (testing)

$ErrorActionPreference = 'Continue'
$COLA   = 'E:\PINN\cola'
$JOBDIR = Join-Path $COLA 'jobs'   # NB: not $JOBS - PowerShell vars are case-insensitive ($jobs below)
$STATE  = Join-Path $COLA 'state'
$LOGDIR = 'E:\PINN\logs\jobs'
$LOCK   = Join-Path $COLA 'runner.lock'
$RLOG   = 'E:\PINN\logs\cola_runner.log'
foreach ($d in $JOBDIR, $STATE, $LOGDIR) { if (-not (Test-Path $d)) { New-Item -ItemType Directory -Force $d | Out-Null } }
$env:TMP = 'E:\tmp'; $env:TEMP = 'E:\tmp'
. E:\PINN\tools\estado.ps1
. E:\PINN\tools\of_env.ps1

function Log($m) { $l = "$(Get-Date -Format s) [runner $PID] $m"; Add-Content -Path $RLOG -Value $l -Encoding UTF8 }
function Send-Canal($tipo, $txt) {
    try { & powershell -NoProfile -ExecutionPolicy Bypass -File C:\hivemind\agent\windows\send.ps1 -Server $env:HIVEMIND_SERVER -Topic $env:HIVEMIND_TOPIC -From claude-culiacan -To hermann -Type $tipo -Body ($txt -replace '"','') | Out-Null } catch {}
}

# ---- single instance lock ----
if (Test-Path $LOCK) {
    $old = (Get-Content $LOCK -ErrorAction SilentlyContinue | Select-Object -First 1) -as [int]
    if ($old -and (Get-Process -Id $old -ErrorAction SilentlyContinue | Where-Object { $_.ProcessName -match 'powershell' })) {
        exit 0   # another runner alive
    }
}
Set-Content -Path $LOCK -Value $PID
Log "runner started"

function Get-Jobs {
    Get-ChildItem $JOBDIR -Filter *.json | Sort-Object Name | ForEach-Object {
        try { $j = Get-Content $_.FullName -Raw -Encoding UTF8 | ConvertFrom-Json; $j | Add-Member -NotePropertyName _file -NotePropertyValue $_.FullName -Force; $j }
        catch { Log "bad job json $($_.FullName)" }
    }
}
function Is-Done($id)   { Test-Path (Join-Path $STATE "$id.DONE") }
function Is-Failed($id) { Test-Path (Join-Path $STATE "$id.FAILED") }

$OF_EXES = 'snappyHexMesh','blockMesh','simpleFoam','pimpleFoam','potentialFoam','decomposePar','reconstructPar','reconstructParMesh','checkMesh','surfaceFeatureExtract','mapFields','postProcess','foamToVTK','mpiexec','topoSet','createPatch','renumberMesh','python'

function Start-Job1($j, $log) {
    $err = "$log.err"
    if ($j.kind -eq 'openfoam') {
        $unix = Convert-ToUnixPath $j.case
        $script = New-OFScriptFile -UnixCase $unix -Cmd $j.cmd
        return Start-Process -FilePath $OF_BASH -ArgumentList @($script) -RedirectStandardOutput $log -RedirectStandardError $err -WindowStyle Hidden -PassThru
    } elseif ($j.kind -eq 'python') {
        $exe = if ($j.python) { $j.python } else { 'E:\PINN\.venv\Scripts\python.exe' }
        $wd  = if ($j.workdir) { $j.workdir } else { 'E:\PINN\v2' }
        # Start-Process re-splits array elements on spaces: quote each arg (escape inner double quotes)
        $argStr = (@($j.args) | ForEach-Object { if ($_ -match '[\s"]') { '"' + ($_ -replace '"','\"') + '"' } else { $_ } }) -join ' '
        return Start-Process -FilePath $exe -ArgumentList $argStr -WorkingDirectory $wd -RedirectStandardOutput $log -RedirectStandardError $err -WindowStyle Hidden -PassThru
    } else { throw "unknown kind $($j.kind)" }
}

$processed = 0
while ($true) {
    $jobs = @(Get-Jobs)
    $pending = @($jobs | Where-Object { -not (Is-Done $_.id) -and -not (Is-Failed $_.id) })
    $total = $jobs.Count; $ndone = @($jobs | Where-Object { Is-Done $_.id }).Count
    # first pending job whose dependencies are all DONE
    $j = $pending | Where-Object { $deps = @($_.after); (@($deps | Where-Object { $_ -and -not (Is-Done $_) }).Count -eq 0) } | Select-Object -First 1
    if (-not $j) {
        $blocked = $pending.Count
        Set-Estado -Fase 'cola' -Caso '-' -Progreso "$ndone/$total" -Detalle $(if ($blocked) { "cola detenida: $blocked trabajos esperan dependencias fallidas o pendientes" } else { 'cola vacía: todos los trabajos terminados' }) -Corriendo $false -Proceso '' -Log ''
        Log "nothing runnable (pending=$blocked); exit"
        break
    }
    if ($Once -and $processed -ge 1) { break }

    # ---- disk check ----
    $minFree = if ($j.min_free_gb) { [double]$j.min_free_gb } else { 15 }
    $free = [math]::Round((Get-PSDrive E).Free / 1GB, 1)
    if ($free -lt $minFree) {
        Log "disk low ($free GB < $minFree) before $($j.id); stopping"
        Set-Estado -Fase $j.fase -Caso $j.id -Detalle "PAUSA: disco E: con $free GB (< $minFree GB); liberar espacio" -Corriendo $false
        Send-Canal 'bloqueo' "[PINN] Cola en pausa: disco E: con $free GB libres antes de $($j.id). Hay que liberar espacio o mover resultados a D:."
        break
    }

    # ---- attempt bookkeeping ----
    $attF = Join-Path $STATE "$($j.id).attempts"
    $att = 0; if (Test-Path $attF) { $att = [int](Get-Content $attF) }
    $maxAtt = if ($j.max_attempts) { [int]$j.max_attempts } else { 3 }
    if ($att -ge $maxAtt) {
        Set-Content (Join-Path $STATE "$($j.id).FAILED") "max attempts reached ($att) $(Get-Date -Format s)"
        Send-Canal 'bloqueo' "[PINN] Trabajo FALLIDO tras $att intentos: $($j.id) ($($j.fase)). Log: E:\PINN\logs\jobs\$($j.id).log"
        Log "$($j.id) FAILED (max attempts)"
        continue
    }
    $att++; Set-Content $attF $att
    $log = Join-Path $LOGDIR "$($j.id).log"
    if (Test-Path $log) { Move-Item -Force $log "$log.prev$($att-1)" -ErrorAction SilentlyContinue }
    $proc0 = if ($j.kind -eq 'python') { 'python' } else { 'bash' }
    Set-Estado -Fase $j.fase -Caso $j.id -Progreso "$($ndone+1)/$total" -Detalle "intento $att/$maxAtt; arrancando" -Corriendo $true -Proceso $proc0 -Log $log
    Log "start $($j.id) attempt $att"
    # cache the process handle so ExitCode is available after exit
    try { $p = Start-Job1 $j $log; $null = $p.Handle } catch {Log "start error $($j.id): $_"; Start-Sleep 30; continue }
    try { $p.PriorityClass = 'BelowNormal' } catch {}

    # ---- heartbeat loop ----
    $lastLen = -1; $lastBeat = Get-Date
    while (-not $p.HasExited) {
        Start-Sleep -Seconds 60
        # lower priority of any solver children too
        Get-Process -Name $OF_EXES -ErrorAction SilentlyContinue | ForEach-Object { try { if ($_.PriorityClass -ne 'BelowNormal' -and $_.ProcessName -ne 'python') { $_.PriorityClass = 'BelowNormal' } } catch {} }
        $len = (Get-Item $log -ErrorAction SilentlyContinue).Length
        $active = (Get-Process -Name $OF_EXES -ErrorAction SilentlyContinue | Select-Object -ExpandProperty ProcessName -Unique) -join ','
        $tail = (Get-Content $log -Tail 40 -ErrorAction SilentlyContinue | Where-Object { $_ -match '^Time = |^Iteration|epoch|step' } | Select-Object -Last 1)
        if ($len -ne $lastLen) {
            $lastLen = $len; $lastBeat = Get-Date
            Set-Estado -Detalle ("intento $att/$maxAtt; activo: $active; " + "$tail").Trim() -Corriendo $true -Proceso $proc0 -Log $log
        }
        # log silent for > 3 h -> considered hung: kill tree, will retry (resumable jobs)
        $hang = if ($j.hang_minutes) { [int]$j.hang_minutes } else { 180 }
        if (((Get-Date) - $lastBeat).TotalMinutes -gt $hang) {
            Log "$($j.id) hung (no log growth $hang min); killing"
            & taskkill /PID $p.Id /T /F | Out-Null
            break
        }
    }
    $p.WaitForExit()
    $code = $p.ExitCode
    Log "$($j.id) exited code=$code"

    # ---- verification (must pass before DONE) ----
    $ok = $false
    if ($code -eq 0 -or $j.ignore_exit_code) {
        if ($j.verify) {
            $vlog = Join-Path $STATE "$($j.id).verify.log"
            Set-Estado -Detalle "verificando resultados" -Corriendo $false
            & powershell -NoProfile -ExecutionPolicy Bypass -Command $j.verify *> $vlog
            $ok = ($LASTEXITCODE -eq 0)
            Log "$($j.id) verify exit=$LASTEXITCODE"
        } else { $ok = $true }
    }
    if ($ok) {
        Set-Content (Join-Path $STATE "$($j.id).DONE") "done $(Get-Date -Format s) attempt $att"
        Set-Estado -Detalle "terminado y verificado: $($j.id)" -Corriendo $false -Proceso '' -Log ''
        if ($j.notify) { Send-Canal 'hecho' "[PINN] Hecho y verificado: $($j.id) ($($j.fase)). $($j.notify)" }
    } else {
        Set-Estado -Detalle "intento $att falló (code $code o verificación); se reintentará" -Corriendo $false -Proceso '' -Log ''
        Start-Sleep -Seconds 20
    }
    $processed++
}
Remove-Item $LOCK -ErrorAction SilentlyContinue
Log "runner exit"
