# sync_repo.ps1 - copy version-controllable v2 content (code, configs, docs, small outputs) from
# E:\PINN\v2 and the root docs into the git repo E:\PINN\wind-pinn (branch fase2-zonatec), then
# optionally commit and create a bundle in E:\PINN\outbox. Bulky data never enters git.
# Usage: powershell -File E:\PINN\tools\sync_repo.ps1 [-Commit "mensaje"] [-Bundle]
param([string]$Commit, [switch]$Bundle)
$ErrorActionPreference = 'Stop'
$repo = 'E:\PINN\wind-pinn'
# robocopy: mirror code/docs; exclude heavy/generated stuff
$xd = @('__pycache__','.pytest_cache','data','runs','cache','raw','.ipynb_checkpoints')
$xf = @('*.npz','*.npy','*.h5','*.hdf5','*.parquet','*.body','*.pt','*.pth','*.ckpt','*.stl','*.vtk','*.vtu','*.tif','*.log','*.pyc')
robocopy E:\PINN\v2 "$repo\v2" /MIR /XD $xd /XF $xf /NFL /NDL /NJH /NJS /NP | Out-Null
# small, essential geometry outputs are whitelisted back in (base STL is needed to reproduce; < 10 MB each)
New-Item -ItemType Directory -Force "$repo\v2\geometry\out" | Out-Null
Get-ChildItem E:\PINN\v2\geometry\out -Recurse -File -Include *.csv,*.json,*.md,*.png | ForEach-Object {
    $rel = $_.FullName.Substring('E:\PINN\v2\geometry\out\'.Length); $dst = Join-Path "$repo\v2\geometry\out" $rel
    New-Item -ItemType Directory -Force (Split-Path $dst) | Out-Null; Copy-Item $_.FullName $dst -Force }
# root docs
foreach ($f in 'DECISIONES.md','PLAN.md','ESTADO.md') { Copy-Item "E:\PINN\$f" "$repo\v2\docs\$f" -Force }
New-Item -ItemType Directory -Force "$repo\v2\docs\fuentes","$repo\v2\tools\cola" | Out-Null
Copy-Item E:\PINN\datos\FUENTES.md "$repo\v2\docs\fuentes\FUENTES.md" -Force
Get-ChildItem E:\PINN\datos -Recurse -File -Include *.md | ForEach-Object { Copy-Item $_.FullName "$repo\v2\docs\fuentes\$($_.Directory.Name)_$($_.Name)" -Force }
Copy-Item E:\PINN\datos\alturas\alturas_consolidadas.csv "$repo\v2\docs\fuentes\" -Force -ErrorAction SilentlyContinue
foreach ($f in 'estado.ps1','of_env.ps1','of_run.ps1','sync_repo.ps1','OPENFOAM_SETUP.md') { if (Test-Path "E:\PINN\tools\$f") { Copy-Item "E:\PINN\tools\$f" "$repo\v2\tools\$f" -Force } }
Copy-Item E:\PINN\tools\cola\*.ps1 "$repo\v2\tools\cola\" -Force; Copy-Item E:\PINN\cola\README.md "$repo\v2\tools\cola\README.md" -Force
Set-Location $repo
if ($Commit) {
    git add -A v2
    git -c core.autocrlf=false commit -q -m $Commit
    git log --oneline -1
}
if ($Bundle) {
    New-Item -ItemType Directory -Force E:\PINN\outbox | Out-Null
    $b = "E:\PINN\outbox\cambios-$(Get-Date -Format yyyyMMdd-HHmm).bundle"
    git bundle create $b fase2-zonatec 2>&1 | Out-Null
    git bundle verify $b 2>&1 | Select-Object -Last 1
    Write-Output "BUNDLE $b"
}
