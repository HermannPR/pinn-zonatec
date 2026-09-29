# =============================================================================
# of_run.ps1 - Run an OpenFOAM command (or Allrun script) in a case directory
# =============================================================================
# Usage:
#   E:\PINN\tools\of_run.ps1 -Case E:\PINN\runs\x -Cmd "simpleFoam"
#   E:\PINN\tools\of_run.ps1 -Case E:\PINN\runs\x -Cmd "blockMesh"
#   E:\PINN\tools\of_run.ps1 -Case E:\PINN\runs\x -Cmd "./Allrun"
#   E:\PINN\tools\of_run.ps1 -Case E:\PINN\runs\x -Cmd "mpiexec -n 6 simpleFoam -parallel"
#   E:\PINN\tools\of_run.ps1 -Case E:\PINN\runs\x -Cmd "simpleFoam" -Background -LogFile E:\PINN\logs\myrun.log
#
# -Background launches the command detached (Start-Process) so this script
# returns immediately; stdout+stderr go to -LogFile (required in that mode).
# Without -Background, the command runs synchronously and output is streamed
# to the console (and also to -LogFile if given). The process exit code is
# written to $LASTEXITCODE / returned by this script's exit code.
#
# This script (and of_env.ps1) can be called from other agents' scripts or
# from a detached Start-Process, e.g.:
#   Start-Process powershell -ArgumentList '-NoProfile','-File','E:\PINN\tools\of_run.ps1','-Case','E:\PINN\runs\x','-Cmd','simpleFoam','-LogFile','E:\PINN\logs\x.log' -WindowStyle Hidden
# =============================================================================
param(
    [Parameter(Mandatory=$true)][string]$Case,
    [Parameter(Mandatory=$true)][string]$Cmd,
    [string]$LogFile,
    [switch]$Background
)

. (Join-Path $PSScriptRoot "of_env.ps1")

if (-not (Test-Path $Case)) {
    Write-Error "Case directory does not exist: $Case"
    exit 2
}

if ($Background) {
    if (-not $LogFile) {
        Write-Error "-LogFile is required when using -Background"
        exit 2
    }
    $unixCase = Convert-ToUnixPath $Case
    $scriptPath = New-OFScriptFile -UnixCase $unixCase -Cmd $Cmd
    $errLog = "$LogFile.err"

    # Pass the script file as the sole argument (no -c string) - see the
    # comment on New-OFScriptFile for why this avoids a Start-Process
    # argument-quoting bug that silently truncates `bash -c "..."` strings.
    $proc = Start-Process -FilePath $OF_BASH -ArgumentList @($scriptPath) `
        -RedirectStandardOutput $LogFile -RedirectStandardError $errLog `
        -WindowStyle Hidden -PassThru

    Write-Output "Started PID=$($proc.Id) LogFile=$LogFile ErrLog=$errLog ScriptFile=$scriptPath"
    exit 0
} else {
    $code = Invoke-OFCommand -Case $Case -Cmd $Cmd -LogFile $LogFile
    exit $code
}
