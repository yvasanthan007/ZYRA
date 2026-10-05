# Stages a portable Python runtime for the "full" ZYRA Desktop installer.
#
# A virtualenv (.venv) is NOT portable: it only holds a tiny launcher plus a
# pyvenv.cfg that points at the build machine's base Python install. To make
# the installer truly self-contained we ship:
#
#   1. A copy of the BASE Python installation (interpreter, DLLs, stdlib)
#   2. The project's installed third-party packages (from .venv site-packages)
#      merged into that copy's Lib\site-packages
#
# The result is a relocatable runtime at .build/python which electron-builder
# copies into the installer as <resources>\zyra\python (see
# desktop/builder-full.json). desktop/main.js already looks for pythonw.exe /
# python.exe at that location.

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot   # desktop/ -> project root
$buildDir    = Join-Path $projectRoot ".build"
$targetPy    = Join-Path $buildDir "python"
$venvDir     = Join-Path $projectRoot ".venv"

Write-Host "[stage-python] Project root: $projectRoot"

# --- Locate the base Python interpreter ------------------------------
$venvPython = Join-Path $venvDir "Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
  throw "Project .venv not found at $venvDir. Create it first (e.g. 'uv venv' then 'uv pip install -r requirements.txt')."
}

$basePrefix = (& $venvPython -c "import sys; print(sys.base_prefix)").Trim()
if (-not (Test-Path $basePrefix)) {
  throw "Base Python prefix '$basePrefix' does not exist."
}
Write-Host "[stage-python] Base Python: $basePrefix"

# --- Fresh staging directory -----------------------------------------
if (Test-Path $targetPy) { Remove-Item $targetPy -Recurse -Force }
New-Item -ItemType Directory -Path $targetPy -Force | Out-Null

# --- 1. Copy the base Python runtime ---------------------------------
$null = robocopy $basePrefix $targetPy /E /NFL /NDL /NJH /NJS /NP
if ($LASTEXITCODE -ge 8) { throw "robocopy failed copying base Python (exit $LASTEXITCODE)." }

# --- 2. Merge the venv's installed packages --------------------------
$venvSite   = Join-Path $venvDir "Lib\site-packages"
$targetSite = Join-Path $targetPy "Lib\site-packages"
if (-not (Test-Path $venvSite)) { throw "site-packages not found at $venvSite" }
if (-not (Test-Path $targetSite)) { New-Item -ItemType Directory -Path $targetSite -Force | Out-Null }

$null = robocopy $venvSite $targetSite /E /NFL /NDL /NJH /NJS /NP
if ($LASTEXITCODE -ge 8) { throw "robocopy failed merging site-packages (exit $LASTEXITCODE)." }

# --- 3. Verify -------------------------------------------------------
$pyExe  = Join-Path $targetPy "python.exe"
$pywExe = Join-Path $targetPy "pythonw.exe"
if (-not (Test-Path $pyExe))  { throw "Bundled python.exe missing." }
if (-not (Test-Path $pywExe)) { throw "Bundled pythonw.exe missing." }

Write-Host "[stage-python] Verifying bundled interpreter + native dependencies..."
& $pyExe -c "import sys, fastapi, uvicorn, numpy; print('bundled python', sys.version.split()[0]); print('prefix', sys.prefix)"
if ($LASTEXITCODE -ne 0) { throw "Bundled interpreter verification failed." }

$size = (Get-ChildItem $targetPy -Recurse -File | Measure-Object -Property Length -Sum).Sum
Write-Host ("[stage-python] Done. Portable runtime at {0} ({1:N0} MB)" -f $targetPy, ($size / 1MB))
