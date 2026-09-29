# estado.ps1 - shared helper to update E:\PINN\estado.json (read by the scheduled
# task HivemindPinnEstado -> tools\reportar-estado.ps1) and E:\PINN\ESTADO.md.
# Usage:  . E:\PINN\tools\estado.ps1 ; Set-Estado -Fase 'F1 AIJ' -Caso 'bld_rke_M' -Progreso '1/3' `
#             -Detalle 'simpleFoam it 1200' -Corriendo $true -Proceso 'bash' -Log 'E:\PINN\logs\x.log'
# Only the parameters you pass are changed; 'latido' is set to now unless -NoLatido.
# Writes atomically (temp file + move) so the monitor never reads a half-written file.

$Global:ESTADO_JSON = 'E:\PINN\estado.json'
$Global:ESTADO_MD   = 'E:\PINN\ESTADO.md'

function Get-Estado {
    try { return (Get-Content $ESTADO_JSON -Raw -Encoding UTF8 | ConvertFrom-Json) } catch { return $null }
}

function Set-Estado {
    param(
        [string]$Fase, [string]$Caso, [string]$Progreso, [string]$Detalle,
        [Nullable[bool]]$Corriendo, [string]$Proceso, [string]$Log,
        [switch]$NoLatido
    )
    $e = Get-Estado
    $h = [ordered]@{ fase=''; caso=''; progreso=''; detalle=''; corriendo=$false; proceso=''; log=''; latido=(Get-Date).ToString('s') }
    if ($e) { foreach ($k in @($h.Keys)) { if ($null -ne $e.$k) { $h[$k] = $e.$k } } }
    if ($PSBoundParameters.ContainsKey('Fase'))      { $h.fase = $Fase }
    if ($PSBoundParameters.ContainsKey('Caso'))      { $h.caso = $Caso }
    if ($PSBoundParameters.ContainsKey('Progreso'))  { $h.progreso = $Progreso }
    if ($PSBoundParameters.ContainsKey('Detalle'))   { $h.detalle = $Detalle }
    if ($PSBoundParameters.ContainsKey('Corriendo')) { $h.corriendo = [bool]$Corriendo }
    if ($PSBoundParameters.ContainsKey('Proceso'))   { $h.proceso = $Proceso }
    if ($PSBoundParameters.ContainsKey('Log'))       { $h.log = $Log }
    if (-not $NoLatido) { $h.latido = (Get-Date).ToString('s') }
    $tmp = "$ESTADO_JSON.tmp"
    for ($i = 0; $i -lt 5; $i++) {
        try {
            ([pscustomobject]$h | ConvertTo-Json) | Set-Content -Path $tmp -Encoding UTF8
            Move-Item -Force $tmp $ESTADO_JSON
            break
        } catch { Start-Sleep -Milliseconds 300 }
    }
    try { Update-EstadoMd $h } catch {}
}

function Update-EstadoMd($h) {
    # Regenerates the auto section of ESTADO.md (between the AUTO markers); keeps the manual part.
    $auto = @"
<!-- AUTO:BEGIN (generado por tools\estado.ps1; no editar a mano) -->
| Campo | Valor |
|---|---|
| Fase | $($h.fase) |
| Caso | $($h.caso) |
| Progreso | $($h.progreso) |
| Detalle | $($h.detalle) |
| Corriendo | $($h.corriendo) |
| Proceso | $($h.proceso) |
| Log | ``$($h.log)`` |
| Último latido | $($h.latido) |
<!-- AUTO:END -->
"@
    $txt = if (Test-Path $ESTADO_MD) { Get-Content $ESTADO_MD -Raw -Encoding UTF8 } else { "# ESTADO - PINN Zona Tec`n`n" }
    if ($txt -match '(?s)<!-- AUTO:BEGIN.*?<!-- AUTO:END -->') {
        $txt = [regex]::Replace($txt, '(?s)<!-- AUTO:BEGIN.*?<!-- AUTO:END -->', [System.Text.RegularExpressions.MatchEvaluator]{ param($m) $auto })
    } else { $txt = $txt.TrimEnd() + "`n`n## Estado automático`n" + $auto + "`n" }
    Set-Content -Path $ESTADO_MD -Value $txt -Encoding UTF8
}
