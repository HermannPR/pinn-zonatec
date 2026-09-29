# =============================================================================
# of_env.ps1 - OpenFOAM v2306 (Windows MinGW build) environment helper
# =============================================================================
# Dot-source this file, or let of_run.ps1 dot-source it, to get the paths and
# the Convert-ToUnixPath / Invoke-OFCommand helper functions used to drive
# OpenFOAM non-interactively from PowerShell.
#
# Install layout (no admin rights used anywhere in this setup):
#   E:\PINN\tools\openfoam\msys64\...                     <- MSYS2 + OpenFOAM
#       ...\home\ofuser\OpenFOAM\OpenFOAM-v2306\           <- WM_PROJECT_DIR
#   E:\PINN\tools\msmpi\bin\mpiexec.exe, smpd.exe, msmpi.dll
#       (extracted by hand from the official msmpisetup.exe v10.1.3, x64
#        payload, WITHOUT running the installer -> no admin/UAC needed)
# =============================================================================

$Global:OF_ROOT          = "E:\PINN\tools\openfoam"
$Global:OF_MSYS_ROOT     = Join-Path $OF_ROOT "msys64"
$Global:OF_BASH          = Join-Path $OF_MSYS_ROOT "usr\bin\bash.exe"
$Global:OF_PROJECT_UNIX  = "/home/ofuser/OpenFOAM/OpenFOAM-v2306"
$Global:OF_PROJECT_WIN   = Join-Path $OF_MSYS_ROOT "home\ofuser\OpenFOAM\OpenFOAM-v2306"
$Global:MSMPI_BIN_WIN    = "E:\PINN\tools\msmpi\bin"
$Global:MSMPI_BIN_UNIX   = "/e/PINN/tools/msmpi/bin"

# Always keep TMP/TEMP under E: (C: has ~1GB free only)
$env:TMP  = "E:\tmp"
$env:TEMP = "E:\tmp"
if (-not (Test-Path "E:\tmp")) { New-Item -ItemType Directory -Force -Path "E:\tmp" | Out-Null }

function Convert-ToUnixPath {
    <#
        Converts a Windows path (e.g. E:\PINN\runs\foo) to the MSYS2-style
        unix path the bundled bash expects (/e/PINN/runs/foo).
        The path does not need to exist for this to work, but if it exists
        it will be fully resolved first.
    #>
    param([Parameter(Mandatory=$true)][string]$Path)

    if (Test-Path $Path) {
        $full = (Resolve-Path $Path).Path
    } else {
        # Best effort for paths that will be created by the command itself
        $full = [System.IO.Path]::GetFullPath($Path)
    }
    $drive = $full.Substring(0,1).ToLower()
    $rest  = $full.Substring(2) -replace '\\','/'
    return "/$drive$rest"
}

function New-OFInnerCommand {
    <#
        Builds the full shell command string to hand to bash -c, including
        sourcing the OpenFOAM environment (etc/bashrc) and cd'ing into the
        case directory (given as a unix path).
    #>
    param(
        [Parameter(Mandatory=$true)][string]$UnixCase,
        [Parameter(Mandatory=$true)][string]$Cmd
    )
    $path = "/usr/bin:/bin:$MSMPI_BIN_UNIX"
    return "export HOME=/home/ofuser; export PATH='$path'; source $OF_PROJECT_UNIX/etc/bashrc; cd '$UnixCase' && $Cmd"
}

function New-OFScriptFile {
    <#
        Writes the inner command to a standalone temp .sh file and returns
        its Windows path. Using a script FILE (instead of passing the whole
        command as a `bash -c "..."` argument) sidesteps a real PowerShell/
        Start-Process quoting bug where a single -ArgumentList element
        containing spaces, quotes and semicolons gets re-split into several
        argv entries, so bash -c only ever sees its first word (e.g. plain
        "export", which just dumps the environment and ignores the rest).
        A script file has no such quoting hazard: bash gets exactly one
        plain path argument.
    #>
    param(
        [Parameter(Mandatory=$true)][string]$UnixCase,
        [Parameter(Mandatory=$true)][string]$Cmd
    )
    $inner = New-OFInnerCommand -UnixCase $UnixCase -Cmd $Cmd
    $tmpDir = "E:\tmp\of_scripts"
    if (-not (Test-Path $tmpDir)) { New-Item -ItemType Directory -Force -Path $tmpDir | Out-Null }
    $scriptPath = Join-Path $tmpDir ("of_cmd_{0}.sh" -f ([guid]::NewGuid().ToString("N")))
    # LF-only, no BOM - Set-Content on Windows PowerShell 5.1 defaults to
    # ASCII-safe here since our content is plain ASCII; force no BOM anyway.
    $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($scriptPath, ($inner -replace "`r`n","`n"), $utf8NoBom)
    return $scriptPath
}

function Invoke-OFCommand {
    <#
        Runs a command synchronously inside the OpenFOAM environment, in the
        given case directory, streaming/capturing output. Returns the
        process exit code.
    #>
    param(
        [Parameter(Mandatory=$true)][string]$Case,
        [Parameter(Mandatory=$true)][string]$Cmd,
        [string]$LogFile
    )
    $unixCase = Convert-ToUnixPath $Case
    $scriptPath = New-OFScriptFile -UnixCase $unixCase -Cmd $Cmd

    if ($LogFile) {
        & $OF_BASH $scriptPath 2>&1 | Tee-Object -FilePath $LogFile
    } else {
        & $OF_BASH $scriptPath 2>&1
    }
    $code = $LASTEXITCODE
    Remove-Item -Force $scriptPath -ErrorAction SilentlyContinue
    return $code
}
