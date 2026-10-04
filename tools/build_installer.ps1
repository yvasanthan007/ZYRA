<#
.SYNOPSIS
    Build the distributable ZYRA Windows installer.

.DESCRIPTION
    Steps run in order, because electron-builder copies the backend into the app:

      1. PyInstaller      -> <repo>\dist\ZYRA-backend\ZYRA-backend.exe  (Python backend)
      2. Webpack          -> <repo>\desktop-ui\dist\**                  (Electron code)
      3. electron-builder -> <repo>\desktop-ui\release\ZYRA-Setup-<ver>.exe  (NSIS)

.PARAMETER BackendOnly
    Build only the PyInstaller backend and stop.

.PARAMETER SkipBackend
    Reuse an already-built backend (skip PyInstaller).

.PARAMETER SkipWebpack
    Reuse the existing webpack output.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File tools\build_installer.ps1
    Builds the backend, the Electron bundles and the NSIS installer.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File tools\build_installer.ps1 -SkipBackend
    Rebuilds only the Electron bundles and the installer.

.NOTES
    One-off prerequisites (dev dependencies, not committed):
        .venv\Scripts\python.exe -m pip install pyinstaller
        cd desktop-ui; npm install
#>
[CmdletBinding()]
param(
    [switch]$BackendOnly,
    [switch]$SkipBackend,
    [switch]$SkipWebpack
)

$ErrorActionPreference = 'Stop'
# NOTE: StrictMode is deliberately not enabled. npm/electron-builder emit
# stream records that older PowerShell builds cannot expose, and turning that
# into a hard error breaks the build for no real benefit.

$RepoRoot     = Split-Path -Parent $PSScriptRoot
$DesktopUi    = Join-Path $RepoRoot 'desktop-ui'
$Spec         = Join-Path $RepoRoot 'zyra.spec'
$BackendDir   = Join-Path $RepoRoot 'dist/ZYRA-backend'
$ReleaseDir   = Join-Path $DesktopUi 'release'

function Write-Step([string]$msg) {
    Write-Host ''
    Write-Host "=== $msg ===" -ForegroundColor Cyan
}

function Resolve-Python {
    # Prefer the project virtualenv; fall back to whatever python is on PATH.
    $venv = Join-Path $RepoRoot '.venv/Scripts/python.exe'
    if (Test-Path $venv) { return $venv }
    $cmd = Get-Command python -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    throw 'No Python interpreter found. Install Python or create .venv.'
}

$python = Resolve-Python
Write-Step "Using Python: $python"

# On Windows `npm`/`npx` resolve to .ps1 shims that mangle the first argument
# (npm becomes "pm"), so invoke the .cmd entry points directly.
$IS_WINDOWS = ($env:OS -eq 'Windows_NT')
$npm = if ($IS_WINDOWS) { 'npm.cmd' } else { 'npm' }
$npx = if ($IS_WINDOWS) { 'npx.cmd' } else { 'npx' }

# ── 1. Python backend ────────────────────────────────────────────────────────
if (-not $SkipBackend) {
    Write-Step '1/3 PyInstaller: building the ZYRA Python backend'
    Push-Location $RepoRoot
    try {
        & $python -m PyInstaller $Spec --noconfirm --clean --log-level WARN
        if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed with exit code $LASTEXITCODE" }
    } finally { Pop-Location }

    $backendExe = Join-Path $BackendDir 'ZYRA-backend.exe'
    if (-not (Test-Path $backendExe)) {
        throw "PyInstaller did not produce $backendExe"
    }
    $sizeMb = [math]::Round(
        (Get-ChildItem $BackendDir -Recurse -File | Measure-Object Length -Sum).Sum / 1MB, 1)
    Write-Host "    backend built: $backendExe ($sizeMb MB)" -ForegroundColor Green
}

if ($BackendOnly) {
    Write-Step 'Backend-only build complete.'
    exit 0
}

# ── 2. Electron bundle ───────────────────────────────────────────────────────
if (-not $SkipWebpack) {
    Write-Step '2/3 Webpack: building the Electron main/preload/renderer bundles'
    Push-Location $DesktopUi
    try {
        & $npm run build
        if ($LASTEXITCODE -ne 0) { throw "npm run build failed with exit code $LASTEXITCODE" }
    } finally { Pop-Location }
}

# ── 3. electron-builder / NSIS ───────────────────────────────────────────────
Write-Step '3/3 electron-builder: producing the NSIS installer'
if (-not (Test-Path (Join-Path $BackendDir 'ZYRA-backend.exe'))) {
    throw "Missing $BackendDir\ZYRA-backend.exe - run the PyInstaller step first."
}

Push-Location $DesktopUi
try {
    & $npx electron-builder --win --publish never
    if ($LASTEXITCODE -ne 0) { throw "electron-builder failed with exit code $LASTEXITCODE" }
} finally { Pop-Location }

$installer = Get-ChildItem $ReleaseDir -Filter 'ZYRA-Setup-*.exe' -ErrorAction SilentlyContinue |
             Sort-Object LastWriteTime -Descending | Select-Object -First 1

Write-Step 'Done'
if ($installer) {
    $mb = [math]::Round($installer.Length / 1MB, 1)
    Write-Host "    Installer: $($installer.FullName) ($mb MB)" -ForegroundColor Green
} else {
    Write-Host "    Installer not found in $ReleaseDir" -ForegroundColor Yellow
}
