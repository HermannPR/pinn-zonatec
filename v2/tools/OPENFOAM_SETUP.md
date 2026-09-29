# OpenFOAM v2306 (Windows MinGW build) — no-admin setup for PINN Zona Tec

All numbers and test results below were produced by actually running the
commands on this machine and reading their logs. No admin rights, no UAC
prompt, and no installer was ever executed to get here.

## What was installed

**Route used:** ESI/openfoam.com official Windows MinGW cross-compiled build,
version **v2306** (`OpenFOAM-v2306-windows-mingw.exe`, 325,233,616 bytes,
downloaded from SourceForge / dl.openfoam.com).

This installer is an NSIS package whose PE manifest has **no
`requestedExecutionLevel`** entry (defaults to `asInvoker`), and it embeds its
entire payload as a single `msys64.7z` archive plus a few launcher batch
files. Instead of running the installer at all, we:

1. Extracted a full-featured `7z.exe`/`7z.dll` from the official 7-Zip
   installer (`7z2409-x64.exe`) using the minimal standalone `7zr.exe`
   (downloaded from 7-zip.org) — this never runs any installer either, it
   just unpacks the 7-Zip SFX payload.
2. Used that `7z.exe` to extract the OpenFOAM NSIS installer's payload
   directly (`7z x OpenFOAM-v2306-windows-mingw.exe msys64.7z ...`),
   without ever launching the installer's UI/wizard.
3. Extracted `msys64.7z` (315,900,763 bytes compressed, 1,563,316,469 bytes
   uncompressed, 40,090 files) into `E:\PINN\tools\openfoam\`.

**Install root:** `E:\PINN\tools\openfoam\msys64\...`
**`WM_PROJECT_DIR`:**
`E:\PINN\tools\openfoam\msys64\home\ofuser\OpenFOAM\OpenFOAM-v2306`
(unix path inside the bundled MSYS2: `/home/ofuser/OpenFOAM/OpenFOAM-v2306`)

**Platform / build:** `win64MingwDPInt32Opt` (64-bit, double precision,
32-bit labels, optimised). `OPENFOAM=2306`, build `34e226dfe3-20211220`.
This is a **binary-only** distribution: compiling OpenFOAM itself or any
dynamic/`codedFixedValue`-style code is **not supported** (confirmed by the
vendor's own `README.txt` inside the package; not something we hit a bug on,
just a documented limitation).

All required applications are present and were exercised successfully:
`simpleFoam`, `blockMesh`, `snappyHexMesh`, `surfaceFeatureExtract`,
`checkMesh`, `decomposePar`, `reconstructPar`, `reconstructParMesh`,
`postProcess`, `foamToVTK`. Note: there is no standalone `sample` binary in
this version (normal for OpenFOAM.com ≥ ~v1906) — sampling is done via
`postProcess -func sample` instead.

## MPI (parallel) — WORKING, no admin

The bundle's own third-party MS-MPI installer (`thirdParty\msmpisetup.exe`,
and the current official one from microsoft.com, both checked) has a PE
manifest that **requires admin** (`requestedExecutionLevel level=
'requireAdministrator'`), so it cannot be run directly under the project's
no-UAC rule.

Instead, MS-MPI's runtime binaries were extracted **without running the
installer**, using the same `7z.exe`:

- `msmpisetup.exe` (current official v10.1.3, `10.1.12498.52`, downloaded
  directly from
  `download.microsoft.com/download/7/2/7/72731ebb-b63c-4170-ade7-836966263a8f/msmpisetup.exe`)
  is a WiX-Burn bootstrapper containing **two embedded MSI packages**
  concatenated in the file: an x86 one first, and an x64 one appended after
  it (7-Zip's automatic archive-type detection only sees the first one and
  reports the rest as "data after the end of archive" — the x64 payload had
  to be carved out by byte offset and re-opened with `7z` as its own
  compound/MSI file).
- From the **x64** payload's `product.cab` we extracted `mpiexec.exe`,
  `smpd.exe`, and `msmpi64.dll` (renamed to `msmpi.dll`) into
  `E:\PINN\tools\msmpi\bin\`.
- **Pitfall hit and fixed:** the first (x86) payload looks identical in
  filenames (`msmpi.dll`, `mpiexec.exe`, `smpd.exe`) but is 32-bit. Using it
  against the 64-bit OpenFOAM binaries made every solver crash immediately
  with exit code `0xC000007B` (`STATUS_INVALID_IMAGE_FORMAT`). Verified
  architecture via raw PE header parsing (`0x8664` = x64, `0x14C` = x86)
  before and after the fix.

No MS-MPI Windows service (`smpd`) needed to be installed or registered —
`mpiexec.exe` happily spawns and manages local worker processes itself.
Confirmed both with Intel MPI Benchmarks (`mpiexec -n 4 IMB_MPI1.exe
pingpong`, exit code 0) and with real OpenFOAM parallel runs (see Test c
below). OpenFOAM's shipped `libPstream.dll` is already the MSMPI variant by
default (`WM_MPLIB=MSMPI` is the built-in default in this build's
`etc/bashrc`, no `prefs.sh` needed).

**Parallel status: fully working, no admin, no service.**

## How to launch OpenFOAM commands (the launcher scripts)

- `E:\PINN\tools\of_env.ps1` — dot-sourced helper, defines paths
  (`$OF_ROOT`, `$OF_BASH`, `$OF_PROJECT_UNIX`, `$MSMPI_BIN_*`) and the
  functions `Convert-ToUnixPath`, `New-OFInnerCommand`, `New-OFScriptFile`,
  `Invoke-OFCommand`.
- `E:\PINN\tools\of_run.ps1` — the actual entry point:

  ```powershell
  E:\PINN\tools\of_run.ps1 -Case E:\PINN\runs\x -Cmd "simpleFoam"
  E:\PINN\tools\of_run.ps1 -Case E:\PINN\runs\x -Cmd "blockMesh"
  E:\PINN\tools\of_run.ps1 -Case E:\PINN\runs\x -Cmd "./Allrun"
  E:\PINN\tools\of_run.ps1 -Case E:\PINN\runs\x -Cmd "mpiexec -n 6 simpleFoam -parallel"
  E:\PINN\tools\of_run.ps1 -Case E:\PINN\runs\x -Cmd "simpleFoam" -Background -LogFile E:\PINN\logs\myrun.log
  ```

  `-Background` launches the command detached via `Start-Process`
  (hidden window) and returns immediately; stdout+stderr go to `-LogFile`
  (and `-LogFile.err`). Without `-Background` it runs synchronously and
  streams to the console (and to `-LogFile` if given too). Works fine when
  called from another agent's script or from a detached process.

### Implementation notes / pitfalls fixed inside the launcher

1. **Environment sourcing.** OpenFOAM's `etc/bashrc` must be sourced inside
   the *bundled* MSYS2 `bash.exe`
   (`E:\PINN\tools\openfoam\msys64\usr\bin\bash.exe`), with `PATH` starting
   with that same MSYS2's own `/usr/bin:/bin` **before** anything else. If
   `bash.exe` inherits an outer shell's `PATH` that puts a *different*
   MSYS2/Cygwin runtime first (e.g. Git for Windows' bash), calling plain
   `dirname` from inside `etc/bashrc` silently cross-execs the wrong
   runtime's `dirname.exe` and fails with "missing operand" even though the
   argument is clearly present in a `bash -x` trace — this breaks
   `WM_PROJECT_DIR` detection (it silently becomes `/`) and cascades into
   "Could not find mandatory etc entry" errors. Fixed by explicitly setting
   `PATH='/usr/bin:/bin:<msmpi bin>'` before sourcing.
2. **`Start-Process -ArgumentList` quoting bug.** Passing
   `bash.exe -c "<long command with quotes/semicolons>"` through
   PowerShell's `Start-Process -ArgumentList` array can get re-split, so
   `bash -c` only ever receives its first word (observed: bash ran bare
   `export`, dumping the whole environment instead of our command). Fixed
   by writing the full command to a temp `.sh` file
   (`E:\tmp\of_scripts\of_cmd_<guid>.sh`) and invoking
   `bash.exe <scriptfile>` with a single plain-path argument — no quoting
   hazard at all.
3. `$env:TMP` / `$env:TEMP` are forced to `E:\tmp` inside `of_env.ps1` on
   every call (C: has ~1 GB free and must not be touched).

## Acceptance tests — all run and verified on this machine

### (a) simpleFoam / pitzDaily — PASS
Copied to `E:\PINN\runs\_oftests\pitzDaily`. `blockMesh` then `simpleFoam`.
**Converged in 283 iterations**, `ExecutionTime = 4.584 s`.
Logs: `E:\PINN\logs\openfoam_pitzDaily_blockMesh.log`,
`E:\PINN\logs\openfoam_pitzDaily_simpleFoam.log`.

### (b) blockMesh + snappyHexMesh + checkMesh — PASS
Custom case `E:\PINN\runs\_oftests\snappyBox`: a 4×1×1 m channel
(`blockMesh`, 6912 background cells) with a 0.5×0.2×0.2 m box STL obstacle
(`constant/triSurface/box.stl`, hand-written). Ran `surfaceFeatureExtract`,
then `snappyHexMesh -overwrite` (castellate+snap, 2 refinement levels on the
box): **"Finished meshing without any errors"**, final mesh **7987 cells**
(well under the 300k limit). `checkMesh` → **"Mesh OK."**
Logs: `openfoam_snappyBox_blockMesh.log`,
`openfoam_snappyBox_surfaceFeatureExtract.log`,
`openfoam_snappyBox_snappyHexMesh.log`, `openfoam_snappyBox_checkMesh.log`.

### (c) Parallel (decomposePar + mpiexec -n 6 + reconstructPar) — PASS
Fresh pitzDaily copy `E:\PINN\runs\_oftests\pitzDaily_parallel`,
`decomposeParDict` set to 6 subdomains, method `scotch`. `endTime` set to
50 to force a fixed-length run.
- `decomposePar`: OK, 6 processor directories (~2037 cells each).
- `mpiexec -n 6 simpleFoam -parallel`: ran the full 50 iterations to
  completion, "Finalising parallel run", exit code 0.
- `reconstructPar`: OK, produced top-level time directory `50`.

No admin rights, no MS-MPI service were needed for any of this.
Logs: `openfoam_parallel_decomposePar.log`,
`openfoam_parallel_simpleFoam.log`, `openfoam_parallel_reconstructPar.log`.

### (d) Atmospheric boundary layer BCs — PASS
Confirmed present (RTTI-registered) in `libatmosphericModels.dll` by
inspecting exported symbol strings:
`atmBoundaryLayerInletVelocity`, `atmBoundaryLayerInletK`,
`atmBoundaryLayerInletEpsilon`, `atmBoundaryLayerInletOmega`,
`atmEpsilonWallFunction`, `atmOmegaWallFunction`, `atmNutkWallFunction`.

Note the naming in this openfoam.com build:  the wall roughness function is
called **`atmNutkWallFunction`**, not `nutkAtmRoughWallFunction` (that name
belongs to a different OpenFOAM fork/version and does not exist here).

Also **functionally verified live**: added `atmBoundaryLayerInletVelocity` /
`atmBoundaryLayerInletK` / `atmBoundaryLayerInletEpsilon` on the `inlet`
patch and `atmEpsilonWallFunction` / `atmNutkWallFunction` on `walls` of the
`snappyBox` case (kEpsilon RAS), then ran `simpleFoam`. All boundary
conditions constructed and evaluated correctly through a real solve (no
FATAL errors from the BCs themselves — the only errors hit and fixed along
the way were dictionary syntax, e.g. the current v2306 entry name is `d`
(zero-plane displacement), not `zGround`, confirmed against the
`turbineSiting` tutorial's `include/ABLConditions`).
Log: `openfoam_atmBC_test.log`. `atmBoundaryLayerInletOmega` was confirmed
present as a symbol but not exercised live (the live test used kEpsilon,
not kOmega).

### (e) Benchmark — 1,000,000-cell box, kEpsilon, simpleFoam
Case `E:\PINN\runs\_oftests\benchmark1M`: 2×2×2 m cube, `blockMesh`
100×100×100 = exactly 1,000,000 cells, kEpsilon RAS, fixed 20 iterations
(no convergence stop, so timing is comparable between serial/parallel).
Per-iteration cost below excludes iteration 1 (mesh read + matrix
allocation overhead) and the final write iteration (disk I/O), using only
the steady middle iterations, taken directly from each run's own
`ExecutionTime` log deltas.

| Run                       | s / iteration (1M cells) | Peak RAM (working set) |
|---------------------------|---------------------------|--------------------------|
| Serial (1 core)           | **2.76 s/iter**           | **~1.23 GiB** (1,320,038,400 B) |
| Parallel (6 ranks, scotch)| **1.11 s/iter**           | **~1.31 GiB total, summed across all 6 rank processes** (1,407,320,064 B) |

Speed-up with 6 ranks ≈ **2.5×** (not linear — expected on a 6c/12t Ryzen
5600X for a memory-bandwidth-bound GAMG pressure solve at this cell count;
per-rank subdomains are only ~167k cells here, so MPI overhead is a bigger
fraction of the work than it would be on a much larger mesh).
Extrapolating: a 1-million-cell steady RANS case costs roughly **~55 s of
solver time per 20 iterations serial, ~22 s per 20 iterations on 6 ranks**;
scale linearly with cell count and iteration count for campaign-cost
estimates (e.g. a converged ~300-iteration case at 1M cells: serial ≈ 14
min, 6-rank parallel ≈ 5.5 min compute time, plus the same meshing overhead
either way).
Logs: `openfoam_benchmark1M_blockMesh.log`, `openfoam_benchmark1M_serial.log`,
`openfoam_benchmark1M_decomposePar.log`, `openfoam_benchmark1M_parallel.log`.

## Known issues / limitations

- **No compilation support.** This is a binary-only mingw cross-compiled
  distribution; `wmake`, custom solvers, and `codedFixedValue`/dynamic code
  are not available. If a custom solver or BC is ever needed, it would have
  to be compiled elsewhere (e.g. via the WSL2 fallback below) or found
  among the ~500 stock utilities/solvers already shipped.
- **ParaView is not installed** (the vendor explicitly expects it to be
  installed separately; out of scope here). `foamToVTK` is available for
  exporting results to a format any external tool (e.g. PyVista) can read.
- **SourceForge downloads were unstable** on this connection (one download
  died after 183 MB with an abrupt TLS close, later attempts briefly served
  an HTML mirror-selection page instead of the binary). Resolved with a
  chunked `curl -C -` (byte-range resume) retry loop; if re-downloading in
  the future and it stalls, retry with that pattern rather than assuming
  the file/URL is broken.
- **Only one CPU/architecture combination is bundled**
  (`win64MingwDPInt32Opt`); there is no 32-bit or debug build available in
  this package.
- The vendor's `OpenFOAM-MS-DOSPrompt.bat` / `setEnvVariables-v2306.bat`
  (the plain-cmd launch route) has a real bug in its `WM_THIRD_PARTY_DIR`
  line (malformed `%...%` expansion). It is harmless for this build because
  all third-party libraries (scotch, metis, kahip, etc.) already ship
  directly under `platforms\win64MingwDPInt32Opt\bin`, but it means that
  batch file cannot be trusted as-is for anything relying on
  `WM_THIRD_PARTY_DIR`. Our launcher does not use that batch file at all —
  it sources `etc/bashrc` directly inside the bundled MSYS2 bash, which
  works correctly.
- All downloads/extraction live under `E:\PINN\tools\downloads\` (kept, in
  case anything needs re-extracting) and `E:\tmp` is used for `TMP`/`TEMP`
  everywhere, per the hard rule about C: free space.

## WSL2 fallback (documented, NOT executed)

Per the project's standing instruction, a fully commented (Spanish)
fallback script was also written at
`E:\PINN\admin\instalar_wsl2_openfoam.ps1`, even though it was not needed —
the native no-admin Windows route above works. It documents enabling
WSL2 + VirtualMachinePlatform, importing an Ubuntu 24.04 distro with its
disk on `E:\PINN\wsl\...` (not C:), and installing OpenFOAM from the
official `dl.openfoam.com` apt repo. It requires admin rights and a reboot,
so it has deliberately been left unexecuted.

## Directory summary

```
E:\PINN\tools\openfoam\msys64\...                     OpenFOAM v2306 + MSYS2 (install)
E:\PINN\tools\msmpi\bin\{mpiexec,smpd}.exe, msmpi.dll  MS-MPI v10.1.3 runtime (x64, hand-extracted)
E:\PINN\tools\7z\7z.exe                                Full 7-Zip (for future extraction needs)
E:\PINN\tools\of_env.ps1                               Environment helper (dot-sourced)
E:\PINN\tools\of_run.ps1                               Main launcher (see usage above)
E:\PINN\tools\downloads\                               Installers/archives (kept)
E:\PINN\runs\_oftests\pitzDaily                        Test (a)
E:\PINN\runs\_oftests\snappyBox                        Test (b) + (d)
E:\PINN\runs\_oftests\pitzDaily_parallel               Test (c)
E:\PINN\runs\_oftests\benchmark1M                      Test (e)
E:\PINN\logs\openfoam_*.log                            All acceptance-test logs
E:\PINN\admin\instalar_wsl2_openfoam.ps1               WSL2 fallback (documented, not run)
```
