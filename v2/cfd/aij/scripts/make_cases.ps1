<#
  Generate the AIJ Case A run matrix under E:\PINN\runs\aij (existing non-empty case dirs are skipped).
    homogeneity (2-D empty domain): hom_<model>_<inlet>_<ground>
    building (3-D):                  bld_<model>_<mesh>   mesh C (f=0.77), M (f=1.0), F (f=1.3)
  Usage: powershell -File make_cases.ps1 [-Set hom|bld|gci] [-GciModel realizableKE] [-Gwf atm|std]
#>
param([ValidateSet('hom', 'bld', 'gci', 'all')][string]$Set = 'all',
      [string]$GciModel = 'realizableKE', [ValidateSet('atm', 'std')][string]$Gwf = 'atm',
      [string]$Root = 'E:\PINN\runs\aij')
$py = 'E:\PINN\.venv\Scripts\python.exe'
$gen = Join-Path $PSScriptRoot 'gen_case.py'
$short = @{ realizableKE = 'rke'; kOmegaSST = 'sst'; kEpsilon = 'ske' }
New-Item -ItemType Directory -Force $Root | Out-Null
function Gen($name, [string[]]$extra) {
    $out = Join-Path $Root $name
    if ((Test-Path $out) -and (Get-ChildItem $out | Measure-Object).Count -gt 0) { "skip $name (exists)"; return }
    & $py $gen --out $out --gwf $Gwf @extra | Out-Null
    if ($LASTEXITCODE -eq 0) { "made $name" } else { "ERROR $name" }
}
if ($Set -in 'hom', 'all') {
    foreach ($m in 'realizableKE', 'kOmegaSST', 'kEpsilon') {
        Gen "hom_$($short[$m])_table_rough"  @('--kind', 'empty2d', '--model', $m, '--inlet', 'table', '--ground', 'rough', '--end', '3000')
        Gen "hom_$($short[$m])_table_smooth" @('--kind', 'empty2d', '--model', $m, '--inlet', 'table', '--ground', 'smooth', '--end', '3000')
        Gen "hom_$($short[$m])_loglaw_rough" @('--kind', 'empty2d', '--model', $m, '--inlet', 'loglaw', '--ground', 'rough', '--end', '3000')
    }
}
if ($Set -in 'bld', 'all') {
    foreach ($m in 'realizableKE', 'kOmegaSST', 'kEpsilon') {
        Gen "bld_$($short[$m])_M" @('--kind', 'building', '--model', $m, '--level', '1.0')
    }
}
if ($Set -eq 'gci') {
    Gen "bld_$($short[$GciModel])_C" @('--kind', 'building', '--model', $GciModel, '--level', '0.77')
    Gen "bld_$($short[$GciModel])_F" @('--kind', 'building', '--model', $GciModel, '--level', '1.3')
}
